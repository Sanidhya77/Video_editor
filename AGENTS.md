# Agent Instructions — GTA VI Clipping MVP

This file serves as persistent context and guidelines for AI agents (including Antigravity, Codex, etc.) collaborating on this workspace.

## Project Purpose
A Windows-first local tool for creating vertical Shorts and Reels (1080×1920) from long gaming recordings, with Grand Theft Auto VI as the primary benchmark and extensible game configurations.
Now includes **Reference Reel to Captioned Stream Clips**: deriving reusable style presets from example Reels/Shorts or style notes, and producing synchronized on-screen subtitles for streamer dialogue.

## Workspace & Storage Constraints
- **Shared Workspace**: `c:\Users\sanid\OneDrive - Rīgas Tehniskā Universitāte\Darbvirsma\GTA_clipping`
- **CRITICAL - Intermediates Stay Outside OneDrive**: Do NOT write large source videos, intermediate cache files, Whisper models, or render scratch files inside OneDrive.
- **Configurable Data Directory**: All intermediate data resides outside OneDrive (e.g. `%LOCALAPPDATA%\gta_clipping` or `tempfile.gettempdir()\gta_clipping_data`). Configurable via CLI flag `--data-dir` or environment variable `GTA_CLIPPING_DATA_DIR`.
- **Default Deliverables Location**: Finished final exports are placed by default under `GTA_clipping\exports\<original-source-video-name>\` with clean names `<original-source-video-name>_clip_01.mp4` and `.srt`. Intermediates stay in local data dir. To export deliverables outside OneDrive as well, pass `--export-outside-onedrive`.

## Environment Overview (Detected 17 Nov 2026)
- **OS**: Windows (x64)
- **Python**: 3.13.9 (standard library preferred for orchestration)
- **Node**: v24.13.0
- **FFmpeg**: N-122158-gb9078c0939-20251215
  - Video Encoders: `libx264`, `libx264rgb`
  - Audio Encoders: `aac`
  - Subtitle Filters: `ass`, `subtitles` (libass enabled)
  - Audio/Video Filters: `whisper`, `silencedetect`, `crop`, `scale`
- **whisper-cli / yt-dlp**: Optional external tools not bundled on PATH; CLI handles their absence gracefully with diagnostics, setup guidance, and SRT/JSON fallback imports.

## Core Architecture
- `gta_clipper/`: Python CLI and processing package.
  - `cli.py`: Entry points (`doctor`, `style-preset`, `discover`, `analyze`, `preview`, `render`, `test-synth`).
  - `config.py`: Local data directory resolver (outside OneDrive) and game preset loader.
  - `doctor.py`: Diagnostics for FFmpeg, codecs, filters, Whisper, and storage.
  - `metadata.py`: Rights, creator attribution, and job metadata management.
  - `style.py`: Reference Reel style extraction, notes parsing, two-reference composition, trait categorization.
  - `audio.py`: Multi-track inspection, 16 kHz PCM extraction, volume/silence dynamics, Whisper runner, SRT fallback parser.
  - `visual.py`: Scene change detection, thumbnail extraction, motion cues.
  - `candidates.py`: Dual-signal candidate generation, style preset adaptation, speech guardrails, and deduplication.
  - `groq_transcriber.py`: Groq Whisper API client (`whisper-large-v3-turbo`) with `verbose_json` word timings, rate-limit `Retry-After` parsing, and fallback orchestration.
  - `subtitles.py`: ASS and SRT generation with safe-zone styling, timed recomputation on clip trimming.
  - `renderer.py`: FFmpeg 1080×1920 vertical renderer (center crop, manual, fit-bg, follow-crop, pip), square-pixel enforcement (SAR 1:1, DAR 9:16), render fingerprint cache invalidation, and caption guardrails.
  - `preview.py`: Self-contained HTML review contact sheet, caption preview, and editable JSON generator.
- `config/`:
  - `games.json`: Game presets and safe-zone presets.
  - `styles/`: Reusable style presets (`viral_streamer_yellow.json`, `kinetic_bold_white.json`).
- `research_template.csv`: Standard research template for short-form gaming clip analysis.
- `tests/`: Automated end-to-end verification suite (31 test cases).

## Review & State Tracking
All progress, commands executed, test results, and open items are tracked in `CURRENT_RUN.md`.
