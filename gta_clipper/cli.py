"""Command Line Interface for GTA VI Clipper MVP.
Entry points: doctor, style-preset, discover, analyze, preview, render, test-synth.
"""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import List, Optional, Dict, Any

from .config import (
    StorageConfig, load_game_config, DEFAULT_GAME_ID,
    resolve_export_paths, sanitize_windows_filename
)
from .doctor import run_doctor, print_doctor_summary
from .metadata import create_job_metadata, save_job_metadata, load_job_metadata, JobMetadata
from .audio import analyze_audio, AudioSegment, check_whisper_backend, extract_candidate_audio_pcm, run_transcription
from .visual import analyze_visual, probe_video
from .candidates import generate_candidates, CandidateClip
from .subtitles import generate_subtitles_for_clip, recompute_subtitles_for_trimmed_clip
from .preview import generate_review_artifacts, refresh_contact_sheet
from .renderer import render_clip, RenderOptions, RenderResult
from .style import StylePreset, parse_style_from_notes, extract_style_from_local_media, merge_style_presets


REPO_ROOT = Path(__file__).resolve().parent.parent


def _parse_markers(marker_str: Optional[str]) -> List[float]:
    """Parses comma-separated timestamp strings into floats."""
    if not marker_str:
        return []
    markers = []
    for part in marker_str.split(","):
        try:
            m = float(part.strip())
            if m >= 0:
                markers.append(m)
        except ValueError:
            pass
    return sorted(markers)


def _resolve_style_preset(
    preset_name_or_path: Optional[str],
    ref_file: Optional[str] = None,
    ref_notes: Optional[str] = None,
    ref_url: Optional[str] = None,
) -> StylePreset:
    """Resolves or derives a StylePreset from name, path, local media, or style notes."""
    # 1. Local reference file inspection
    if ref_file:
        rf = Path(ref_file).resolve()
        if rf.is_file():
            return extract_style_from_local_media(rf, notes=ref_notes)

    # 2. Reference notes or URL notes
    if ref_notes or ref_url:
        notes = ref_notes or f"Derived from reference URL: {ref_url}"
        return parse_style_from_notes(notes, source_reference=ref_url)

    # 3. Explicit preset name or file path
    if preset_name_or_path:
        p_path = Path(preset_name_or_path).resolve()
        if p_path.is_file():
            with open(p_path, "r", encoding="utf-8") as f:
                return StylePreset.from_dict(json.load(f))

        # Check config/styles/<name>.json
        style_dir = REPO_ROOT / "config" / "styles"
        named_path = style_dir / f"{preset_name_or_path}.json"
        if named_path.is_file():
            with open(named_path, "r", encoding="utf-8") as f:
                return StylePreset.from_dict(json.load(f))

    # 4. Default to viral_streamer_yellow
    default_path = REPO_ROOT / "config" / "styles" / "viral_streamer_yellow.json"
    if default_path.is_file():
        with open(default_path, "r", encoding="utf-8") as f:
            return StylePreset.from_dict(json.load(f))

    # Fallback in-memory preset
    return parse_style_from_notes(
        "Yellow bold subtitles, rapid cuts, 22s target, center crop",
        preset_id="viral_streamer_yellow",
        name="Viral Streamer Yellow"
    )


# =====================================================================
# CLI Handlers
# =====================================================================

def cmd_doctor(args: argparse.Namespace) -> int:
    storage = StorageConfig(args.data_dir)
    report = run_doctor(storage)
    print_doctor_summary(report)
    return 0 if report["ready_for_visual"] else 1


def cmd_style_preset(args: argparse.Namespace) -> int:
    """Derives, merges, or displays a StylePreset."""
    print("=" * 64)
    print(" GTA VI Clipper — Style Preset Creator & Inspector ")
    print("=" * 64)

    # Two-reference merge mode
    if args.merge_captions_from and args.merge_layout_from:
        cap_preset = _resolve_style_preset(args.merge_captions_from)
        layout_preset = _resolve_style_preset(args.merge_layout_from)
        preset = merge_style_presets(
            cap_preset, layout_preset,
            new_id=args.save or "merged_style",
            new_name=args.name or "Merged Custom Style"
        )
        print(f"[*] Successfully merged styles:")
        print(f"    - Captions from: [{cap_preset.name}]")
        print(f"    - Layout/Pacing from: [{layout_preset.name}]")

    elif args.ref_file:
        rf = Path(args.ref_file).resolve()
        if not rf.is_file():
            print(f"[!] Reference media file not found: {rf}", file=sys.stderr)
            return 1
        print(f"[*] Probing local reference video: {rf.name}...")
        preset = extract_style_from_local_media(
            rf, notes=args.notes, preset_id=args.save or f"ref_{rf.stem[:12]}", name=args.name
        )

    elif args.notes or args.ref_url:
        notes = args.notes or f"Reference URL: {args.ref_url}"
        print(f"[*] Deriving style preset from notes/URL...")
        preset = parse_style_from_notes(
            notes, preset_id=args.save or "custom_notes_style", name=args.name or "Custom Notes Preset",
            source_reference=args.ref_url
        )
    else:
        # Load existing preset
        preset = _resolve_style_preset(args.load or "viral_streamer_yellow")

    # Print summary
    print(f"\n[x] Preset ID:   {preset.preset_id} ({preset.name})")
    print(f"    Layout:      {preset.layout_mode} (Crop X offset: {preset.crop_x_offset_pct})")
    print(f"    Pacing:      {preset.typical_length:.1f}s typical length (Pace: {preset.cut_pace})")
    print(f"    Subtitles:   {preset.font_name} {preset.font_size}pt | Primary: {preset.primary_color} | Outline: {preset.outline_width}px")
    print(f"    Safe Zone:   Margin V: {preset.margin_v}px (TikTok/Reels safe)")
    print(f"    Hook Banner: {preset.hook_style} ({preset.hook_duration:.1f}s)")

    if preset.observed_traits:
        print("\n[*] Observed Traits (Direct visual evidence / explicit notes):")
        for k, v in preset.observed_traits.items():
            print(f"    - {k}: {v}")

    if preset.inferred_traits:
        print("[*] Inferred Traits (Safe sensible defaults):")
        for k, v in preset.inferred_traits.items():
            print(f"    - {k}: {v}")

    if preset.unknown_traits:
        print("[*] Unknown Traits (Not identifiable from reference):")
        for k in preset.unknown_traits:
            print(f"    - {k}")

    # Save to file if requested
    if args.save:
        style_dir = REPO_ROOT / "config" / "styles"
        save_path = style_dir / f"{args.save}.json"
        preset.save(save_path)
        print(f"\n[x] Saved style preset to:\n    {save_path}")

    print("=" * 64)
    return 0


def cmd_discover(args: argparse.Namespace) -> int:
    """Optional reference discovery for viral Shorts/Reels."""
    query = args.query or "GTA V funny streamer reaction Shorts"
    print("=" * 64)
    print(f" GTA VI Clipper — Reference Discovery: '{query}'")
    print("=" * 64)

    # Curated benchmarks and search query leads
    curated_leads = [
        {
            "title": "Joe Bart Reacts to Every GTA 5 Ending",
            "url": "https://www.youtube.com/shorts/KgEhMgfpL_M",
            "style_cue": "Fast streamer laugh, loud reaction spike, yellow center-bottom captions, 23s",
        },
        {
            "title": "Jynxzi Iconic GTA V Reaction & Laugh",
            "url": "https://www.youtube.com/shorts/HasLqsJTWRI",
            "style_cue": "Facecam PiP top-right, animated scream payoff at 14s, high-contrast captions",
        },
        {
            "title": "GTA Online NPC Experiment / Physics Stunt",
            "url": "https://www.youtube.com/shorts/KWxP4-T7nSc",
            "style_cue": "Testing AI reactions, center crop 9:16, top hook banner 'Wait for it...'",
        },
        {
            "title": "GTA VI Vice City Physics Glitch / Car Jump",
            "url": "https://www.youtube.com/shorts/C68VHjdclc8",
            "style_cue": "High speed vehicle flip, explosion payoff, bold white captions with black outline",
        },
    ]

    print("[*] Suggested reference Shorts/Reels for style benchmark:")
    for idx, item in enumerate(curated_leads, 1):
        print(f"\n  {idx}. {item['title']}")
        print(f"     URL: {item['url']}")
        print(f"     Why Relevant: {item['style_cue']}")

    print("\n[i] To derive a style preset from any reference:")
    print('  python -m gta_clipper.cli style-preset --ref-url "<URL>" --notes "Yellow bold subtitles, PiP facecam, 20s" --save my_style')
    print("=" * 64)
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        print(f"[!] Error: Source file not found: {input_path}", file=sys.stderr)
        return 1

    storage = StorageConfig(args.data_dir)
    game_config = load_game_config(args.game)
    markers = _parse_markers(args.markers)

    # 1. Resolve Style Preset
    style_preset = _resolve_style_preset(
        preset_name_or_path=args.style_preset,
        ref_file=args.ref_file,
        ref_notes=args.ref_notes,
        ref_url=args.ref_url,
    )

    print("=" * 64)
    print(f" GTA VI Clipper — Analyzing: {input_path.name}")
    print(f"[*] Style Preset: {style_preset.name} (Layout: {style_preset.layout_mode})")
    print("=" * 64)
    print(f"[*] Storage root (outside OneDrive): {storage.root}")

    # 2. Create Job Metadata & Directory
    metadata = create_job_metadata(
        source_path=input_path,
        source_creator=args.creator,
        source_identifier=args.source_id,
        footage_rights=args.rights,
        permission_reference=args.permission_ref,
        intended_platforms=args.platforms.split(",") if args.platforms else ["tiktok", "instagram_reels", "youtube_shorts"],
        intended_accounts=args.accounts.split(",") if args.accounts else ["@main_clips"],
        known_limits=args.limits,
        game_id=args.game,
        original_source_name=getattr(args, "source_name", None) or input_path.stem,
        original_source_file=str(input_path),
    )
    ranking_mode = getattr(args, "ranking_mode", "default")
    if ranking_mode != "default":
        metadata.job_id = f"{metadata.job_id}_{ranking_mode}"
    job_dir = storage.get_job_dir(metadata.job_id)
    save_job_metadata(metadata, job_dir)
    print(f"[*] Job ID: {metadata.job_id}")
    print(f"[*] Job directory: {job_dir}")

    # 3. Audio Track Selection & Extraction
    track_to_use = args.mic_track if args.mic_track is not None else (args.audio_track or 0)
    ext_transcript = Path(args.transcript).resolve() if args.transcript else None
    provider = getattr(args, "transcription_provider", "local")

    print(f"[*] Extracting audio stream (Track {track_to_use}, provider: {provider})...")
    audio_res = analyze_audio(
        video_path=input_path,
        storage=storage,
        source_hash=metadata.source_hash,
        track_index=track_to_use,
        external_transcript_path=ext_transcript,
        language=args.language,
        transcription_provider=provider,
    )

    if audio_res.has_audio:
        print(f"    - Selected track: Track {track_to_use} ({len(audio_res.audio_tracks)} audio track(s) present)")
        print(f"    - Audio duration: {audio_res.duration:.1f}s | Peaks detected: {len(audio_res.peaks)}")
        print(f"    - Whisper Status: {audio_res.whisper_status} ({audio_res.whisper_diagnostic})")
        if audio_res.is_transcribed:
            print(f"    - Transcribed speech segments: {len(audio_res.transcript_segments)}")
        else:
            print("    - [!] Speech transcription unavailable. Candidates with dialogue will be held awaiting captions.")
        if audio_res.baked_music_flag:
            print("    - [!] Caution: Continuous background music detected; flagged for review.")
    else:
        print("    - [i] No audio stream detected. Proceeding with visual-only analysis.")

    # 4. Visual Stream Inspection
    print("[*] Inspecting video stream & scene transitions...")
    visual_res = analyze_visual(input_path)
    info = visual_res.info
    print(f"    - Dimensions: {info.width}x{info.height}, FPS: {info.fps:.2f}, Codec: {info.video_codec}")
    print(f"    - Scene transitions found: {len(visual_res.scene_changes)}")

    # 5. Generate Candidate Clips using Dual Signals + Style Preset
    chat_events = []
    chat_log_arg = getattr(args, "chat_log", None)
    if chat_log_arg:
        from .ranking import load_chat_log
        chat_events = load_chat_log(Path(chat_log_arg).resolve())
        print(f"[*] Loaded {len(chat_events)} timestamped chat events from {chat_log_arg}")

    target_dur_arg = getattr(args, "target_duration", None)
    min_dur_arg = getattr(args, "min_duration", 20.0)
    max_dur_arg = getattr(args, "max_duration", 60.0)
    if ranking_mode == "gta_highlight":
        eff_target = target_dur_arg if target_dur_arg is not None else 50.0
        print(f"[*] Running Research-Informed GTA Highlight Ranking (target={eff_target:.0f}s, range={min_dur_arg:.0f}-{max_dur_arg:.0f}s, chat={'yes' if chat_events else 'no'})...")
    else:
        print("[*] Evaluating dual signals against style preset & game presets...")

    candidates = generate_candidates(
        video_path=input_path,
        audio_res=audio_res,
        visual_res=visual_res,
        game_config=game_config,
        job_dir=job_dir,
        manual_markers=markers,
        max_candidates=min(args.max_clips, 3),  # Up to 3 vertical draft clips as requested
        style_preset=style_preset,
        ranking_mode=ranking_mode,
        target_duration=target_dur_arg,
        min_duration=min_dur_arg,
        max_duration=max_dur_arg,
        chat_events=chat_events,
        cache_dir=storage.cache_dir / "rank_frames",
    )

    print(f"[*] Generated {len(candidates)} candidate clips (ranked & deduplicated):")
    for c in candidates:
        status_tag = ""
        if c.awaiting_captions:
            status_tag = " [AWAITING CAPTIONS]"
        elif c.is_visual_only:
            status_tag = " [SPEECH-FREE]"
        elif c.uncertain_speech:
            status_tag = " [CHECK SPEECH ACCURACY]"

        print(f"    - [{c.id}] ({c.category_name}) {c.start_time:.2f}s -> {c.end_time:.2f}s ({c.duration:.1f}s){status_tag}")
        print(f"      Confidence: {int(c.confidence*100)}% | Layout: {c.proposed_layout} | Hook: \"{c.hook_text}\"")
        if c.ranking_breakdown:
            rb = c.ranking_breakdown
            print(f"      Ranking Score: {rb['score']:.1f}/100 | Hook @{rb['hook_time']:.2f}s | Payoff @{rb['payoff_time']:.2f}s")
            if rb.get("supports_dual_cut"):
                tc = rb["tight_cut"]
                lc = rb["long_cut"]
                print(f"      Dual-Cut Support: Tight {tc['start']:.2f}s->{tc['end']:.2f}s ({tc['duration']:.1f}s) | Long {lc['start']:.2f}s->{lc['end']:.2f}s ({lc['duration']:.1f}s)")
            print(f"      Evidence: {c.evidence_detail}")
        if c.speech_summary:
            print(f"      Spoken Dialogue: \"{c.speech_summary[:70]}...\"")

    # 5.5. Groq Cloud Whisper Transcription for Candidates
    if provider == "groq":
        from .groq_transcriber import transcribe_candidate_with_groq, get_groq_api_key, check_groq_status
        print("\n[*] Groq cloud transcription enabled: processing candidate audio slices...")
        groq_key = get_groq_api_key(storage)
        if not groq_key:
            status, msg = check_groq_status(storage)
            print(f"    [!] Caution: {msg}")
            for c in candidates:
                c.awaiting_captions = True
                c.speech_summary = "[Awaiting captions: GROQ_API_KEY not configured]"
        else:
            for c in candidates:
                clip_wav = storage.audio_cache_dir / f"{metadata.source_hash}_{c.id}_slice.wav"
                print(f"    [*] Extracting audio slice for {c.id} ({c.duration:.1f}s, Track {track_to_use})...")
                extracted = extract_candidate_audio_pcm(
                    video_path=input_path,
                    output_wav=clip_wav,
                    start_time=c.start_time,
                    duration=c.duration,
                    track_index=track_to_use,
                )
                if extracted:
                    from .groq_transcriber import transcribe_candidate_with_fallback
                    fallback_prov = getattr(args, "fallback_provider", "local")
                    fallback_srt = getattr(args, "transcript", None)
                    print(f"    [*] Calling Groq Whisper API (whisper-large-v3-turbo) with fallback ({fallback_prov})...")
                    segs, status, diag = transcribe_candidate_with_fallback(
                        audio_path=clip_wav,
                        candidate_start_time=c.start_time,
                        api_key=groq_key,
                        storage=storage,
                        language=args.language,
                        fallback_provider=fallback_prov,
                        fallback_srt_path=Path(fallback_srt) if fallback_srt else None,
                    )
                    if segs:
                        c.speech_segments = [s.to_dict() for s in segs]
                        c.speech_summary = " ".join(s.text for s in segs)
                        c.awaiting_captions = False
                        c.is_visual_only = False
                        c.evidence_type = "speech_quote"
                        c.evidence_detail = f'"{c.speech_summary[:60]}..."'
                        audio_res.transcript_segments.extend(segs)
                        audio_res.is_transcribed = True
                        audio_res.whisper_status = status
                        audio_res.whisper_diagnostic = diag
                        print(f"    [x] Successfully transcribed {c.id} ({status}): {len(segs)} segment(s)")
                        print(f"        Spoken dialogue: \"{c.speech_summary}\"")
                    else:
                        c.awaiting_captions = True
                        c.speech_summary = f"[Awaiting captions: {diag}]"
                        print(f"    [!] Transcription held awaiting captions ({status}): {diag}")
                else:
                    c.awaiting_captions = True
                    c.speech_summary = "[Awaiting captions: audio slice extraction failed]"
                    print(f"    [!] Failed to extract audio slice for {c.id}")

    # 6. Generate Subtitles (ASS & SRT) for each candidate
    print("[*] Generating ASS hardsubs and editable SRT files using style typography...")
    subs_dir = job_dir / "subtitles"
    subs_dir.mkdir(parents=True, exist_ok=True)
    for c in candidates:
        ass_file = subs_dir / f"{c.id}.ass"
        srt_file = subs_dir / f"{c.id}.srt"
        generate_subtitles_for_clip(
            transcript_segments=audio_res.transcript_segments,
            clip_start=c.start_time,
            clip_end=c.end_time,
            ass_path=ass_file,
            srt_path=srt_file,
            hook_text=c.hook_text,
            style=style_preset,
        )

    # 7. Generate Review Artifacts (HTML contact sheet + review_sheet.json)
    print("[*] Building review contact sheet and editable JSON manifests...")
    review_json, contact_html = generate_review_artifacts(
        metadata=metadata,
        candidates=candidates,
        job_dir=job_dir,
        style_preset=style_preset,
    )

    print("=" * 64)
    print(" ANALYSIS COMPLETE ")
    print(f"[x] HTML Review Contact Sheet: file:///{contact_html.as_posix()}")
    print(f"[x] Editable Review JSON:      {review_json}")
    print("\nNext step: Open review sheet, verify dialogue wording, then run:")
    print(f'  python -m gta_clipper.cli render --job-dir "{job_dir}"')
    print("=" * 64)

    return 0


def cmd_preview(args: argparse.Namespace) -> int:
    storage = StorageConfig(args.data_dir)
    job_dir = Path(args.job_dir).resolve() if args.job_dir else None

    if not job_dir or not job_dir.is_dir():
        jobs = sorted(storage.jobs_dir.glob("job_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not jobs:
            print("[!] No existing jobs found in storage directory.", file=sys.stderr)
            return 1
        job_dir = jobs[0]

    contact_html = job_dir / "contact_sheet.html"
    if not contact_html.is_file():
        print(f"[!] Contact sheet not found in {job_dir}", file=sys.stderr)
        return 1

    print(f"Review Contact Sheet URL:")
    print(f"file:///{contact_html.as_posix()}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    storage = StorageConfig(args.data_dir)
    job_dir = Path(args.job_dir).resolve() if args.job_dir else None

    if not job_dir or not job_dir.is_dir():
        jobs = sorted(storage.jobs_dir.glob("job_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not jobs:
            print("[!] Error: No job directory specified and no existing jobs found.", file=sys.stderr)
            return 1
        job_dir = jobs[0]

    print("=" * 64)
    print(f" GTA VI Clipper — Rendering Job: {job_dir.name}")
    print("=" * 64)

    meta_file = job_dir / "job_metadata.json"
    if not meta_file.is_file():
        print(f"[!] Error: job_metadata.json not found in {job_dir}", file=sys.stderr)
        return 1

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    source_video = Path(meta["source_file"])
    if not source_video.is_file():
        print(f"[!] Error: Original source video file missing: {source_video}", file=sys.stderr)
        return 1

    review_file = job_dir / "review_sheet.json"
    if not review_file.is_file():
        print(f"[!] Error: review_sheet.json not found in {job_dir}", file=sys.stderr)
        return 1

    with open(review_file, "r", encoding="utf-8") as f:
        review_data = json.load(f)

    raw_clips = review_data.get("clips", [])
    clips = [CandidateClip.from_dict(c) for c in raw_clips]

    # Load style preset if stored in review sheet
    style_dict = review_data.get("style_preset")
    style_preset = StylePreset.from_dict(style_dict) if style_dict else None

    # Load cached audio segments if present for recomputing subtitles on trimmed clips
    cached_transcript = storage.transcript_cache_dir / f"{meta.get('source_hash')}_t0.json"
    all_segs = []
    if cached_transcript.is_file():
        try:
            with open(cached_transcript, "r", encoding="utf-8") as f:
                all_segs = [AudioSegment(**item) for item in json.load(f)]
        except Exception:
            pass

    if args.clip_id:
        clips = [c for c in clips if c.id == args.clip_id]
        if not clips:
            print(f"[!] Clip ID '{args.clip_id}' not found in review sheet.", file=sys.stderr)
            return 1

    active_clips = [c for c in clips if not c.rejected]
    print(f"[*] Rendering {len(active_clips)} active clip(s)...")

    intermediate_export_dir = storage.get_export_dir(job_dir.name)
    export_outside_onedrive = getattr(args, "export_outside_onedrive", False)
    custom_export_dir = Path(args.export_dir).resolve() if getattr(args, "export_dir", None) else None

    # Determine project export folder for final deliverables
    project_export_dir, _, _ = resolve_export_paths(
        metadata=meta,
        clip_id="clip_01",
        export_outside_onedrive=export_outside_onedrive,
        custom_export_dir=custom_export_dir,
        storage=storage,
        repo_root=REPO_ROOT,
    )
    print(f"[*] Final Deliverables Destination: {project_export_dir}")

    results: List[RenderResult] = []
    for c in active_clips:
        print(f"\n[*] Rendering {c.id}: {c.title} ({c.duration:.1f}s)...")

        # 1. Caption Guardrail Check
        if c.awaiting_captions and not args.allow_uncaptioned:
            print(
                f"    [!] Error: Clip '{c.id}' is awaiting captions. "
                "Download Whisper model or supply an SRT transcript before export.",
                file=sys.stderr
            )
            results.append(RenderResult(
                clip_id=c.id, output_path="", srt_path=None, duration_seconds=c.duration,
                file_size_bytes=0, render_time_seconds=0.0, layout_used=c.proposed_layout,
                title=c.title, posting_caption=c.posting_caption, success=False,
                error="Awaiting captions: transcription required before export"
            ))
            continue

        # 2. Subtitle file resolution & recomputation on trimmed clip
        subs_dir = job_dir / "subtitles"
        ass_path = subs_dir / f"{c.id}.ass"
        srt_path = subs_dir / f"{c.id}.srt"

        if all_segs and (not ass_path.is_file() or args.force):
            recompute_subtitles_for_trimmed_clip(
                clip_dict=c.to_dict(),
                all_transcript_segments=all_segs,
                ass_path=ass_path,
                srt_path=srt_path,
                style=style_preset,
            )

        layout_to_use = args.layout or (style_preset.layout_mode if style_preset else None) or c.proposed_layout or "center_crop"
        burn_subs = (not args.no_subtitles) and ass_path.is_file() and (not c.is_visual_only)

        suffix = getattr(args, "suffix", None)
        if not suffix and args.layout:
            if args.layout == "fit_background":
                suffix = "fit_bg"
            elif args.layout == "follow_crop":
                suffix = "follow_crop"
            elif args.layout == "hybrid":
                suffix = "hybrid"
            elif args.layout != (c.proposed_layout or "center_crop"):
                suffix = args.layout

        # Automatic framing analysis if requested or when suffix is auto_hybrid / auto_hybrid_v2
        auto_framing = getattr(args, "auto_framing", False) or (suffix and "auto_hybrid" in suffix)
        if auto_framing or (layout_to_use == "hybrid" and (not c.shot_framing or not any(s.get("crop_source") == "manual" for s in c.shot_framing))):
            from .visual import compute_clip_shot_framing
            c.shot_framing = compute_clip_shot_framing(
                video_path=source_video,
                clip_start=c.start_time,
                clip_end=c.end_time,
                scene_changes=None,
                manual_keyframes=None,
                auto_framing=True,
            )
            # Update clip file and review sheet with new framing
            clip_file = job_dir / "clips" / f"{c.id}.json"
            if clip_file.is_file():
                try:
                    with open(clip_file, "r", encoding="utf-8") as f:
                        cf_data = json.load(f)
                    cf_data["shot_framing"] = c.shot_framing
                    with open(clip_file, "w", encoding="utf-8") as f:
                        json.dump(cf_data, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass

        # Print per-shot breakdown
        if c.shot_framing:
            print("    [+] Shot Framing Breakdown:")
            for s in c.shot_framing:
                s_num = s.get("shot", 1)
                t_start = s.get("start", 0.0)
                t_end = s.get("end", 0.0)
                s_mode = s.get("mode", "follow_crop")
                s_src = s.get("crop_source", "auto")
                crop_pct = s.get("crop_x_pct", 0.50)
                reason = s.get("reason", "")
                smooth_str = f" -> smooth to {s['smooth_to']:.2f}" if "smooth_to" in s else ""
                print(f"        Shot {s_num:02d} ({t_start:5.2f}s -> {t_end:5.2f}s): {s_mode:14s} [{s_src.upper()}] crop_x={crop_pct:.2f}{smooth_str} -- {reason}")

        opts = RenderOptions(
            layout=layout_to_use,
            crop_x_offset_pct=args.crop_offset if args.crop_offset is not None else 0.5,
            shot_framing=c.shot_framing,
            burn_subtitles=burn_subs,
            ass_path=ass_path if burn_subs else None,
            mute_audio=args.mute,
            audio_track_index=args.audio_track if args.audio_track is not None else 0,
            force_reencode=args.force,
            allow_uncaptioned=args.allow_uncaptioned,
            style_preset=style_preset,
            facecam_confirmed=c.has_facecam,
            suffix=suffix,
        )

        # Resolve target deliverable names
        final_dir, mp4_name, srt_name = resolve_export_paths(
            metadata=meta,
            clip_id=c.id,
            export_outside_onedrive=export_outside_onedrive,
            custom_export_dir=custom_export_dir,
            storage=storage,
            repo_root=REPO_ROOT,
            suffix=suffix,
        )
        final_mp4 = final_dir / mp4_name
        final_srt = final_dir / srt_name
        final_meta = final_mp4.with_suffix(".render_meta.json")

        from .renderer import compute_render_fingerprint
        expected_fingerprint = compute_render_fingerprint(c, opts, source_video)

        intermediate_suffix = f"_{suffix}" if suffix else ""
        intermediate_mp4 = intermediate_export_dir / f"{c.id}_1080x1920{intermediate_suffix}.mp4"
        intermediate_meta = intermediate_mp4.with_suffix(".render_meta.json")

        def has_valid_fingerprint(m_file: Path) -> bool:
            if not m_file.is_file():
                return False
            try:
                with open(m_file, "r", encoding="utf-8") as f:
                    return json.load(f).get("fingerprint") == expected_fingerprint
            except Exception:
                return False

        # Check for reuse of existing renders with fingerprint validation
        can_reuse_final = (
            final_mp4.is_file()
            and final_mp4.stat().st_size > 1000
            and not args.force
            and has_valid_fingerprint(final_meta)
        )
        can_reuse_intermediate = (
            intermediate_mp4.is_file()
            and intermediate_mp4.stat().st_size > 1000
            and not args.force
            and has_valid_fingerprint(intermediate_meta)
        )

        t_start = time.time()
        if can_reuse_final:
            res = RenderResult(
                clip_id=c.id,
                output_path=str(final_mp4),
                srt_path=str(final_srt) if final_srt.is_file() else None,
                duration_seconds=c.duration,
                file_size_bytes=final_mp4.stat().st_size,
                render_time_seconds=0.001,
                layout_used=layout_to_use,
                title=c.title,
                posting_caption=c.posting_caption,
                success=True,
            )
            print(f"    [x] Reusing existing final deliverable (0.00s): {final_mp4.name}")
        elif can_reuse_intermediate:
            shutil.copy2(intermediate_mp4, final_mp4)
            if srt_path.is_file():
                shutil.copy2(srt_path, final_srt)
            if intermediate_meta.is_file():
                shutil.copy2(intermediate_meta, final_meta)
            render_time = round(time.time() - t_start, 3)
            res = RenderResult(
                clip_id=c.id,
                output_path=str(final_mp4),
                srt_path=str(final_srt) if final_srt.is_file() else None,
                duration_seconds=c.duration,
                file_size_bytes=final_mp4.stat().st_size,
                render_time_seconds=render_time,
                layout_used=layout_to_use,
                title=c.title,
                posting_caption=c.posting_caption,
                success=True,
            )
            print(f"    [x] Reusing existing render and copied to deliverables ({render_time:.2f}s): {final_mp4.name}")
        else:
            # Render via FFmpeg
            res = render_clip(
                source_video=source_video,
                clip=c,
                output_dir=intermediate_export_dir,
                options=opts,
            )
            if res.success and Path(res.output_path).is_file():
                shutil.copy2(res.output_path, final_mp4)
                if srt_path.is_file():
                    shutil.copy2(srt_path, final_srt)
                rendered_meta = Path(res.output_path).with_suffix(".render_meta.json")
                if rendered_meta.is_file():
                    shutil.copy2(rendered_meta, final_meta)
                res.output_path = str(final_mp4)
                res.srt_path = str(final_srt) if final_srt.is_file() else None

        results.append(res)
        if res.success:
            print(f"    [x] Full Deliverable MP4: {final_mp4.resolve()}")
            if final_srt.is_file():
                print(f"    [x] Full Deliverable SRT: {final_srt.resolve()}")
            print(f"        Size: {res.file_size_bytes / 1024 / 1024:.2f} MB | Render/Copy time: {res.render_time_seconds:.2f}s")
            print(f"        Layout: {res.layout_used} | Subtitles: {'Burned' if opts.burn_subtitles else 'None'}")
        else:
            print(f"    [!] Failed to render {c.id}: {res.error}")

    manifest_path = project_export_dir / "job_manifest.json"
    manifest_data = {
        "job_id": job_dir.name,
        "source_file": str(source_video),
        "source_hash": meta.get("source_hash"),
        "style_preset": style_preset.to_dict() if style_preset else None,
        "total_clips_rendered": len([r for r in results if r.success]),
        "results": [r.to_dict() for r in results],
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    # Also keep a copy of manifest in intermediate export dir
    intermediate_manifest = intermediate_export_dir / "job_manifest.json"
    with open(intermediate_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2)

    print("\n" + "=" * 64)
    print(" EXPORT COMPLETE ")
    print(f"[x] Deliverables Folder: {project_export_dir.resolve()}")
    print(f"[x] Job Manifest:        {manifest_path.resolve()}")
    print("=" * 64)

    return 0 if all(r.success for r in results) else 1


def cmd_transcribe_clip(args: argparse.Namespace) -> int:
    """Transcribes a specific candidate clip using Groq Whisper API or local Whisper."""
    storage = StorageConfig(args.data_dir)
    job_dir = Path(args.job_dir).resolve()
    if not job_dir.is_dir():
        print(f"[!] Error: Job directory not found: {job_dir}", file=sys.stderr)
        return 1

    meta_file = job_dir / "job_metadata.json"
    if not meta_file.is_file():
        print(f"[!] Error: job_metadata.json not found in {job_dir}", file=sys.stderr)
        return 1

    with open(meta_file, "r", encoding="utf-8") as f:
        meta = json.load(f)

    source_path = Path(meta["source_file"]).resolve()
    if not source_path.is_file():
        print(f"[!] Error: Source video not found: {source_path}", file=sys.stderr)
        return 1

    clip_id = args.clip_id or "clip_01"
    clip_file = job_dir / "clips" / f"{clip_id}.json"
    if not clip_file.is_file():
        print(f"[!] Error: Candidate clip {clip_id} not found in {job_dir / 'clips'}", file=sys.stderr)
        return 1

    with open(clip_file, "r", encoding="utf-8") as f:
        clip_data = json.load(f)
    clip = CandidateClip.from_dict(clip_data)

    print("=" * 64)
    print(f" GTA VI Clipper — Transcribing Clip: {clip.id}")
    print(f"[*] Time Range: {clip.start_time:.1f}s -> {clip.end_time:.1f}s ({clip.duration:.1f}s)")
    print(f"[*] Provider:   {args.provider}")
    print("=" * 64)

    # 1. Extract audio slice
    track_to_use = getattr(args, "mic_track", None)
    if track_to_use is None:
        track_to_use = 0
    slice_wav = storage.audio_cache_dir / f"{meta.get('source_hash')}_{clip.id}_slice.wav"
    print(f"[*] Extracting audio slice ({clip.duration:.1f}s) from {source_path.name}...")
    extracted = extract_candidate_audio_pcm(
        video_path=source_path,
        output_wav=slice_wav,
        start_time=clip.start_time,
        duration=clip.duration,
        track_index=track_to_use,
    )
    if not extracted:
        print("[!] Failed to extract audio slice from source video", file=sys.stderr)
        return 1

    # 2. Call transcription provider
    fallback_provider = getattr(args, "fallback_provider", "local")
    fallback_srt = getattr(args, "fallback_srt", None)
    if args.provider == "groq":
        from .groq_transcriber import transcribe_candidate_with_fallback
        print(f"[*] Calling Groq Whisper API (whisper-large-v3-turbo) with fallback ({fallback_provider})...")
        segs, status, diag = transcribe_candidate_with_fallback(
            audio_path=slice_wav,
            candidate_start_time=clip.start_time,
            storage=storage,
            language=args.language,
            fallback_provider=fallback_provider,
            fallback_srt_path=Path(fallback_srt) if fallback_srt else None,
        )
        if not segs:
            print(f"[!] Transcription failed or held awaiting captions ({status}):\n    {diag}", file=sys.stderr)
            return 1
    else:
        # Local whisper fallback
        segs, status, diag = run_transcription(
            wav_path=slice_wav,
            storage=storage,
            cache_key=f"{meta.get('source_hash')}_{clip.id}_local",
            language=args.language,
        )
        for s in segs:
            s.start += clip.start_time
            s.end += clip.start_time

    # 3. Update candidate
    clip.speech_segments = [s.to_dict() for s in segs]
    clip.speech_summary = " ".join(s.text for s in segs)
    clip.awaiting_captions = False
    clip.is_visual_only = False
    clip.evidence_type = "speech_quote"
    clip.evidence_detail = f'"{clip.speech_summary[:60]}..."'

    # Save clip JSON
    with open(clip_file, "w", encoding="utf-8") as f:
        json.dump(clip.to_dict(), f, indent=2, ensure_ascii=False)

    # 4. Re-generate ASS and SRT
    review_sheet_path = job_dir / "review_sheet.json"
    style_preset = None
    if review_sheet_path.is_file():
        with open(review_sheet_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)
            if rdata.get("style_preset"):
                style_preset = StylePreset.from_dict(rdata["style_preset"])
            for idx, c_dict in enumerate(rdata.get("clips", [])):
                if c_dict.get("id") == clip.id:
                    rdata["clips"][idx] = clip.to_dict()
        with open(review_sheet_path, "w", encoding="utf-8") as f:
            json.dump(rdata, f, indent=2, ensure_ascii=False)

    subs_dir = job_dir / "subtitles"
    subs_dir.mkdir(parents=True, exist_ok=True)
    ass_path = subs_dir / f"{clip.id}.ass"
    srt_path = subs_dir / f"{clip.id}.srt"
    generate_subtitles_for_clip(
        transcript_segments=segs,
        clip_start=clip.start_time,
        clip_end=clip.end_time,
        ass_path=ass_path,
        srt_path=srt_path,
        hook_text=clip.hook_text,
        style=style_preset,
    )

    # 5. Refresh HTML review sheet
    if review_sheet_path.is_file():
        with open(review_sheet_path, "r", encoding="utf-8") as f:
            rdata = json.load(f)
            clips_list = [CandidateClip.from_dict(c) for c in rdata.get("clips", [])]
            metadata = load_job_metadata(job_dir)
            try:
                refresh_contact_sheet(metadata, clips_list, job_dir, style_preset=style_preset)
            except OSError as error:
                print(f"[!] Captions saved, but the HTML review page could not be refreshed: {error}", file=sys.stderr)

    print(f"[x] Successfully transcribed {clip.id}:")
    print(f"    Segments: {len(segs)}")
    print(f"    Dialogue: \"{clip.speech_summary}\"")
    print(f"    Subtitles updated: {ass_path}")
    print(f"    SRT updated:       {srt_path}")
    print("=" * 64)
    return 0


def cmd_test_synth(args: argparse.Namespace) -> int:
    from tests.generate_test_media import build_synthetic_visual_video, build_synthetic_speech_video
    storage = StorageConfig(args.data_dir)
    out_path = Path(args.output).resolve() if args.output else (storage.root / "test_sources" / f"synth_{args.mode}.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"[*] Generating synthetic test video ({args.mode}) at:\n    {out_path}")
    if args.mode == "visual_only":
        ok = build_synthetic_visual_video(out_path, duration=40, impact_time=20.0)
    else:
        ok = build_synthetic_speech_video(out_path, duration=35)

    if ok:
        print(f"[x] Successfully created: {out_path} ({out_path.stat().st_size / 1024 / 1024:.2f} MB)")
        return 0
    else:
        print(f"[!] Failed to generate synthetic video", file=sys.stderr)
        return 1


# =====================================================================
# Main Parser
# =====================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="gta_clipper",
        description="GTA VI Clipping MVP — Reference Reel to Captioned Stream Clips."
    )
    parser.add_argument("--data-dir", help="Custom local data directory outside OneDrive")

    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. doctor
    sub_doctor = subparsers.add_parser("doctor", help="Inspect environment, FFmpeg, codecs, and Whisper support")
    sub_doctor.set_defaults(func=cmd_doctor)

    # 2. style-preset
    sub_style = subparsers.add_parser("style-preset", help="Create, inspect, or merge style presets from references/notes")
    sub_style.add_argument("--notes", help="Text description of reference Reel style")
    sub_style.add_argument("--ref-file", help="Path to local reference MP4 for visual/pacing probe")
    sub_style.add_argument("--ref-url", help="Public Instagram Reel or YouTube Short URL")
    sub_style.add_argument("--load", help="Load existing preset name or path")
    sub_style.add_argument("--save", help="Save derived preset under name (e.g. viral_stunt)")
    sub_style.add_argument("--name", help="Display name for preset")
    sub_style.add_argument("--merge-captions-from", help="First reference preset (controls captions)")
    sub_style.add_argument("--merge-layout-from", help="Second reference preset (controls layout/pacing)")
    sub_style.set_defaults(func=cmd_style_preset)

    # 3. discover
    sub_discover = subparsers.add_parser("discover", help="Discover public reference Shorts/Reels by keyword")
    sub_discover.add_argument("--query", "-q", help="Search query (e.g. 'GTA V funny streamer reaction Shorts')")
    sub_discover.set_defaults(func=cmd_discover)

    # 4. analyze
    sub_analyze = subparsers.add_parser("analyze", help="Import stream recording, analyze signals, propose captioned clips")
    sub_analyze.add_argument("--input", "-i", required=True, help="Path to raw gaming recording (MP4 or MKV)")
    sub_analyze.add_argument("--style-preset", help="Style preset name or path (default: viral_streamer_yellow)")
    sub_analyze.add_argument("--ref-notes", help="Quick style notes to apply on the fly")
    sub_analyze.add_argument("--ref-file", help="Local reference video file for style probe")
    sub_analyze.add_argument("--ref-url", help="Public reference Reel/Short URL")
    sub_analyze.add_argument("--mic-track", type=int, help="Audio track index for streamer microphone (e.g. 1)")
    sub_analyze.add_argument("--audio-track", type=int, help="Audio track index to analyze (alias for --mic-track)")
    sub_analyze.add_argument("--transcript", help="Path to existing SRT or JSON transcript file")
    sub_analyze.add_argument("--transcription-provider", default="local", choices=["local", "groq", "none"], help="Transcription backend: 'local' (whisper.cpp), 'groq' (cloud whisper-large-v3-turbo), or 'none'")
    sub_analyze.add_argument("--fallback-provider", default="local", choices=["local", "srt", "freellmapi", "none"], help="Fallback provider on cloud rate-limit / quota exhaustion (default: local)")
    sub_analyze.add_argument("--language", help="Optional language hint for transcription (e.g. 'en')")
    sub_analyze.add_argument("--creator", default="Unknown Streamer", help="Source creator / streamer handle")
    sub_analyze.add_argument("--source-id", default="Direct Recording", help="Source URL, stream ID, or file info")
    sub_analyze.add_argument("--source-name", help="Original input video name for clean deliverable naming (defaults to filename)")
    sub_analyze.add_argument("--rights", default="creator_supplied", choices=["owned", "creator_supplied", "approved", "fair_use_review"], help="Footage ownership status")
    sub_analyze.add_argument("--permission-ref", default="Streamer Agreement", help="Permission reference / license note")
    sub_analyze.add_argument("--platforms", default="tiktok,instagram_reels,youtube_shorts", help="Comma-separated target platforms")
    sub_analyze.add_argument("--accounts", default="@main_shorts", help="Comma-separated intended account handles")
    sub_analyze.add_argument("--limits", default="No story cutscene leaks; check radio music", help="Known rights limits or embargoes")
    sub_analyze.add_argument("--markers", help="Optional comma-separated key timestamps (e.g. 14.5,42.0)")
    sub_analyze.add_argument("--max-clips", type=int, default=3, help="Maximum candidate clips to propose (default 3)")
    sub_analyze.add_argument("--game", default=DEFAULT_GAME_ID, help="Game configuration preset (default: gtavi)")
    sub_analyze.add_argument("--ranking-mode", default="default", choices=["default", "gta_highlight"], help="Highlight ranking engine: 'default' or research-informed 'gta_highlight'")
    sub_analyze.add_argument("--target-duration", type=float, help="Target clip duration in seconds (e.g. 45-60s), independent of caption style preset")
    sub_analyze.add_argument("--min-duration", type=float, default=20.0, help="Minimum clip duration in seconds (default: 20.0)")
    sub_analyze.add_argument("--max-duration", type=float, default=60.0, help="Maximum clip duration in seconds (default: 60.0)")
    sub_analyze.add_argument("--chat-log", help="Optional timestamped chat JSON file to include chat spike signals")
    sub_analyze.set_defaults(func=cmd_analyze)

    # 5. transcribe-clip
    sub_transcribe = subparsers.add_parser("transcribe-clip", help="Transcribe a candidate clip using Groq Whisper or local Whisper")
    sub_transcribe.add_argument("--job-dir", required=True, help="Path to job directory")
    sub_transcribe.add_argument("--clip-id", default="clip_01", help="Clip ID to transcribe (default: clip_01)")
    sub_transcribe.add_argument("--provider", default="groq", choices=["groq", "local"], help="Transcription provider (default: groq)")
    sub_transcribe.add_argument("--fallback-provider", default="local", choices=["local", "srt", "freellmapi", "none"], help="Fallback provider on cloud rate-limit / quota exhaustion (default: local)")
    sub_transcribe.add_argument("--fallback-srt", help="Path to fallback SRT file if provider is srt")
    sub_transcribe.add_argument("--mic-track", type=int, help="Audio track index for streamer microphone")
    sub_transcribe.add_argument("--language", help="Optional language hint (e.g. 'en')")
    sub_transcribe.set_defaults(func=cmd_transcribe_clip)

    # 6. preview
    sub_preview = subparsers.add_parser("preview", help="Show review contact sheet URL")
    sub_preview.add_argument("--job-dir", help="Path to specific job directory")
    sub_preview.set_defaults(func=cmd_preview)

    # 6. render
    sub_render = subparsers.add_parser("render", help="Render approved clips to 1080x1920 vertical MP4s with burned subtitles")
    sub_render.add_argument("--job-dir", help="Path to job directory (defaults to latest)")
    sub_render.add_argument("--clip-id", help="Render only a specific clip ID (e.g. clip_01)")
    sub_render.add_argument("--layout", choices=["center_crop", "fit_background", "manual_crop", "pip", "follow_crop", "hybrid"], help="Override layout mode")
    sub_render.add_argument("--auto-framing", action="store_true", help="Automatically analyze and determine per-shot framing from footage")
    sub_render.add_argument("--crop-offset", type=float, help="Manual crop X offset ratio (0.0=left to 1.0=right)")
    sub_render.add_argument("--suffix", help="Custom filename suffix for export (e.g. 'fit_bg' or 'follow_crop')")
    sub_render.add_argument("--no-subtitles", action="store_true", help="Disable burning ASS subtitles")
    sub_render.add_argument("--mute", action="store_true", help="Mute audio in exported video")
    sub_render.add_argument("--audio-track", type=int, help="Select audio track index for final render")
    sub_render.add_argument("--allow-uncaptioned", action="store_true", help="Bypass caption guardrail for uncaptioned dialogue clips")
    sub_render.add_argument("--force", action="store_true", help="Force re-rendering existing clips")
    sub_render.add_argument("--export-outside-onedrive", action="store_true", help="Export deliverables to local data directory outside OneDrive instead of GTA_clipping/exports/")
    sub_render.add_argument("--export-dir", help="Custom destination directory for deliverables")
    sub_render.set_defaults(func=cmd_render)

    # 7. test-synth
    sub_synth = subparsers.add_parser("test-synth", help="Generate synthetic test video")
    sub_synth.add_argument("--mode", default="visual_only", choices=["visual_only", "with_speech"], help="Type of synthetic video")
    sub_synth.add_argument("--output", "-o", help="Output path for synthetic video")
    sub_synth.set_defaults(func=cmd_test_synth)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
