# GTA VI Clipping MVP — Reference Reel to Captioned Stream Clips

A Windows-first, local-first utility for transforming long gaming recordings into vertical **1080×1920 Shorts and Reels** styled after benchmark reference Reels, with synchronized dialogue subtitles and safe-zone formatting. Grand Theft Auto VI is the initial reference benchmark, with game categories and style presets stored in modular configuration files for seamless reuse across games and streamers.

The tool enables an operator to:
1. Supply an example Reel/Short URL, local reference video, or style notes to derive a reusable style preset.
2. Point at a raw creator stream recording (including multi-track OBS files with separate game and mic audio).
3. Transcribe and synchronize what the streamer actually says as readable, on-screen subtitles.
4. Review up to three vertical draft clips via a local HTML contact sheet or editable JSON.
5. Render clean 1080×1920 MP4 clips with burned ASS hardsubs and sidecar SRT caption files.

---

## Key Features

1. **Reference Style Engine (`style-preset`)**
   - Extracts editing traits (typography, cut pace, typical length, layout, and hook placement) from reference videos, URLs, or notes.
   - Categorizes traits into **observed** (direct evidence), **inferred** (sensible defaults), and **unknown**.
   - **Two-Reference Composition**: Blend subtitle styling from Reference A (e.g. bold yellow typography) with pacing/layout from Reference B (e.g. blurred background, 25s cuts).
2. **Synchronized Dialogue Subtitles & Safe Margins**
   - Transcribes streamer speech and burns high-contrast ASS subtitles (Arial Black, bold yellow/white, black outline, shadow).
   - Generates sidecar `.srt` files for external editing or closed captions.
   - Respects TikTok and Instagram Reels UI safe zones (Margin V: 380px) and enforces a maximum of two lines per fragment.
   - Automatically recomputes caption timings if in/out points are trimmed during review.
3. **Groq Cloud Whisper & Local Whisper Options**
   - Opt-in cloud transcription via `--transcription-provider groq` using `whisper-large-v3-turbo`.
   - Privacy-first: keeps source video 100% local; uploads only candidate audio slices (30–60s) from the streamer's mic track.
   - Captures segment and word timestamps (aligned with SupoClip's word-timing workflow) for future word-by-word animation.
   - Local Whisper (`whisper.cpp`) and external SRT import remain fully supported.
4. **Multi-Track Audio & Mic Selection**
   - Ingests recordings with multiple audio tracks (e.g. Track 0 = Game Audio, Track 1 = Streamer Mic).
   - Use `--mic-track <idx>` to isolate the streamer's voice for clean transcription and energy analysis.
5. **Speech & Caption Guardrails**
   - Checks local Whisper availability (`whisper-cli` and GGML models) and Groq API key configuration.
   - Supports external transcript fallback (`--transcript <file.srt|json>`).
   - Dialogue candidates are held in an `[AWAITING CAPTIONS]` state if transcription is missing or API errors/quota limits occur.
   - **Strict Guardrail**: The renderer will never export a dialogue clip as finished with empty subtitles or invented dialogue. Genuine speech-free clips can be reviewed and rendered separately.
6. **Clean Deliverables & Storage Isolation (OneDrive-Safe)**
   - Finished deliverables are placed by default under `GTA_clipping\exports\<original-source-video-name>\` named `<original-source-video-name>_clip_01.mp4` and `.srt`.
   - Large source footage, 16 kHz audio slices, whisper models, and intermediate renders are stored **strictly outside OneDrive** by default.
   - Configurable via `--data-dir <path>` or `GTA_CLIPPING_DATA_DIR` (defaults to `%LOCALAPPDATA%\gta_clipping` or fallback `tempfile.gettempdir()\gta_clipping_data`).
   - Use `--export-outside-onedrive` to route finished deliverables outside OneDrive as well.
7. **Zero External SaaS Dependencies**
   - Runs 100% locally with Python's standard library, FFmpeg/ffprobe, and optional local whisper.cpp or Groq API.

---

## Environment & Prerequisites

Tested and verified on Windows (x64) on 17 November 2026:

| Tool | Detected Version | Path | Status |
| :--- | :--- | :--- | :--- |
| **Python** | 3.13.9 | `python.exe` | Verified (Standard library orchestration) |
| **FFmpeg** | N-122158-gb9078c0939-20251215 | `ffmpeg.exe` | Verified (`libx264`, `aac`, `ass`, `subtitles`, `whisper` filter) |
| **FFprobe** | N-122158-gb9078c0939-20251215 | `ffprobe.exe` | Verified |
| **Node.js** | v24.13.0 | `node.exe` | Detected |
| **whisper-cli** | Optional | Not on PATH | Optional (Visual pipeline active; fallback SRT supported) |
| **yt-dlp** | Optional | Not on PATH | Optional adapter for permitted source downloads |

### Configuring Speech-to-Text Providers

#### Option A: Groq Cloud Whisper (Recommended for Speed & Accuracy)
Groq provides ultra-fast transcription using `whisper-large-v3-turbo` with word-level timestamps.
To configure safely in PowerShell (without writing to code, git, or OneDrive):
```powershell
# For the current session:
$env:GROQ_API_KEY = "gsk_your_key_here"

# Or persistently as a Windows user environment variable:
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'gsk_your_key_here', 'User')
```
*Note: Your video never leaves your PC. Only the short (30–60s) candidate audio slice is uploaded.*

#### Option B: Local Whisper.cpp (Fully Offline)
1. Download official pre-built Windows release:
   - Repository: [ggml-org/whisper.cpp Releases](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.7.4)
   - Asset: `whisper-bin-x64.zip` (Pinned release: **v1.7.4**)
2. Place `whisper-cli.exe` in system `PATH` or `<data_dir>/models/`.
3. Download GGML model (e.g. `ggml-tiny.bin` or `ggml-base.bin`) from [HuggingFace ggerganov/whisper.cpp](https://huggingface.co/ggerganov/whisper.cpp/tree/main) into:
   `<data_dir>/models/`

---

## One-Command Workflow & CLI Reference

All commands run through `python -m gta_clipper.cli`:

```bash
# 1. Environment diagnostic
python -m gta_clipper.cli doctor

# 2. Derive style preset from notes or reference Reel
python -m gta_clipper.cli style-preset \
  --notes "Fast-paced GTA stunts, bold yellow Arial Black captions, top hook banner, 22s" \
  --save viral_stunt

# 3. Analyze raw stream with style preset, mic track, and dialogue transcription
python -m gta_clipper.cli analyze \
  --input "D:\Recordings\GTA6_Stream_Session.mp4" \
  --style-preset viral_stunt \
  --mic-track 1 \
  --creator "ViceCityStreamer"

# 4. View the review contact sheet URL
python -m gta_clipper.cli preview

# 5. Render approved vertical clips (1080x1920 MP4 + burned subtitles + SRT)
python -m gta_clipper.cli render
```

### Detailed Command Options

#### `style-preset`
Derive, inspect, or merge style presets from user descriptions, local reference files, or public URLs:
```bash
# From notes:
python -m gta_clipper.cli style-preset \
  --notes "White bold captions, fit background blur, 25s duration" \
  --save kinetic_white

# From local reference video:
python -m gta_clipper.cli style-preset \
  --ref-file "C:\refs\sample_viral_reel.mp4" \
  --save probed_style

# Merge two references (captions from Ref A, layout/pacing from Ref B):
python -m gta_clipper.cli style-preset \
  --merge-captions-from viral_streamer_yellow \
  --merge-layout-from kinetic_bold_white \
  --save hybrid_style
```

#### `discover`
Find benchmark public Shorts/Reels by keyword:
```bash
python -m gta_clipper.cli discover --query "GTA V funny streamer reaction Shorts"
```

#### `analyze`
Ingests the stream recording, applies the style preset, inspects audio tracks, extracts dialogue, and generates up to 3 vertical draft clips:
```bash
# With Groq Cloud Whisper (accurate dialogue without importing SRT):
python -m gta_clipper.cli analyze \
  --input "C:\path\to\recording.mp4" \
  --transcription-provider groq \
  --mic-track 1 \
  --style-preset viral_streamer_yellow \
  --creator "StreamerName"

# With local Whisper.cpp:
python -m gta_clipper.cli analyze \
  --input "C:\path\to\recording.mp4" \
  --transcription-provider local \
  --mic-track 1

# With existing SRT transcript:
python -m gta_clipper.cli analyze \
  --input "C:\path\to\recording.mp4" \
  --transcript "C:\path\to\stream_transcript.srt" \
  --mic-track 1
```

#### `transcribe-clip`
Transcribe a specific candidate clip on an existing job (useful when an API key was added after analysis):
```bash
python -m gta_clipper.cli transcribe-clip \
  --job-dir "<job_dir>" \
  --clip-id clip_01 \
  --provider groq \
  --mic-track 1
```

#### `render`
Renders approved clips to 1080×1920 vertical H.264/AAC MP4 with burned ASS hardsubs and sidecar SRT. Automatically reuses existing renders in ~0.00s if unchanged:
```bash
# Render all approved clips into GTA_clipping/exports/<original-source-name>/
python -m gta_clipper.cli render --job-dir "<job_dir>"

# Override layout or manual crop offset
python -m gta_clipper.cli render --job-dir "<job_dir>" --layout manual_crop --crop-offset 0.25

# Export deliverables outside OneDrive as well
python -m gta_clipper.cli render --job-dir "<job_dir>" --export-outside-onedrive
```

---

## Review Experience

The review contact sheet (`contact_sheet.html`) provides a local, offline dashboard displaying:
- **Synchronized Subtitles Preview**: Shows the exact words spoken by the streamer.
- **Candidate Badges**: Highlights clip status (`[AWAITING CAPTIONS]`, `[CHECK SPEECH ACCURACY]`, `[SPEECH-FREE CLIP]`).
- **Three Frame Thumbnails**: Start / Hook Frame, Payoff / Action Climax, and End / Resolution.
- **Style Preset Badge**: Shows active style styling.
- **Editable Parameters**: In `review_sheet.json`, the editor can adjust start/end timestamps (which automatically re-synchronizes subtitle timings), change layout mode, or set `"rejected": true`.

---

## Reusable Built-in Style Presets

Located in [`config/styles/`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/config/styles/):
1. **`viral_streamer_yellow.json`**:
   - Bold yellow typography (`&H0000FFFF`), Arial Black, 70pt.
   - Black 4.5px outline, 380px vertical margin (safe zone).
   - Rapid cuts, 22s duration, center crop.
   - Top headline hook banner.
2. **`kinetic_bold_white.json`**:
   - Clean white typography (`&H00FFFFFF`), 66pt.
   - Fit-with-background layout (blurred ambient background with centered fitted gameplay).
   - Moderate pacing (25s duration).

---

## Verification Test Suite

Run the automated test suite (31 end-to-end tests):
```bash
python tests/run_tests.py
```
**Tests include**:
1. Doctor environment diagnostics
2. Storage isolation outside OneDrive
3. Attribution, rights, and metadata logging
4. Audio extraction and RMS peak detection
5. Visual stream inspection
6. Dual-signal candidate proposal & deduplication
7. ASS & SRT subtitle generation with safe margins
8. 1080x1920 vertical MP4 rendering across all layouts
9. ffprobe stream verification
10. Paths with spaces and Unicode characters
11. Re-render caching and idempotence
12. Error handling for invalid inputs and time ranges
13. Style preset derivation from notes and local media probe
14. Two-reference style composition (captions from ref A, layout from ref B)
15. Multi-track audio and streamer mic track selection
16. External transcript fallback with synchronized burned dialogue
17. Caption guardrail: blocks uncaptioned dialogue export
18. Recomputing subtitle timing when clip boundaries are trimmed
19. Inaccessible reference URL fallback to style notes
20. Candidate audio slice extraction (video kept 100% local)
21. Groq verbose_json parsing and stream timing offsets (SupoClip reference)
22. Groq quota / rate limit handling and guardrails
23. Full workflow spot-check captions (first, middle, last)
24. Groq HTTP 429 quota exhaustion fallback to local Whisper
25. Groq HTTP 429 quota exhaustion fallback to manual SRT import
26. FreeLLMAPI unverified route evaluation guardrail
27. Clean deliverable naming, Windows path sanitization, and export reuse
28. Square pixels verification (SAR 1:1, DAR 9:16 via ffprobe)
29. Stale render reuse invalidation on layout, crop, hook, or subtitle changes
30. Storytelling setup, action, and payoff timestamps + shot-by-shot framing
31. Facecam guardrail falling back from PiP to fit-background when unconfirmed
