"""Dual-signal candidate generation, ranking, and deduplication for GTA VI clipping.
Supports style presets, speech verification guardrails, and multi-reference cues.
"""

from __future__ import annotations
import dataclasses
import json
import math
from pathlib import Path
from typing import List, Dict, Any, Optional

from .audio import AudioAnalysisResult, AudioSegment, REACTION_KEYWORDS
from .visual import VisualAnalysisResult, extract_thumbnail_frame, compute_clip_shot_framing
from .style import StylePreset


@dataclasses.dataclass
class CandidateClip:
    id: str
    category_id: str
    category_name: str
    start_time: float
    end_time: float
    duration: float
    payoff_time: float
    hook_lead_seconds: float
    cue: str
    reason: str
    evidence_type: str  # "speech_quote" | "visual_frame" | "audio_energy" | "manual_marker"
    evidence_detail: str
    confidence: float
    proposed_layout: str  # "center_crop" | "fit_background" | "manual_crop" | "pip" | "follow_crop"
    hook_text: str
    title: str
    description: str
    posting_caption: str
    spoiler_flag: bool
    music_review_flag: bool
    preview_frames: Dict[str, str]
    rejected: bool = False
    operator_notes: str = ""
    # 3-part storytelling timestamps (YouTube Shorts & Reels best practice)
    setup_start_time: float = 0.0
    setup_end_time: float = 0.0
    action_start_time: float = 0.0
    action_end_time: float = 0.0
    payoff_start_time: float = 0.0
    payoff_end_time: float = 0.0
    # Dynamic per-shot framing and facecam confirmation
    shot_framing: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    has_facecam: bool = False
    facecam_rect: Optional[Dict[str, float]] = None
    framing_override: Optional[Dict[str, Any]] = None
    # Speech & caption verification guardrails
    awaiting_captions: bool = False
    is_visual_only: bool = False
    uncertain_speech: bool = False
    speech_summary: str = ""
    speech_segments: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    # Research-informed highlight ranking breakdown & dual-cut metadata
    ranking_breakdown: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CandidateClip:
        # Gracefully handle older dicts missing new fields
        fields = {f.name for f in dataclasses.fields(cls)}
        clean_data = {k: v for k, v in data.items() if k in fields}
        return cls(**clean_data)


def _compute_overlap_ratio(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    """Calculates Intersection-over-Union (IoU) of two time ranges."""
    intersection = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return (intersection / union) if union > 0 else 0.0


def _align_to_silence(target_time: float, silence_ranges: List[tuple[float, float]], max_shift: float = 1.5) -> float:
    """Snaps a timestamp to a nearby silence boundary to avoid cutting speech."""
    for s_start, s_end in silence_ranges:
        if abs(target_time - s_start) <= max_shift:
            return s_start
        if abs(target_time - s_end) <= max_shift:
            return s_end
    return target_time


def generate_candidates(
    video_path: Path,
    audio_res: AudioAnalysisResult,
    visual_res: VisualAnalysisResult,
    game_config: Dict[str, Any],
    job_dir: Path,
    manual_markers: Optional[List[float]] = None,
    max_candidates: int = 5,
    style_preset: Optional[StylePreset] = None,
    ranking_mode: str = "default",
    target_duration: Optional[float] = None,
    min_duration: float = 20.0,
    max_duration: float = 60.0,
    chat_events: Optional[List[tuple[float, float]]] = None,
    cache_dir: Optional[Path] = None,
) -> List[CandidateClip]:
    """Generates, scores, ranks, and deduplicates candidate clips from dual signals.
    When ranking_mode == 'gta_highlight', runs research-informed GTA highlight ranking
    with configurable duration independent of the caption style preset.
    """
    if ranking_mode == "gta_highlight":
        from .ranking import rank_gta_highlights, HighlightDurationConfig
        dur_cfg = HighlightDurationConfig(
            target_duration=target_duration if target_duration is not None else 50.0,
            min_duration=min_duration,
            max_duration=max_duration,
        )
        return rank_gta_highlights(
            video_path=video_path,
            audio_res=audio_res,
            visual_res=visual_res,
            game_config=game_config,
            job_dir=job_dir,
            max_candidates=max_candidates,
            style_preset=style_preset,
            duration_config=dur_cfg,
            chat_events=chat_events,
            manual_markers=manual_markers,
            cache_dir=cache_dir,
        )

    total_duration = visual_res.info.duration
    categories = game_config.get("categories", [])
    cat_by_id = {c["id"]: c for c in categories}

    # Explicit --target-duration is independent of the caption style preset
    target_duration_override = target_duration if target_duration is not None else (
        style_preset.typical_length if style_preset else None
    )
    layout_override = style_preset.layout_mode if style_preset else None

    raw_candidates: List[CandidateClip] = []

    # 1. Evaluate Manual Markers (highest confidence)
    if manual_markers:
        for idx, m in enumerate(manual_markers):
            if 0 <= m <= total_duration:
                cat = cat_by_id.get("unexpected_gameplay_stunt", categories[0])
                pre_roll = cat.get("pre_roll", 3.5)
                target_dur = target_duration_override or cat.get("target_duration", 22.0)
                start_t = max(0.0, m - pre_roll)
                end_t = min(total_duration, start_t + target_dur)
                dur = round(end_t - start_t, 2)
                if dur >= 10.0:
                    raw_candidates.append(CandidateClip(
                        id=f"clip_marker_{idx+1}",
                        category_id=cat["id"],
                        category_name=cat["name"],
                        start_time=round(start_t, 2),
                        end_time=round(end_t, 2),
                        duration=dur,
                        payoff_time=round(m, 2),
                        hook_lead_seconds=3.0,
                        cue="Operator manual bookmark",
                        reason=f"Operator manually marked key event at {m:.1f}s",
                        evidence_type="manual_marker",
                        evidence_detail=f"Timestamp {m:.2f}s",
                        confidence=0.95,
                        proposed_layout=layout_override or cat.get("default_layout", "center_crop"),
                        hook_text=cat["suggested_hooks"][0] if cat.get("suggested_hooks") else "Watch this moment",
                        title=f"Insane GTA 6 Moment at {int(m)}s!",
                        description="Key GTA VI gameplay highlight marked during review. #GTA6 #Gaming #Shorts",
                        posting_caption="You won't believe what happened here 🤯 #GTA6",
                        spoiler_flag=False,
                        music_review_flag=audio_res.baked_music_flag,
                        preview_frames={},
                        awaiting_captions=False,
                        is_visual_only=False,
                    ))

    # 2. Evaluate Audio/Speech Peaks & Reactions
    if audio_res.has_audio:
        # Check transcript reaction phrases
        for seg in audio_res.transcript_segments:
            text_lower = seg.text.lower()
            matching_keywords = [kw for kw in REACTION_KEYWORDS if kw in text_lower]
            if matching_keywords:
                cat = cat_by_id.get("creator_reaction_with_context", categories[-1])
                pre_roll = cat.get("pre_roll", 4.5)
                target_dur = target_duration_override or cat.get("target_duration", 20.0)
                payoff = seg.start + (seg.end - seg.start) / 2.0
                start_t = max(0.0, payoff - pre_roll)
                end_t = min(total_duration, start_t + target_dur)
                start_t = _align_to_silence(start_t, audio_res.silence_ranges)
                end_t = _align_to_silence(end_t, audio_res.silence_ranges)
                dur = round(end_t - start_t, 2)

                if 12.0 <= dur <= 35.0:
                    raw_candidates.append(CandidateClip(
                        id=f"clip_speech_{len(raw_candidates)+1}",
                        category_id=cat["id"],
                        category_name=cat["name"],
                        start_time=round(start_t, 2),
                        end_time=round(end_t, 2),
                        duration=dur,
                        payoff_time=round(payoff, 2),
                        hook_lead_seconds=3.0,
                        cue=f"Creator reaction quote: '{matching_keywords[0]}'",
                        reason=f"Spoken reaction '{seg.text}' with gameplay lead-up",
                        evidence_type="speech_quote",
                        evidence_detail=f'"{seg.text}" ({seg.start:.1f}s - {seg.end:.1f}s)',
                        confidence=0.88,
                        proposed_layout=layout_override or cat.get("default_layout", "pip"),
                        hook_text=cat["suggested_hooks"][0] if cat.get("suggested_hooks") else "His reaction says it all 😭",
                        title="Bro lost his mind playing GTA 6 😭",
                        description=f"GTA VI gameplay reaction: {seg.text} #GTA6 #Shorts #Gaming",
                        posting_caption=f"Bro was NOT ready for that 💀 '{seg.text}' #GTA6",
                        spoiler_flag=False,
                        music_review_flag=audio_res.baked_music_flag,
                        preview_frames={},
                        awaiting_captions=False,
                        is_visual_only=False,
                        uncertain_speech=seg.uncertain,
                        speech_summary=seg.text,
                    ))

        # Check raw audio loudness spikes (e.g. crashes/shouting)
        for peak in audio_res.peaks:
            cat = cat_by_id.get("unexpected_gameplay_stunt", categories[0])
            pre_roll = cat.get("pre_roll", 3.5)
            target_dur = target_duration_override or cat.get("target_duration", 22.0)
            payoff = peak.timestamp
            start_t = max(0.0, payoff - pre_roll)
            end_t = min(total_duration, start_t + target_dur)
            start_t = _align_to_silence(start_t, audio_res.silence_ranges)
            end_t = _align_to_silence(end_t, audio_res.silence_ranges)
            dur = round(end_t - start_t, 2)

            if 12.0 <= dur <= 35.0:
                raw_candidates.append(CandidateClip(
                    id=f"clip_audio_{len(raw_candidates)+1}",
                    category_id=cat["id"],
                    category_name=cat["name"],
                    start_time=round(start_t, 2),
                    end_time=round(end_t, 2),
                    duration=dur,
                    payoff_time=round(payoff, 2),
                    hook_lead_seconds=3.0,
                    cue=f"Audio loudness surge (+{peak.relative_prominence:.1f} dB)",
                    reason=f"Sudden audio peak ({peak.rms_db:.1f} dB) indicating explosion, crash, or intense event",
                    evidence_type="audio_energy",
                    evidence_detail=f"RMS {peak.rms_db:.1f} dB (+{peak.relative_prominence:.1f} dB prominence at {peak.timestamp:.1f}s)",
                    confidence=0.82,
                    proposed_layout=layout_override or cat.get("default_layout", "center_crop"),
                    hook_text=cat["suggested_hooks"][0] if cat.get("suggested_hooks") else "Wait for the ending...",
                    title="Unexpected crash in GTA 6!",
                    description="Insane audio spike and crash in GTA VI gameplay. #GTA6 #Shorts #Gaming",
                    posting_caption="How did this even happen?! 🚗💥 #GTA6",
                    spoiler_flag=False,
                    music_review_flag=audio_res.baked_music_flag,
                    preview_frames={},
                    # If whisper transcription was not available, flag as awaiting captions if creator reaction
                    awaiting_captions=not audio_res.is_transcribed and cat["id"] == "creator_reaction_with_context",
                    is_visual_only=not audio_res.is_transcribed and cat["id"] != "creator_reaction_with_context",
                ))

    # 3. Evaluate Visual Scene Changes & Action Clusters
    for cluster_start, cluster_end in visual_res.action_clusters:
        cat = cat_by_id.get("unexpected_gameplay_stunt", categories[0])
        pre_roll = 2.0
        start_t = max(0.0, cluster_start - pre_roll)
        target_dur = target_duration_override or cat.get("target_duration", 22.0)
        end_t = min(total_duration, max(cluster_end + 3.0, start_t + target_dur))
        dur = round(end_t - start_t, 2)

        if 12.0 <= dur <= 35.0:
            payoff = round((cluster_start + cluster_end) / 2.0, 2)
            raw_candidates.append(CandidateClip(
                id=f"clip_visual_{len(raw_candidates)+1}",
                category_id=cat["id"],
                category_name=cat["name"],
                start_time=round(start_t, 2),
                end_time=round(end_t, 2),
                duration=dur,
                payoff_time=payoff,
                hook_lead_seconds=3.0,
                cue="Rapid visual scene changes / high motion cluster",
                reason=f"Dense visual transitions between {cluster_start:.1f}s and {cluster_end:.1f}s",
                evidence_type="visual_frame",
                evidence_detail=f"Action cluster {cluster_start:.1f}s - {cluster_end:.1f}s",
                confidence=0.78,
                proposed_layout=layout_override or "fit_background",
                hook_text="GTA 6 physics are already unmatched",
                title="Insane GTA 6 stunt sequence!",
                description="High action sequence from GTA VI. #GTA6 #Shorts #Gaming",
                posting_caption="Watch till the end 💀 #GTA6",
                spoiler_flag=False,
                music_review_flag=audio_res.baked_music_flag,
                preview_frames={},
                awaiting_captions=False,
                is_visual_only=True,
            ))

    # 4. Fallback if no events detected
    if not raw_candidates:
        cat = cat_by_id.get("unexpected_gameplay_stunt", categories[0])
        dur = min(total_duration, target_duration_override or cat.get("target_duration", 22.0))
        dur = round(dur, 2)
        raw_candidates.append(CandidateClip(
            id="clip_fallback_1",
            category_id=cat["id"],
            category_name=cat["name"],
            start_time=0.0,
            end_time=dur,
            duration=dur,
            payoff_time=round(dur * 0.7, 2),
            hook_lead_seconds=3.0,
            cue="Primary footage segment",
            reason="Baseline highlight segment from available footage",
            evidence_type="visual_frame",
            evidence_detail="Opening sequence of video",
            confidence=0.70,
            proposed_layout=layout_override or "center_crop",
            hook_text=cat["suggested_hooks"][0] if cat.get("suggested_hooks") else "Watch this GTA 6 clip",
            title="GTA 6 Gameplay Highlight",
            description="First look gameplay highlight. #GTA6 #Gaming #Shorts",
            posting_caption="GTA 6 looking clean 🔥 #GTA6",
            spoiler_flag=False,
            music_review_flag=audio_res.baked_music_flag,
            preview_frames={},
            awaiting_captions=False,
            is_visual_only=True,
        ))

    # 5. Populate Storytelling Timestamps, Speech Segments & Framing Guardrails
    for c in raw_candidates:
        # Establish 3-part storytelling arc (Setup -> Action -> Payoff)
        lead = min(c.hook_lead_seconds, 3.5)
        c.setup_start_time = c.start_time
        c.setup_end_time = round(min(c.start_time + lead, c.start_time + 4.0), 2)
        c.action_start_time = c.setup_end_time
        c.action_end_time = round(max(c.action_start_time, c.payoff_time - 1.0), 2)
        c.payoff_start_time = c.action_end_time
        c.payoff_end_time = c.end_time

        # Calculate shot framing
        c.shot_framing = compute_clip_shot_framing(
            video_path=video_path,
            clip_start=c.start_time,
            clip_end=c.end_time,
            scene_changes=visual_res.scene_changes,
            default_mode=layout_override or c.proposed_layout or "follow_crop",
        )

        matching_segs = [
            s for s in audio_res.transcript_segments
            if max(c.start_time, s.start) <= min(c.end_time, s.end) and min(c.end_time, s.end) - max(c.start_time, s.start) >= 0.2
        ]
        c.speech_segments = [s.to_dict() for s in matching_segs]
        if matching_segs:
            c.speech_summary = " ".join(s.text for s in matching_segs)
            c.is_visual_only = False
            c.awaiting_captions = False
            if any(s.uncertain for s in matching_segs):
                c.uncertain_speech = True

    # 6. Score and Rank favoring visible payoff and penalizing generic commentary
    def score_candidate(c: CandidateClip) -> float:
        score = c.confidence
        relative_payoff = (c.payoff_time - c.start_time) / c.duration if c.duration > 0 else 0.5
        if 0.50 <= relative_payoff <= 0.85:
            score += 0.08

        # Favor clips with confirmed visible payoff and action
        has_payoff = (
            c.evidence_type in ("audio_energy", "speech_quote", "visual_frame")
            and (c.payoff_time > c.start_time + 3.0)
        )
        if has_payoff:
            score += 0.12

        # Penalty for generic intros / low-energy commentary without clear payoff
        is_generic_intro = (c.start_time < 3.0 and not c.speech_segments and c.confidence < 0.80)
        if is_generic_intro:
            score -= 0.15

        # Duration match bonus
        target_len = target_duration_override or 22.0
        if abs(c.duration - target_len) <= 4.0:
            score += 0.05

        if c.speech_segments:
            score += 0.06

        return max(0.0, min(1.0, score))

    for c in raw_candidates:
        c.confidence = round(score_candidate(c), 2)

    raw_candidates.sort(key=lambda x: x.confidence, reverse=True)

    # 7. Deduplicate Overlaps (>55% IoU)
    deduped: List[CandidateClip] = []
    for cand in raw_candidates:
        overlap = False
        for kept in deduped:
            iou = _compute_overlap_ratio(cand.start_time, cand.end_time, kept.start_time, kept.end_time)
            if iou > 0.55:
                if cand.category_id == kept.category_id:
                    overlap = True
                    break
                elif cand.confidence < kept.confidence - 0.10:
                    overlap = True
                    break
        if not overlap:
            deduped.append(cand)
        if len(deduped) >= max_candidates:
            break

    # Number cleanly: clip_01, clip_02, ...
    for idx, c in enumerate(deduped, 1):
        c.id = f"clip_{idx:02d}"

    # 8. Extract Frame Thumbnails
    thumbs_dir = job_dir / "thumbnails"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    for c in deduped:
        start_thumb = thumbs_dir / f"{c.id}_start.jpg"
        payoff_thumb = thumbs_dir / f"{c.id}_payoff.jpg"
        end_thumb = thumbs_dir / f"{c.id}_end.jpg"

        extract_thumbnail_frame(video_path, c.start_time + 0.5, start_thumb)
        extract_thumbnail_frame(video_path, c.payoff_time, payoff_thumb)
        extract_thumbnail_frame(video_path, max(c.start_time, c.end_time - 0.5), end_thumb)

        c.preview_frames = {
            "start": str(start_thumb),
            "payoff": str(payoff_thumb),
            "end": str(end_thumb),
        }

    return deduped
