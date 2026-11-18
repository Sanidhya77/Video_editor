"""Environment and dependency diagnostics for GTA VI Clipper.
Verifies FFmpeg, encoders, libass filters, Whisper capabilities, and OneDrive-free storage.
"""

from __future__ import annotations
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, List

from .config import StorageConfig


def _run_cmd(cmd: List[str]) -> tuple[int, str, str]:
    """Runs a subprocess command and returns (returncode, stdout, stderr)."""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        return res.returncode, res.stdout, res.stderr
    except FileNotFoundError:
        return -1, "", "Command not found"
    except Exception as e:
        return -1, "", str(e)


def run_doctor(storage: StorageConfig) -> Dict[str, Any]:
    """Executes all diagnostics and returns structured status."""
    report: Dict[str, Any] = {
        "python": {},
        "ffmpeg": {},
        "ffprobe": {},
        "encoders": {},
        "filters": {},
        "whisper": {},
        "node": {},
        "storage": {},
        "ready_for_visual": False,
        "ready_for_speech": False,
    }

    # 1. Python check
    report["python"] = {
        "version": sys.version.split()[0],
        "path": sys.executable,
        "compatible": sys.version_info >= (3, 10),
    }

    # 2. FFmpeg check
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        code, out, err = _run_cmd(["ffmpeg", "-version"])
        first_line = (out or err).splitlines()[0] if (out or err) else "Unknown"
        report["ffmpeg"] = {
            "found": True,
            "path": ffmpeg_path,
            "version": first_line,
        }
    else:
        report["ffmpeg"] = {"found": False, "path": None, "version": None}

    # 3. FFprobe check
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path:
        code, out, err = _run_cmd(["ffprobe", "-version"])
        first_line = (out or err).splitlines()[0] if (out or err) else "Unknown"
        report["ffprobe"] = {
            "found": True,
            "path": ffprobe_path,
            "version": first_line,
        }
    else:
        report["ffprobe"] = {"found": False, "path": None, "version": None}

    # 4. Encoders check (libx264, aac)
    if report["ffmpeg"]["found"]:
        code, out, _ = _run_cmd(["ffmpeg", "-encoders"])
        encoders_text = out.lower()
        report["encoders"] = {
            "libx264": "libx264" in encoders_text,
            "aac": "aac" in encoders_text,
        }
    else:
        report["encoders"] = {"libx264": False, "aac": False}

    # 5. Filters check (ass, subtitles, whisper, silencedetect)
    if report["ffmpeg"]["found"]:
        code, out, _ = _run_cmd(["ffmpeg", "-filters"])
        filters_text = out.lower()
        report["filters"] = {
            "ass": " ass " in filters_text or ".. ass" in filters_text,
            "subtitles": "subtitles" in filters_text,
            "silencedetect": "silencedetect" in filters_text,
            "whisper_filter": " whisper " in filters_text,
            "crop": " crop " in filters_text,
            "scale": " scale " in filters_text,
        }
    else:
        report["filters"] = {
            "ass": False,
            "subtitles": False,
            "silencedetect": False,
            "whisper_filter": False,
            "crop": False,
            "scale": False,
        }

    # 6. Whisper CLI & GGML model check
    whisper_cli_path = shutil.which("whisper-cli") or shutil.which("whisper")
    model_files = list(storage.models_dir.glob("*.bin")) if storage.models_dir.exists() else []

    report["whisper"] = {
        "cli_found": bool(whisper_cli_path),
        "cli_path": whisper_cli_path,
        "models_found": [m.name for m in model_files],
        "ffmpeg_whisper_supported": report["filters"].get("whisper_filter", False),
    }

    # 7. Groq Cloud Whisper check
    from .groq_transcriber import get_groq_api_key, DEFAULT_GROQ_MODEL
    groq_key = get_groq_api_key(storage)
    report["groq"] = {
        "key_configured": bool(groq_key),
        "model": DEFAULT_GROQ_MODEL,
        "endpoint": "https://api.groq.com/openai/v1/audio/transcriptions",
    }

    # 8. Node check
    node_path = shutil.which("node")
    if node_path:
        code, out, _ = _run_cmd(["node", "--version"])
        report["node"] = {"found": True, "path": node_path, "version": out.strip()}
    else:
        report["node"] = {"found": False, "path": None, "version": None}

    # 8. Storage check
    outside_onedrive = storage.is_outside_onedrive()
    storage_writable = False
    try:
        test_file = storage.root / ".doctor_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink()
        storage_writable = True
    except Exception:
        pass

    report["storage"] = {
        "data_dir": str(storage.root),
        "is_outside_onedrive": outside_onedrive,
        "is_writable": storage_writable,
        "models_dir": str(storage.models_dir),
        "exports_dir": str(storage.exports_dir),
    }

    # Pipeline readiness
    report["ready_for_visual"] = (
        report["python"]["compatible"]
        and report["ffmpeg"]["found"]
        and report["ffprobe"]["found"]
        and report["encoders"]["libx264"]
        and report["encoders"]["aac"]
        and report["storage"]["is_writable"]
    )

    report["ready_for_speech"] = report["ready_for_visual"] and (
        report["whisper"]["cli_found"]
        or report["groq"]["key_configured"]
        or (report["whisper"]["ffmpeg_whisper_supported"] and len(report["whisper"]["models_found"]) > 0)
    )

    return report


def print_doctor_summary(report: Dict[str, Any]) -> None:
    """Pretty prints the diagnostic report to console."""
    print("=" * 64)
    print(" GTA VI Clipper — Environment & Dependency Diagnostic ")
    print("=" * 64)

    # Python
    py = report["python"]
    print(f"[x] Python: {py['version']} ({py['path']})")

    # Storage
    st = report["storage"]
    od_mark = "[x]" if st["is_outside_onedrive"] else "[!]"
    print(f"{od_mark} Data Directory: {st['data_dir']}")
    print(f"    Outside OneDrive: {'YES' if st['is_outside_onedrive'] else 'NO (Caution: sync issues possible)'}")
    print(f"    Writable: {'YES' if st['is_writable'] else 'NO'}")

    # FFmpeg / FFprobe
    ff = report["ffmpeg"]
    if ff["found"]:
        print(f"[x] FFmpeg: {ff['version']} ({ff['path']})")
    else:
        print("[!] FFmpeg: NOT FOUND on PATH")

    fp = report["ffprobe"]
    if fp["found"]:
        print(f"[x] FFprobe: {fp['version']} ({fp['path']})")
    else:
        print("[!] FFprobe: NOT FOUND on PATH")

    # Encoders
    enc = report["encoders"]
    print(f"    - H.264 Encoder (libx264): {'OK' if enc['libx264'] else 'MISSING'}")
    print(f"    - AAC Encoder (aac): {'OK' if enc['aac'] else 'MISSING'}")

    # Filters
    filt = report["filters"]
    print(f"    - Subtitle Filter (ass / libass): {'OK' if filt['ass'] else 'MISSING'}")
    print(f"    - Subtitle Filter (subtitles): {'OK' if filt['subtitles'] else 'MISSING'}")
    print(f"    - Audio Silence Filter: {'OK' if filt['silencedetect'] else 'MISSING'}")
    print(f"    - FFmpeg Whisper Filter: {'AVAILABLE' if filt['whisper_filter'] else 'NOT COMPILED'}")

    # Whisper
    wh = report["whisper"]
    if wh["cli_found"]:
        print(f"[x] Whisper CLI: Found ({wh['cli_path']})")
    else:
        print("[ ] Whisper CLI: Not found on PATH (visual pipeline works; speech optional)")

    if wh["models_found"]:
        print(f"    GGML Models: {', '.join(wh['models_found'])}")
    else:
        print(f"    GGML Models: None in {st['models_dir']}")

    # Groq Cloud Whisper
    gr = report.get("groq", {})
    if gr.get("key_configured"):
        print(f"[x] Groq Whisper API: Configured (Model: {gr.get('model')})")
    else:
        print(f"[ ] Groq Whisper API: Key not set (Optional: $env:GROQ_API_KEY='gsk_...')")

    # Node
    node = report["node"]
    if node["found"]:
        print(f"[x] Node.js: {node['version']} ({node['path']})")

    # Readiness
    print("-" * 64)
    if report["ready_for_visual"]:
        print("[*] Visual Pipeline Status: READY (Scene detection, 1080x1920 crop, export)")
    else:
        print("[!] Visual Pipeline Status: BLOCKED (Check missing FFmpeg / codecs above)")

    if report["ready_for_speech"]:
        provider_name = "Groq Whisper API" if gr.get("key_configured") else "Local Whisper CLI"
        print(f"[*] Speech Pipeline Status: READY ({provider_name} enabled)")
    else:
        print("[i] Speech Pipeline Status: OPTIONAL (Whisper CLI, GGML model, or Groq API key not detected)")
        print("    To enable speech-to-text:")
        print("    Option A (Cloud, fast): Set Groq API key:")
        print("       $env:GROQ_API_KEY = 'gsk_your_key_here'")
        print("    Option B (Local): Download whisper-cli (pinned v1.7.4) from:")
        print("       https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.4")
        print("       and place a GGML model (.bin) in:")
        print(f"       {st['models_dir']}")
        print("    Visual candidates, SRT import, and manual transcript entry remain fully functional.")
    print("=" * 64)
