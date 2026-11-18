"""Research-informed GTA highlight ranking engine.

Scans full recordings using scene changes, adaptive audio peaks, low-res visual
motion/novelty profiles, speech-band vocal dynamics, and optional timestamped chat
logs. Ranks distinct moments with transparent evidence, hook/payoff timestamps,
penalties for dead time / intro chatter / repetition, and adaptive duration
sizing (20-35s tight story cuts vs. configurable 45-60s expanded cuts) independent
of the caption style preset.
"""

from __future__ import annotations
import dataclasses
import json
import math
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from .audio import AudioAnalysisResult, AudioSegment, REACTION_KEYWORDS
from .visual import VisualAnalysisResult, extract_thumbnail_frame, compute_clip_shot_framing
from .style import StylePreset


@dataclasses.dataclass
class HighlightDurationConfig:
    """Duration configuration independent of caption style presets."""
    target_duration: float = 50.0   # Configurable 45-60s target for expanded arcs
    min_duration: float = 20.0      # Floor for tight complete-story moments
    max_duration: float = 60.0      # Ceiling for expanded highlights
    tight_min: float = 20.0
    tight_max: float = 35.0
    expand_min: float = 45.0
    expand_max: float = 60.0


def load_chat_log(chat_log_path: Optional[Path]) -> List[Tuple[float, float]]:
    """Loads optional timestamped chat events as (timestamp_sec, weight) tuples.

    Supports JSON formats:
      - [{"timestamp": 123.4, "count": 15}, ...]
      - [{"timestamp": 123.4, "message": "LMAO"}, ...]
      - {"messages": [...]} or {"events": [...]}
    Returns empty list when not supplied.
    """
    if not chat_log_path or not chat_log_path.is_file():
        return []
    try:
        raw = json.loads(chat_log_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    if isinstance(raw, dict):
        items = raw.get("events") or raw.get("messages") or raw.get("chat") or []
    elif isinstance(raw, list):
        items = raw
    else:
        return []

    events: List[Tuple[float, float]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ts = item.get("timestamp", item.get("time", item.get("t")))
        if ts is None:
            continue
        try:
            t_val = float(ts)
            w_val = float(item.get("count", item.get("weight", 1.0)))
            if t_val >= 0.0 and w_val > 0.0:
                events.append((t_val, w_val))
        except (TypeError, ValueError):
            continue
    return sorted(events, key=lambda x: x[0])


def _extract_1fps_visual_profile(
    video_path: Path,
    total_duration: float,
    cache_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts a fast 1 fps low-res (160x90) visual profile across the full video.

    Returns per-second motion deltas, color histograms, flash/monochrome indicators,
    and global baseline histogram for novelty & repetition scoring.
    """
    scratch = cache_dir or (Path(tempfile.gettempdir()) / "gta_clipping_rank_frames")
    scratch.mkdir(parents=True, exist_ok=True)

    # Use a deterministic subfolder per video size + stem so repeated runs reuse cache
    sig = f"{video_path.stem[:32]}_{video_path.stat().st_size if video_path.is_file() else 0}"
    sig_clean = "".join(ch if ch.isalnum() or ch in ("_", "-") else "_" for ch in sig)
    frames_dir = scratch / sig_clean
    frames_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(frames_dir.glob("f_*.jpg"))
    expected_min = max(1, int(total_duration * 0.85))
    if len(existing) < expected_min:
        for old in existing:
            try:
                old.unlink()
            except Exception:
                pass
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "fps=1,scale=160:90:flags=fast_bilinear",
            "-q:v", "6",
            str(frames_dir / "f_%05d.jpg"),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180)
        existing = sorted(frames_dir.glob("f_*.jpg"))

    if not existing:
        n = max(1, int(math.ceil(total_duration)))
        return {
            "fps": 1.0,
            "n_frames": n,
            "motion": np.zeros(n, dtype=np.float32),
            "flash": np.zeros(n, dtype=np.float32),
            "hists": np.zeros((n, 24), dtype=np.float32),
            "global_hist": np.ones(24, dtype=np.float32) / 24.0,
        }

    hists = []
    motion = []
    flash = []
    prev_arr: Optional[np.ndarray] = None
    prev_luma: Optional[float] = None

    for fp in existing:
        try:
            arr = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32)
        except Exception:
            continue
        # 8-bin RGB histogram (24 dims, L1 normalized)
        h_r, _ = np.histogram(arr[:, :, 0], bins=8, range=(0, 256))
        h_g, _ = np.histogram(arr[:, :, 1], bins=8, range=(0, 256))
        h_b, _ = np.histogram(arr[:, :, 2], bins=8, range=(0, 256))
        hist = np.concatenate([h_r, h_g, h_b]).astype(np.float32)
        hist /= (np.sum(hist) + 1e-6)
        hists.append(hist)

        luma = float(np.mean(0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]))
        sat = float(np.mean(np.max(arr, axis=2) - np.min(arr, axis=2)))
        if prev_arr is not None and prev_luma is not None:
            m_val = float(np.mean(np.abs(arr - prev_arr)))
            # Flash/climax indicator: sudden luminance jump OR drop to monochrome (WASTED)
            f_val = abs(luma - prev_luma) + (12.0 if sat < 14.0 else 0.0)
        else:
            m_val = 0.0
            f_val = 0.0
        motion.append(m_val)
        flash.append(f_val)
        prev_arr = arr
        prev_luma = luma

    hists_np = np.array(hists, dtype=np.float32) if hists else np.zeros((1, 24), dtype=np.float32)
    global_hist = np.mean(hists_np, axis=0)
    global_hist /= (np.sum(global_hist) + 1e-6)

    return {
        "fps": 1.0,
        "n_frames": len(hists_np),
        "motion": np.array(motion, dtype=np.float32),
        "flash": np.array(flash, dtype=np.float32),
        "hists": hists_np,
        "global_hist": global_hist,
    }


def _compute_audio_dynamics_profile(wav_path: Optional[str | Path], step_sec: float = 0.5) -> Dict[str, Any]:
    """Computes per-0.5s RMS dB, vocal-band (300-3400 Hz) energy, and dead-time mask."""
    wav_p = Path(wav_path) if wav_path else None
    if not wav_p or not wav_p.is_file() or wav_p.stat().st_size <= 44:
        return {
            "step": step_sec,
            "db": np.array([-40.0], dtype=np.float32),
            "vocal_ratio": np.array([0.0], dtype=np.float32),
            "avg_db": -40.0,
            "std_db": 1.0,
        }

    with wave.open(str(wav_p), "rb") as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if len(data) == 0:
        return {
            "step": step_sec,
            "db": np.array([-40.0], dtype=np.float32),
            "vocal_ratio": np.array([0.0], dtype=np.float32),
            "avg_db": -40.0,
            "std_db": 1.0,
        }

    win = max(1, int(sr * step_sec))
    n_win = max(1, len(data) // win)
    dbs = np.zeros(n_win, dtype=np.float32)
    vocal_ratios = np.zeros(n_win, dtype=np.float32)

    freqs = np.fft.rfftfreq(win, d=1.0 / sr)
    vocal_mask = (freqs >= 300.0) & (freqs <= 3400.0)

    for i in range(n_win):
        seg = data[i * win : (i + 1) * win]
        rms = float(np.sqrt(np.mean(seg * seg)))
        dbs[i] = 20.0 * math.log10(max(rms, 1.0) / 32768.0)
        spec = np.abs(np.fft.rfft(seg)) ** 2
        tot_p = float(np.sum(spec)) + 1e-9
        vocal_ratios[i] = float(np.sum(spec[vocal_mask])) / tot_p

    avg_db = float(np.mean(dbs))
    std_db = float(np.std(dbs)) + 1e-6
    return {
        "step": step_sec,
        "db": dbs,
        "vocal_ratio": vocal_ratios,
        "avg_db": avg_db,
        "std_db": std_db,
    }


def _snap_to_cut_or_silence(
    target_t: float,
    scene_changes: List[float],
    silence_ranges: List[Tuple[float, float]],
    total_duration: float,
    max_shift: float = 1.6,
) -> float:
    """Snaps a window boundary to the nearest scene cut (preferred) or silence gap."""
    best_t = target_t
    best_dist = max_shift + 1.0

    for sc in scene_changes:
        d = abs(sc - target_t)
        if d <= max_shift and d < best_dist:
            best_dist = d
            best_t = sc

    if best_dist <= max_shift:
        return round(max(0.0, min(total_duration, best_t)), 2)

    for s0, s1 in silence_ranges:
        for edge in (s0, s1):
            d = abs(edge - target_t)
            if d <= max_shift and d < best_dist:
                best_dist = d
                best_t = edge

    return round(max(0.0, min(total_duration, best_t)), 2)


def _window_activity_quality(
    t_start: float,
    t_end: float,
    audio_prof: Dict[str, Any],
    vis_prof: Dict[str, Any],
    scene_changes: List[float],
    audio_peaks: List[Any],
) -> Tuple[float, float]:
    """Returns (activity_score 0..1, dead_ratio 0..1) for a candidate slice [t_start, t_end]."""
    dur = max(0.5, t_end - t_start)
    step = audio_prof["step"]
    dbs = audio_prof["db"]
    vrat = audio_prof["vocal_ratio"]
    a0 = max(0, int(t_start / step))
    a1 = min(len(dbs), max(a0 + 1, int(math.ceil(t_end / step))))

    w_dbs = dbs[a0:a1]
    w_vrat = vrat[a0:a1]
    quiet_mask = w_dbs < max(-30.0, audio_prof["avg_db"] - 1.4 * audio_prof["std_db"])
    quiet_ratio = float(np.mean(quiet_mask)) if len(w_dbs) else 1.0

    mot = vis_prof["motion"]
    v0 = max(0, int(t_start))
    v1 = min(len(mot), max(v0 + 1, int(math.ceil(t_end))))
    w_mot = mot[v0:v1]
    mot_med = float(np.median(mot)) if len(mot) else 1.0
    static_ratio = float(np.mean(w_mot < max(3.0, 0.35 * mot_med))) if len(w_mot) else 1.0

    dead_ratio = 0.55 * quiet_ratio + 0.45 * static_ratio

    n_cuts = sum(1 for sc in scene_changes if t_start <= sc <= t_end)
    n_peaks = sum(1 for pk in audio_peaks if t_start <= pk.timestamp <= t_end)
    cut_rate = min(1.0, (n_cuts / dur) / 0.35)
    peak_rate = min(1.0, (n_peaks / dur) / 0.08)
    loud_norm = min(1.0, max(0.0, (float(np.mean(w_dbs)) - (audio_prof["avg_db"] - audio_prof["std_db"])) / (2.0 * audio_prof["std_db"])))
    vocal_norm = min(1.0, float(np.mean(w_vrat)) / 0.65) if len(w_vrat) else 0.0

    activity = 0.30 * cut_rate + 0.30 * peak_rate + 0.20 * loud_norm + 0.20 * vocal_norm
    return float(max(0.0, min(1.0, activity))), float(max(0.0, min(1.0, dead_ratio)))


def _score_window(
    start_t: float,
    end_t: float,
    total_duration: float,
    audio_res: AudioAnalysisResult,
    visual_res: VisualAnalysisResult,
    audio_prof: Dict[str, Any],
    vis_prof: Dict[str, Any],
    chat_events: List[Tuple[float, float]],
) -> Dict[str, Any]:
    """Computes research-informed multi-factor highlight score and itemized evidence."""
    dur = max(1.0, end_t - start_t)
    step = audio_prof["step"]
    dbs = audio_prof["db"]
    vrat = audio_prof["vocal_ratio"]
    avg_db = audio_prof["avg_db"]
    std_db = audio_prof["std_db"]

    a0 = max(0, int(start_t / step))
    a1 = min(len(dbs), max(a0 + 1, int(math.ceil(end_t / step))))
    w_dbs = dbs[a0:a1]
    w_vrat = vrat[a0:a1]

    mot = vis_prof["motion"]
    fls = vis_prof["flash"]
    hists = vis_prof["hists"]
    global_hist = vis_prof["global_hist"]

    v0 = max(0, int(start_t))
    v1 = min(len(mot), max(v0 + 1, int(math.ceil(end_t))))
    w_mot = mot[v0:v1]
    w_fls = fls[v0:v1]
    w_hists = hists[v0:v1]
    win_mean_hist = np.mean(w_hists, axis=0) if len(w_hists) else global_hist
    win_mean_hist = win_mean_hist / (np.sum(win_mean_hist) + 1e-6)

    cuts_in = [sc for sc in visual_res.scene_changes if start_t <= sc <= end_t]
    peaks_in = [pk for pk in audio_res.peaks if start_t <= pk.timestamp <= end_t]
    segs_in = [seg for seg in audio_res.transcript_segments if seg.end > start_t and seg.start < end_t]

    # 1. Gameplay Novelty (0..1)
    # L1 distance from global video histogram + within-window visual variety + motion contrast
    hist_l1 = float(np.sum(np.abs(win_mean_hist - global_hist)))  # 0..2
    novelty_global = min(1.0, hist_l1 / 0.65)
    if len(w_hists) >= 3:
        internal_diffs = np.sum(np.abs(np.diff(w_hists, axis=0)), axis=1)
        novelty_internal = min(1.0, float(np.mean(internal_diffs)) / 0.55)
    else:
        novelty_internal = 0.2
    mot_p90 = float(np.percentile(mot, 90)) + 1e-6 if len(mot) else 25.0
    motion_contrast = min(1.0, float(np.max(w_mot)) / max(15.0, mot_p90)) if len(w_mot) else 0.0
    cut_density = min(1.0, (len(cuts_in) / dur) / 0.45)
    gameplay_novelty = 0.35 * novelty_global + 0.30 * novelty_internal + 0.20 * motion_contrast + 0.15 * cut_density

    # 2. Streamer Dialogue / Reaction Energy (0..1)
    peak_density = min(1.0, len(peaks_in) / max(1.0, dur / 12.0))
    max_prom = max((pk.relative_prominence for pk in peaks_in), default=0.0)
    prom_score = min(1.0, max_prom / 6.5)
    vocal_energy = min(1.0, float(np.mean(w_vrat)) / 0.60) if len(w_vrat) else 0.0
    vocal_dynamics = min(1.0, float(np.std(w_dbs)) / max(2.5, std_db * 1.1)) if len(w_dbs) > 1 else 0.0

    # Bonus if actual transcript segments with reaction keywords exist
    kw_hits = 0
    for seg in segs_in:
        tl = seg.text.lower()
        if any(kw in tl for kw in REACTION_KEYWORDS) or "!" in seg.text or "?" in seg.text:
            kw_hits += 1
    transcript_bonus = min(1.0, kw_hits / 3.0) if segs_in else None

    if transcript_bonus is not None:
        dialogue_reaction = 0.25 * peak_density + 0.20 * prom_score + 0.20 * vocal_energy + 0.15 * vocal_dynamics + 0.20 * transcript_bonus
    else:
        dialogue_reaction = 0.32 * peak_density + 0.26 * prom_score + 0.24 * vocal_energy + 0.18 * vocal_dynamics

    # 3. Opening Hook Strength (first 3.5s) (0..1)
    hook_end = min(end_t, start_t + 3.5)
    ha0 = max(0, int(start_t / step))
    ha1 = min(len(dbs), max(ha0 + 1, int(math.ceil(hook_end / step))))
    hook_dbs = dbs[ha0:ha1]
    hook_vrat = vrat[ha0:ha1]
    hook_cuts = [sc for sc in cuts_in if sc <= hook_end]
    hv0 = max(0, int(start_t))
    hv1 = min(len(mot), max(hv0 + 1, int(math.ceil(hook_end))))
    hook_mot = mot[hv0:hv1]

    hook_audio = min(1.0, max(0.0, (float(np.max(hook_dbs)) - (avg_db - 0.5 * std_db)) / (2.2 * std_db))) if len(hook_dbs) else 0.0
    hook_vocal = min(1.0, float(np.mean(hook_vrat)) / 0.58) if len(hook_vrat) else 0.0
    hook_visual = min(1.0, (0.55 * (float(np.max(hook_mot)) / max(15.0, mot_p90)) if len(hook_mot) else 0.0) + (0.45 if hook_cuts else 0.0))
    opening_hook = 0.40 * hook_audio + 0.25 * hook_vocal + 0.35 * hook_visual

    # Locate exact hook timestamp (strongest onset in first 3.5s)
    if len(hook_dbs):
        best_h_idx = int(np.argmax(hook_dbs))
        hook_time = round(min(end_t, start_t + best_h_idx * step), 2)
    else:
        hook_time = round(start_t, 2)

    # 4. Setup -> Visible Payoff Progression (0..1)
    # Find payoff strictly after initial setup (>= 30% into clip, min +4.0s)
    setup_cutoff = start_t + max(4.0, 0.30 * dur)
    payoff_search_end = end_t - 0.5
    if payoff_search_end <= setup_cutoff:
        setup_cutoff = start_t + 0.25 * dur
        payoff_search_end = end_t

    pv0 = max(0, int(setup_cutoff))
    pv1 = min(len(mot), max(pv0 + 1, int(math.ceil(payoff_search_end))))
    late_mot = mot[pv0:pv1]
    late_fls = fls[pv0:pv1]

    # Combine visual motion + flash + nearby audio peak at each second in payoff zone
    best_payoff_t = round(start_t + 0.72 * dur, 2)
    best_payoff_val = -1.0
    for sec_idx in range(pv0, pv1):
        sec_t = float(sec_idx)
        vis_sig = (float(mot[sec_idx]) / max(15.0, mot_p90)) * 0.55 + (float(fls[sec_idx]) / 35.0) * 0.45
        # Local audio energy near this second
        sa0 = max(0, int((sec_t - 1.0) / step))
        sa1 = min(len(dbs), max(sa0 + 1, int((sec_t + 1.5) / step)))
        aud_max = float(np.max(dbs[sa0:sa1])) if sa1 > sa0 else avg_db
        aud_sig = max(0.0, (aud_max - avg_db) / max(2.0, 1.5 * std_db))
        has_near_peak = any(abs(pk.timestamp - sec_t) <= 2.5 for pk in peaks_in)
        comb = vis_sig + 0.75 * aud_sig + (0.35 if has_near_peak else 0.0)
        if comb > best_payoff_val:
            best_payoff_val = comb
            best_payoff_t = round(min(end_t - 0.5, max(setup_cutoff, sec_t)), 2)

    # Compare setup visual/audio energy vs payoff zone energy
    sv0, sv1 = max(0, int(start_t)), min(len(mot), max(int(start_t) + 1, int(setup_cutoff)))
    setup_mot_mean = float(np.mean(mot[sv0:sv1])) if sv1 > sv0 else 1.0
    late_mot_peak = float(np.max(late_mot)) if len(late_mot) else 0.0
    late_fls_peak = float(np.max(late_fls)) if len(late_fls) else 0.0

    late_peaks = [pk for pk in peaks_in if pk.timestamp >= setup_cutoff]
    has_audio_payoff = 1.0 if late_peaks else min(0.7, max(0.0, best_payoff_val / 2.2))
    visible_payoff_sig = min(1.0, 0.55 * (late_mot_peak / max(15.0, mot_p90)) + 0.45 * min(1.0, late_fls_peak / 28.0))
    escalation_ratio = min(1.0, (late_mot_peak / (setup_mot_mean + 1e-6)) / 2.2)
    setup_to_payoff = 0.40 * visible_payoff_sig + 0.35 * has_audio_payoff + 0.25 * escalation_ratio

    # 5. Optional Chat Spikes (ONLY when chat_events is supplied!)
    chat_used = bool(chat_events)
    chat_score = 0.0
    chat_count_in = 0.0
    if chat_used:
        # Bin full recording chat into 10s bins to get baseline mean & std
        n_bins = max(1, int(math.ceil(total_duration / 10.0)))
        bins = np.zeros(n_bins, dtype=np.float32)
        for ts, wt in chat_events:
            bi = min(n_bins - 1, max(0, int(ts // 10.0)))
            bins[bi] += wt
        b_mean = float(np.mean(bins))
        b_std = float(np.std(bins)) + 1e-6
        chat_count_in = sum(wt for ts, wt in chat_events if start_t <= ts <= end_t)
        win_rate_per_10s = chat_count_in / max(1.0, dur / 10.0)
        z_chat = (win_rate_per_10s - b_mean) / b_std
        chat_score = max(0.0, min(1.0, (z_chat + 0.5) / 3.0))

    # Weighted base score (0..100)
    if chat_used:
        base_score = 100.0 * (
            0.21 * gameplay_novelty
            + 0.21 * dialogue_reaction
            + 0.17 * opening_hook
            + 0.25 * setup_to_payoff
            + 0.16 * chat_score
        )
    else:
        base_score = 100.0 * (
            0.25 * gameplay_novelty
            + 0.25 * dialogue_reaction
            + 0.20 * opening_hook
            + 0.30 * setup_to_payoff
        )

    # Penalties
    _, dead_ratio = _window_activity_quality(
        start_t, end_t, audio_prof, vis_prof, visual_res.scene_changes, audio_res.peaks
    )
    # Dead time penalty: kicks in strongly above 12% dead/quiet/static time
    dead_time_penalty = 0.0
    if dead_ratio > 0.12:
        dead_time_penalty = min(25.0, (dead_ratio - 0.12) * 55.0)

    # Intro chatter without payoff penalty:
    # Early recording intro (< 45s on recordings >= 120s) without strong gameplay climax
    intro_chatter_penalty = 0.0
    if total_duration >= 120.0 and start_t < 45.0:
        intro_weight = max(0.0, 1.0 - (start_t / 45.0))
        # If no strong late payoff or low novelty, penalize heavily; even moderate intro gets mild penalty
        lack_of_payoff = max(0.0, 0.85 - setup_to_payoff)
        lack_of_novelty = max(0.0, 0.80 - gameplay_novelty)
        intro_chatter_penalty = min(25.0, intro_weight * (10.0 + 22.0 * lack_of_payoff + 12.0 * lack_of_novelty))

    raw_final = max(0.0, min(100.0, base_score - dead_time_penalty - intro_chatter_penalty))

    return {
        "score": round(raw_final, 2),
        "base_score": round(base_score, 2),
        "hook_time": hook_time,
        "payoff_time": best_payoff_t,
        "mean_hist": win_mean_hist,
        "factors": {
            "gameplay_novelty": round(gameplay_novelty * 100.0, 1),
            "dialogue_reaction": round(dialogue_reaction * 100.0, 1),
            "opening_hook": round(opening_hook * 100.0, 1),
            "setup_to_payoff": round(setup_to_payoff * 100.0, 1),
            "chat_spike": round(chat_score * 100.0, 1) if chat_used else None,
            "chat_used": chat_used,
        },
        "penalties": {
            "dead_time": round(-dead_time_penalty, 2),
            "intro_chatter": round(-intro_chatter_penalty, 2),
            "repeated_moment": 0.0,
        },
        "metrics": {
            "scene_cuts": len(cuts_in),
            "audio_peaks": len(peaks_in),
            "max_audio_prominence_db": round(max_prom, 2),
            "dead_ratio": round(dead_ratio, 3),
            "hist_novelty_l1": round(hist_l1, 3),
            "late_motion_peak": round(late_mot_peak, 1),
            "late_flash_peak": round(late_fls_peak, 1),
            "chat_messages": round(chat_count_in, 1) if chat_used else 0.0,
        },
    }


def _build_adaptive_cuts(
    anchor_t: float,
    total_duration: float,
    dur_cfg: HighlightDurationConfig,
    audio_res: AudioAnalysisResult,
    visual_res: VisualAnalysisResult,
    audio_prof: Dict[str, Any],
    vis_prof: Dict[str, Any],
) -> Dict[str, Any]:
    """Builds a tight complete-story cut (20-35s) and evaluates whether surrounding
    footage justifies expanding to the configurable 45-60s target.
    """
    cuts = visual_res.scene_changes
    sil = audio_res.silence_ranges

    # 1. Core tight story cut (20-35s): pre-roll 10s before anchor, post-roll 16s after anchor
    tight_target = min(dur_cfg.tight_max, max(dur_cfg.tight_min, 26.0))
    t0_raw = max(0.0, anchor_t - tight_target * 0.38)
    t1_raw = min(total_duration, t0_raw + tight_target)
    if t1_raw - t0_raw < dur_cfg.tight_min and total_duration >= dur_cfg.tight_min:
        t0_raw = max(0.0, t1_raw - dur_cfg.tight_min)

    t_start = _snap_to_cut_or_silence(t0_raw, cuts, sil, total_duration, max_shift=1.8)
    t_end = _snap_to_cut_or_silence(t1_raw, cuts, sil, total_duration, max_shift=1.8)
    # Clamp tight cut inside [tight_min, tight_max] when recording allows
    if t_end - t_start < dur_cfg.tight_min and total_duration >= dur_cfg.tight_min:
        t_end = round(min(total_duration, t_start + dur_cfg.tight_min), 2)
        if t_end - t_start < dur_cfg.tight_min:
            t_start = round(max(0.0, t_end - dur_cfg.tight_min), 2)
    if t_end - t_start > dur_cfg.tight_max:
        t_end = round(t_start + dur_cfg.tight_max, 2)
    tight_dur = round(t_end - t_start, 2)

    tight_cut = {"start": round(t_start, 2), "end": round(t_end, 2), "duration": tight_dur}

    # 2. Evaluate surrounding footage for expansion toward configurable target_duration (45-60s)
    wants_expansion = dur_cfg.target_duration >= dur_cfg.expand_min and total_duration >= dur_cfg.expand_min
    if not wants_expansion:
        return {
            "primary_cut": tight_cut,
            "tight_cut": tight_cut,
            "long_cut": None,
            "supports_dual_cut": False,
            "cut_mode": "tight",
            "expansion_reason": f"Target duration ({dur_cfg.target_duration:.0f}s) fits tight story range.",
        }

    exp_target = min(dur_cfg.max_duration, max(dur_cfg.expand_min, dur_cfg.target_duration))
    extra_needed = max(0.0, exp_target - tight_dur)

    # Probe pre-extension and post-extension independently for genuine context / escalation / reaction
    pre_cand_start = max(0.0, t_start - extra_needed * 0.45)
    post_cand_end = min(total_duration, t_end + extra_needed * 0.55)

    pre_act, pre_dead = (
        _window_activity_quality(pre_cand_start, t_start, audio_prof, vis_prof, cuts, audio_res.peaks)
        if (t_start - pre_cand_start) >= 4.0 else (0.0, 1.0)
    )
    post_act, post_dead = (
        _window_activity_quality(t_end, post_cand_end, audio_prof, vis_prof, cuts, audio_res.peaks)
        if (post_cand_end - t_end) >= 4.0 else (0.0, 1.0)
    )

    pre_worthy = (t_start - pre_cand_start) >= 4.0 and pre_act >= 0.38 and pre_dead <= 0.28
    post_worthy = (post_cand_end - t_end) >= 4.0 and post_act >= 0.38 and post_dead <= 0.28

    l_start = _snap_to_cut_or_silence(pre_cand_start, cuts, sil, total_duration, max_shift=1.8) if pre_worthy else t_start
    l_end = _snap_to_cut_or_silence(post_cand_end, cuts, sil, total_duration, max_shift=1.8) if post_worthy else t_end

    # If only one side was worthy and it's rich, try extending that side further up to expand_min
    if pre_worthy and not post_worthy and (l_end - l_start) < dur_cfg.expand_min:
        alt_pre = max(0.0, t_end - exp_target)
        a_act, a_dead = _window_activity_quality(alt_pre, t_start, audio_prof, vis_prof, cuts, audio_res.peaks)
        if a_act >= 0.38 and a_dead <= 0.28:
            l_start = _snap_to_cut_or_silence(alt_pre, cuts, sil, total_duration, max_shift=1.8)
    elif post_worthy and not pre_worthy and (l_end - l_start) < dur_cfg.expand_min:
        alt_post = min(total_duration, t_start + exp_target)
        a_act, a_dead = _window_activity_quality(t_end, alt_post, audio_prof, vis_prof, cuts, audio_res.peaks)
        if a_act >= 0.38 and a_dead <= 0.28:
            l_end = _snap_to_cut_or_silence(alt_post, cuts, sil, total_duration, max_shift=1.8)

    if l_end - l_start > dur_cfg.max_duration:
        l_end = round(l_start + dur_cfg.max_duration, 2)
    long_dur = round(l_end - l_start, 2)

    if long_dur >= dur_cfg.expand_min and (pre_worthy or post_worthy):
        long_cut = {"start": round(l_start, 2), "end": round(l_end, 2), "duration": long_dur}
        sides = []
        if pre_worthy:
            sides.append(f"pre-context ({t_start - l_start:.1f}s, activity={pre_act:.2f})")
        if post_worthy:
            sides.append(f"post-escalation/reaction ({l_end - t_end:.1f}s, activity={post_act:.2f})")
        return {
            "primary_cut": long_cut,
            "tight_cut": tight_cut,
            "long_cut": long_cut,
            "supports_dual_cut": True,
            "cut_mode": "expanded_with_tight",
            "expansion_reason": f"Expanded to {long_dur:.1f}s (target {exp_target:.0f}s): surrounding footage adds " + " + ".join(sides),
        }

    return {
        "primary_cut": tight_cut,
        "tight_cut": tight_cut,
        "long_cut": None,
        "supports_dual_cut": False,
        "cut_mode": "tight",
        "expansion_reason": (
            f"Kept tight {tight_dur:.1f}s story cut (20-35s): surrounding footage did not add enough "
            f"escalation/context (pre_act={pre_act:.2f}/dead={pre_dead:.2f}, post_act={post_act:.2f}/dead={post_dead:.2f})."
        ),
    }


def _build_evidence_summary(
    scoring: Dict[str, Any],
    cut_info: Dict[str, Any],
    start_t: float,
    end_t: float,
) -> str:
    """Formats concise human-readable evidence explaining why a window ranked where it did."""
    f = scoring["factors"]
    p = scoring["penalties"]
    m = scoring["metrics"]

    parts = [
        f"Score {scoring['score']:.1f}/100",
        f"Novelty={f['gameplay_novelty']:.0f} (hist L1={m['hist_novelty_l1']:.2f}, {m['scene_cuts']} cuts)",
        f"Reaction={f['dialogue_reaction']:.0f} ({m['audio_peaks']} peaks, max +{m['max_audio_prominence_db']:.1f}dB)",
        f"Hook={f['opening_hook']:.0f} (@{scoring['hook_time']:.1f}s)",
        f"Payoff={f['setup_to_payoff']:.0f} (@{scoring['payoff_time']:.1f}s, motion={m['late_motion_peak']:.1f}, flash={m['late_flash_peak']:.1f})",
    ]
    if f["chat_used"]:
        parts.append(f"Chat={f['chat_spike']:.0f} ({m['chat_messages']:.0f} msgs)")
    pen_list = []
    if p["dead_time"] < -0.1:
        pen_list.append(f"dead_time {p['dead_time']:.1f}")
    if p["intro_chatter"] < -0.1:
        pen_list.append(f"intro_chatter {p['intro_chatter']:.1f}")
    if p["repeated_moment"] < -0.1:
        pen_list.append(f"repeat {p['repeated_moment']:.1f}")
    if pen_list:
        parts.append("Penalties: " + ", ".join(pen_list))
    parts.append(cut_info["expansion_reason"])
    return " | ".join(parts)


def rank_gta_highlights(
    video_path: Path,
    audio_res: AudioAnalysisResult,
    visual_res: VisualAnalysisResult,
    game_config: Dict[str, Any],
    job_dir: Path,
    max_candidates: int = 3,
    style_preset: Optional[StylePreset] = None,
    duration_config: Optional[HighlightDurationConfig] = None,
    chat_events: Optional[List[Tuple[float, float]]] = None,
    manual_markers: Optional[List[float]] = None,
    cache_dir: Optional[Path] = None,
) -> List[Any]:
    """Scans the full recording, builds adaptive tight/expanded highlight windows,
    ranks them with research-informed GTA highlight scoring + penalties, and returns
    up to `max_candidates` distinct top CandidateClip objects.
    """
    from .candidates import CandidateClip, _compute_overlap_ratio

    total_duration = visual_res.info.duration
    dur_cfg = duration_config or HighlightDurationConfig()
    chat_list = chat_events or []

    # 1. Compute full-recording visual (1fps) & audio (0.5s) profiles
    vis_prof = _extract_1fps_visual_profile(video_path, total_duration, cache_dir=cache_dir)
    audio_prof = _compute_audio_dynamics_profile(audio_res.pcm_wav_path, step_sec=0.5)

    # 2. Discover candidate anchors from scene changes, audio peaks, and optional chat spikes
    anchors: List[Tuple[float, str]] = []
    if manual_markers:
        for m in manual_markers:
            if 0.0 <= m <= total_duration:
                anchors.append((float(m), "manual_marker"))

    for pk in audio_res.peaks:
        anchors.append((float(pk.timestamp), "audio_peak"))

    for cs, ce in visual_res.action_clusters:
        # Place anchors at start-mid, center, and late-mid of long clusters so distinct moments inside long clusters are discovered
        c_dur = ce - cs
        if c_dur <= 35.0:
            anchors.append(((cs + ce) / 2.0, "visual_cluster"))
        else:
            step_c = 25.0
            t = cs + 12.0
            while t < ce - 8.0:
                anchors.append((t, "visual_cluster"))
                t += step_c

    # Also scan rolling 10s scene-change density bursts (catches intense multi-cut highlights)
    if visual_res.scene_changes:
        for t_win in range(10, max(11, int(total_duration) - 10), 10):
            n_sc = sum(1 for sc in visual_res.scene_changes if t_win <= sc < t_win + 10.0)
            if n_sc >= 4:
                anchors.append((float(t_win + 5.0), "scene_burst"))

    # Optional chat spike anchors (only when timestamped chat is supplied)
    if chat_list:
        n_bins = max(1, int(math.ceil(total_duration / 10.0)))
        cbins = np.zeros(n_bins, dtype=np.float32)
        for ts, wt in chat_list:
            bi = min(n_bins - 1, max(0, int(ts // 10.0)))
            cbins[bi] += wt
        c_mean = float(np.mean(cbins))
        c_std = float(np.std(cbins)) + 1e-6
        for bi, val in enumerate(cbins):
            if val >= c_mean + 1.5 * c_std and val > 0:
                anchors.append((bi * 10.0 + 5.0, "chat_spike"))

    # Fallback anchors across the timeline if recording is calm/short
    if not anchors:
        t = min(total_duration / 2.0, 15.0)
        while t < total_duration:
            anchors.append((t, "timeline_scan"))
            t += max(20.0, dur_cfg.tight_min)

    # Merge anchors within 10s of each other to avoid redundant scoring work
    anchors.sort(key=lambda x: x[0])
    merged_anchors: List[Tuple[float, str]] = []
    for t_val, src_tag in anchors:
        if not merged_anchors or (t_val - merged_anchors[-1][0]) >= 10.0:
            merged_anchors.append((t_val, src_tag))

    # 3. Build adaptive cuts and score every candidate window
    evaluated: List[Dict[str, Any]] = []
    for anchor_t, anchor_src in merged_anchors:
        cut_info = _build_adaptive_cuts(
            anchor_t=anchor_t,
            total_duration=total_duration,
            dur_cfg=dur_cfg,
            audio_res=audio_res,
            visual_res=visual_res,
            audio_prof=audio_prof,
            vis_prof=vis_prof,
        )
        p_cut = cut_info["primary_cut"]
        if p_cut["duration"] < min(12.0, total_duration):
            continue

        scoring = _score_window(
            start_t=p_cut["start"],
            end_t=p_cut["end"],
            total_duration=total_duration,
            audio_res=audio_res,
            visual_res=visual_res,
            audio_prof=audio_prof,
            vis_prof=vis_prof,
            chat_events=chat_list,
        )
        # Also score tight cut separately if dual-cut is available
        tight_scoring = None
        if cut_info["supports_dual_cut"] and cut_info["tight_cut"]:
            tc = cut_info["tight_cut"]
            tight_scoring = _score_window(
                start_t=tc["start"],
                end_t=tc["end"],
                total_duration=total_duration,
                audio_res=audio_res,
                visual_res=visual_res,
                audio_prof=audio_prof,
                vis_prof=vis_prof,
                chat_events=chat_list,
            )
            # If the tight cut actually scores meaningfully higher (> +5 pts) than the expanded cut,
            # prefer the tight cut as primary while still keeping long_cut available for review
            if tight_scoring["score"] > scoring["score"] + 5.0:
                cut_info["primary_cut"] = tc
                scoring = tight_scoring
                cut_info["expansion_reason"] = (
                    f"Tight {tc['duration']:.1f}s cut scored higher than {cut_info['long_cut']['duration']:.1f}s cut; "
                    "both tight and expanded cuts available for review."
                )

        evaluated.append({
            "anchor_t": anchor_t,
            "anchor_src": anchor_src,
            "cut_info": cut_info,
            "scoring": scoring,
            "tight_scoring": tight_scoring,
        })

    # 4. Greedy distinct selection with repeated-moment penalty
    selected_entries: List[Dict[str, Any]] = []
    remaining = list(evaluated)

    while remaining and len(selected_entries) < max_candidates:
        # Apply repeated-moment penalty relative to already-selected highlights
        for item in remaining:
            p_cut = item["cut_info"]["primary_cut"]
            h_cur = item["scoring"]["mean_hist"]
            max_rep_pen = 0.0
            for prev in selected_entries:
                prev_cut = prev["cut_info"]["primary_cut"]
                iou = _compute_overlap_ratio(p_cut["start"], p_cut["end"], prev_cut["start"], prev_cut["end"])
                # Gap between intervals
                gap = max(0.0, max(p_cut["start"] - prev_cut["end"], prev_cut["start"] - p_cut["end"]))
                # Cosine similarity of visual color histograms
                h_prev = prev["scoring"]["mean_hist"]
                cos_sim = float(np.dot(h_cur, h_prev) / ((np.linalg.norm(h_cur) * np.linalg.norm(h_prev)) + 1e-6))
                if iou > 0.05 or gap < 20.0:
                    max_rep_pen = max(max_rep_pen, 25.0)
                elif cos_sim > 0.94:
                    max_rep_pen = max(max_rep_pen, min(18.0, (cos_sim - 0.90) * 180.0))
            item["scoring"]["penalties"]["repeated_moment"] = round(-max_rep_pen, 2)
            base_after_pen = (
                item["scoring"]["base_score"]
                + item["scoring"]["penalties"]["dead_time"]
                + item["scoring"]["penalties"]["intro_chatter"]
                - max_rep_pen
            )
            item["scoring"]["score"] = round(max(0.0, min(100.0, base_after_pen)), 2)

        remaining.sort(key=lambda x: x["scoring"]["score"], reverse=True)
        best = remaining.pop(0)
        b_cut = best["cut_info"]["primary_cut"]

        # Enforce strictly distinct non-overlapping top moments
        overlaps_existing = any(
            _compute_overlap_ratio(
                b_cut["start"], b_cut["end"],
                prev["cut_info"]["primary_cut"]["start"], prev["cut_info"]["primary_cut"]["end"]
            ) > 0.05
            for prev in selected_entries
        )
        if overlaps_existing:
            continue
        selected_entries.append(best)

    # 5. Materialize CandidateClip objects with full metadata, framing, and thumbnails
    categories = game_config.get("categories", [])
    cat = categories[0] if categories else {"id": "gta_highlight", "name": "GTA Highlight"}
    thumb_dir = job_dir / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)

    final_clips: List[CandidateClip] = []
    for rank_idx, entry in enumerate(selected_entries, start=1):
        p_cut = entry["cut_info"]["primary_cut"]
        scoring = entry["scoring"]
        start_t = p_cut["start"]
        end_t = p_cut["end"]
        dur = p_cut["duration"]
        cid = f"clip_{rank_idx:02d}"

        t_start_img = thumb_dir / f"{cid}_start.jpg"
        t_payoff_img = thumb_dir / f"{cid}_payoff.jpg"
        t_end_img = thumb_dir / f"{cid}_end.jpg"
        extract_thumbnail_frame(video_path, start_t + 0.5, t_start_img)
        extract_thumbnail_frame(video_path, scoring["payoff_time"], t_payoff_img)
        extract_thumbnail_frame(video_path, max(start_t, end_t - 0.5), t_end_img)

        # Match any transcript segments inside [start_t, end_t]
        matching_segs = [
            seg for seg in audio_res.transcript_segments
            if seg.end > start_t and seg.start < end_t
        ]
        speech_summary = " ".join(s.text for s in matching_segs).strip()
        speech_segments_dicts = [
            {"start": s.start, "end": s.end, "text": s.text, "tokens": s.tokens}
            for s in matching_segs
        ]

        evidence_str = _build_evidence_summary(scoring, entry["cut_info"], start_t, end_t)
        setup_end = round(min(end_t, start_t + min(4.0, dur * 0.25)), 2)
        action_end = round(max(setup_end, min(end_t - 1.0, scoring["payoff_time"] - 1.0)), 2)

        shot_framing = compute_clip_shot_framing(
            video_path=video_path,
            clip_start=start_t,
            clip_end=end_t,
            scene_changes=visual_res.scene_changes,
            auto_framing=False,  # Computed dynamically during render --auto-framing
        )

        ranking_breakdown = {
            "mode": "gta_highlight",
            "rank": rank_idx,
            "score": scoring["score"],
            "base_score": scoring["base_score"],
            "hook_time": scoring["hook_time"],
            "payoff_time": scoring["payoff_time"],
            "factors": scoring["factors"],
            "penalties": scoring["penalties"],
            "metrics": scoring["metrics"],
            "anchor_source": entry["anchor_src"],
            "cut_mode": entry["cut_info"]["cut_mode"],
            "supports_dual_cut": entry["cut_info"]["supports_dual_cut"],
            "tight_cut": entry["cut_info"]["tight_cut"],
            "long_cut": entry["cut_info"]["long_cut"],
            "expansion_reason": entry["cut_info"]["expansion_reason"],
        }

        clip = CandidateClip(
            id=cid,
            category_id=cat.get("id", "gta_highlight"),
            category_name=f"GTA Highlight Rank #{rank_idx}",
            start_time=start_t,
            end_time=end_t,
            duration=dur,
            payoff_time=scoring["payoff_time"],
            hook_lead_seconds=round(max(0.5, scoring["hook_time"] - start_t), 2),
            cue=f"Rank #{rank_idx} ({scoring['score']:.1f}/100) — {entry['anchor_src']}",
            reason=evidence_str,
            evidence_type="audio_energy" if scoring["metrics"]["audio_peaks"] > 0 else "visual_frame",
            evidence_detail=evidence_str,
            confidence=round(min(0.99, max(0.50, scoring["score"] / 100.0)), 2),
            proposed_layout="hybrid",
            hook_text=f"GTA CHAOS HIGHLIGHT #{rank_idx}",
            title=f"GTA Highlight #{rank_idx} ({start_t:.1f}s - {end_t:.1f}s)",
            description=f"Research-ranked GTA highlight ({start_t:.1f}s-{end_t:.1f}s). {evidence_str}",
            posting_caption=f"Wait for the payoff at {scoring['payoff_time'] - start_t:.0f}s #GTAV #Gaming #Shorts",
            spoiler_flag=False,
            music_review_flag=audio_res.baked_music_flag,
            preview_frames={
                "start": str(t_start_img) if t_start_img.is_file() else "",
                "payoff": str(t_payoff_img) if t_payoff_img.is_file() else "",
                "end": str(t_end_img) if t_end_img.is_file() else "",
            },
            setup_start_time=start_t,
            setup_end_time=setup_end,
            action_start_time=setup_end,
            action_end_time=action_end,
            payoff_start_time=action_end,
            payoff_end_time=end_t,
            shot_framing=shot_framing,
            awaiting_captions=(not audio_res.is_transcribed and not matching_segs),
            is_visual_only=False,
            uncertain_speech=any(s.uncertain for s in matching_segs),
            speech_summary=speech_summary,
            speech_segments=speech_segments_dicts,
            ranking_breakdown=ranking_breakdown,
        )
        final_clips.append(clip)

    return final_clips
