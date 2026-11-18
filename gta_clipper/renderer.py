"""FFmpeg rendering engine for 1080x1920 vertical Shorts & Reels.
Supports centered crop, manual crop, fit-with-background, picture-in-picture, and caption guardrails.
"""

from __future__ import annotations
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Dict, Any, Optional, List

from .candidates import CandidateClip
from .visual import probe_video
from .style import StylePreset


@dataclasses.dataclass
class RenderOptions:
    layout: str = "center_crop"  # "center_crop" | "manual_crop" | "fit_background" | "pip" | "follow_crop" | "hybrid"
    crop_x_offset_pct: float = 0.5  # 0.0 (left) to 1.0 (right)
    shot_framing: Optional[List[Dict[str, Any]]] = None
    burn_subtitles: bool = True
    ass_path: Optional[Path] = None
    mute_audio: bool = False
    audio_track_index: int = 0
    force_reencode: bool = False
    allow_uncaptioned: bool = False
    style_preset: Optional[StylePreset] = None
    facecam_confirmed: bool = False
    suffix: Optional[str] = None


@dataclasses.dataclass
class RenderResult:
    clip_id: str
    output_path: str
    srt_path: Optional[str]
    duration_seconds: float
    file_size_bytes: int
    render_time_seconds: float
    layout_used: str
    title: str
    posting_caption: str
    success: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


def escape_filter_path(path: Path) -> str:
    """Escapes Windows path for FFmpeg filter arguments (colons and backslashes)."""
    p_str = path.as_posix()
    return p_str.replace(":", r"\:")


def build_dynamic_crop_expr(
    shot_framing: Optional[List[Dict[str, Any]]],
    fallback_pct: float = 0.5,
) -> str:
    """Builds an FFmpeg crop expression for per-shot follow crop with cut resets and optional smoothing."""
    pct = max(0.0, min(1.0, fallback_pct))
    if not shot_framing:
        return f"'(iw-ow)*{pct:.3f}'"

    if len(shot_framing) == 1:
        s0 = shot_framing[0]
        x1 = float(s0.get("crop_x_pct", pct))
        x2 = s0.get("smooth_to")
        if x2 is not None and float(s0.get("end", 1.0)) > float(s0.get("start", 0.0)):
            t1 = float(s0.get("start", 0.0))
            t2 = float(s0.get("end", 1.0))
            dur = max(0.01, t2 - t1)
            return f"'(iw-ow)*({x1:.3f}+({float(x2)-x1:.3f})*(t-{t1:.2f})/{dur:.2f})'"
        return f"'(iw-ow)*{x1:.3f}'"

    def shot_subexpr(s: Dict[str, Any]) -> str:
        x1 = float(s.get("crop_x_pct", pct))
        x2 = s.get("smooth_to")
        if x2 is not None and float(s.get("end", 1.0)) > float(s.get("start", 0.0)):
            t1 = float(s.get("start", 0.0))
            t2 = float(s.get("end", 1.0))
            dur = max(0.01, t2 - t1)
            return f"({x1:.3f}+({float(x2)-x1:.3f})*(t-{t1:.2f})/{dur:.2f})"
        return f"{x1:.3f}"

    # Build nested if expression from right to left
    last_s = shot_framing[-1]
    expr = shot_subexpr(last_s)
    for s in reversed(shot_framing[:-1]):
        t_cut = float(s.get("end", 0.0))
        s_expr = shot_subexpr(s)
        expr = f"if(lt(t,{t_cut:.2f}),{s_expr},{expr})"

    return f"'(iw-ow)*{expr}'"


def build_filter_graph(
    layout: str,
    crop_x_pct: float = 0.5,
    ass_path: Optional[Path] = None,
    shot_framing: Optional[List[Dict[str, Any]]] = None,
    facecam_confirmed: bool = False,
    source_is_portrait: bool = False,
) -> tuple[List[str], str]:
    """Constructs FFmpeg video filter arguments ensuring square pixels (SAR 1:1, DAR 9:16).
    Preserves native portrait framing without horizontal cropping or 16:9 shrinking when
    the source video is already vertical (height >= width).
    """
    pct = max(0.0, min(1.0, crop_x_pct))

    ass_filter = ""
    if ass_path and ass_path.is_file():
        escaped_ass = escape_filter_path(ass_path)
        ass_filter = f",ass='{escaped_ass}'"

    shots = shot_framing or []
    if source_is_portrait or (shots and all(s.get("mode") == "portrait_preserve" for s in shots)):
        if layout == "fit_background":
            filter_complex = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];"
                f"[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg_scaled];"
                f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16{ass_filter}[v_out]"
            )
            return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"
        vf = (
            f"scale=1080:1920:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop=1080:1920,setsar=1,setdar=9/16{ass_filter}"
        )
        return ["-vf", vf], "vf"

    fit_shots = [s for s in shots if s.get("mode") == "fit_background"]
    crop_shots = [s for s in shots if s.get("mode") != "fit_background"]

    if layout == "hybrid" or (layout == "follow_crop" and fit_shots and crop_shots):
        if fit_shots and crop_shots:
            crop_expr = build_dynamic_crop_expr(shots, fallback_pct=pct)
            fit_intervals = [f"between(t,{float(s['start']):.2f},{float(s['end']):.2f})" for s in fit_shots]
            fit_enable = "+".join(fit_intervals)
            filter_complex = (
                f"[0:v]crop=ih*9/16:ih:{crop_expr}:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16[cropped];"
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];"
                f"[fg]scale=1080:608:force_original_aspect_ratio=decrease[fg_scaled];"
                f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16[fit_bg];"
                f"[cropped][fit_bg]overlay=0:0:enable='{fit_enable}',setsar=1,setdar=9/16{ass_filter}[v_out]"
            )
            return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"
        elif fit_shots and not crop_shots:
            filter_complex = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];"
                f"[fg]scale=1080:608:force_original_aspect_ratio=decrease[fg_scaled];"
                f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16{ass_filter}[v_out]"
            )
            return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"
        else:
            crop_expr = build_dynamic_crop_expr(shots, fallback_pct=pct)
            vf = f"crop=ih*9/16:ih:{crop_expr}:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16{ass_filter}"
            return ["-vf", vf], "vf"

    elif layout == "follow_crop":
        crop_expr = build_dynamic_crop_expr(shot_framing, fallback_pct=pct)
        vf = f"crop=ih*9/16:ih:{crop_expr}:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16{ass_filter}"
        return ["-vf", vf], "vf"

    elif layout == "center_crop":
        vf = f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16{ass_filter}"
        return ["-vf", vf], "vf"

    elif layout == "manual_crop":
        vf = f"crop=ih*9/16:ih:(iw-ih*9/16)*{pct:.3f}:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16{ass_filter}"
        return ["-vf", vf], "vf"

    elif layout == "fit_background":
        # Blurred background (scaled to cover 1080x1920) + centered fitted gameplay (1080x608)
        filter_complex = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];"
            f"[fg]scale=1080:608:force_original_aspect_ratio=decrease[fg_scaled];"
            f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16{ass_filter}[v_out]"
        )
        return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"

    elif layout == "pip":
        if not facecam_confirmed:
            # Facecam guardrail: if facecam region is not confirmed, fall back safely to fit_background
            filter_complex = (
                f"[0:v]split=2[bg][fg];"
                f"[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];"
                f"[fg]scale=1080:608:force_original_aspect_ratio=decrease[fg_scaled];"
                f"[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16{ass_filter}[v_out]"
            )
            return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"

        # Streamer facecam PiP top-left, centered gameplay below
        filter_complex = (
            f"[0:v]split=2[cam][game];"
            f"[cam]crop=iw/3:ih/3:iw*2/3:0,scale=480:360[cam_scaled];"
            f"[game]crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos[game_scaled];"
            f"[game_scaled][cam_scaled]overlay=60:220,setsar=1,setdar=9/16{ass_filter}[v_out]"
        )
        return ["-filter_complex", filter_complex, "-map", "[v_out]"], "filter_complex"

    else:
        vf = f"crop=ih*9/16:ih:(iw-ih*9/16)/2:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16{ass_filter}"
        return ["-vf", vf], "vf"


def compute_render_fingerprint(
    clip: CandidateClip,
    options: RenderOptions,
    source_video: Path,
) -> str:
    """Computes a SHA256 hash of all parameters affecting the rendered output."""
    hasher = hashlib.sha256()
    hasher.update(str(source_video.resolve()).encode("utf-8"))
    if source_video.is_file():
        hasher.update(str(source_video.stat().st_size).encode("utf-8"))
    hasher.update(f"{clip.start_time:.3f}:{clip.end_time:.3f}".encode("utf-8"))
    hasher.update(str(options.layout).encode("utf-8"))
    hasher.update(f"{options.crop_x_offset_pct:.3f}".encode("utf-8"))
    if options.shot_framing:
        hasher.update(json.dumps(options.shot_framing, sort_keys=True).encode("utf-8"))
    hasher.update(str(options.burn_subtitles).encode("utf-8"))
    if options.burn_subtitles and options.ass_path and Path(options.ass_path).is_file():
        try:
            hasher.update(Path(options.ass_path).read_bytes())
        except Exception:
            pass
    hasher.update(f"{options.audio_track_index}:{options.mute_audio}".encode("utf-8"))
    hasher.update(str(clip.hook_text or "").encode("utf-8"))
    return hasher.hexdigest()[:16]


def render_clip(
    source_video: Path,
    clip: CandidateClip,
    output_dir: Path,
    options: Optional[RenderOptions] = None,
) -> RenderResult:
    """Renders a single candidate clip to 1080x1920 vertical H.264/AAC MP4 atomically."""
    opts = options or RenderOptions()
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix_part = f"_{opts.suffix}" if opts.suffix else ""
    out_file = output_dir / f"{clip.id}_1080x1920{suffix_part}.mp4"
    tmp_file = output_dir / f"{clip.id}_1080x1920{suffix_part}.tmp.mp4"
    meta_file = output_dir / f"{clip.id}_1080x1920{suffix_part}.render_meta.json"

    # 1. Validation & Speech Guardrails
    if not source_video.is_file():
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=0.0,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=opts.layout,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error=f"Source video file not found: {source_video}",
        )

    # Caption Guardrail: Never export a dialogue clip as finished with empty subtitles
    if clip.awaiting_captions and not opts.allow_uncaptioned:
        clip_dur = max(0.0, clip.end_time - clip.start_time)
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=clip_dur,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=opts.layout,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error=(
                f"Cannot export dialogue clip '{clip.id}' as finished: awaiting captions. "
                "Download Whisper model or supply an SRT transcript before export."
            ),
        )

    if clip.start_time >= clip.end_time:
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=0.0,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=opts.layout,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error=f"Invalid time range: start_time ({clip.start_time}s) >= end_time ({clip.end_time}s)",
        )

    clip_duration = clip.end_time - clip.start_time
    if clip_duration < 1.0:
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=clip_duration,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=opts.layout,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error=f"Clip duration ({clip_duration:.2f}s) is too short (< 1.0s)",
        )

    # 2. Check cache / idempotence with fingerprint validation
    fingerprint = compute_render_fingerprint(clip, opts, source_video)
    if out_file.is_file() and meta_file.is_file() and not opts.force_reencode:
        try:
            with open(meta_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if saved.get("fingerprint") == fingerprint and out_file.stat().st_size > 1000:
                srt_candidate = output_dir / f"{clip.id}{suffix_part}.srt"
                return RenderResult(
                    clip_id=clip.id,
                    output_path=str(out_file),
                    srt_path=str(srt_candidate) if srt_candidate.is_file() else None,
                    duration_seconds=clip_duration,
                    file_size_bytes=out_file.stat().st_size,
                    render_time_seconds=0.0,
                    layout_used=opts.layout,
                    title=clip.title,
                    posting_caption=clip.posting_caption,
                    success=True,
                )
        except Exception:
            pass

    # 3. Build FFmpeg command
    t0 = time.time()
    src_info = probe_video(source_video)
    source_is_portrait = (src_info.height >= src_info.width) if (src_info.width > 0 and src_info.height > 0) else False
    layout_to_use = opts.layout or clip.proposed_layout or "center_crop"
    filter_args, filter_type = build_filter_graph(
        layout=layout_to_use,
        crop_x_pct=opts.crop_x_offset_pct,
        ass_path=opts.ass_path if opts.burn_subtitles else None,
        shot_framing=opts.shot_framing,
        facecam_confirmed=opts.facecam_confirmed,
        source_is_portrait=source_is_portrait,
    )

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{clip.start_time:.3f}",
        "-t", f"{clip_duration:.3f}",
        "-i", str(source_video),
    ]

    cmd.extend(filter_args)
    if filter_type == "vf":
        cmd.extend(["-map", "0:v:0"])

    # Audio mapping with explicit track selection
    if opts.mute_audio:
        cmd.append("-an")
    else:
        track_map = f"0:a:{opts.audio_track_index}?"
        cmd.extend(["-map", track_map, "-c:a", "aac", "-b:a", "192k", "-ar", "48000"])

    # Video encoding (H.264, standard yuv420p for max mobile compatibility)
    cmd.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(tmp_file),
    ])

    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300)
        render_elapsed = time.time() - t0

        if res.returncode != 0:
            if tmp_file.is_file():
                tmp_file.unlink()
            return RenderResult(
                clip_id=clip.id,
                output_path="",
                srt_path=None,
                duration_seconds=clip_duration,
                file_size_bytes=0,
                render_time_seconds=round(render_elapsed, 2),
                layout_used=layout_to_use,
                title=clip.title,
                posting_caption=clip.posting_caption,
                success=False,
                error=f"FFmpeg render failed (code {res.returncode}): {res.stderr[-400:]}",
            )

        # Atomic move
        tmp_file.replace(out_file)
        srt_candidate = output_dir / f"{clip.id}{suffix_part}.srt"

        # Save render fingerprint metadata to invalidate stale cache on edit
        try:
            with open(meta_file, "w", encoding="utf-8") as f:
                json.dump({
                    "clip_id": clip.id,
                    "fingerprint": fingerprint,
                    "layout": layout_to_use,
                    "crop_x_offset_pct": opts.crop_x_offset_pct,
                    "shot_framing": opts.shot_framing,
                    "hook_text": clip.hook_text,
                    "duration": clip_duration,
                    "rendered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }, f, indent=2)
        except Exception:
            pass

        return RenderResult(
            clip_id=clip.id,
            output_path=str(out_file),
            srt_path=str(srt_candidate) if srt_candidate.is_file() else None,
            duration_seconds=round(clip_duration, 2),
            file_size_bytes=out_file.stat().st_size,
            render_time_seconds=round(render_elapsed, 2),
            layout_used=layout_to_use,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=True,
        )

    except subprocess.TimeoutExpired:
        if tmp_file.is_file():
            tmp_file.unlink()
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=clip_duration,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=layout_to_use,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error="FFmpeg rendering timed out (> 300s)",
        )
    except Exception as e:
        if tmp_file.is_file():
            tmp_file.unlink()
        return RenderResult(
            clip_id=clip.id,
            output_path="",
            srt_path=None,
            duration_seconds=clip_duration,
            file_size_bytes=0,
            render_time_seconds=0.0,
            layout_used=layout_to_use,
            title=clip.title,
            posting_caption=clip.posting_caption,
            success=False,
            error=str(e),
        )
