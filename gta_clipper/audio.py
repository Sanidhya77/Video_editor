"""Audio extraction, loudness/energy analysis, multi-track selection, and local Whisper transcription.
"""

from __future__ import annotations
import dataclasses
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
from typing import List, Dict, Any, Optional
import wave

from .config import StorageConfig


REACTION_KEYWORDS = {
    "no way", "oh my god", "omg", "what", "bro", "dude", "look", "holy",
    "shit", "what the", "are you kidding", "insane", "crazy", "survive",
    "dead", "died", "killed", "jump", "crashed", "wrecked", "wait", "watch",
    "police", "cops", "run", "help", "haha", "lol", "lmao", "gg"
}


@dataclasses.dataclass
class AudioSegment:
    start: float
    end: float
    text: str
    tokens: Optional[List[Dict[str, Any]]] = None
    speaker: str = "Streamer"
    uncertain: bool = False
    uncertainty_reason: Optional[str] = None
    words: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class AudioPeak:
    timestamp: float
    rms_db: float
    relative_prominence: float  # dB above baseline

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class AudioAnalysisResult:
    has_audio: bool
    pcm_wav_path: Optional[str]
    duration: float
    peaks: List[AudioPeak]
    silence_ranges: List[tuple[float, float]]
    transcript_segments: List[AudioSegment]
    is_transcribed: bool
    baked_music_flag: bool
    audio_tracks: List[Dict[str, Any]]
    selected_track_index: int
    whisper_status: str  # "READY" | "MODEL_MISSING" | "CLI_MISSING" | "EXTERNAL_IMPORT"
    whisper_diagnostic: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_audio": self.has_audio,
            "pcm_wav_path": self.pcm_wav_path,
            "duration": self.duration,
            "peaks": [p.to_dict() for p in self.peaks],
            "silence_ranges": self.silence_ranges,
            "transcript_segments": [s.to_dict() for s in self.transcript_segments],
            "is_transcribed": self.is_transcribed,
            "baked_music_flag": self.baked_music_flag,
            "audio_tracks": self.audio_tracks,
            "selected_track_index": self.selected_track_index,
            "whisper_status": self.whisper_status,
            "whisper_diagnostic": self.whisper_diagnostic,
        }


def probe_audio_tracks(video_path: Path) -> List[Dict[str, Any]]:
    """Probes all audio streams in the video to enable explicit mic/game track selection."""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=20)
        data = json.loads(res.stdout)
        audio_streams = []
        track_idx = 0
        for s in data.get("streams", []):
            if s.get("codec_type") == "audio":
                tags = s.get("tags", {})
                title = tags.get("title") or tags.get("handler_name") or f"Track {track_idx}"
                audio_streams.append({
                    "track_index": track_idx,
                    "codec_name": s.get("codec_name", "unknown"),
                    "channels": int(s.get("channels", 2)),
                    "sample_rate": int(s.get("sample_rate", 44100)),
                    "title": title,
                })
                track_idx += 1
        return audio_streams
    except Exception:
        return [{"track_index": 0, "codec_name": "unknown", "channels": 2, "sample_rate": 48000, "title": "Track 0"}]


def extract_pcm_16k_mono(
    video_path: Path,
    output_wav: Path,
    track_index: int = 0,
) -> bool:
    """Extracts 16 kHz 16-bit mono PCM audio from the selected audio stream."""
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-map", f"0:a:{track_index}?",
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        if res.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 44:
            return True

        # Fallback if map fails (e.g. invalid track_index)
        fallback_cmd = [
            "ffmpeg", "-y", "-i", str(video_path), "-vn",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(output_wav)
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=120)
        return res_fb.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 44
    except Exception:
        return False


def extract_candidate_audio_pcm(
    video_path: Path,
    output_wav: Path,
    start_time: float,
    duration: float,
    track_index: int = 0,
) -> bool:
    """Extracts a 16 kHz mono WAV slice for a candidate clip [start_time, start_time + duration].
    Keeps all video processing local; only this audio slice is sent to cloud transcription if enabled.
    """
    output_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-ss", f"{start_time:.3f}",
        "-t", f"{duration:.3f}",
        "-i", str(video_path),
        "-map", f"0:a:{track_index}?",
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        str(output_wav)
    ]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        if res.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 44:
            return True
        # Fallback without explicit map if track index mapping fails
        fallback_cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_time:.3f}",
            "-t", f"{duration:.3f}",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_wav)
        ]
        res_fb = subprocess.run(fallback_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        return res_fb.returncode == 0 and output_wav.is_file() and output_wav.stat().st_size > 44
    except Exception:
        return False


def analyze_audio_energy(
    wav_path: Path,
    window_sec: float = 0.5
) -> tuple[float, List[AudioPeak], bool]:
    """Analyzes RMS energy across windows using standard-library wave and struct."""
    if not wav_path.is_file() or wav_path.stat().st_size <= 44:
        return 0.0, [], False

    try:
        with wave.open(str(wav_path), "rb") as wf:
            framerate = wf.getframerate()
            n_frames = wf.getnframes()
            duration = n_frames / float(framerate) if framerate > 0 else 0.0

            if duration <= 0:
                return 0.0, [], False

            samples_per_window = int(framerate * window_sec)
            total_windows = int(math.ceil(n_frames / samples_per_window))

            energies = []
            for i in range(total_windows):
                raw_bytes = wf.readframes(samples_per_window)
                if not raw_bytes:
                    break
                num_samples = len(raw_bytes) // 2
                if num_samples == 0:
                    continue
                samples = struct.unpack(f"<{num_samples}h", raw_bytes[:num_samples * 2])
                sum_sq = sum(s * s for s in samples)
                mean_sq = sum_sq / num_samples
                rms = math.sqrt(mean_sq) if mean_sq > 0 else 1.0
                db = 20 * math.log10(max(rms, 1.0) / 32768.0)
                energies.append(db)

        if not energies:
            return duration, [], False

        avg_db = sum(energies) / len(energies)
        variance = sum((x - avg_db) ** 2 for x in energies) / len(energies)
        std_db = math.sqrt(variance)
        peaks: List[AudioPeak] = []

        # Adaptive threshold: catches +8 dB spikes on dynamic/synthetic audio AND
        # genuine loudness surges on broadcast-normalized gaming streams (YouTube/Twitch)
        adaptive_prom_thresh = min(8.0, max(3.8, 1.15 * std_db))

        for idx, db in enumerate(energies):
            t = idx * window_sec
            prominence = db - avg_db
            lo = max(0, idx - 10)
            hi = min(len(energies), idx + 11)
            local_avg = sum(energies[lo:hi]) / (hi - lo)
            local_prom = db - local_avg

            is_strong_global = prominence >= 8.0 and db > -35.0
            is_adaptive_surge = (
                prominence >= adaptive_prom_thresh
                and local_prom >= 2.2
                and db > -22.0
            )
            if is_strong_global or is_adaptive_surge:
                prev_db = energies[idx - 1] if idx > 0 else -100.0
                next_db = energies[idx + 1] if idx + 1 < len(energies) else -100.0
                if db >= prev_db and db >= next_db:
                    peaks.append(AudioPeak(timestamp=round(t, 2), rms_db=round(db, 2), relative_prominence=round(prominence, 2)))

        baked_music = (avg_db > -22.0) and (variance < 15.0) and (duration > 10.0)

        return duration, peaks, baked_music

    except Exception:
        return 0.0, [], False


def detect_silence(wav_path: Path) -> List[tuple[float, float]]:
    """Runs FFmpeg silencedetect to find quiet pauses."""
    cmd = [
        "ffmpeg",
        "-i", str(wav_path),
        "-af", "silencedetect=noise=-30dB:d=0.6",
        "-f", "null",
        "-"
    ]
    silence_ranges = []
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
        output = res.stderr
        starts = re.findall(r"silence_start:\s*([0-9.]+)", output)
        ends = re.findall(r"silence_end:\s*([0-9.]+)", output)
        for s, e in zip(starts, ends):
            silence_ranges.append((float(s), float(e)))
    except Exception:
        pass
    return silence_ranges


def check_whisper_backend(storage: StorageConfig) -> tuple[str, str, Optional[str], Optional[str]]:
    """Checks whether whisper-cli and GGML models exist locally."""
    whisper_cli = shutil.which("whisper-cli") or shutil.which("whisper")

    # Also check inside storage.models_dir for a bundled executable
    if not whisper_cli:
        candidate_exe = storage.models_dir / "whisper-cli.exe"
        if candidate_exe.is_file():
            whisper_cli = str(candidate_exe)

    models = list(storage.models_dir.glob("*.bin")) if storage.models_dir.exists() else []
    model_path = str(models[0]) if models else None

    if not whisper_cli:
        status = "CLI_MISSING"
        msg = (
            "whisper-cli executable not found on PATH or in models directory.\n"
            "Download official Windows whisper-cli (pinned v1.7.4) from:\n"
            "https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.4"
        )
        return status, msg, None, model_path

    if not model_path:
        status = "MODEL_MISSING"
        msg = (
            f"whisper-cli found ({whisper_cli}), but no GGML model (.bin) located in:\n"
            f"{storage.models_dir}\n"
            "Download e.g. ggml-tiny.bin or ggml-base.bin from:\n"
            "https://huggingface.co/ggerganov/whisper.cpp/tree/main"
        )
        return status, msg, whisper_cli, None

    return "READY", f"Whisper backend ready ({whisper_cli}) using {Path(model_path).name}", whisper_cli, model_path


def parse_external_transcript(transcript_path: Path) -> List[AudioSegment]:
    """Parses an existing SRT or JSON transcript file."""
    if not transcript_path.is_file():
        raise FileNotFoundError(f"Transcript file not found: {transcript_path}")

    segments: List[AudioSegment] = []
    ext = transcript_path.suffix.lower()

    if ext == ".json":
        with open(transcript_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    segments.append(AudioSegment(
                        start=float(item["start"]),
                        end=float(item["end"]),
                        text=str(item["text"]).strip(),
                        tokens=item.get("tokens"),
                        speaker=item.get("speaker", "Streamer"),
                    ))
            elif isinstance(data, dict) and "segments" in data:
                for item in data["segments"]:
                    segments.append(AudioSegment(
                        start=float(item["start"]),
                        end=float(item["end"]),
                        text=str(item["text"]).strip(),
                        speaker=item.get("speaker", "Streamer"),
                    ))

    elif ext == ".srt":
        content = transcript_path.read_text(encoding="utf-8")
        blocks = re.split(r"\n\s*\n", content.strip())
        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if len(lines) >= 2:
                time_line = lines[1] if re.match(r"^\d+$", lines[0]) else lines[0]
                text_lines = lines[2:] if re.match(r"^\d+$", lines[0]) else lines[1:]
                m = re.match(r"(\d{2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{3})", time_line)
                if m:
                    s_sec = _timestamp_to_seconds(m.group(1))
                    e_sec = _timestamp_to_seconds(m.group(2))
                    text = " ".join(text_lines)
                    segments.append(AudioSegment(start=s_sec, end=e_sec, text=text))

    return segments


def run_transcription(
    wav_path: Path,
    storage: StorageConfig,
    cache_key: str,
    language: Optional[str] = None,
) -> tuple[List[AudioSegment], str, str]:
    """Transcribes audio using whisper-cli if available, with caching and diagnostic status."""
    cached_file = storage.transcript_cache_dir / f"{cache_key}.json"
    if cached_file.is_file():
        try:
            with open(cached_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [AudioSegment(**item) for item in data], "READY", "Loaded from local cache"
        except Exception:
            pass

    status, diag, whisper_cli, model_path = check_whisper_backend(storage)
    if status != "READY" or not whisper_cli or not model_path:
        return [], status, diag

    out_prefix = storage.transcript_cache_dir / f"temp_{cache_key}"
    cmd = [
        whisper_cli,
        "-m", model_path,
        "-f", str(wav_path),
        "-oj",
        "-of", str(out_prefix),
        "--no-prints",
    ]
    if language:
        cmd.extend(["-l", language])

    segments: List[AudioSegment] = []
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=240)
        json_file = Path(f"{out_prefix}.json")
        if json_file.is_file():
            with open(json_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
                transcription = raw.get("transcription", [])
                for item in transcription:
                    t_start = item.get("timestamps", {}).get("from", "00:00:00,000")
                    t_end = item.get("timestamps", {}).get("to", "00:00:00,000")
                    text = item.get("text", "").strip()
                    tokens = item.get("tokens")

                    s_sec = _timestamp_to_seconds(t_start)
                    e_sec = _timestamp_to_seconds(t_end)
                    if text and e_sec > s_sec:
                        segments.append(AudioSegment(
                            start=s_sec,
                            end=e_sec,
                            text=text,
                            tokens=tokens,
                            speaker="Streamer",
                        ))

            with open(cached_file, "w", encoding="utf-8") as f:
                json.dump([s.to_dict() for s in segments], f, indent=2)

            if json_file.is_file():
                json_file.unlink()

            return segments, "READY", f"Transcribed {len(segments)} segments"
        else:
            return [], "EXEC_ERROR", f"Whisper exited without creating output JSON (code {res.returncode})"

    except Exception as e:
        return [], "EXEC_ERROR", str(e)


def _timestamp_to_seconds(ts: str) -> float:
    """Converts '00:01:23,456' or '00:01:23.456' to float seconds."""
    ts = ts.replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
        return float(h) * 3600 + float(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        return float(m) * 60 + float(s)
    try:
        return float(ts)
    except ValueError:
        return 0.0


def analyze_audio(
    video_path: Path,
    storage: StorageConfig,
    source_hash: str,
    track_index: int = 0,
    external_transcript_path: Optional[Path] = None,
    language: Optional[str] = None,
    transcription_provider: str = "local",
) -> AudioAnalysisResult:
    """Full audio pipeline: multi-track inspection, extraction, energy analysis, and transcription."""
    audio_tracks = probe_audio_tracks(video_path)
    wav_cache = storage.audio_cache_dir / f"{source_hash}_track{track_index}_16k.wav"

    if not wav_cache.is_file():
        success = extract_pcm_16k_mono(video_path, wav_cache, track_index=track_index)
        if not success:
            return AudioAnalysisResult(
                has_audio=False,
                pcm_wav_path=None,
                duration=0.0,
                peaks=[],
                silence_ranges=[],
                transcript_segments=[],
                is_transcribed=False,
                baked_music_flag=False,
                audio_tracks=audio_tracks,
                selected_track_index=track_index,
                whisper_status="NO_AUDIO",
                whisper_diagnostic="No audio stream extracted",
            )

    duration, peaks, baked_music = analyze_audio_energy(wav_cache)
    silence = detect_silence(wav_cache)

    # 1. External transcript provided as fallback
    if external_transcript_path and external_transcript_path.is_file():
        transcript = parse_external_transcript(external_transcript_path)
        whisper_status = "EXTERNAL_IMPORT"
        whisper_diag = f"Imported {len(transcript)} segments from {external_transcript_path.name}"
        # Cache imported segments so trimming clips in review_sheet.json recomputes subtitles cleanly
        try:
            cache_file = storage.transcript_cache_dir / f"{source_hash}_t{track_index}.json"
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as cf:
                json.dump([dataclasses.asdict(seg) for seg in transcript], cf, indent=2, ensure_ascii=False)
        except Exception:
            pass
    elif transcription_provider == "groq":
        # Groq Whisper: Candidate audio slice is extracted and transcribed per-candidate
        # to preserve bandwidth and privacy. Check API key presence here.
        groq_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not groq_key:
            from .groq_transcriber import get_groq_api_key
            groq_key = get_groq_api_key(storage)

        if groq_key:
            whisper_status = "GROQ_OPTED_IN"
            whisper_diag = "Groq cloud transcription opted-in (whisper-large-v3-turbo); candidate slice will be transcribed"
        else:
            whisper_status = "GROQ_KEY_MISSING"
            whisper_diag = "Groq API key not configured ($env:GROQ_API_KEY); candidates will await captions"
        transcript = []
    elif transcription_provider == "none":
        whisper_status = "DISABLED"
        whisper_diag = "Speech transcription disabled by operator"
        transcript = []
    else:
        # 2. Local Whisper runner
        transcript, whisper_status, whisper_diag = run_transcription(
            wav_path=wav_cache,
            storage=storage,
            cache_key=f"{source_hash}_t{track_index}",
            language=language,
        )

    # 3. Flag uncertain sections (overlapping loud crashes, music, or short exclamations)
    for seg in transcript:
        # Check if segment overlaps with a loud peak (> 15 dB prominence)
        coincident_peak = any(seg.start <= p.timestamp <= seg.end and p.relative_prominence >= 15.0 for p in peaks)
        if coincident_peak or baked_music:
            seg.uncertain = True
            seg.uncertainty_reason = "Loud audio background / music overlay; verify words"

    return AudioAnalysisResult(
        has_audio=True,
        pcm_wav_path=str(wav_cache),
        duration=duration,
        peaks=peaks,
        silence_ranges=silence,
        transcript_segments=transcript,
        is_transcribed=len(transcript) > 0,
        baked_music_flag=baked_music,
        audio_tracks=audio_tracks,
        selected_track_index=track_index,
        whisper_status=whisper_status,
        whisper_diagnostic=whisper_diag,
    )
