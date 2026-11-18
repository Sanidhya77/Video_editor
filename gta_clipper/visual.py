"""Visual signal analysis, scene detection, and frame thumbnail extraction.
"""

from __future__ import annotations
import dataclasses
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import List, Dict, Any, Optional

import numpy as np
from PIL import Image


@dataclasses.dataclass
class VideoInfo:
    width: int
    height: int
    duration: float
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class VisualAnalysisResult:
    info: VideoInfo
    scene_changes: List[float]  # Timestamps in seconds
    action_clusters: List[tuple[float, float]]  # High activity windows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "info": self.info.to_dict(),
            "scene_changes": self.scene_changes,
            "action_clusters": self.action_clusters,
        }


def probe_video(video_path: Path) -> VideoInfo:
    """Uses ffprobe to extract stream details (dimensions, fps, duration, codecs)."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=30)
        data = json.loads(res.stdout)
    except Exception as e:
        raise RuntimeError(f"Failed to probe video file {video_path}: {e}")

    video_stream = None
    audio_stream = None

    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and not video_stream:
            video_stream = s
        elif s.get("codec_type") == "audio" and not audio_stream:
            audio_stream = s

    if not video_stream:
        raise ValueError(f"No video stream found in {video_path}")

    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))
    video_codec = video_stream.get("codec_name", "h264")

    # Duration parsing
    fmt = data.get("format", {})
    dur_str = video_stream.get("duration") or fmt.get("duration", "0.0")
    duration = float(dur_str)

    # Framerate parsing (e.g. "60/1" or "30000/1001")
    r_frame_rate = video_stream.get("r_frame_rate", "30/1")
    fps = 30.0
    if "/" in r_frame_rate:
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den) if float(den) > 0 else 30.0
    else:
        fps = float(r_frame_rate)

    has_audio = audio_stream is not None
    audio_codec = audio_stream.get("codec_name") if audio_stream else None

    return VideoInfo(
        width=width,
        height=height,
        duration=duration,
        fps=round(fps, 2),
        video_codec=video_codec,
        has_audio=has_audio,
        audio_codec=audio_codec,
    )


def detect_scene_changes(video_path: Path, threshold: float = 0.30) -> List[float]:
    """Detects scene transitions using FFmpeg's scene detection filter."""
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-filter:v", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null",
        "-"
    ]
    scene_timestamps: List[float] = []
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=180)
        output = res.stderr
        # Look for pts_time:(\d+\.?\d*)
        matches = re.findall(r"pts_time:\s*([0-9.]+)", output)
        for m in matches:
            t = round(float(m), 2)
            if not scene_timestamps or (t - scene_timestamps[-1] > 0.4):
                scene_timestamps.append(t)
    except Exception:
        pass
    return scene_timestamps


def cluster_visual_events(scene_changes: List[float], min_window: float = 15.0) -> List[tuple[float, float]]:
    """Groups dense scene transitions into action/stunt event clusters."""
    if not scene_changes:
        return []

    clusters: List[tuple[float, float]] = []
    current_start = scene_changes[0]
    current_end = scene_changes[0]

    for t in scene_changes[1:]:
        if t - current_end <= 6.0:  # Activity within 6 seconds
            current_end = t
        else:
            if current_end - current_start >= 4.0:
                clusters.append((current_start, current_end))
            current_start = t
            current_end = t

    if current_end - current_start >= 4.0:
        clusters.append((current_start, current_end))

    return clusters


def extract_thumbnail_frame(
    video_path: Path,
    timestamp: float,
    output_path: Path,
    width: int = 480,
) -> bool:
    """Extracts a scaled JPEG thumbnail at the requested timestamp."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ts = max(0.0, timestamp)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{ts:.2f}",
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", f"scale={width}:-1",
        "-q:v", "3",
        str(output_path)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        return res.returncode == 0 and output_path.is_file() and output_path.stat().st_size > 0
    except Exception:
        return False


def analyze_shot_framing_auto(
    video_path: Path,
    shot_start_src: float,
    shot_end_src: float,
    shot_start_clip: float,
    shot_end_clip: float,
    shot_idx: int,
    temp_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Inspects multiple frames within a shot to determine whether to use follow_crop or fit_background.
    Evaluates several samples across the whole shot. If important subjects cannot both fit (dual subjects/
    widening action), the likely subject changes, the tracker jumps across unrelated subjects, or evidence
    is inconsistent, preserves the full source frame with fit_background.
    """
    dur = max(0.1, shot_end_src - shot_start_src)
    # Check several samples across the whole shot
    if dur < 0.4:
        sample_fractions = [0.50]
    elif dur < 1.8:
        sample_fractions = [0.20, 0.80]
    elif dur < 3.5:
        sample_fractions = [0.15, 0.38, 0.62, 0.85]
    elif dur < 6.0:
        sample_fractions = [0.10, 0.30, 0.50, 0.70, 0.90]
    else:
        sample_fractions = [0.08, 0.25, 0.42, 0.58, 0.75, 0.92]

    sample_times = [shot_start_src + f * dur for f in sample_fractions]

    scratch_dir = temp_dir or (Path(tempfile.gettempdir()) / "gta_clipping_framing")
    scratch_dir.mkdir(parents=True, exist_ok=True)

    frame_images = []
    for i, t in enumerate(sample_times):
        fpath = scratch_dir / f"shot_{shot_idx:02d}_{i}_{int(t*1000)}.jpg"
        cmd = [
            "ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", str(video_path),
            "-vframes", "1", "-q:v", "3", str(fpath)
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if fpath.is_file():
            try:
                im = Image.open(fpath).convert("RGB")
                frame_images.append((t, np.array(im, dtype=np.float32)))
            except Exception:
                pass

    if not frame_images:
        return {
            "shot": shot_idx,
            "start": round(shot_start_clip, 2),
            "end": round(shot_end_clip, 2),
            "mode": "fit_background",
            "crop_x_pct": 0.50,
            "crop_source": "auto",
            "reason": "Tracking failed (no frames could be extracted); preserved full frame",
            "subject": "unknown",
            "tracking_reset": True,
        }

    h, w, _ = frame_images[0][1].shape
    if h >= w:
        return {
            "shot": shot_idx,
            "start": round(shot_start_clip, 2),
            "end": round(shot_end_clip, 2),
            "mode": "portrait_preserve",
            "crop_x_pct": 0.50,
            "crop_source": "auto",
            "reason": f"Source is already portrait ({w}x{h}); preserved native vertical framing",
            "subject": "portrait_native",
            "tracking_reset": False,
        }

    nbins = 32
    bin_w = max(1, w // nbins)
    w_crop_norm = 0.3164  # (9/16)/(16/9)

    motion_maps = []
    if len(frame_images) > 1:
        for i in range(len(frame_images) - 1):
            gray1 = np.mean(frame_images[i][1], axis=2)
            gray2 = np.mean(frame_images[i+1][1], axis=2)
            motion_maps.append(np.abs(gray2 - gray1))

    sample_analyses = []
    for i, (t, arr) in enumerate(frame_images):
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]

        minimap_y = int(0.75 * h)
        minimap_x = int(0.22 * w)

        # 1. Skin tone / avatar detection
        skin_mask = (r > 95) & (g > 40) & (b > 20) & (r > g) & (r > b) & ((r - g) > 15)
        skin_mask[minimap_y:, :minimap_x] = False
        skin_mask[:int(0.10 * h), :] = False
        skin_x = np.sum(skin_mask, axis=0)

        # 2. Luminance edge energy
        gray = 0.299 * r + 0.587 * g + 0.114 * b
        gray[minimap_y:, :minimap_x] = 0
        gray[:int(0.10 * h), :] = 0
        dx = np.abs(np.diff(gray, axis=1))
        dx = np.pad(dx, ((0, 0), (0, 1)), mode="edge")
        edge_x = np.sum(dx, axis=0)

        # 3. Motion energy
        if motion_maps:
            m_idx = min(i, len(motion_maps) - 1)
            m_arr = motion_maps[m_idx].copy()
            m_arr[minimap_y:, :minimap_x] = 0
            m_arr[:int(0.10 * h), :] = 0
            motion_x = np.sum(m_arr, axis=0)
        else:
            motion_x = np.zeros_like(edge_x)

        skin_norm = skin_x / (np.max(skin_x) + 1e-6)
        edge_norm = edge_x / (np.max(edge_x) + 1e-6)
        motion_norm = motion_x / (np.max(motion_x) + 1e-6)

        saliency = 0.45 * skin_norm + 0.35 * motion_norm + 0.20 * edge_norm
        b_vals = np.array([np.mean(saliency[j*bin_w:(j+1)*bin_w]) for j in range(nbins)])
        b_max = np.max(b_vals)
        if b_max < 0.05:
            continue

        tot_e = np.sum(b_vals)
        cdf = np.cumsum(b_vals) / tot_e
        idx_low = np.searchsorted(cdf, 0.10)
        idx_high = np.searchsorted(cdf, 0.90)
        energy_span = ((idx_high + 0.5) - (idx_low + 0.5)) / nbins

        # Peak detection: local maxima with prominence
        peaks = []
        for j in range(len(b_vals)):
            left_v = b_vals[j-1] if j > 0 else 0
            right_v = b_vals[j+1] if j < len(b_vals) - 1 else 0
            if b_vals[j] >= left_v and b_vals[j] >= right_v and b_vals[j] >= 0.28 * b_max:
                peaks.append((j, b_vals[j], (j + 0.5) / nbins))

        # Merge adjacent peaks (within 2 bins)
        merged_peaks = []
        for p in peaks:
            if not merged_peaks:
                merged_peaks.append(p)
            else:
                if p[0] - merged_peaks[-1][0] <= 2:
                    if p[1] > merged_peaks[-1][1]:
                        merged_peaks[-1] = p
                else:
                    merged_peaks.append(p)

        # Check peak separation and valley
        dual_peaks = False
        peak_sep = 0.0
        if len(merged_peaks) >= 2:
            for i1 in range(len(merged_peaks)):
                for i2 in range(i1 + 1, len(merged_peaks)):
                    p1 = merged_peaks[i1]
                    p2 = merged_peaks[i2]
                    sep = abs(p2[2] - p1[2])
                    if sep >= 0.26:
                        j1, j2 = min(p1[0], p2[0]), max(p1[0], p2[0])
                        val_min = np.min(b_vals[j1:j2+1])
                        if val_min <= 0.85 * min(p1[1], p2[1]):
                            dual_peaks = True
                            peak_sep = max(peak_sep, sep)

        # Left / Right mass split (streamer on one side, gameplay on other)
        left_mass = np.sum(b_vals[:nbins//3])
        right_mass = np.sum(b_vals[2*nbins//3:])
        wide_split = (left_mass >= 0.18 * tot_e) and (right_mass >= 0.18 * tot_e)

        primary_pos = merged_peaks[0][2] if merged_peaks else 0.50
        is_wide = dual_peaks or (energy_span > w_crop_norm) or wide_split

        sample_analyses.append({
            "t": t,
            "primary_pos": primary_pos,
            "dual_peaks": dual_peaks,
            "peak_sep": peak_sep,
            "energy_span": energy_span,
            "wide_split": wide_split,
            "is_wide": is_wide,
        })

    if not sample_analyses:
        return {
            "shot": shot_idx,
            "start": round(shot_start_clip, 2),
            "end": round(shot_end_clip, 2),
            "mode": "fit_background",
            "crop_x_pct": 0.50,
            "crop_source": "auto",
            "reason": "Uncertain tracking / diffuse action across screen; preserved full frame",
            "subject": "diffuse_action",
            "tracking_reset": True,
        }

    # Rule 1: Dual subjects / wide action across shot (or late widening)
    wide_samples = [s for s in sample_analyses if s["is_wide"]]
    if wide_samples:
        max_sep = max([s["peak_sep"] for s in wide_samples] + [s["energy_span"] for s in wide_samples])
        return {
            "shot": shot_idx,
            "start": round(shot_start_clip, 2),
            "end": round(shot_end_clip, 2),
            "mode": "fit_background",
            "crop_x_pct": 0.50,
            "crop_source": "auto",
            "reason": f"Dual subjects far apart / widening action across shot (span={max_sep:.2f} > 0.28); preserved full frame",
            "subject": "dual_subjects_wide",
            "tracking_reset": True,
        }

    # Rule 2: Subject switching / erratic jump across shot
    positions = [s["primary_pos"] for s in sample_analyses]
    if len(positions) >= 2:
        jump = abs(positions[-1] - positions[0])
        pos_span = max(positions) - min(positions)
        if jump > 0.38 or pos_span > 0.45:
            return {
                "shot": shot_idx,
                "start": round(shot_start_clip, 2),
                "end": round(shot_end_clip, 2),
                "mode": "fit_background",
                "crop_x_pct": 0.50,
                "crop_source": "auto",
                "reason": f"Tracker inconsistent / switched between unrelated subjects (jump from x={positions[0]:.2f} to x={positions[-1]:.2f}); preserved full frame",
                "subject": "unrelated_subject_jump",
                "tracking_reset": True,
            }

    # Rule 3: Single clear subject fitting comfortably in 9:16
    def center_to_crop_pct(xs: float) -> float:
        pct = (xs - w_crop_norm / 2.0) / (1.0 - w_crop_norm)
        return max(0.0, min(1.0, pct))

    x_start_pct = center_to_crop_pct(positions[0])
    x_end_pct = center_to_crop_pct(positions[-1])

    shot_dict = {
        "shot": shot_idx,
        "start": round(shot_start_clip, 2),
        "end": round(shot_end_clip, 2),
        "mode": "follow_crop",
        "crop_x_pct": round(x_start_pct, 2),
        "crop_source": "auto",
        "subject": "tracked_subject",
        "tracking_reset": True,
    }

    if abs(x_end_pct - x_start_pct) >= 0.05 and len(positions) > 1:
        shot_dict["smooth_to"] = round(x_end_pct, 2)
        shot_dict["reason"] = f"Single clear subject at x={positions[0]:.2f}; smooth pan to x={shot_dict['smooth_to']:.2f}"
    else:
        shot_dict["reason"] = f"Single clear subject centered at x={positions[0]:.2f} fits in 9:16 crop"

    return shot_dict


def compute_clip_shot_framing(
    video_path: Optional[Path],
    clip_start: float,
    clip_end: float,
    scene_changes: Optional[List[float]] = None,
    default_mode: str = "follow_crop",
    default_pct: float = 0.5,
    manual_keyframes: Optional[List[Dict[str, Any]]] = None,
    auto_framing: bool = True,
) -> List[Dict[str, Any]]:
    """Analyzes scene cuts inside the clip and calculates shot-by-shot framing.
    Resets tracking at cuts and determines follow_crop vs fit_background per shot.
    If manual_keyframes are provided, applies them directly to the matching shots.
    If manual_keyframes is None and auto_framing is True with video_path present,
    inspects frames within each shot to choose framing automatically.
    """
    if manual_keyframes:
        for kf in manual_keyframes:
            if "crop_source" not in kf:
                kf["crop_source"] = "manual"
            if "reason" not in kf:
                kf["reason"] = "Manual operator framing"
        return manual_keyframes

    clip_dur = max(0.01, round(clip_end - clip_start, 2))
    cuts_inside: List[float] = []

    if scene_changes:
        cuts_inside = sorted([
            round(c - clip_start, 2)
            for c in scene_changes
            if clip_start < c < clip_end
        ])
    elif video_path and video_path.is_file():
        detected = detect_scene_changes(video_path, threshold=0.25)
        cuts_inside = sorted([
            round(c - clip_start, 2)
            for c in detected
            if clip_start < c < clip_end
        ])

    # Filter cuts that are too close together (< 0.4s)
    clean_cuts: List[float] = []
    prev_c = 0.0
    for c in cuts_inside:
        if c - prev_c >= 0.4 and (clip_dur - c) >= 0.4:
            clean_cuts.append(c)
            prev_c = c

    shots: List[Dict[str, Any]] = []
    prev = 0.0
    shot_idx = 1
    has_video = video_path is not None and video_path.is_file()

    for cut in clean_cuts + [clip_dur]:
        if cut - prev >= 0.3:
            s_rel = prev
            e_rel = cut
            if has_video and auto_framing:
                s_src = clip_start + s_rel
                e_src = clip_start + e_rel
                shot_data = analyze_shot_framing_auto(
                    video_path=video_path,
                    shot_start_src=s_src,
                    shot_end_src=e_src,
                    shot_start_clip=s_rel,
                    shot_end_clip=e_rel,
                    shot_idx=shot_idx,
                )
                shots.append(shot_data)
            else:
                shots.append({
                    "shot": shot_idx,
                    "start": s_rel,
                    "end": e_rel,
                    "mode": default_mode,
                    "crop_x_pct": default_pct,
                    "crop_source": "auto",
                    "reason": "Default framing without video analysis",
                    "subject": "centered",
                    "tracking_reset": True,
                })
            prev = cut
            shot_idx += 1

    if not shots:
        if has_video and auto_framing:
            shot_data = analyze_shot_framing_auto(
                video_path=video_path,
                shot_start_src=clip_start,
                shot_end_src=clip_end,
                shot_start_clip=0.0,
                shot_end_clip=clip_dur,
                shot_idx=1,
            )
            shots.append(shot_data)
        else:
            shots.append({
                "shot": 1,
                "start": 0.0,
                "end": clip_dur,
                "mode": default_mode,
                "crop_x_pct": default_pct,
                "crop_source": "auto",
                "reason": "Default framing without video analysis",
                "subject": "centered",
                "tracking_reset": False,
            })

    # Smooth layout transitions: suppress sub-0.80s isolated follow_crop flickers sandwiched between fit_background shots
    if has_video and auto_framing and len(shots) >= 3:
        for i in range(1, len(shots) - 1):
            cur = shots[i]
            prev_s = shots[i - 1]
            next_s = shots[i + 1]
            cur_dur = float(cur.get("end", 0.0)) - float(cur.get("start", 0.0))
            if (
                cur.get("crop_source") == "auto"
                and cur.get("mode") == "follow_crop"
                and cur_dur < 0.80
                and prev_s.get("mode") == "fit_background"
                and next_s.get("mode") == "fit_background"
            ):
                cur["mode"] = "fit_background"
                cur["crop_x_pct"] = 0.50
                cur.pop("smooth_to", None)
                cur["subject"] = "smoothed_transient"
                cur["reason"] = (
                    f"Smoothed short ({cur_dur:.2f}s < 0.80s) transient crop between wide shots "
                    "into fit_background for smooth layout transitions"
                )

    return shots


def analyze_visual(video_path: Path) -> VisualAnalysisResult:
    """Runs complete visual inspection and scene detection."""
    info = probe_video(video_path)
    scenes = detect_scene_changes(video_path)
    clusters = cluster_visual_events(scenes)
    return VisualAnalysisResult(
        info=info,
        scene_changes=scenes,
        action_clusters=clusters,
    )
