"""Groq Whisper API integration for speech-to-text.
Uses whisper-large-v3-turbo with verbose_json for segment and word timestamps.
Maintains privacy by sending only candidate audio slices and keeping video 100% local.
"""

from __future__ import annotations
import dataclasses
import json
import os
from pathlib import Path
import re
from typing import List, Dict, Any, Optional, Tuple

from .config import StorageConfig
from .audio import AudioSegment


GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
DEFAULT_GROQ_MODEL = "whisper-large-v3-turbo"


def _parse_key_from_env_file(env_path: Path, key_name: str) -> Optional[str]:
    """Safely extracts key value from a .env file without printing or logging."""
    if not env_path.is_file():
        return None
    try:
        content = env_path.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            line = line.strip()
            if line.startswith(f"{key_name}="):
                val = line[len(key_name) + 1:].strip()
                if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                    val = val[1:-1]
                return val.strip() if val.strip() else None
    except Exception:
        pass
    return None


def get_groq_api_key(storage: Optional[StorageConfig] = None) -> Optional[str]:
    """Retrieves GROQ_API_KEY from environment or safe .env files outside OneDrive.
    Never logs or leaks the key value.
    """
    # 1. Environment variable (recommended)
    val = os.environ.get("GROQ_API_KEY", "").strip()
    if val:
        return val

    # 2. Storage root .env (outside OneDrive)
    if storage and storage.root:
        storage_env = storage.root / ".env"
        key = _parse_key_from_env_file(storage_env, "GROQ_API_KEY")
        if key:
            return key

    # 3. User home directory ~/.env (standard outside OneDrive)
    home_env = Path.home() / ".env"
    key = _parse_key_from_env_file(home_env, "GROQ_API_KEY")
    if key:
        return key

    return None


def check_groq_status(storage: Optional[StorageConfig] = None) -> Tuple[str, str]:
    """Checks whether Groq API key is configured.
    Returns (status, diagnostic_message).
    """
    key = get_groq_api_key(storage)
    if not key:
        msg = (
            "GROQ_API_KEY is not configured.\n"
            "To set it safely in PowerShell without putting it in code or OneDrive:\n"
            "  For current session:\n"
            '    $env:GROQ_API_KEY = "gsk_your_key_here"\n'
            "  For persistent user variable:\n"
            "    [System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'gsk_your_key_here', 'User')\n"
            "Get an API key from https://console.groq.com/keys"
        )
        return "KEY_MISSING", msg

    return "API_KEY_CONFIGURED", "Groq API key configured."


def call_groq_transcription_api(
    audio_path: Path,
    api_key: str,
    model: str = DEFAULT_GROQ_MODEL,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    temperature: float = 0.0,
    timeout: float = 60.0,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Performs HTTP POST to Groq Whisper API requesting verbose_json with word timestamps.
    Returns (raw_json_dict, status, error_or_success_message).
    """
    if not audio_path.is_file():
        return None, "FILE_NOT_FOUND", f"Audio file not found: {audio_path}"

    if audio_path.stat().st_size <= 44:
        return None, "EMPTY_AUDIO", f"Audio file is empty or corrupted: {audio_path}"

    # Try requests first if available
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {api_key}",
        }
        # In Groq API, timestamp_granularities[] takes 'word' and/or 'segment'
        data_fields: List[Tuple[str, str]] = [
            ("model", model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
            ("temperature", str(temperature)),
        ]
        if language:
            data_fields.append(("language", language))
        if prompt:
            data_fields.append(("prompt", prompt))

        with open(audio_path, "rb") as af:
            files = {
                "file": (audio_path.name, af, "audio/wav"),
            }
            resp = requests.post(
                GROQ_API_URL,
                headers=headers,
                data=data_fields,
                files=files,
                timeout=timeout,
            )

        if resp.status_code == 200:
            return resp.json(), "READY", f"Transcribed via Groq {model}"
        elif resp.status_code == 401:
            return None, "INVALID_KEY", "Groq API returned 401 Unauthorized: Invalid API Key."
        elif resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "")
            retry_note = f" (Retry-After: {retry_after}s)" if retry_after else ""
            return None, "QUOTA_EXCEEDED", f"Groq API rate limit or quota exceeded (HTTP 429){retry_note}."
        else:
            return None, "API_ERROR", f"Groq API request failed (HTTP {resp.status_code})."

    except Exception as e:
        # Standard library urllib fallback
        try:
            return _call_groq_urllib(audio_path, api_key, model, language, prompt, temperature, timeout)
        except Exception as fb_err:
            return None, "NETWORK_ERROR", f"Failed to connect to Groq API: {e} (fallback: {fb_err})"


def _call_groq_urllib(
    audio_path: Path,
    api_key: str,
    model: str,
    language: Optional[str],
    prompt: Optional[str],
    temperature: float,
    timeout: float,
) -> Tuple[Optional[Dict[str, Any]], str, str]:
    """Fallback multipart/form-data upload using standard library urllib."""
    import urllib.request
    import urllib.error
    import uuid

    boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"
    body = bytearray()

    def add_field(name: str, value: str):
        nonlocal body
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{value}\r\n".encode("utf-8"))

    add_field("model", model)
    add_field("response_format", "verbose_json")
    add_field("timestamp_granularities[]", "word")
    add_field("timestamp_granularities[]", "segment")
    add_field("temperature", str(temperature))
    if language:
        add_field("language", language)
    if prompt:
        add_field("prompt", prompt)

    # Add file
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{audio_path.name}"\r\n'.encode("utf-8")
    )
    body.extend(b"Content-Type: audio/wav\r\n\r\n")
    body.extend(audio_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    req = urllib.request.Request(
        GROQ_API_URL,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data, "READY", f"Transcribed via Groq {model}"
    except urllib.error.HTTPError as he:
        if he.code == 401:
            return None, "INVALID_KEY", "Groq API returned 401 Unauthorized."
        elif he.code == 429:
            retry_after = he.headers.get("Retry-After", "") if hasattr(he, "headers") else ""
            retry_note = f" (Retry-After: {retry_after}s)" if retry_after else ""
            return None, "QUOTA_EXCEEDED", f"Groq API rate limit or quota exceeded (HTTP 429){retry_note}."
        return None, "API_ERROR", f"Groq API request failed (HTTP {he.code})."
    except Exception as ex:
        return None, "NETWORK_ERROR", f"Network error connecting to Groq: {ex}"


def parse_groq_verbose_json(
    raw_json: Dict[str, Any],
    candidate_start_time: float = 0.0,
    speaker: str = "Streamer",
) -> List[AudioSegment]:
    """Parses Groq verbose_json output, offsets timestamps by candidate_start_time,
    and structures segments with word timings for future word-by-word animation.
    """
    segments: List[AudioSegment] = []
    raw_segments = raw_json.get("segments", [])
    root_words = raw_json.get("words", [])

    if not raw_segments:
        # Fallback if only root text is present
        text = raw_json.get("text", "").strip()
        duration = float(raw_json.get("duration", 0.0))
        if text:
            # Build words if present
            words_list = []
            for w in root_words:
                w_start = candidate_start_time + float(w.get("start", 0.0))
                w_end = candidate_start_time + float(w.get("end", 0.0))
                words_list.append({
                    "word": w.get("word", "").strip(),
                    "text": w.get("word", "").strip(),
                    "start": round(w_start, 3),
                    "end": round(w_end, 3),
                    "duration": round(w_end - w_start, 3),
                    "rel_start": round(float(w.get("start", 0.0)), 3),
                    "rel_end": round(float(w.get("end", 0.0)), 3),
                })
            segments.append(AudioSegment(
                start=round(candidate_start_time, 3),
                end=round(candidate_start_time + duration, 3),
                text=text,
                tokens=words_list,
                words=words_list,
                speaker=speaker,
            ))
        return segments

    for seg in raw_segments:
        seg_start_rel = float(seg.get("start", 0.0))
        seg_end_rel = float(seg.get("end", 0.0))
        text = seg.get("text", "").strip()

        if not text or seg_end_rel <= seg_start_rel:
            continue

        abs_start = candidate_start_time + seg_start_rel
        abs_end = candidate_start_time + seg_end_rel

        # Extract word timestamps
        seg_words = seg.get("words")
        if not seg_words and root_words:
            # Filter root words falling within this segment's window
            seg_words = [
                w for w in root_words
                if seg_start_rel <= float(w.get("start", 0.0)) < seg_end_rel + 0.1
            ]

        converted_words: List[Dict[str, Any]] = []
        if seg_words:
            for w in seg_words:
                w_start_rel = float(w.get("start", 0.0))
                w_end_rel = float(w.get("end", 0.0))
                w_text = w.get("word", "").strip()
                if w_text:
                    converted_words.append({
                        "word": w_text,
                        "text": w_text,
                        "start": round(candidate_start_time + w_start_rel, 3),
                        "end": round(candidate_start_time + w_end_rel, 3),
                        "duration": round(max(0.05, w_end_rel - w_start_rel), 3),
                        "rel_start": round(w_start_rel, 3),
                        "rel_end": round(w_end_rel, 3),
                    })

        # Uncertainty heuristic: high compression ratio or low avg logprob
        uncertain = False
        reason = None
        if seg.get("avg_logprob", 0.0) < -0.9:
            uncertain = True
            reason = "Low Whisper model confidence (low logprob)"
        elif seg.get("no_speech_prob", 0.0) > 0.4:
            uncertain = True
            reason = "High probability of background noise / music"

        segments.append(AudioSegment(
            start=round(abs_start, 3),
            end=round(abs_end, 3),
            text=text,
            tokens=converted_words,  # tokens for ASS karaoke
            words=converted_words,   # explicit word timings
            speaker=speaker,
            uncertain=uncertain,
            uncertainty_reason=reason,
        ))

    return segments


def transcribe_candidate_with_groq(
    audio_path: Path,
    candidate_start_time: float,
    api_key: Optional[str] = None,
    storage: Optional[StorageConfig] = None,
    model: str = DEFAULT_GROQ_MODEL,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> Tuple[List[AudioSegment], str, str]:
    """Transcribes a candidate audio slice using Groq Whisper API.
    Accounts for candidate_start_time offset in the original stream.
    Returns (segments, status, diagnostic).
    """
    resolved_key = api_key or get_groq_api_key(storage)
    if not resolved_key:
        status, msg = check_groq_status(storage)
        return [], status, msg

    raw_json, status, msg = call_groq_transcription_api(
        audio_path=audio_path,
        api_key=resolved_key,
        model=model,
        language=language,
        prompt=prompt,
    )

    if status != "READY" or not raw_json:
        return [], status, msg

    segments = parse_groq_verbose_json(
        raw_json=raw_json,
        candidate_start_time=candidate_start_time,
        speaker="Streamer",
    )

    return segments, "READY", f"Transcribed {len(segments)} segments via Groq {model}"


def transcribe_candidate_with_fallback(
    audio_path: Path,
    candidate_start_time: float,
    api_key: Optional[str] = None,
    storage: Optional[StorageConfig] = None,
    model: str = DEFAULT_GROQ_MODEL,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
    fallback_provider: str = "local",  # "local", "srt", "freellmapi", "none"
    fallback_srt_path: Optional[Path] = None,
) -> Tuple[List[AudioSegment], str, str]:
    """Transcribes candidate audio with graceful fallback on quota exhaustion / rate limiting.
    1. Primary: Groq Whisper API (whisper-large-v3-turbo).
    2. Fallback on 429 quota exhaustion or API failure:
       - Avoids repeated requests; respects retry note.
       - Tries local whisper.cpp (if available).
       - Tries manual SRT import (if provided).
       - Evaluates FreeLLMAPI (kept disabled if unverified/sharing Groq quota).
       - Holds candidate awaiting captions if no fallback is available.
    """
    st = storage or StorageConfig()
    resolved_key = api_key or get_groq_api_key(st)

    quota_msg = ""
    if resolved_key:
        raw_json, status, msg = call_groq_transcription_api(
            audio_path=audio_path,
            api_key=resolved_key,
            model=model,
            language=language,
            prompt=prompt,
        )
        if status == "READY" and raw_json:
            segments = parse_groq_verbose_json(
                raw_json=raw_json,
                candidate_start_time=candidate_start_time,
                speaker="Streamer",
            )
            return segments, "GROQ_READY", f"Transcribed {len(segments)} segments via Groq {model}"

        quota_msg = msg
    else:
        status = "KEY_MISSING"
        quota_msg = "GROQ_API_KEY is not configured."

    # --- FALLBACK STAGE ---
    # 1. Fallback to Local Whisper (whisper.cpp) if configured
    if fallback_provider in ("local", "auto"):
        from .audio import check_whisper_backend, run_transcription
        wh_status, wh_diag, wh_cli, wh_model = check_whisper_backend(st)
        if wh_status == "READY" and wh_cli and wh_model:
            cache_key = f"fb_{audio_path.stem}"
            local_segs, l_status, l_diag = run_transcription(
                wav_path=audio_path,
                storage=st,
                cache_key=cache_key,
                language=language,
            )
            if l_status == "READY" and local_segs:
                for s in local_segs:
                    s.start += candidate_start_time
                    s.end += candidate_start_time
                diag_msg = f"{quota_msg} Successfully fell back to local Whisper ({len(local_segs)} segments)."
                return local_segs, "FALLBACK_LOCAL_WHISPER", diag_msg

    # 2. Fallback to SRT import if provided
    if fallback_srt_path and Path(fallback_srt_path).is_file():
        from .audio import parse_external_transcript
        try:
            srt_segs = parse_external_transcript(Path(fallback_srt_path))
            clip_segs = [
                s for s in srt_segs
                if max(candidate_start_time, s.start) < min(candidate_start_time + 60.0, s.end)
            ]
            if not clip_segs and srt_segs:
                # Clip-relative SRT (starts at 0.0s)
                clip_segs = []
                for s in srt_segs:
                    s_copy = dataclasses.replace(
                        s,
                        start=round(s.start + candidate_start_time, 3),
                        end=round(s.end + candidate_start_time, 3),
                    )
                    clip_segs.append(s_copy)
            if clip_segs:
                diag_msg = f"{quota_msg} Successfully fell back to imported SRT ({len(clip_segs)} segments)."
                return clip_segs, "FALLBACK_SRT_IMPORT", diag_msg
        except Exception:
            pass

    # 3. FreeLLMAPI route evaluation
    if fallback_provider == "freellmapi":
        # Check FreeLLMAPI: disabled because its free audio endpoint proxies back to Groq (shared quota)
        return [], "FREELLMAPI_UNVERIFIED", f"{quota_msg} FreeLLMAPI fallback route unverified/disabled (shares Groq quota). Held awaiting captions."

    # 4. No fallback available: retain awaiting_captions
    return [], "QUOTA_AWAITING_CAPTIONS", f"{quota_msg} No enabled fallback available. Held awaiting captions."
