"""End-to-end verification test suite for GTA VI Clipping MVP.
Exercises:
1. Doctor diagnostics
2. Storage isolation outside OneDrive
3. Rights, attribution, and metadata tracking
4. Audio extraction and RMS peak detection
5. Visual stream inspection
6. Dual-signal candidate proposal & deduplication
7. ASS & SRT subtitle generation with safe margins
8. 1080x1920 vertical MP4 rendering across all 4 layouts
9. ffprobe stream verification
10. Paths with spaces and Unicode characters
11. Re-render caching / idempotence
12. Error handling for invalid inputs and time ranges
13. Style preset derivation from notes and local media
14. Two-reference style composition (captions from ref A, layout from ref B)
15. Multi-track audio and streamer mic track selection
16. External transcript fallback with synchronized burned dialogue
17. Caption guardrail: blocks uncaptioned dialogue export
18. Recomputing subtitle timing when clip boundaries are trimmed
19. Inaccessible reference URL fallback to style notes
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gta_clipper.config import StorageConfig, load_game_config
from gta_clipper.doctor import run_doctor
from gta_clipper.metadata import create_job_metadata, save_job_metadata, load_job_metadata
from gta_clipper.audio import (
    analyze_audio, AudioSegment, probe_audio_tracks, parse_external_transcript
)
from gta_clipper.visual import analyze_visual, probe_video
from gta_clipper.candidates import generate_candidates, CandidateClip
from gta_clipper.subtitles import (
    generate_subtitles_for_clip, recompute_subtitles_for_trimmed_clip
)
from gta_clipper.renderer import render_clip, RenderOptions
from gta_clipper.preview import generate_review_artifacts
from gta_clipper.style import (
    StylePreset, parse_style_from_notes, extract_style_from_local_media, merge_style_presets
)
from tests.generate_test_media import generate_all_test_media


class TestGtaClipperPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.storage = StorageConfig()
        cls.media = generate_all_test_media(cls.storage)
        cls.game_config = load_game_config("gtavi")
        cls.srt_sample = REPO_ROOT / "tests" / "sample_stream_speech.srt"

    def test_01_doctor_diagnostic(self):
        report = run_doctor(self.storage)
        self.assertTrue(report["python"]["compatible"])
        self.assertTrue(report["ffmpeg"]["found"])
        self.assertTrue(report["ffprobe"]["found"])
        self.assertTrue(report["encoders"]["libx264"])
        self.assertTrue(report["encoders"]["aac"])
        self.assertTrue(report["filters"]["ass"])
        self.assertTrue(report["filters"]["subtitles"])
        self.assertTrue(report["storage"]["is_writable"])
        self.assertTrue(report["ready_for_visual"])

    def test_02_storage_outside_onedrive(self):
        self.assertTrue(self.storage.is_outside_onedrive())
        self.assertTrue(self.storage.root.is_dir())
        self.assertNotIn("onedrive", str(self.storage.root).lower())

    def test_03_job_metadata_and_rights(self):
        v1 = self.media["visual_only"]
        meta = create_job_metadata(
            source_path=v1,
            source_creator="TestStreamer",
            source_identifier="https://twitch.tv/teststreamer",
            footage_rights="creator_supplied",
            permission_reference="Direct streamer DM",
            intended_platforms=["tiktok", "instagram_reels"],
            intended_accounts=["@test_clips"],
            known_limits="No story leaks",
            game_id="gtavi",
        )
        self.assertTrue(meta.job_id.startswith("job_"))
        self.assertEqual(meta.source_creator, "TestStreamer")
        self.assertEqual(meta.footage_rights, "creator_supplied")

        job_dir = self.storage.get_job_dir(meta.job_id)
        save_path = save_job_metadata(meta, job_dir)
        self.assertTrue(save_path.is_file())

        loaded = load_job_metadata(job_dir)
        self.assertEqual(loaded.job_id, meta.job_id)
        self.assertEqual(loaded.permission_reference, "Direct streamer DM")

    def test_04_audio_analysis_and_peaks(self):
        v1 = self.media["visual_only"]
        audio_res = analyze_audio(v1, self.storage, "test_v1_hash")
        self.assertTrue(audio_res.has_audio)
        self.assertGreater(audio_res.duration, 30.0)
        self.assertGreaterEqual(len(audio_res.peaks), 1)
        impact_peaks = [p for p in audio_res.peaks if 18.0 <= p.timestamp <= 22.0]
        self.assertGreaterEqual(len(impact_peaks), 1)

    def test_05_visual_probe(self):
        v1 = self.media["visual_only"]
        info = probe_video(v1)
        self.assertEqual(info.width, 1920)
        self.assertEqual(info.height, 1080)
        self.assertGreaterEqual(info.duration, 39.0)
        self.assertEqual(info.video_codec, "h264")

    def test_06_candidate_generation_and_thumbnails(self):
        v1 = self.media["visual_only"]
        audio_res = analyze_audio(v1, self.storage, "test_v1_hash")
        visual_res = analyze_visual(v1)
        job_dir = self.storage.get_job_dir("test_candidate_job")

        candidates = generate_candidates(
            video_path=v1,
            audio_res=audio_res,
            visual_res=visual_res,
            game_config=self.game_config,
            job_dir=job_dir,
            max_candidates=3,
        )
        self.assertGreaterEqual(len(candidates), 1)
        c = candidates[0]
        self.assertGreater(c.duration, 10.0)
        self.assertLessEqual(c.duration, 35.0)
        self.assertGreater(c.confidence, 0.5)

        self.assertIn("start", c.preview_frames)
        self.assertIn("payoff", c.preview_frames)
        self.assertIn("end", c.preview_frames)
        self.assertTrue(Path(c.preview_frames["start"]).is_file())
        self.assertTrue(Path(c.preview_frames["payoff"]).is_file())

    def test_07_subtitles_ass_and_srt(self):
        job_dir = self.storage.get_job_dir("test_subs_job")
        ass_path = job_dir / "test.ass"
        srt_path = job_dir / "test.srt"

        segments = [
            AudioSegment(start=1.0, end=3.5, text="Watch this insane GTA 6 stunt!"),
            AudioSegment(start=4.0, end=6.5, text="No way he survived that crash!"),
        ]

        success = generate_subtitles_for_clip(
            transcript_segments=segments,
            clip_start=0.0,
            clip_end=10.0,
            ass_path=ass_path,
            srt_path=srt_path,
            hook_text="WAIT FOR IT 💀",
        )
        self.assertTrue(success)
        self.assertTrue(ass_path.is_file())
        self.assertTrue(srt_path.is_file())

        ass_content = ass_path.read_text(encoding="utf-8")
        self.assertIn("PlayResX: 1080", ass_content)
        self.assertIn("PlayResY: 1920", ass_content)
        self.assertIn("Style: Default", ass_content)
        self.assertIn("WAIT FOR IT", ass_content)

        srt_content = srt_path.read_text(encoding="utf-8")
        self.assertIn("Watch this insane\nGTA 6 stunt!", srt_content)
        self.assertIn("No way he\nsurvived that crash!", srt_content)

    def test_08_render_all_layouts_and_ffprobe(self):
        v1 = self.media["visual_only"]
        export_dir = self.storage.get_export_dir("test_layouts_export")

        clip = CandidateClip(
            id="clip_test_layout",
            category_id="unexpected_gameplay_stunt",
            category_name="Unexpected Gameplay / Stunt",
            start_time=16.0,
            end_time=32.0,
            duration=16.0,
            payoff_time=20.0,
            hook_lead_seconds=3.0,
            cue="Test Cue",
            reason="Test Reason",
            evidence_type="visual_frame",
            evidence_detail="Frame test",
            confidence=0.88,
            proposed_layout="center_crop",
            hook_text="WAIT FOR THE ENDING 💀",
            title="GTA 6 Stunt Test",
            description="#GTA6 #Shorts",
            posting_caption="Bro flew across the map #GTA6",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            is_visual_only=True,
        )

        layouts = ["center_crop", "manual_crop", "fit_background", "pip"]
        for layout in layouts:
            clip.id = f"clip_{layout}"
            opts = RenderOptions(
                layout=layout,
                crop_x_offset_pct=0.3 if layout == "manual_crop" else 0.5,
                burn_subtitles=False,
                force_reencode=True,
            )
            res = render_clip(v1, clip, export_dir, opts)
            self.assertTrue(res.success, f"Render failed for layout: {layout}: {res.error}")
            out_file = Path(res.output_path)
            self.assertTrue(out_file.is_file())
            self.assertGreater(out_file.stat().st_size, 100000)

            probe_cmd = [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", str(out_file)
            ]
            p_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True)
            p_data = json.loads(p_res.stdout)
            v_stream = next(s for s in p_data["streams"] if s["codec_type"] == "video")
            self.assertEqual(int(v_stream["width"]), 1080)
            self.assertEqual(int(v_stream["height"]), 1920)
            self.assertEqual(v_stream["codec_name"], "h264")

    def test_09_unicode_and_spaces_path(self):
        v3 = self.media["unicode_path"]
        self.assertTrue(v3.is_file())

        meta = create_job_metadata(v3, source_creator="Lucia & Jason", source_identifier="OBS")
        job_dir = self.storage.get_job_dir(meta.job_id)
        save_job_metadata(meta, job_dir)

        audio_res = analyze_audio(v3, self.storage, meta.source_hash)
        visual_res = analyze_visual(v3)
        candidates = generate_candidates(v3, audio_res, visual_res, self.game_config, job_dir)
        self.assertGreaterEqual(len(candidates), 1)

        export_dir = self.storage.get_export_dir(meta.job_id)
        res = render_clip(v3, candidates[0], export_dir)
        self.assertTrue(res.success)
        self.assertTrue(Path(res.output_path).is_file())

    def test_10_cache_and_idempotence(self):
        v1 = self.media["visual_only"]
        export_dir = self.storage.get_export_dir("test_cache_export")
        clip = CandidateClip(
            id="clip_cache_test",
            category_id="unexpected_gameplay_stunt",
            category_name="Test",
            start_time=5.0,
            end_time=18.0,
            duration=13.0,
            payoff_time=10.0,
            hook_lead_seconds=3.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.85,
            proposed_layout="center_crop",
            hook_text="Hook",
            title="Title",
            description="Desc",
            posting_caption="Cap",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            is_visual_only=True,
        )
        res1 = render_clip(v1, clip, export_dir, RenderOptions(force_reencode=True))
        self.assertTrue(res1.success)
        self.assertGreater(res1.render_time_seconds, 0.0)

        res2 = render_clip(v1, clip, export_dir, RenderOptions(force_reencode=False))
        self.assertTrue(res2.success)
        self.assertEqual(res2.render_time_seconds, 0.0)

    def test_11_error_handling_actionable(self):
        v1 = self.media["visual_only"]
        export_dir = self.storage.get_export_dir("test_error_export")

        bad_clip = CandidateClip(
            id="clip_bad",
            category_id="unexpected_gameplay_stunt",
            category_name="Test",
            start_time=25.0,
            end_time=10.0,
            duration=-15.0,
            payoff_time=20.0,
            hook_lead_seconds=3.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.8,
            proposed_layout="center_crop",
            hook_text="Hook",
            title="Title",
            description="Desc",
            posting_caption="Cap",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            is_visual_only=True,
        )
        res = render_clip(v1, bad_clip, export_dir)
        self.assertFalse(res.success)
        self.assertIn("Invalid time range", res.error)

        res_missing = render_clip(Path("does_not_exist_file.mp4"), bad_clip, export_dir)
        self.assertFalse(res_missing.success)
        self.assertIn("Source video file not found", res_missing.error)

    def test_12_style_preset_from_notes_and_probe(self):
        notes = "Fast GTA 6 clips, bold yellow Arial Black captions, top red hook, 20s length, pip facecam"
        preset = parse_style_from_notes(notes, preset_id="custom_test", name="Custom Stunt Style")

        self.assertEqual(preset.layout_mode, "pip")
        self.assertEqual(preset.typical_length, 20.0)
        self.assertEqual(preset.primary_color, "&H0000FFFF")
        self.assertEqual(preset.cut_pace, "rapid")
        self.assertIn("primary_color", preset.observed_traits)
        self.assertIn("layout_mode", preset.observed_traits)
        self.assertIn("exact_subtitle_outline_thickness_px", preset.unknown_traits)

        # Probe local video
        v1 = self.media["visual_only"]
        probed_preset = extract_style_from_local_media(v1, notes="Yellow captions", preset_id="probed_v1")
        self.assertGreaterEqual(probed_preset.typical_length, 39.0)
        self.assertIn("actual_reference_duration", probed_preset.observed_traits)

    def test_13_two_reference_style_merge(self):
        cap_ref = parse_style_from_notes("Bright yellow subtitles at bottom, bold outline", preset_id="cap_ref")
        layout_ref = parse_style_from_notes("Fit background with blur, 25s pacing", preset_id="layout_ref")

        merged = merge_style_presets(cap_ref, layout_ref, new_id="hybrid", new_name="Hybrid Preset")
        # Subtitles from cap_ref
        self.assertEqual(merged.primary_color, "&H0000FFFF")
        # Layout & pacing from layout_ref
        self.assertEqual(merged.layout_mode, "fit_background")
        self.assertEqual(merged.typical_length, 25.0)
        self.assertIn("captions_source", merged.observed_traits)
        self.assertIn("layout_source", merged.observed_traits)

    def test_14_multitrack_mic_selection(self):
        v4 = self.media["multitrack"]
        tracks = probe_audio_tracks(v4)
        self.assertGreaterEqual(len(tracks), 2)
        self.assertEqual(tracks[0]["track_index"], 0)
        self.assertEqual(tracks[1]["track_index"], 1)

        # Analyze specifying track 1 (Streamer Mic)
        audio_res = analyze_audio(v4, self.storage, "test_v4_hash", track_index=1)
        self.assertTrue(audio_res.has_audio)
        self.assertEqual(audio_res.selected_track_index, 1)

    def test_15_external_transcript_fallback_and_burned_dialogue(self):
        v4 = self.media["multitrack"]
        self.assertTrue(self.srt_sample.is_file())

        parsed_segs = parse_external_transcript(self.srt_sample)
        self.assertEqual(len(parsed_segs), 4)
        self.assertIn("Wait, watch this car jump!", parsed_segs[0].text)

        # Analyze using external transcript
        meta = create_job_metadata(v4, source_creator="TestStreamer", source_identifier="OBS")
        job_dir = self.storage.get_job_dir("test_transcript_job")

        audio_res = analyze_audio(
            v4, self.storage, meta.source_hash,
            track_index=1,
            external_transcript_path=self.srt_sample,
        )
        self.assertTrue(audio_res.is_transcribed)
        self.assertEqual(len(audio_res.transcript_segments), 4)

        visual_res = analyze_visual(v4)
        candidates = generate_candidates(
            v4, audio_res, visual_res, self.game_config, job_dir, max_candidates=2
        )
        self.assertGreaterEqual(len(candidates), 1)
        c0 = candidates[0]
        self.assertFalse(c0.awaiting_captions)
        self.assertFalse(c0.is_visual_only)
        self.assertTrue(len(c0.speech_segments) > 0)

        # Generate subtitles using style preset
        style = parse_style_from_notes("Yellow subtitles, 20s length")
        ass_path = job_dir / "test_dialogue.ass"
        srt_path = job_dir / "test_dialogue.srt"
        generate_subtitles_for_clip(
            audio_res.transcript_segments, c0.start_time, c0.end_time,
            ass_path, srt_path, hook_text=c0.hook_text, style=style
        )
        self.assertTrue(ass_path.is_file())
        self.assertTrue(srt_path.is_file())

        # Render clip with burned dialogue subtitles
        export_dir = self.storage.get_export_dir("test_captioned_export")
        opts = RenderOptions(
            layout="center_crop",
            burn_subtitles=True,
            ass_path=ass_path,
            force_reencode=True,
        )
        res = render_clip(v4, c0, export_dir, opts)
        self.assertTrue(res.success)
        out_mp4 = Path(res.output_path)
        self.assertTrue(out_mp4.is_file())
        self.assertGreater(out_mp4.stat().st_size, 100000)

    def test_16_caption_guardrail_blocks_uncaptioned_dialogue(self):
        v1 = self.media["visual_only"]
        export_dir = self.storage.get_export_dir("test_guardrail_export")

        clip_awaiting = CandidateClip(
            id="clip_awaiting",
            category_id="creator_reaction_with_context",
            category_name="Creator Reaction",
            start_time=0.0,
            end_time=18.0,
            duration=18.0,
            payoff_time=12.0,
            hook_lead_seconds=3.0,
            cue="Reaction quote without subtitles",
            reason="Dialogue clip awaiting whisper",
            evidence_type="speech_quote",
            evidence_detail="Pending model",
            confidence=0.88,
            proposed_layout="center_crop",
            hook_text="Wait for it",
            title="Uncaptioned Reaction",
            description="#Shorts",
            posting_caption="Caption",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            awaiting_captions=True,  # Guardrail should trigger
            is_visual_only=False,
        )

        # Standard render should fail with actionable error
        res = render_clip(v1, clip_awaiting, export_dir, RenderOptions(allow_uncaptioned=False))
        self.assertFalse(res.success)
        self.assertIn("awaiting captions", res.error.lower())

        # If operator explicitly permits uncaptioned export
        res_allowed = render_clip(v1, clip_awaiting, export_dir, RenderOptions(allow_uncaptioned=True, force_reencode=True))
        self.assertTrue(res_allowed.success)

    def test_17_trim_clip_recomputes_subtitles(self):
        job_dir = self.storage.get_job_dir("test_trim_job")
        all_segs = [
            AudioSegment(start=2.0, end=4.0, text="First phrase"),
            AudioSegment(start=8.0, end=11.0, text="Second phrase"),
            AudioSegment(start=14.0, end=17.0, text="Third phrase"),
        ]

        # Clip trimmed to [6.0s, 18.0s]
        clip_dict = {
            "start_time": 6.0,
            "end_time": 18.0,
            "hook_text": "Trimmed Hook",
        }
        ass_path = job_dir / "trimmed.ass"
        srt_path = job_dir / "trimmed.srt"

        recompute_subtitles_for_trimmed_clip(clip_dict, all_segs, ass_path, srt_path)
        self.assertTrue(ass_path.is_file())
        self.assertTrue(srt_path.is_file())

        ass_text = ass_path.read_text(encoding="utf-8")
        # "First phrase" was before 6.0s, should be omitted
        self.assertNotIn("First phrase", ass_text)
        # "Second phrase" (8.0s) should now be at 8.0 - 6.0 = 2.0s
        self.assertIn("0:00:02.00", ass_text)
        self.assertIn("Second phrase", ass_text)
        # "Third phrase" (14.0s) should now be at 14.0 - 6.0 = 8.0s
        self.assertIn("0:00:08.00", ass_text)
        self.assertIn("Third phrase", ass_text)

    def test_18_inaccessible_reference_url_with_manual_notes(self):
        # When reference URL is inaccessible/blocked, operator notes supply visible style
        inaccessible_url = "https://instagram.com/reel/inaccessible_private_123"
        operator_notes = "White bold Arial Black subtitles, fit background, 24s duration, top hook banner"

        preset = parse_style_from_notes(
            notes=operator_notes,
            preset_id="inaccessible_ref_preset",
            name="Inaccessible Reel Style",
            source_reference=inaccessible_url
        )
        self.assertEqual(preset.layout_mode, "fit_background")
        self.assertEqual(preset.primary_color, "&H00FFFFFF")
        self.assertEqual(preset.typical_length, 24.0)
        self.assertEqual(preset.source_reference, inaccessible_url)
        # Verify unknown traits are tracked
        self.assertGreater(len(preset.unknown_traits), 0)

    def test_19_groq_key_missing_guardrail(self):
        from gta_clipper.groq_transcriber import get_groq_api_key, check_groq_status, transcribe_candidate_with_groq
        # Temporarily clear GROQ_API_KEY from environment to test missing key guardrail
        old_val = os.environ.pop("GROQ_API_KEY", None)
        try:
            status, msg = check_groq_status()
            self.assertEqual(status, "KEY_MISSING")
            self.assertIn("GROQ_API_KEY", msg)
            self.assertIn("$env:GROQ_API_KEY", msg)

            # Transcribing with missing key should return KEY_MISSING and empty segments
            dummy_wav = self.storage.audio_cache_dir / "dummy.wav"
            dummy_wav.parent.mkdir(parents=True, exist_ok=True)
            dummy_wav.write_bytes(b"RIFF" + b"\x00" * 40)
            segs, trans_status, diag = transcribe_candidate_with_groq(dummy_wav, candidate_start_time=10.0)
            self.assertEqual(trans_status, "KEY_MISSING")
            self.assertEqual(len(segs), 0)
        finally:
            if old_val is not None:
                os.environ["GROQ_API_KEY"] = old_val

    def test_20_candidate_audio_slice_extraction(self):
        from gta_clipper.audio import extract_candidate_audio_pcm
        v_multi = self.media["multitrack"]
        slice_wav = self.storage.audio_cache_dir / "test_slice_10s_to_25s.wav"

        # Extract 15 seconds from Track 1 (Streamer Mic) starting at 10.0s
        ok = extract_candidate_audio_pcm(
            video_path=v_multi,
            output_wav=slice_wav,
            start_time=10.0,
            duration=15.0,
            track_index=1,
        )
        self.assertTrue(ok)
        self.assertTrue(slice_wav.is_file())
        self.assertGreater(slice_wav.stat().st_size, 44)

        # Verify extracted audio properties with ffprobe
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(slice_wav)]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
        probe_data = json.loads(res.stdout)
        astream = probe_data["streams"][0]
        self.assertEqual(int(astream["sample_rate"]), 16000)
        self.assertEqual(int(astream["channels"]), 1)
        dur = float(astream["duration"])
        self.assertAlmostEqual(dur, 15.0, delta=0.5)

    def test_21_groq_verbose_json_parsing_and_timing_offsets(self):
        from gta_clipper.groq_transcriber import parse_groq_verbose_json
        sample_groq_response = {
            "task": "transcribe",
            "language": "english",
            "duration": 20.0,
            "text": "Wait watch this jump! He actually survived that!",
            "segments": [
                {
                    "id": 0,
                    "start": 1.20,
                    "end": 3.80,
                    "text": "Wait watch this jump!",
                    "words": [
                        {"word": "Wait", "start": 1.20, "end": 1.50},
                        {"word": "watch", "start": 1.55, "end": 1.90},
                        {"word": "this", "start": 1.95, "end": 2.20},
                        {"word": "jump!", "start": 2.25, "end": 2.80},
                    ]
                },
                {
                    "id": 1,
                    "start": 4.50,
                    "end": 7.20,
                    "text": "He actually survived that!",
                    "words": [
                        {"word": "He", "start": 4.50, "end": 4.70},
                        {"word": "actually", "start": 4.75, "end": 5.20},
                        {"word": "survived", "start": 5.25, "end": 5.80},
                        {"word": "that!", "start": 5.85, "end": 6.30},
                    ]
                }
            ]
        }

        # Candidate starts at 15.0s in the original stream recording
        candidate_offset = 15.0
        segs = parse_groq_verbose_json(sample_groq_response, candidate_start_time=candidate_offset)

        self.assertEqual(len(segs), 2)
        # Segment 0 offset verification
        self.assertAlmostEqual(segs[0].start, 15.0 + 1.20, places=2)  # 16.20s in stream
        self.assertAlmostEqual(segs[0].end, 15.0 + 3.80, places=2)    # 18.80s in stream
        self.assertEqual(segs[0].text, "Wait watch this jump!")

        # Segment 0 word timestamps verification (SupoClip reference)
        self.assertEqual(len(segs[0].words), 4)
        first_word = segs[0].words[0]
        self.assertEqual(first_word["word"], "Wait")
        self.assertAlmostEqual(first_word["start"], 15.0 + 1.20, places=2)
        self.assertAlmostEqual(first_word["end"], 15.0 + 1.50, places=2)
        self.assertAlmostEqual(first_word["rel_start"], 1.20, places=2)
        self.assertAlmostEqual(first_word["rel_end"], 1.50, places=2)
        self.assertAlmostEqual(first_word["duration"], 0.30, places=2)

        # Segment 1 offset verification
        self.assertAlmostEqual(segs[1].start, 15.0 + 4.50, places=2)  # 19.50s in stream
        self.assertAlmostEqual(segs[1].end, 15.0 + 7.20, places=2)    # 22.20s in stream
        self.assertEqual(segs[1].text, "He actually survived that!")

    def test_22_groq_quota_or_api_error_handling(self):
        from gta_clipper.groq_transcriber import parse_groq_verbose_json
        from gta_clipper.candidates import CandidateClip
        from gta_clipper.renderer import render_clip, RenderOptions

        # Simulate candidate where Groq API failed with 429 Rate Limit
        clip = CandidateClip(
            id="clip_quota_test",
            category_id="reaction",
            category_name="Creator Reaction",
            start_time=10.0,
            end_time=32.0,
            duration=22.0,
            payoff_time=20.0,
            hook_lead_seconds=3.0,
            cue="Reaction surge",
            reason="Loud exclamations",
            evidence_type="audio_energy",
            evidence_detail="Peak at 18.5s",
            confidence=0.85,
            proposed_layout="center_crop",
            hook_text="UNBELIEVABLE MOMENT",
            title="Clip Quota Test",
            description="Testing rate limit guardrail",
            posting_caption="Bro check this out! #GTA",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            awaiting_captions=True,  # Kept awaiting captions
            speech_summary="[Awaiting captions: Groq API returned 429 Rate limit exceeded]",
        )

        export_dir = self.storage.exports_dir / "test_quota_job"
        v_multi = self.media["multitrack"]

        # Renderer guardrail MUST prevent exporting this clip as finished
        res = render_clip(v_multi, clip, export_dir, RenderOptions(allow_uncaptioned=False))
        self.assertFalse(res.success)
        self.assertIn("awaiting captions", res.error.lower())

    def test_23_groq_full_workflow_spot_check_captions(self):
        from gta_clipper.groq_transcriber import parse_groq_verbose_json
        from gta_clipper.subtitles import generate_subtitles_for_clip
        from gta_clipper.candidates import CandidateClip
        from gta_clipper.renderer import render_clip, RenderOptions
        from gta_clipper.style import StylePreset

        # 1. Setup candidate from multitrack stream: 22.0s duration [0.0s -> 22.0s]
        v_multi = self.media["multitrack"]
        clip = CandidateClip(
            id="clip_groq_verified",
            category_id="reaction",
            category_name="Creator Reaction with Context",
            start_time=0.0,
            end_time=22.0,
            duration=22.0,
            payoff_time=16.0,
            hook_lead_seconds=3.5,
            cue="Loud streamer reaction",
            reason="High energy spike at 14.5s",
            evidence_type="speech_quote",
            evidence_detail="Wait, watch this car jump!",
            confidence=0.92,
            proposed_layout="center_crop",
            hook_text="INSANE CAR JUMP",
            title="Insane GTA Jump",
            description="Streamer reaction to physics jump",
            posting_caption="No way bro survived this! #GTA6 #Shorts",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            awaiting_captions=False,
        )

        # 2. Simulated Groq verbose_json representing streamer speech on Track 1
        groq_verbose_data = {
            "task": "transcribe",
            "language": "english",
            "duration": 22.0,
            "text": "Wait, watch this car jump! No way bro, he actually survived that! Bro broke the physics engine live!",
            "segments": [
                {
                    "id": 0,
                    "start": 1.20,
                    "end": 3.80,
                    "text": "Wait, watch this car jump!",
                    "words": [
                        {"word": "Wait,", "start": 1.20, "end": 1.60},
                        {"word": "watch", "start": 1.65, "end": 2.00},
                        {"word": "this", "start": 2.05, "end": 2.30},
                        {"word": "car", "start": 2.35, "end": 2.70},
                        {"word": "jump!", "start": 2.75, "end": 3.40},
                    ]
                },
                {
                    "id": 1,
                    "start": 6.50,
                    "end": 10.20,
                    "text": "No way bro, he actually survived that!",
                    "words": [
                        {"word": "No", "start": 6.50, "end": 6.80},
                        {"word": "way", "start": 6.85, "end": 7.15},
                        {"word": "bro,", "start": 7.20, "end": 7.60},
                        {"word": "he", "start": 7.70, "end": 7.90},
                        {"word": "actually", "start": 7.95, "end": 8.40},
                        {"word": "survived", "start": 8.45, "end": 9.10},
                        {"word": "that!", "start": 9.15, "end": 9.60},
                    ]
                },
                {
                    "id": 2,
                    "start": 14.00,
                    "end": 17.50,
                    "text": "Bro broke the physics engine live!",
                    "words": [
                        {"word": "Bro", "start": 14.00, "end": 14.30},
                        {"word": "broke", "start": 14.35, "end": 14.70},
                        {"word": "the", "start": 14.75, "end": 14.95},
                        {"word": "physics", "start": 15.00, "end": 15.50},
                        {"word": "engine", "start": 15.55, "end": 16.00},
                        {"word": "live!", "start": 16.05, "end": 16.60},
                    ]
                }
            ]
        }

        # Parse Groq verbose_json with candidate start offset (0.0s)
        segs = parse_groq_verbose_json(groq_verbose_data, candidate_start_time=clip.start_time)
        clip.speech_segments = [s.to_dict() for s in segs]
        clip.speech_summary = " ".join(s.text for s in segs)

        # 3. Apply viral_streamer_yellow style preset
        style_path = REPO_ROOT / "config" / "styles" / "viral_streamer_yellow.json"
        with open(style_path, "r", encoding="utf-8") as f:
            style = StylePreset.from_dict(json.load(f))

        job_dir = self.storage.get_job_dir("test_groq_verified_job")
        ass_path = job_dir / "subtitles" / f"{clip.id}.ass"
        srt_path = job_dir / "subtitles" / f"{clip.id}.srt"

        generate_subtitles_for_clip(
            transcript_segments=segs,
            clip_start=clip.start_time,
            clip_end=clip.end_time,
            ass_path=ass_path,
            srt_path=srt_path,
            hook_text=clip.hook_text,
            style=style,
        )

        self.assertTrue(ass_path.is_file())
        self.assertTrue(srt_path.is_file())

        # 4. Spot-check First, Middle, and Last Caption
        ass_content = ass_path.read_text(encoding="utf-8")
        srt_content = srt_path.read_text(encoding="utf-8")

        # Spot-check First Caption: "Wait, watch this car jump!" (1.20s -> 3.80s)
        self.assertIn("0:00:01.20", ass_content)
        self.assertIn("0:00:03.80", ass_content)
        self.assertIn("Wait, watch", ass_content)
        self.assertIn("00:00:01,200 --> 00:00:03,800", srt_content)
        self.assertIn("Wait, watch", srt_content)

        # Spot-check Middle Caption: "No way bro, he actually survived that!" (6.50s -> 10.20s)
        self.assertIn("0:00:06.50", ass_content)
        self.assertIn("0:00:10.20", ass_content)
        self.assertIn("No way bro", ass_content)
        self.assertIn("00:00:06,500 --> 00:00:10,200", srt_content)
        self.assertIn("actually survived", srt_content)

        # Spot-check Last Caption: "Bro broke the physics engine live!" (14.00s -> 17.50s)
        self.assertIn("0:00:14.00", ass_content)
        self.assertIn("0:00:17.50", ass_content)
        self.assertIn("physics engine", ass_content)
        self.assertIn("00:00:14,000 --> 00:00:17,500", srt_content)
        self.assertIn("Bro broke", srt_content)

        # 5. Render to 1080x1920 vertical MP4 with burned ASS subtitles
        export_dir = self.storage.exports_dir / "test_groq_verified_job"
        render_opts = RenderOptions(
            layout="center_crop",
            burn_subtitles=True,
            ass_path=ass_path,
            audio_track_index=1,  # Streamer Mic
            force_reencode=True,
            style_preset=style,
        )
        res = render_clip(v_multi, clip, export_dir, render_opts)
        self.assertTrue(res.success)
        self.assertTrue(Path(res.output_path).is_file())
        self.assertGreater(res.file_size_bytes, 100_000)

        # Verify stream specs with ffprobe
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", res.output_path]
        ff_res = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
        probe_json = json.loads(ff_res.stdout)
        v_stream = next(s for s in probe_json["streams"] if s["codec_type"] == "video")
        self.assertEqual(int(v_stream["width"]), 1080)
        self.assertEqual(int(v_stream["height"]), 1920)

    def test_24_groq_429_quota_fallback_to_local_whisper(self):
        from unittest.mock import patch
        from gta_clipper.groq_transcriber import transcribe_candidate_with_fallback
        from gta_clipper.audio import AudioSegment

        dummy_audio = self.storage.cache_dir / "dummy_fallback.wav"
        dummy_audio.write_bytes(b"RIFF" + b"\x00" * 40)

        # Mock Groq API returning HTTP 429 Quota Exceeded with Retry-After: 30
        quota_err = (None, "QUOTA_EXCEEDED", "Groq API rate limit or quota exceeded (HTTP 429) (Retry-After: 30s).")
        mock_local_segs = [
            AudioSegment(start=1.0, end=3.5, text="Local Whisper Fallback Line 1", speaker="Streamer")
        ]

        with patch("gta_clipper.groq_transcriber.call_groq_transcription_api", return_value=quota_err):
            with patch("gta_clipper.audio.check_whisper_backend", return_value=("READY", "whisper ready", Path("whisper-cli"), Path("model.bin"))):
                with patch("gta_clipper.audio.run_transcription", return_value=(mock_local_segs, "READY", "ok")):
                    segs, status, diag = transcribe_candidate_with_fallback(
                        audio_path=dummy_audio,
                        candidate_start_time=20.0,
                        api_key="mock_key",
                        storage=self.storage,
                        fallback_provider="local",
                    )

        self.assertEqual(status, "FALLBACK_LOCAL_WHISPER")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].text, "Local Whisper Fallback Line 1")
        # Offset check: 20.0 candidate_start_time + 1.0 = 21.0
        self.assertAlmostEqual(segs[0].start, 21.0, places=2)
        self.assertAlmostEqual(segs[0].end, 23.5, places=2)
        self.assertIn("Retry-After: 30s", diag)
        self.assertIn("Successfully fell back to local Whisper", diag)

    def test_25_groq_429_quota_fallback_to_srt_import(self):
        from unittest.mock import patch
        from gta_clipper.groq_transcriber import transcribe_candidate_with_fallback

        dummy_audio = self.storage.cache_dir / "dummy_srt_fallback.wav"
        dummy_audio.write_bytes(b"RIFF" + b"\x00" * 40)

        quota_err = (None, "QUOTA_EXCEEDED", "Groq API rate limit or quota exceeded (HTTP 429) (Retry-After: 15s).")

        with patch("gta_clipper.groq_transcriber.call_groq_transcription_api", return_value=quota_err):
            segs, status, diag = transcribe_candidate_with_fallback(
                audio_path=dummy_audio,
                candidate_start_time=0.0,
                api_key="mock_key",
                storage=self.storage,
                fallback_provider="srt",
                fallback_srt_path=self.srt_sample,
            )

        self.assertEqual(status, "FALLBACK_SRT_IMPORT")
        self.assertGreater(len(segs), 0)
        self.assertIn("Wait, watch this car jump!", segs[0].text)
        self.assertIn("Successfully fell back to imported SRT", diag)

    def test_26_freellmapi_unverified_guardrail(self):
        from unittest.mock import patch
        from gta_clipper.groq_transcriber import transcribe_candidate_with_fallback

        dummy_audio = self.storage.cache_dir / "dummy_freellm.wav"
        dummy_audio.write_bytes(b"RIFF" + b"\x00" * 40)

        quota_err = (None, "QUOTA_EXCEEDED", "Groq API rate limit or quota exceeded (HTTP 429).")

        with patch("gta_clipper.groq_transcriber.call_groq_transcription_api", return_value=quota_err):
            segs, status, diag = transcribe_candidate_with_fallback(
                audio_path=dummy_audio,
                candidate_start_time=10.0,
                api_key="mock_key",
                storage=self.storage,
                fallback_provider="freellmapi",
            )

        self.assertEqual(status, "FREELLMAPI_UNVERIFIED")
        self.assertEqual(len(segs), 0)
        self.assertIn("shares Groq quota", diag)
        self.assertIn("Held awaiting captions", diag)

    def test_27_deliverable_reuse_and_export_path_resolution(self):
        from gta_clipper.config import resolve_export_paths, sanitize_windows_filename
        from gta_clipper.metadata import JobMetadata

        # Test Windows sanitization
        dirty_name = 'Stream: GTA VI <Stunt> & Chaos? "Best" | Episode 1 / Part 2 * ...   '
        clean = sanitize_windows_filename(dirty_name)
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, clean)
        self.assertFalse(clean.endswith("."))
        self.assertFalse(clean.endswith(" "))

        # Test export path resolution with original source name
        meta = JobMetadata(
            job_id="job_test_export",
            source_file="C:/sources/cached_hash123.mp4",
            source_file_name="cached_hash123.mp4",
            source_file_size_bytes=1000,
            source_hash="abcdef0123456789",
            game_id="gtavi",
            source_creator="StreamerX",
            source_identifier="Stream 1",
            footage_rights="owned",
            permission_reference="Direct",
            intended_platforms=["tiktok"],
            intended_accounts=["@test"],
            known_limits="none",
            created_at="2026-11-17T12:00:00Z",
            original_source_name="GTA V Chaos Mod Fun Moments",
            original_source_file="C:/Downloads/GTA V Chaos Mod Fun Moments.mp4",
        )

        dest_dir, mp4_name, srt_name = resolve_export_paths(
            metadata=meta,
            clip_id="clip_01",
            repo_root=REPO_ROOT,
        )

        self.assertEqual(dest_dir, REPO_ROOT / "exports" / "GTA V Chaos Mod Fun Moments")
        self.assertEqual(mp4_name, "GTA V Chaos Mod Fun Moments_clip_01.mp4")
        self.assertEqual(srt_name, "GTA V Chaos Mod Fun Moments_clip_01.srt")

        # Test outside OneDrive override
        out_dir, out_mp4, out_srt = resolve_export_paths(
            metadata=meta,
            clip_id="clip_01",
            export_outside_onedrive=True,
            storage=self.storage,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(out_dir, self.storage.exports_dir / "GTA V Chaos Mod Fun Moments")

    def test_28_square_pixels_sar_dar_verification(self):
        from gta_clipper.renderer import render_clip, RenderOptions
        from gta_clipper.candidates import CandidateClip

        v_source = self.media["visual_only"]
        clip = CandidateClip(
            id="clip_test_sar",
            category_id="test",
            category_name="SAR DAR Test",
            start_time=2.0,
            end_time=5.0,
            duration=3.0,
            payoff_time=4.0,
            hook_lead_seconds=1.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.9,
            proposed_layout="fit_background",
            hook_text="Test Hook",
            title="SAR DAR Test",
            description="SAR DAR Test",
            posting_caption="#Test",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            awaiting_captions=False,
            is_visual_only=True,
        )

        export_dir = self.storage.exports_dir / "test_sar_job"
        res = render_clip(v_source, clip, export_dir, RenderOptions(layout="fit_background", force_reencode=True))
        self.assertTrue(res.success)
        self.assertTrue(Path(res.output_path).is_file())

        # Verify SAR is 1:1 and DAR is 9:16 using ffprobe
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-select_streams", "v:0", "-show_entries", "stream=width,height,sample_aspect_ratio,display_aspect_ratio", res.output_path]
        ff = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
        data = json.loads(ff.stdout)
        v_stream = data["streams"][0]
        self.assertEqual(int(v_stream["width"]), 1080)
        self.assertEqual(int(v_stream["height"]), 1920)
        self.assertEqual(v_stream.get("sample_aspect_ratio"), "1:1")
        self.assertEqual(v_stream.get("display_aspect_ratio"), "9:16")

    def test_29_stale_render_reuse_invalidation(self):
        from gta_clipper.renderer import render_clip, RenderOptions, compute_render_fingerprint
        from gta_clipper.candidates import CandidateClip

        v_source = self.media["visual_only"]
        clip = CandidateClip(
            id="clip_test_reuse",
            category_id="test",
            category_name="Reuse Test",
            start_time=1.0,
            end_time=4.0,
            duration=3.0,
            payoff_time=3.0,
            hook_lead_seconds=1.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.9,
            proposed_layout="center_crop",
            hook_text="Original Hook",
            title="Reuse Test",
            description="Reuse Test",
            posting_caption="#Test",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            awaiting_captions=False,
            is_visual_only=True,
        )

        export_dir = self.storage.exports_dir / "test_reuse_job"
        opts_a = RenderOptions(layout="center_crop", force_reencode=True)
        res_a = render_clip(v_source, clip, export_dir, opts_a)
        self.assertTrue(res_a.success)
        self.assertGreater(res_a.render_time_seconds, 0.0)

        # 1. Rerun with identical options -> Reuses render in 0.00s
        res_cached = render_clip(v_source, clip, export_dir, RenderOptions(layout="center_crop", force_reencode=False))
        self.assertTrue(res_cached.success)
        self.assertEqual(res_cached.render_time_seconds, 0.0)

        # 2. Change layout to fit_background -> Fingerprint changes, invalidates cache and re-renders
        opts_b = RenderOptions(layout="fit_background", force_reencode=False)
        res_b = render_clip(v_source, clip, export_dir, opts_b)
        self.assertTrue(res_b.success)
        self.assertEqual(res_b.layout_used, "fit_background")
        self.assertGreater(res_b.render_time_seconds, 0.0)

        # 3. Change crop offset -> Fingerprint changes, invalidates cache
        opts_c = RenderOptions(layout="manual_crop", crop_x_offset_pct=0.85, force_reencode=False)
        res_c = render_clip(v_source, clip, export_dir, opts_c)
        self.assertTrue(res_c.success)
        self.assertEqual(res_c.layout_used, "manual_crop")
        self.assertGreater(res_c.render_time_seconds, 0.0)

    def test_30_storytelling_setup_action_payoff_timestamps(self):
        from gta_clipper.candidates import generate_candidates
        from gta_clipper.audio import analyze_audio
        from gta_clipper.visual import analyze_visual

        v_source = self.media["visual_only"]
        audio_res = analyze_audio(v_source, self.storage, source_hash="test_visual_hash")
        visual_res = analyze_visual(v_source)
        job_dir = self.storage.get_job_dir("test_storytelling_job")

        candidates = generate_candidates(
            video_path=v_source,
            audio_res=audio_res,
            visual_res=visual_res,
            game_config=self.game_config,
            job_dir=job_dir,
            max_candidates=3,
        )

        self.assertGreater(len(candidates), 0)
        c = candidates[0]
        # Verify 3-part storytelling timestamps
        self.assertGreaterEqual(c.setup_start_time, c.start_time)
        self.assertGreater(c.setup_end_time, c.setup_start_time)
        self.assertEqual(c.action_start_time, c.setup_end_time)
        self.assertGreaterEqual(c.action_end_time, c.action_start_time)
        self.assertEqual(c.payoff_start_time, c.action_end_time)
        self.assertEqual(c.payoff_end_time, c.end_time)

        # Verify shot framing generated
        self.assertIsInstance(c.shot_framing, list)
        self.assertGreater(len(c.shot_framing), 0)
        s0 = c.shot_framing[0]
        self.assertIn("start", s0)
        self.assertIn("end", s0)
        self.assertIn("crop_x_pct", s0)

    def test_31_facecam_guardrail_pip_fallback(self):
        from gta_clipper.renderer import render_clip, RenderOptions
        from gta_clipper.candidates import CandidateClip

        v_source = self.media["visual_only"]
        clip = CandidateClip(
            id="clip_facecam_guard",
            category_id="test",
            category_name="Facecam Test",
            start_time=1.0,
            end_time=3.5,
            duration=2.5,
            payoff_time=2.5,
            hook_lead_seconds=1.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.85,
            proposed_layout="pip",
            hook_text="Test",
            title="Facecam Test",
            description="Facecam Test",
            posting_caption="#Test",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            has_facecam=False,  # Facecam NOT confirmed!
            awaiting_captions=False,
            is_visual_only=True,
        )

        export_dir = self.storage.exports_dir / "test_pip_guard_job"
        # Since facecam is not confirmed, render should succeed by falling back to fit_background
        res = render_clip(v_source, clip, export_dir, RenderOptions(layout="pip", facecam_confirmed=False, force_reencode=True))
        self.assertTrue(res.success)
        self.assertTrue(Path(res.output_path).is_file())

    def test_32_hybrid_per_shot_layout_switching(self):
        from gta_clipper.renderer import render_clip, RenderOptions, build_filter_graph
        from gta_clipper.candidates import CandidateClip

        v_source = self.media["visual_only"]
        mixed_shots = [
            {"shot": 1, "start": 0.0, "end": 1.5, "mode": "follow_crop", "crop_x_pct": 0.35, "crop_source": "manual"},
            {"shot": 2, "start": 1.5, "end": 3.0, "mode": "fit_background", "crop_x_pct": 0.50, "crop_source": "manual"}
        ]

        # Verify filter graph structure
        filter_args, filter_type = build_filter_graph(layout="hybrid", shot_framing=mixed_shots)
        self.assertEqual(filter_type, "filter_complex")
        self.assertIn("between(t,1.50,3.00)", filter_args[1])
        self.assertIn("setsar=1,setdar=9/16", filter_args[1])

        clip = CandidateClip(
            id="clip_hybrid_test",
            category_id="test",
            category_name="Hybrid Test",
            start_time=1.0,
            end_time=4.0,
            duration=3.0,
            payoff_time=2.5,
            hook_lead_seconds=1.0,
            cue="Test",
            reason="Test",
            evidence_type="visual_frame",
            evidence_detail="Test",
            confidence=0.90,
            proposed_layout="hybrid",
            hook_text="Hybrid Test",
            title="Hybrid Test",
            description="Hybrid Test",
            posting_caption="#Hybrid",
            spoiler_flag=False,
            music_review_flag=False,
            preview_frames={},
            has_facecam=False,
            awaiting_captions=False,
            is_visual_only=True,
            shot_framing=mixed_shots,
        )

        export_dir = self.storage.exports_dir / "test_hybrid_job"
        res = render_clip(
            v_source, clip, export_dir,
            RenderOptions(layout="hybrid", shot_framing=mixed_shots, force_reencode=True)
        )
        self.assertTrue(res.success)
        out_p = Path(res.output_path)
        self.assertTrue(out_p.is_file())

        # ffprobe square pixels & DAR 9:16
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(out_p)]
        ff_res = subprocess.run(cmd, capture_output=True, text=True)
        data = json.loads(ff_res.stdout)
        v = data["streams"][0]
        self.assertEqual(v["width"], 1080)
        self.assertEqual(v["height"], 1920)
        self.assertEqual(v.get("sample_aspect_ratio"), "1:1")
        self.assertEqual(v.get("display_aspect_ratio"), "9:16")

    def test_33_automatic_subject_framing_dual_vs_single(self):
        from gta_clipper.visual import compute_clip_shot_framing

        v_source = self.media["visual_only"]
        # Generate automatic shot framing from real media frames
        shots = compute_clip_shot_framing(
            video_path=v_source,
            clip_start=0.0,
            clip_end=4.0,
            auto_framing=True,
        )

        self.assertGreater(len(shots), 0)
        for s in shots:
            self.assertIn("shot", s)
            self.assertIn("start", s)
            self.assertIn("end", s)
            self.assertIn("mode", s)
            self.assertIn(s["mode"], ("follow_crop", "fit_background"))
            self.assertEqual(s.get("crop_source"), "auto")
            self.assertIn("reason", s)
            self.assertNotEqual(s["reason"], "")
            # If follow_crop is chosen, it must have a tracked position or reason
            if s["mode"] == "follow_crop":
                self.assertIn("Single clear subject", s["reason"])

    def test_34_late_widening_and_subject_jump_guardrails(self):
        from gta_clipper.visual import analyze_shot_framing_auto
        from PIL import Image, ImageDraw

        synth_dir = self.storage.cache_dir / "test_34_synth"
        synth_dir.mkdir(parents=True, exist_ok=True)

        # 1. Late Widening: Single subject at x=0.25 for first 1.5s, second subject at x=0.85 appears at 1.5s-3.0s
        clip_a = synth_dir / "late_widening.mp4"
        if not clip_a.is_file():
            frames_a = synth_dir / "frames_a"
            frames_a.mkdir(exist_ok=True)
            for i in range(45):
                t = i / 15.0
                im = Image.new("RGB", (640, 360), color=(30, 30, 30))
                draw = ImageDraw.Draw(im)
                draw.rectangle([130, 100, 190, 260], fill=(220, 160, 120))  # Subject at x=0.25
                if t >= 1.5:
                    draw.rectangle([514, 100, 574, 260], fill=(220, 160, 120))  # Subject at x=0.85 (late widening)
                im.save(frames_a / f"f_{i:04d}.jpg")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "15", "-i", str(frames_a / "f_%04d.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_a)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        res_a = analyze_shot_framing_auto(clip_a, 0.0, 3.0, 0.0, 3.0, 1, temp_dir=synth_dir)
        self.assertEqual(res_a["mode"], "fit_background")
        self.assertIn("widening action", res_a["reason"].lower())

        # 2. Subject Jump / Inconsistent Tracking: Subject at x=0.85 jumps abruptly to x=0.10
        clip_b = synth_dir / "subject_jump.mp4"
        if not clip_b.is_file():
            frames_b = synth_dir / "frames_b"
            frames_b.mkdir(exist_ok=True)
            for i in range(45):
                t = i / 15.0
                im = Image.new("RGB", (640, 360), color=(30, 30, 30))
                draw = ImageDraw.Draw(im)
                if t < 1.5:
                    draw.rectangle([514, 100, 574, 260], fill=(220, 160, 120))  # Subject at x=0.85
                else:
                    draw.rectangle([34, 100, 94, 260], fill=(220, 160, 120))   # Jump to x=0.10
                im.save(frames_b / f"f_{i:04d}.jpg")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "15", "-i", str(frames_b / "f_%04d.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip_b)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        res_b = analyze_shot_framing_auto(clip_b, 0.0, 3.0, 0.0, 3.0, 2, temp_dir=synth_dir)
        self.assertEqual(res_b["mode"], "fit_background")
        self.assertTrue(
            "unrelated subjects" in res_b["reason"].lower() or "widening action" in res_b["reason"].lower()
        )

    def test_35_portrait_source_preserves_vertical_framing(self):
        from gta_clipper.visual import analyze_shot_framing_auto
        from gta_clipper.renderer import build_filter_graph
        from PIL import Image, ImageDraw

        synth_dir = self.storage.cache_dir / "test_35_portrait"
        synth_dir.mkdir(parents=True, exist_ok=True)
        portrait_mp4 = synth_dir / "portrait_360x640.mp4"
        if not portrait_mp4.is_file():
            frames_p = synth_dir / "frames_p"
            frames_p.mkdir(exist_ok=True)
            for i in range(30):
                im = Image.new("RGB", (360, 640), color=(25, 40, 70))
                draw = ImageDraw.Draw(im)
                draw.rectangle([40, 120, 320, 520], fill=(220, 160, 120))
                im.save(frames_p / f"f_{i:04d}.jpg")
            subprocess.run([
                "ffmpeg", "-y", "-framerate", "15", "-i", str(frames_p / "f_%04d.jpg"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(portrait_mp4)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        res = analyze_shot_framing_auto(portrait_mp4, 0.0, 2.0, 0.0, 2.0, 1, temp_dir=synth_dir)
        self.assertEqual(res["mode"], "portrait_preserve")
        self.assertEqual(res["crop_source"], "auto")
        self.assertIn("portrait", res["reason"].lower())

        # Verify build_filter_graph never shrinks portrait sources to 1080:608
        f_args, f_type = build_filter_graph(layout="hybrid", shot_framing=[res], source_is_portrait=True)
        self.assertEqual(f_type, "vf")
        self.assertNotIn("1080:608", f_args[1])
        self.assertIn("scale=1080:1920", f_args[1])

    def test_36_gta_highlight_ranking_and_chat_optional(self):
        from gta_clipper.candidates import generate_candidates
        from gta_clipper.audio import analyze_audio
        from gta_clipper.visual import analyze_visual
        from gta_clipper.ranking import load_chat_log

        v_source = self.media["visual_only"]
        audio_res = analyze_audio(v_source, self.storage, source_hash="test_rank_hash")
        visual_res = analyze_visual(v_source)
        job_dir = self.storage.get_job_dir("test_gta_highlight_rank")

        # 1. Without chat log: chat_used must be False, duration independent of style preset
        preset = StylePreset.from_dict(
            json.loads((REPO_ROOT / "config" / "styles" / "viral_streamer_yellow.json").read_text(encoding="utf-8"))
        )
        preset.typical_length = 15.0  # Caption style preset says 15s, but target_duration=30s must stay independent!

        cands_no_chat = generate_candidates(
            video_path=v_source,
            audio_res=audio_res,
            visual_res=visual_res,
            game_config=self.game_config,
            job_dir=job_dir,
            max_candidates=2,
            style_preset=preset,
            ranking_mode="gta_highlight",
            target_duration=30.0,
            min_duration=20.0,
            max_duration=60.0,
            chat_events=None,
            cache_dir=self.storage.cache_dir / "rank_frames_test",
        )
        self.assertGreaterEqual(len(cands_no_chat), 1)
        rb0 = cands_no_chat[0].ranking_breakdown
        self.assertIsNotNone(rb0)
        self.assertEqual(rb0["mode"], "gta_highlight")
        self.assertFalse(rb0["factors"]["chat_used"])
        self.assertIsNone(rb0["factors"]["chat_spike"])
        self.assertGreaterEqual(cands_no_chat[0].duration, 20.0)
        self.assertIn("hook_time", rb0)
        self.assertIn("payoff_time", rb0)
        self.assertIn("dead_time", rb0["penalties"])
        self.assertIn("intro_chatter", rb0["penalties"])
        self.assertIn("repeated_moment", rb0["penalties"])

        # 2. With timestamped chat log supplied: chat_used must be True
        chat_file = self.storage.cache_dir / "test_chat.json"
        chat_file.write_text(json.dumps([
            {"timestamp": 18.0, "count": 40},
            {"timestamp": 20.0, "count": 95},
            {"timestamp": 22.0, "count": 60},
        ]), encoding="utf-8")
        chat_events = load_chat_log(chat_file)
        self.assertEqual(len(chat_events), 3)

        cands_with_chat = generate_candidates(
            video_path=v_source,
            audio_res=audio_res,
            visual_res=visual_res,
            game_config=self.game_config,
            job_dir=job_dir,
            max_candidates=2,
            style_preset=preset,
            ranking_mode="gta_highlight",
            target_duration=30.0,
            min_duration=20.0,
            max_duration=60.0,
            chat_events=chat_events,
            cache_dir=self.storage.cache_dir / "rank_frames_test",
        )
        self.assertGreaterEqual(len(cands_with_chat), 1)
        self.assertTrue(cands_with_chat[0].ranking_breakdown["factors"]["chat_used"])
        self.assertIsNotNone(cands_with_chat[0].ranking_breakdown["factors"]["chat_spike"])


if __name__ == "__main__":
    unittest.main()
