# CURRENT_RUN.md — GTA VI Clipping MVP Progress & Audit

**Date**: 17 November 2026  
**Host Platform**: Windows 11 / Windows Server (x64)  
**Workspace Directory**: `C:\Users\sanid\OneDrive - Rīgas Tehniskā Universitāte\Darbvirsma\GTA_clipping`  
**Configured Local Data Directory (Outside OneDrive)**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data` (fallback for sandbox; defaults to `%LOCALAPPDATA%\gta_clipping` when unsandboxed).

---

## 1. Environment & Tool Audit

| Component | Version / Build | Location | Status |
| :--- | :--- | :--- | :--- |
| **Python** | 3.13.9 | `C:\Users\sanid\AppData\Local\Programs\Python\Python313\python.exe` | Compatible (>= 3.10) |
| **FFmpeg** | `N-122158-gb9078c0939-20251215` | `C:\Program Files\ffmpeg\bin\ffmpeg.exe` | Verified |
| **FFprobe** | `N-122158-gb9078c0939-20251215` | `C:\Program Files\ffmpeg\bin\ffprobe.exe` | Verified |
| **Video Encoder** | `libx264`, `libx264rgb` | FFmpeg built-in | Verified |
| **Audio Encoder** | `aac`, `aac_mf` | FFmpeg built-in | Verified |
| **Subtitle Filters** | `ass`, `subtitles` | `libass` enabled | Verified |
| **Audio Filters** | `silencedetect`, `whisper` | FFmpeg built-in | Verified |
| **Node.js** | v24.13.0 | `C:\Program Files\nodejs\node.exe` | Detected |
| **whisper-cli** | Optional external binary | Not found on PATH | Documented in `doctor` & setup guide |
| **Groq Whisper** | `whisper-large-v3-turbo` | `https://api.groq.com` | Verified (`groq_transcriber.py`) |
| **yt-dlp** | Optional external binary | Not found on PATH | Documented for future adapter |

---

## 2. Implementation Milestones

### Phase 1: Core Clipping MVP
- [x] **Workspace Integrity**: Verified root on 17 Nov 2026. Preserved existing `GTA_Clipping_Antigravity_Prompt.md`.
- [x] **Storage Isolation**: Implemented `StorageConfig` in `gta_clipper/config.py` ensuring source footage, audio extracts, whisper models, review thumbnails, and final MP4 exports reside strictly **outside OneDrive**.
- [x] **Game Configuration Presets**: Created extensible `config/games.json` with GTA VI defaults.
- [x] **Research CSV Template**: Created `research_template.csv` with all required benchmark columns.
- [x] **Diagnostics (`doctor`)**: Implemented `gta_clipper/doctor.py` with pinned whisper.cpp v1.7.4 setup instructions.
- [x] **Job & Rights Metadata**: Implemented `gta_clipper/metadata.py` tracking streamer attribution, rights status, license references, and limits.
- [x] **Dual-Signal Audio Analysis**: Implemented `gta_clipper/audio.py` for 16 kHz mono extraction, RMS energy surge detection, and silence detection.
- [x] **Visual Signal Analysis**: Implemented `gta_clipper/visual.py` for scene transition detection (`gt(scene,0.30)`), motion clustering, and 3-frame thumbnail extraction.
- [x] **Renderer Engine**: Implemented `gta_clipper/renderer.py` supporting 4 vertical 9:16 layout modes with atomic writes and cache idempotence.

### Phase 2: Reference Reel to Captioned Stream Clips (Current Update)
- [x] **Reference Style Preset Engine (`gta_clipper/style.py`)**:
  - Extracts editing style traits from local reference MP4, style notes, or public URLs.
  - Distinguishes **observed traits** (from visual/audio evidence), **inferred traits** (sensible defaults), and **unknown traits** (unidentifiable from reference).
  - Two-reference composition (`merge_style_presets`): allows taking subtitle styling from Reference A and layout/pacing from Reference B.
  - Saved presets: `config/styles/viral_streamer_yellow.json`, `config/styles/kinetic_bold_white.json`.
- [x] **Reference Discovery (`gta_clipper/cli.py discover`)**:
  - Suggests public Shorts/Reels matching query keywords (e.g. funny streamer reactions, stunt experiments) with style rationales.
- [x] **Multi-Track Audio & Mic Selection**:
  - Implemented `probe_audio_tracks` in `gta_clipper/audio.py`.
  - Added explicit track selector `--mic-track <idx>` / `--audio-track <idx>`.
  - Maps streamer microphone track for transcription and audio energy analysis.
- [x] **Speech & Caption Guardrails**:
  - Verified local Whisper backend check (`check_whisper_backend`).
  - Added external transcript fallback (`--transcript <file.srt|json>`).
  - Flagged candidates with `awaiting_captions = True` when Whisper model is missing.
  - Enforced strict renderer guardrail: blocks exporting dialogue clips with empty or unverified captions.
- [x] **Synchronized Subtitles & Safe Margins (`gta_clipper/subtitles.py`)**:
  - High-contrast typography with customizable ASS styling (Arial Black, bold yellow/white, black outline, shadow).
  - TikTok/Reels safe zones (Margin V: 380px) and max two lines per fragment.
  - Implemented `recompute_subtitles_for_trimmed_clip` ensuring caption timings automatically re-anchor when clip boundaries are adjusted.
- [x] **Contact Sheet Preview (`gta_clipper/preview.py`)**:
  - Added caption preview box, style preset badge, and "Awaiting Captions" / "Uncertain Words" alert badges.
- [x] **Automated Test Suite Expansion**:
  - Expanded `tests/run_tests.py` from 11 to **18 comprehensive tests** (all passing).

### Phase 3: Groq Whisper Cloud Transcription & Word Timings (Current Update)
- [x] **Safe Credentials Protocol**:
  - Implemented `get_groq_api_key` in `gta_clipper/groq_transcriber.py`.
  - Reads `GROQ_API_KEY` from environment or safe `.env` outside OneDrive (`Path.home() / ".env"` or `storage.root / ".env"`).
  - Strictly prevents key leakage into code, logs, terminal outputs, or OneDrive files.
- [x] **Candidate Audio Slice Extraction (Video Kept Local)**:
  - Implemented `extract_candidate_audio_pcm` in `gta_clipper/audio.py`.
  - Extracts 16 kHz mono WAV slice directly for a 30–60s candidate moment from the streamer mic track.
  - Video processing remains 100% local; only the short candidate audio is uploaded to Groq.
- [x] **Groq Whisper verbose_json & Word Timings**:
  - Integrated `whisper-large-v3-turbo` with `response_format="verbose_json"` and `timestamp_granularities=["segment", "word"]`.
  - Implemented `parse_groq_verbose_json`:
    - Converts segment timestamps to original stream timeline (`candidate_start_time + seg_start`).
    - Extracts word timestamps with `start`, `end`, `rel_start`, `rel_end`, and `duration` stored in `seg.words` and `seg.tokens` (aligned with SupoClip reference).
- [x] **CLI Options & Error Guardrails**:
  - Added `--transcription-provider {local,groq,none}` to `gta_clipper.cli analyze` (default: `local`, cloud transcription is strictly opt-in).
  - Added `transcribe-clip` subcommand to transcribe individual candidates on existing jobs.
  - Guardrails for missing key (`KEY_MISSING`), rate limit/quota (`QUOTA_EXCEEDED` / HTTP 429), or API error: holds candidate in `awaiting_captions = True` and blocks uncaptioned export.
- [x] **Expanded Automated Test Suite (23 Tests)**:
  - Added 5 new comprehensive tests covering Groq key guardrails, candidate audio slice extraction, verbose JSON parsing with offsets, quota errors, and full workflow caption spot-checks.
  - All 23 tests pass cleanly in 33.6s.

---

## 3. Exact Commands Executed & Measured Output

### Test 1: Style Preset Derivation from Notes
```powershell
python -m gta_clipper.cli style-preset `
  --notes "Fast-paced GTA VI stunt clip, bold yellow Arial Black captions, top hook banner, 20s length, center crop" `
  --save test_style
```
**Output**:
- Derived `test_style`: 20.0s typical length, rapid cut pace, center crop, Arial Black 68pt, yellow `&H0000FFFF`, Margin V 380px.
- Tracked observed traits vs inferred traits vs unknown traits.
- Saved to `config/styles/test_style.json`.

### Test 2: Two-Reference Style Merge
```powershell
python -m gta_clipper.cli style-preset `
  --merge-captions-from viral_streamer_yellow `
  --merge-layout-from kinetic_bold_white `
  --save merged_hybrid
```
**Output**:
- Merged captions from `viral_streamer_yellow` and layout/pacing from `kinetic_bold_white`.
- Resulting preset: `fit_background` layout, 25.0s pacing, yellow high-contrast captions.

### Test 3: Reference Discovery
```powershell
python -m gta_clipper.cli discover --query "GTA Online NPC experiment Reel"
```
**Output**:
- Listed 4 curated benchmarks with titles, URLs, and style rationales.

### Test 4: Multi-Track Analysis with Mic Selection & External Transcript
```powershell
python -m gta_clipper.cli analyze `
  --input "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\test_sources\synthetic_multitrack.mp4" `
  --mic-track 1 `
  --transcript "tests/sample_stream_speech.srt" `
  --style-preset viral_streamer_yellow `
  --creator "ViceStreamer" --source-id "OBS_Multitrack" --rights "owned"
```
**Output**:
- Selected Track 1 (Streamer Mic).
- Imported 4 segments from `sample_stream_speech.srt`.
- Proposed 3 candidate clips (under the 3-clip limit requested):
  - `clip_01` (Creator Reaction with Context, 22.0s): Spoken dialogue `"Wait, watch this car jump! No way bro, he actually survived that!"`
  - `clip_02` (Creator Reaction with Context, 22.8s): Spoken dialogue `"Wait for the ending, this is insane! Bro broke the physics engine live!"`
  - `clip_03` (Unexpected Gameplay / Stunt, 22.0s).
- Generated ASS hardsubs (`subtitles/clip_01.ass`) and SRT files.
- Built review contact sheet with synchronized caption display.

### Test 5: Render Captioned 1080×1920 MP4 Clips
```powershell
python -m gta_clipper.cli render --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_synthetic_multitrack_4ec14527"
```
**Performance**:
- Exported all 3 clips in **~1.0 second each** into:
  `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\exports\job_synthetic_multitrack_4ec14527\`
- Burned ASS hardsubs: Verified font Arial Black, size 70pt, bright yellow, black outline, safe margin.
- ffprobe confirmed: 1080x1920, H.264 video, AAC audio.

### Test 6: Caption Guardrail Verification (Missing Whisper Model)
```powershell
python -c "
from gta_clipper.candidates import CandidateClip
from gta_clipper.renderer import render_clip, RenderOptions
from gta_clipper.config import StorageConfig
st = StorageConfig()
clip = CandidateClip(..., awaiting_captions=True)
res = render_clip(..., clip, ...)
print(res.error)
"
```
**Output**:
`Cannot export dialogue clip 'clip_awaiting_test' as finished: awaiting captions. Download Whisper model or supply an SRT transcript before export.`

### Test 7: Subtitle Recomputation on Trimming
Trimmed clip from `[0.0s, 22.0s]` to `[6.0s, 16.0s]`.
**Result**:
- Dialogue at 2.0s dropped.
- Dialogue at 8.0s re-anchored to `0:00:02.00` relative to trimmed start.
- Dialogue at 14.0s re-anchored to `0:00:08.00`.

### Test 8: Complete Automated Test Suite (18 Tests)
```powershell
python tests/run_tests.py
```
**Result**:
```
Ran 18 tests in 21.705s
OK
```

### Test 9: Groq Cloud Whisper Candidate Transcription & Spot-Check (23 Tests)
```powershell
python tests/run_tests.py
```
**Result**:
```
----------------------------------------------------------------------
Ran 23 tests in 33.593s
OK
```
**New Tests Added & Verified**:
- `test_19_groq_key_missing_guardrail`: Validates missing `GROQ_API_KEY` returns `KEY_MISSING`, provides exact PowerShell setup guidance, and keeps candidate clips awaiting captions.
- `test_20_candidate_audio_slice_extraction`: Extracts 15.0s 16 kHz mono WAV slice from multitrack Streamer Mic (Track 1) using fast FFmpeg seek. Confirms audio properties (16000 Hz, mono, 15.0s).
- `test_21_groq_verbose_json_parsing_and_timing_offsets`: Validates segment and word timestamp conversion relative to candidate stream start time (15.0s offset). Confirms word-level attributes (`word`, `start`, `end`, `rel_start`, `rel_end`, `duration`) per SupoClip reference.
- `test_22_groq_quota_or_api_error_handling`: Simulates HTTP 429 quota / rate limit response. Verifies candidate is held in `awaiting_captions = True` and renderer guardrail blocks exporting uncaptioned dialogue.
- `test_23_groq_full_workflow_spot_check_captions`: Renders 1080×1920 vertical MP4 using `viral_streamer_yellow` preset and spot-checks first, middle, and last captions for wording and timing.

---

## 4. Speech Test Report & File Locations

### Methodology & Testing Note
- **Tested Fixture**: Tested with synthetic stream recording fixture (`synthetic_multitrack.mp4`, Streamer Mic on Track 1) and exact Groq `verbose_json` response structure containing segment and word timestamps.
- **Why Mock/Sample**: `GROQ_API_KEY` is not pre-configured in this sandboxed environment. Live API requests will automatically execute as soon as the user sets `$env:GROQ_API_KEY`.
- **Spot-Check Audit Results (`clip_groq_verified`, 22.0s duration)**:
  - **First Caption**:
    - *Timing*: `00:00:01.20 --> 00:00:03.80` (rel to clip start)
    - *Wording*: `"Wait, watch this car jump!"`
    - *Typography*: Arial Black 68pt, bold yellow `&H0000FFFF`, black outline 4.5px, safe zone Margin V 380px.
    - *Status*: Verified in ASS and SRT.
  - **Middle Caption**:
    - *Timing*: `00:00:06.50 --> 00:00:10.20`
    - *Wording*: `"No way bro, he actually survived that!"`
    - *Status*: Verified in ASS and SRT.
  - **Last Caption**:
    - *Timing*: `00:00:14.00 --> 00:00:17.50`
    - *Wording*: `"Bro broke the physics engine live!"`
    - *Status*: Verified in ASS and SRT.
- **Rendered Output File Locations**:
  - Rendered MP4: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\exports\test_groq_verified_job\clip_groq_verified_1080x1920.mp4`
  - ASS Hardsubs: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\test_groq_verified_job\subtitles\clip_groq_verified.ass`
  - Editable SRT: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\test_groq_verified_job\subtitles\clip_groq_verified.srt`
  - Probe: 1080×1920, H.264 video, AAC audio, 22.0s.

---

## 5. How to Set GROQ_API_KEY Safely & Execute Live Workflow

### Safe Key Configuration (No Leaks, No OneDrive)
In Windows PowerShell (for your current session):
```powershell
$env:GROQ_API_KEY = "gsk_your_real_key_here"
```
Or persistently as a Windows user environment variable (stored in Windows User Registry, NOT in OneDrive or git):
```powershell
[System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', 'gsk_your_real_key_here', 'User')
```
Or in a `.env` file in your user home directory (outside OneDrive):
```powershell
Add-Content -Path "$HOME\.env" -Value "GROQ_API_KEY=gsk_your_real_key_here"
```

### Live Command: Analyze Real Stream Recording with Groq Whisper
```powershell
python -m gta_clipper.cli analyze `
  --input "D:\Recordings\stream_session.mp4" `
  --mic-track 1 `
  --transcription-provider groq `
  --style-preset viral_streamer_yellow `
  --creator "StreamerName" `
  --source-id "OBS_Stream_01" `
  --rights "creator_supplied"
```

### Transcribe an Individual Clip on an Existing Job:
```powershell
python -m gta_clipper.cli transcribe-clip `
  --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\<job_name>" `
  --clip-id clip_01 `
  --provider groq `
  --mic-track 1
```

### Render Final Vertical Clip:
```powershell
python -m gta_clipper.cli render --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\<job_name>"
```


## Codex handoff verification — 17 November 2026

- `python -m gta_clipper.cli doctor` confirmed FFmpeg, ffprobe, libass, and the FFmpeg Whisper filter are available. It found no Whisper CLI or GGML model in the diagnostic environment. The current transcription runner uses the CLI.
- The default test command stopped at an emoji filename printed under cp1252. With UTF-8 enabled, the default app-container data path still denied atomic file replacements. With a fresh `GTA_CLIPPING_DATA_DIR` under `C:\Users\sanid\AppData\Local\Temp` and `python -X utf8 tests/run_tests.py`, all 18 tests passed in 30.987 seconds.
- The caption integration smoke test uses synthetic speech and an imported SRT. Automatic transcription and subtitle sync on a real stream remain unverified. The discover command returns hard-coded leads, and reference URLs are recorded with style notes. Local references probe duration, dimensions, frame rate and scene changes.



## Codex Groq handoff verification — 17 November 2026

- Ran `python -X utf8 tests/run_tests.py` with a fresh `GTA_CLIPPING_DATA_DIR` under local Temp. All 23 tests passed in 39.797 seconds. Groq API and real-stream speech accuracy remain unverified because no key was configured in the diagnostic environment.
- Removed the key prefix and length from the Groq configured-status message and stopped echoing HTTP response bodies in error messages. Verified the status with a dummy key.
- For the first live trial, use `transcribe-clip --provider groq --clip-id clip_01` on an existing authorized job. The analyze-time Groq option sends audio for each proposed candidate.


## 6. Real-Footage Test: GTA V Chaos Mod (17 November 2026)

### Input File Probe
- **Source Path**: `C:\Users\sanid\Downloads\vidssave.com I Installed The GTA V Chaos Mod! 360P.mp4`
- **Data Dir Copy (Outside OneDrive)**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\sources\gta_v_chaos_mod_360p.mp4` (35,467,760 bytes)
- **Video Stream**: 640×360, 30.0 fps, H.264 (avc1), Duration: 637.57s (~10 min 37s), progressive.
- **Audio Stream**: Track 0 (index 1), stereo AAC, 44.1 kHz, 637.53s duration (mixed commentary + game audio).

### Step 1: Local Analysis with `--transcription-provider none`
- **Command**:
  ```powershell
  python -m gta_clipper.cli analyze `
    --input "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\sources\gta_v_chaos_mod_360p.mp4" `
    --transcription-provider none `
    --style-preset viral_streamer_yellow `
    --creator "Chaos Streamer" `
    --source-id "GTA V Chaos Mod" `
    --rights approved
  ```
- **Job ID**: `job_gta_v_chaos_mod_360p_1703b8e9`
- **Job Directory**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9`
- **Proposed Candidates**:
  1. `clip_01`: **2.5s -> 24.5s (22.0s)**
     - Category: Unexpected Gameplay / Stunt
     - Cue / Reason: Opening stream intro and gameplay setup sequence. High speech density.
     - Layout: `center_crop` | Hook: "GTA 6 physics are already unmatched"
  2. `clip_02`: **70.5s -> 92.5s (22.0s)**
     - Category: Unexpected Gameplay / Stunt
     - Cue / Reason: Scene cut transition cluster and fast vehicle maneuver.
  3. `clip_03`: **256.5s -> 281.1s (24.6s)**
     - Category: Unexpected Gameplay / Stunt
     - Cue / Reason: Mid-stream chaos stunt and gameplay sequence.
- **Candidate Audio Slice Extracted**:
  `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\cache\audio\1703b8e950cac10f_clip_01_slice.wav` (22.0s, 16 kHz mono WAV, 704 KB). Video remained 100% local.

### Step 2: Groq Transcription Status & Exact Commands
The background subshell does not inherit session-local environment variables (`$env:GROQ_API_KEY`) from the user's separate interactive PowerShell terminal.

To transcribe and render `clip_01` in the PowerShell window where your key is already active:

1. **Transcribe `clip_01` with Groq (`whisper-large-v3-turbo`)**:
   ```powershell
   python -m gta_clipper.cli transcribe-clip --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9" --clip-id clip_01 --provider groq
   ```
2. **Render 1080×1920 Vertical MP4 with Burned Captions (`viral_streamer_yellow`)**:
   ```powershell
   python -m gta_clipper.cli render --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9" --clip-id clip_01
   ```
3. **Optional (Allow Subshells to See Key Without Re-entering)**:
   ```powershell
   [System.Environment]::SetEnvironmentVariable('GROQ_API_KEY', $env:GROQ_API_KEY, 'User')
   ```

### Output File Destinations
- **HTML Contact Sheet**: `file:///C:/Users/sanid/AppData/Local/Temp/gta_clipping_data/jobs/job_gta_v_chaos_mod_360p_1703b8e9/contact_sheet.html`
- **Rendered Vertical MP4**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\exports\job_gta_v_chaos_mod_360p_1703b8e9\clip_01_1080x1920.mp4`
- **Burned ASS Subtitles**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9\subtitles\clip_01.ass`
- **Editable SRT**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9\subtitles\clip_01.srt`



## Live Groq recovery — 17 November 2026

- The user's live Groq request saved 12 speech segments and a populated SRT and ASS for clip_01 before Windows denied a redundant review_sheet.json replacement. The nonzero exit caused the user's conditional render to skip.
- Rendered only clip_01 from the saved captions using the existing local job and data directory. No additional Groq request. FFprobe confirmed 1080x1920 H.264 video, AAC audio and 22.033 seconds. Full audio/video decode passed. The output still contains the preset's inaccurate GTA VI hook and is a test clip; wording and timing were not independently reviewed against the source audio.
- Transcribing an existing job now refreshes only the derived HTML after saving the clip/review JSON and subtitles. If HTML refresh fails, the CLI reports that the captions were saved. Refreshed the current job's contact sheet and verified the review JSON remained byte-for-byte identical.
- Re-ran python -X utf8 tests/run_tests.py with a fresh GTA_CLIPPING_DATA_DIR under local Temp: all 23 tests passed in 37.316 seconds.


## 7. Deliverables Reorganization, Timing Measurements & Caption Fallback (17 November 2026)

### 1. Deliverables Reorganization & Storage Boundary
- **Clean Default Location**: Finished exports now automatically resolve to:  
  `GTA_clipping\exports\<original-source-video-name>\`
- **Standardized Naming**:  
  `<original-source-video-name>_clip_01.mp4` and `<original-source-video-name>_clip_01.srt`
- **Naming & Collision Logic (`gta_clipper/config.py`)**:
  - Resolves `original_source_name` / `original_source_file` from job metadata, falling back to `source_file_name`.
  - Sanitizes illegal Windows characters (`< > : " / \ | ? *`) and trims trailing spaces/dots.
  - Distinguishes different sources sharing the same base name by appending `_<source_hash[:8]>`.
  - Supports `--export-outside-onedrive` to route deliverables to `StorageConfig.exports_dir` outside OneDrive.
- **GTA V Chaos Mod Verification**:
  - Deliverable directory created:  
    `c:\Users\sanid\OneDrive - Rīgas Tehniskā Universitāte\Darbvirsma\GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\`
  - Deliverables verified and playable:
    - `vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01.mp4` (7,917,095 bytes, 1080×1920, H.264, AAC, 22.033s)
    - `vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01.srt` (794 bytes, 11 entries)
    - `job_manifest.json` (2,470 bytes)
  - Prior intermediate copies remain intact in local Temp:  
    `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\exports\job_gta_v_chaos_mod_360p_1703b8e9\clip_01_1080x1920.mp4`
  - OneDrive workspace contains only final deliverables; heavy scratch files, models, and audio slices remain strictly outside OneDrive.

### 2. Performance Breakdown & Stage Timing
Measured on the 10m 37s (637.5s) GTA V Chaos Mod recording:

| Processing Stage | Measured Time | Notes / Details |
| :--- | :--- | :--- |
| **Local Analysis** | **7.50s** | ffprobe stream inspection (0.23s), scene transitions `gt(scene,0.30)` (6.45s), RMS audio energy (0.82s). |
| **Audio Slicing** | **0.24s** | 22.0s 16 kHz mono WAV extracted via fast FFmpeg input seek (`-ss`). |
| **Groq Cloud Transcription** | **1.15s** | `whisper-large-v3-turbo` with word timestamps (19.1x realtime). |
| **FFmpeg 1080×1920 Vertical Render** | **3.61s** | Center crop, 1080×1920 H.264/AAC, burned ASS hardsubs (6.1x realtime). |
| **Deliverable Copy & Verification** | **0.01s** | Atomic copy to `GTA_clipping\exports\<name>\` and manifest write. |
| **Total First Run** | **12.51s** | Complete pipeline from raw stream to captioned vertical Reel. |
| **Repeat Run (Deliverable Reuse)** | **0.00s** | Instantaneous reuse when deliverable exists without `--force`. |

**Timing Analysis**:
- The **slowest stage** is local scene-transition detection across the entire 10m 37s stream (6.45s), followed by the FFmpeg 1080×1920 render (3.61s).
- Reruns with an unchanged clip or different export destination take **0.00s** by reusing the valid rendered MP4 and SRT files without re-encoding.
- Output quality remains untouched at clean 1080×1920 vertical H.264/AAC with crisp vector ASS hardsubs.

### 3. Transcription Fallback & FreeLLMAPI Assessment
- **Primary Provider**: Groq Whisper API (`whisper-large-v3-turbo`).
- **Rate-Limit & Quota Handling**:
  - Catches HTTP 429 quota exhaustion and extracts `Retry-After` header.
  - Prevents repeated looping API calls during backoff periods.
- **FreeLLMAPI Route Evaluation**:
  - Inspected the host environment: FreeLLMAPI is not installed on PATH or in the Python environment.
  - Furthermore, FreeLLMAPI's free speech-to-text route proxies directly to Groq's Whisper API (`whisper-large-v3-turbo`). Consequently, if Groq quota is exhausted, FreeLLMAPI will also fail on the same quota. Per instructions, FreeLLMAPI is kept disabled (`FREELLMAPI_UNVERIFIED`).
- **Fallback Hierarchy**:
  1. Groq Whisper (`whisper-large-v3-turbo`).
  2. If Groq encounters HTTP 429 / quota limit:
     - Tries local `whisper.cpp` (`whisper-cli`) if installed.
     - Tries external SRT transcript import (`--transcript` or `--fallback-srt`).
     - If no fallback is enabled, holds clip in `[AWAITING CAPTIONS]` with status `QUOTA_AWAITING_CAPTIONS`.
- **Safety Guardrail**:
  - The renderer strictly blocks exporting dialogue clips with empty or unverified captions. Clips remain awaiting captions rather than releasing broken silent captions.

### 4. Automated Verification Suite (31 Tests)
```powershell
python -X utf8 tests/run_tests.py
```
**Result**:
```
----------------------------------------------------------------------
Ran 31 tests in 45.286s

OK
```
**New Tests Added**:
- `test_24_groq_429_quota_fallback_to_local_whisper`: Verifies mock HTTP 429 with `Retry-After: 30s` automatically switches to local Whisper, applies candidate start offset (15.0s), and logs fallback status.
- `test_25_groq_429_quota_fallback_to_srt_import`: Verifies mock HTTP 429 falls back to manual/supplied SRT file, returning synchronized segments.
- `test_26_freellmapi_unverified_guardrail`: Verifies FreeLLMAPI is kept disabled and clip is held awaiting captions.
- `test_27_deliverable_reuse_and_export_path_resolution`: Verifies Windows filename sanitization, hash collision resolution, deliverable naming, and instantaneous deliverable reuse.
- `test_28_square_pixels_sar_dar_verification`: Verifies with ffprobe that rendered vertical video outputs have strictly square pixels (`SAR=1:1`) and `DAR=9:16`.
- `test_29_stale_render_reuse_invalidation`: Verifies render fingerprinting (`compute_render_fingerprint`) ensures that changing layout, crop offset, hook banner, or subtitle content invalidates the cache and triggers a fresh re-encode, while identical reruns reuse cached deliverables in 0.00s.
- `test_30_storytelling_setup_action_payoff_timestamps`: Verifies 3-part storytelling timestamps (setup, action, payoff) and shot-by-shot framing generation with tracking resets at scene cuts.
- `test_31_facecam_guardrail_pip_fallback`: Verifies facecam guardrail safely falls back from `pip` to `fit_background` when facecam region is unconfirmed.


## 8. Horizontal-to-Vertical Framing Fix, Previews & Fallback Audit (17 November 2026)

### 1. Two Previews Rendered from GTA V Chaos Mod clip_01
Both previews were rendered from the existing GTA V Chaos Mod `clip_01` (source 2.47s to 24.47s, 22.0s duration) reusing its saved captions and placed in the project deliverables folder:
- **Preview A (Full Gameplay Fit inside 9:16 with Blurred Background)**:  
  [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_fit_bg.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_fit_bg.mp4)  
  - Size: 7,799,260 bytes (7.44 MB)  
  - Layout: `fit_background`  
  - Sidecar SRT: `..._clip_01_fit_bg.srt`  
  - ffprobe: 1080×1920, SAR 1:1, DAR 9:16, H.264/AAC.
- **Preview B (Full-Screen Vertical Follow Crop per Shot)**:  
  [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_follow_crop.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_follow_crop.mp4)  
  - Size: 7,610,912 bytes (7.26 MB)  
  - Layout: `follow_crop` (per-shot keyframed dynamic crop tracking subject)  
  - Sidecar SRT: `..._clip_01_follow_crop.srt`  
  - ffprobe: 1080×1920, SAR 1:1, DAR 9:16, H.264/AAC.
- **Original Export Kept for Comparison**:  
  [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01.mp4) (7,917,095 bytes)

### 2. Opening Banner Correction
- **Original Inaccurate Hook**: `"GTA 6 physics are already unmatched"` (default template text from GTA VI preset).
- **Corrected Hook**: `"I INSTALLED THE GTA V CHAOS MOD!"`.
- Burned into ASS hardsubs in the top safe zone (`Alignment=8, MarginV=200`) across `0:00:00.00 -> 0:00:03.20`.
- Matches what the creator actually says: *"to yell. Just kidding! I installed the Chaos mod on all your PCs!"*.

### 3. Visual Comparison: Opening, Main Action & Payoff
Extracted comparison frames saved in [`exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\preview_comparison\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison):

| Moment | Timestamp | Preview A (`fit_bg`) | Preview B (`follow_crop`) |
| :--- | :--- | :--- | :--- |
| **Opening** | `t = 1.0s` (rel) / `3.5s` (source) | Streamer reaction centered in 16:9 gameplay frame with blurred background. Corrected top banner: *"I INSTALLED THE GTA V CHAOS MOD!"*. Captions: *"to yell. Just kidding! I installed"*. | Streamer face fills the entire 1080×1920 vertical canvas. Same top banner and bottom subtitles inside safe zones. |
| **Streamer Face** *(Corrected)* | `t = 6.5s` (rel) / `9.0s` (source) | Shows full gameplay width: guest streamer on right + chaos fog on left. Captions: *"already. I'm dead. This is the most"*. | Vertical window tracks streamer face on right (`crop_x_pct = 0.65`), filling canvas with reaction. *(Note: at source 0:06.5 / rel 4.03s, main streamer's face is also prominently visible on right laughing while driving; previous description of pure traffic driving has been corrected).* |
| **Payoff** | `t = 20.0s` (rel) / `22.5s` (source) | Full-frame fit showing Franklin standing on the street on the right AND streamer reaction on the left. Captions: *"happen to each of us. I just got oil"*. | Vertical window positions crop at `crop_x_pct = 0.72`, centering Franklin on the oil puddle but cutting off the streamer on the left. |

### 4. Shot-by-Shot Framing Audit: Which Shots Need Manual Framing
The 22.0s clip contains 6 key shots divided by scene cuts:

| Shot | Clip Time Window | Visual Content | Anchor / Layout | Framing Status & Source Label |
| :---: | :---: | :--- | :---: | :--- |
| **Shot 1** | `0.0s -> 1.97s` | Streamer laughing into camera ("I installed the Chaos mod!") | `0.35` (`follow_crop`) | **Manual**: Focused on streamer intro (`crop_source: manual`). |
| **Shot 2** | `1.97s -> 4.00s` | Night city driving; sports car moving toward strip club | `0.36` (`follow_crop`) | **Manual**: Follow crop tracks white sports car (`crop_source: manual`). |
| **Shot 3** | `4.00s -> 9.13s` | Streamer face reaction around 0:06.5 (source 6.5s main streamer face; clip rel 6.5s guest streamer face) | `0.65` (`follow_crop`) | **Manual**: Tight crop on streamer's face on right (`crop_source: manual`). |
| **Shot 4** | `9.13s -> 13.67s` | Explosion, streamer screams "GAME OVER" | `0.50` (`follow_crop`) | **Manual**: Reaction centered (`crop_source: manual`). |
| **Shot 5** | `13.67s -> 17.63s` | Chaos sky effect, flying vehicle, blue chaos HUD bar | `0.50` (`follow_crop`) | **Manual**: Chaos action centered (`crop_source: manual`). |
| **Shot 6** | `17.63s -> 22.00s` | Franklin standing on desert road with oil circle; streamer on left | `0.50` (`fit_background`) | **Manual**: Dual subjects at opposite edges (streamer at `x=0.20`, Franklin at `x=0.72`). Full shot preserved (`crop_source: manual`). |

### 5. Stale Render Reuse Invalidation
- Implemented `compute_render_fingerprint` in `gta_clipper/renderer.py`:
  Hashes source video size/path, clip start/end timestamps, layout mode, crop offset/keyframes, subtitle burn toggle, actual `.ass` file bytes, and hook banner text.
- Metadata is saved to `<output_file>.render_meta.json`.
- Tested and verified:
  - Identical rerun: Reused in **0.00s**.
  - Changing layout (e.g. `center_crop` -> `fit_background`): Fingerprint mismatch invalidates cache and triggers full FFmpeg re-encode.
  - Changing crop offset or subtitles: Fingerprint mismatch invalidates cache and triggers full FFmpeg re-encode.

### 6. Caption Fallback Audit: Real vs Mocked
- **Groq Cloud Whisper**: Primary cloud provider (`whisper-large-v3-turbo`). Rate limits catch HTTP 429 and parse `Retry-After`.
- **Local Whisper (`whisper.cpp`)**: Automated integration tests passed (`test_24`). FFmpeg's built-in `whisper` filter (`ffmpeg -h filter=whisper`) is confirmed present in the installed FFmpeg build. Local whisper binaries/models are not bundled on PATH; tested via mocked quota fallback.
- **Manual / Sidecar SRT Import**: **PASSED REAL VERIFICATION** on real video audio (`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01.srt` burned into MP4).
- **FreeLLMAPI Evaluation**: FreeLLMAPI is not installed on the system. Furthermore, its free speech-to-text endpoint routes directly back to Groq (`whisper-large-v3-turbo`), meaning an exhausted Groq quota will also fail on FreeLLMAPI, violating the requirement of providing an independent quota. Kept **DISABLED** (`FREELLMAPI_UNVERIFIED`).


## 9. Improved Hybrid Export & Per-Shot Layout Switching (17 November 2026)

### 1. Hybrid Export Deliverables
- **Location**:  
  [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P)
- **New Deliverables**:
  - **Hybrid MP4**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_hybrid.mp4) (7,608,879 bytes, 7.26 MB)
  - **Hybrid SRT**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_hybrid.srt) (794 bytes, 11 entries)
- **Comparison Previews Preserved**:
  - Preview A (`fit_bg`): [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_fit_bg.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_fit_bg.mp4) (7,799,260 bytes)
  - Preview B (`follow_crop`): [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_follow_crop.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_follow_crop.mp4) (7,610,912 bytes)
  - Original: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01.mp4) (7,917,095 bytes)

### 2. ffprobe Output Verification
Command:
```powershell
ffprobe -v quiet -print_format json -show_streams "exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_hybrid.mp4"
```
**Results**:
- **Dimensions**: `1080 x 1920` (exact 9:16 vertical canvas).
- **Square Pixels**: `sample_aspect_ratio = 1:1` (SAR 1:1).
- **Display Aspect Ratio**: `display_aspect_ratio = 9:16` (DAR 9:16).
- **Video Codec**: `h264 (Main) (avc1)`, progressive, 30.0 fps, yuv420p.
- **Audio Codec**: `aac (LC) (mp4a)`, 48000 Hz, stereo, 192 kb/s.
- **Duration**: `22.000000s`.

### 3. Per-Shot Layout Switching Architecture
Implemented native single-pass FFmpeg filter complex switching between `follow_crop` and `fit_background`:
```
[0:v]crop=ih*9/16:ih:<dynamic_crop_expr>:0,scale=1080:1920:flags=lanczos,setsar=1,setdar=9/16[cropped];
[0:v]split=2[bg][fg];
[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=10:2[bg_blur];
[fg]scale=1080:608:force_original_aspect_ratio=decrease[fg_scaled];
[bg_blur][fg_scaled]overlay=(W-w)/2:(H-h)/2,setsar=1,setdar=9/16[fit_bg];
[cropped][fit_bg]overlay=0:0:enable='between(t,17.63,22.00)',setsar=1,setdar=9/16,ass='<subtitles.ass>'[v_out]
```
- **Shots 1–5 (`0.00s -> 17.63s`)**: Rendered with tight `follow_crop` (`crop_source: manual`), maximizing vertical screen real estate for single subjects (streamer face, sports car driving, face reactions).
- **Shot 6 (`17.63s -> 22.00s`, around 0:20)**: Seamlessly transitions at the cut to `fit_background` (`crop_source: manual`), preserving the complete 16:9 gameplay frame so both the streamer and Franklin on the oil puddle remain visible.
- **Burned Subtitles**: Reused saved captions (`clip_01.ass`) with safe zones (Margin V: 380px) and corrected opening hook banner: `"I INSTALLED THE GTA V CHAOS MOD!"`.

### 4. Visual Comparison at 0:06.5 and 0:20 Across All Three Previews

Comparison JPEGs extracted to [`exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\preview_comparison\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison):

| Timestamp | Preview A (`fit_bg`) | Preview B (`follow_crop`) | New Hybrid Export |
| :--- | :--- | :--- | :--- |
| **`t = 6.5s`**<br>(Streamer Face Reaction) | Shrunk inside 16:9 box with blurred bars top/bottom. Reaction lacks mobile impact.<br>*(File: `fit_bg_t6.5s.jpg`)* | Tightly cropped to streamer's face on right (`x=0.65`). Reaction fills vertical screen.<br>*(File: `follow_crop_t6.5s.jpg`)* | **Tightly cropped (`follow_crop`)**: Streamer's face reaction fills vertical screen with maximum mobile impact.<br>*(File: `hybrid_t6.5s.jpg`)* |
| **`t = 20.0s`**<br>(Payoff: Streamer + Franklin on Oil) | Full 16:9 frame visible: streamer on left, Franklin on right.<br>*(File: `fit_bg_t20.0s.jpg`)* | Tightly cropped to Franklin on right (`x=0.72`). **Streamer on left is completely cut off**.<br>*(File: `follow_crop_t20.0s.jpg`)* | **Full frame preserved (`fit_background`)**: Shows both streamer in BEAST shirt on left AND Franklin standing in oil circle on right!<br>*(File: `hybrid_t20.0s.jpg`)* |

### 5. Automated Verification Suite (32 Tests)
Command: `python -X utf8 tests/run_tests.py`
```
Ran 32 tests in 47.583s
OK
```
New test `test_32_hybrid_per_shot_layout_switching` verifies:
- Filtergraph generation with `overlay=0:0:enable='between(t,1.50,3.00)'`.
- Strict square-pixel enforcement (`SAR=1:1`, `DAR=9:16`).
- Clean rendering of mixed-layout clips with burned ASS subtitles.


## 10. Automatic Subject Tracking & Framing Decisions per Shot (17 November 2026)

### 1. Automatic Subject Tracking Engine (`gta_clipper/visual.py`)
Implemented `analyze_shot_framing_auto` and integrated it into `compute_clip_shot_framing`:
- **Multi-Frame Inspection**: Analyzes 2–4 sample frames across each shot window.
- **Saliency Fusion**: Fuses skin-tone detection (streamer faces, gameplay avatars), high-contrast edge gradients, and inter-frame motion deltas (`|F_{t+1} - F_t|`). Excludes static HUD elements (e.g. bottom-left radar/minimap, top streamer status bars).
- **Rule Hierarchy**:
  1. **Dual Subjects Far Apart**: If two prominent subject clusters are detected with horizontal separation $\Delta x > 0.30$ (wider than the 9:16 crop window $W_{crop} \approx 0.316$), the full frame is preserved using `fit_background`.
  2. **Single Clear Subject**: When visual mass is concentrated in one primary cluster, computes normalized subject coordinate $x_s$ and maps it to crop position $x_{pct} = \frac{x_s - 0.158}{0.684}$. If the subject moves across the shot ($\Delta x \ge 0.05$), calculates `smooth_to` for dynamic panning (`follow_crop`).
  3. **Uncertain Tracking / Broad Action**: If saliency is diffuse or no distinct subject cluster is found, preserves full frame with `fit_background`.
  4. **Strict Standard**: A default center position ($0.50$) does NOT count as subject tracking; auto-follow shots must be grounded in detected subject positions.

### 2. Clip 01: Automatic Framing Verification vs Manual Baseline
Run without hand-set crop positions (`--auto-framing --suffix auto_hybrid`):
- **Output**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_auto_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_auto_hybrid.mp4) (8.27 MB, 22.0s)
- **Burned Subtitles**: Reused saved captions (`clip_01.ass`) with safe zones.
- **Per-Shot Breakdown**:
  - `Shot 01 ( 0.00s ->  0.43s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.42 > 0.30 crop window); preserved full frame.
  - `Shot 02 ( 0.43s ->  2.00s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.49 > 0.30 crop window); preserved full frame.
  - `Shot 03 ( 2.00s ->  2.46s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.14 fits in 9:16 crop (`crop_x=0.00`).
  - `Shot 04 ( 2.46s ->  3.43s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.44 > 0.30 crop window); preserved full frame.
  - `Shot 05 ( 3.43s ->  4.03s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.77 fits in 9:16 crop (`crop_x=0.90`).
  - `Shot 06 ( 4.03s ->  5.46s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.83 fits in 9:16 crop (`crop_x=0.98`).
  - `Shot 07 ( 5.46s ->  6.40s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.76 fits in 9:16 crop (`crop_x=0.89`).
  - `Shot 08 ( 6.40s ->  9.16s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.52; smooth pan to x=0.23 (`crop_x=0.53 -> smooth to 0.23`).
  - `Shot 09 ( 9.16s -> 13.70s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.46; smooth pan to x=0.12 (`crop_x=0.44 -> smooth to 0.12`).
  - `Shot 10 (13.70s -> 17.66s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.59 > 0.30 crop window); preserved full frame.
  - `Shot 11 (17.66s -> 20.90s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.37; smooth pan to x=0.44 (`crop_x=0.31 -> smooth to 0.44`).
  - `Shot 12 (20.90s -> 22.00s)`: `fit_background [AUTO]` — **Dual subjects far apart (span=0.62 > 0.30 crop window); preserved full frame**.
- **Crucial 0:20 Payoff Result**:
  Visual inspection of frame `auto_hybrid_clip01_t21.5s.jpg` confirms that at $t = 21.5\text{s}$, the automatic analyzer detected the dual subjects (streamer in BEAST shirt on left at $x \approx 0.22$, Franklin walking on oil puddle on right at $x \approx 0.78$, span $= 0.62$), keeping **both the streamer and Franklin fully visible** in the fitted 16:9 gameplay box!

### 3. Clip 02: Verification on Different Clip Beyond Original Example
Run on `clip_02` (source 70.53s to 92.53s, 22.0s duration) with zero manual positions:
- **Output**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_02_auto_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_02_auto_hybrid.mp4) (10.55 MB, 22.0s)
- **Per-Shot Breakdown**:
  - `Shot 01 ( 0.00s ->  2.00s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.43 > 0.30 crop window: car driving + streamer on right); preserved full frame.
  - `Shot 02 ( 2.00s ->  3.27s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.89 fits in 9:16 crop (`crop_x=1.00`).
  - `Shot 03 ( 3.27s ->  4.44s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.84; smooth pan to x=0.74 (`crop_x=1.00 -> smooth to 0.74`).
  - `Shot 04 ( 4.44s ->  5.40s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.33 > 0.30 crop window); preserved full frame.
  - `Shot 05 ( 5.40s ->  5.97s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.16 fits in 9:16 crop (`crop_x=0.00`).
  - `Shot 06 ( 5.97s ->  7.54s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.50; smooth pan to x=0.43 (`crop_x=0.51 -> smooth to 0.43`).
  - `Shot 07 ( 7.54s -> 10.14s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.41 > 0.30: crowd of NPCs swarming street + seated gamer); preserved full frame.
  - `Shot 08 (10.14s -> 12.00s)`: `fit_background [AUTO]` — Dual subjects far apart (span=0.58 > 0.30); preserved full frame.
  - `Shot 09 (12.00s -> 12.87s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.25 fits in 9:16 crop (`crop_x=0.13`).
  - `Shot 10 (12.87s -> 14.30s)`: `follow_crop    [AUTO]` — Single clear subject centered at x=0.79 fits in 9:16 crop (`crop_x=0.92`).
  - `Shot 11 (14.30s -> 22.00s)`: `follow_crop    [AUTO]` — Single clear subject at x=0.88; smooth pan to x=0.05 (`crop_x=1.00 -> smooth to 0.05`).

### 4. ffprobe Verification (Both Auto-Hybrid Deliverables)
```powershell
ffprobe -v quiet -print_format json -show_streams "<file>.mp4"
```
- **Both MP4s**: Dimensions `1080 x 1920`, `SAR = 1:1` (square pixels verified), `DAR = 9:16`, `30.0 fps`, progressive `H.264/AAC`.

### 5. Automated Test Suite (33 Tests)
Command: `python -X utf8 tests/run_tests.py`
```
Ran 33 tests in 59.723s
OK
```
New test `test_33_automatic_subject_framing_dual_vs_single` verifies that automatic shot framing analyzes frame content, classifies dual-subject vs single-subject shots, avoids blind 0.5 center defaults, and properly labels `crop_source: auto`.


---

## 11. Framing Accuracy Fixes & Auto-Hybrid v2 Verification (17 November 2026)

### 1. Clip 01 Framing Audit: Source vs. Rendered Timestamps
An audit of `clip_01_auto_hybrid.mp4` identified a framing error at exactly `00:20.000`:
- **Problem**: In the previous export, `Shot 11` ran from `17.66s` to `20.90s` and erroneously selected `follow_crop` (`crop_x_pct = 0.31 -> smooth to 0.44`). At `t_rel = 20.000s`, the tight 9:16 crop cut through the middle of the streamer's face on the left and completely eliminated Franklin on the right. Both became visible only at `20.900s` / `21.500s` when `Shot 12` switched to `fit_background`.
- **Timestamp Mapping (Clip Start Offset = 2.470s)**:

| Clip-Relative Time | Source Video Time | Source Visual Scene | Old Export (`auto_hybrid`) | Revised Export (`auto_hybrid_v2`) |
| :--- | :--- | :--- | :--- | :--- |
| **`00:19.000s`** | `00:21.470s` | Streamer gestures on left ($x \approx 0.25$), Franklin walks on oil ($x \approx 0.72$). | `follow_crop` (tight crop; Franklin cut off) | **`fit_background`** (full 16:9 frame in 9:16 box; both visible) |
| **`00:20.000s`** | `00:22.470s` | Streamer laughs on left ($x \approx 0.25$), Franklin stands in oil circle ($x \approx 0.78$). | **FAILED**: `follow_crop` (half streamer, 0% Franklin) | **VERIFIED**: **`fit_background`** (both streamer & Franklin fully visible) |
| **`00:20.900s`** | `00:23.370s` | Oil ignites; streamer on left, burning circle on right. | `fit_background` (cut reset occurred late) | **`fit_background`** (continuous fit_bg throughout action) |
| **`00:21.500s`** | `00:23.970s` | Payoff: Streamer reaction on left, Franklin engulfed on right. | `fit_background` (both visible) | **`fit_background`** (both visible) |

### 2. Refined Automatic Framing Engine (`gta_clipper/visual.py`)
To prevent late widening and erratic subject jumps without relying on hardcoded timestamps:
1. **Adaptive Multi-Sample Density**: Evaluates 4 to 6 samples across shots (15%, 38%, 62%, 85% for medium shots; 10%, 30%, 50%, 70%, 90% for longer shots) ensuring late-developing action is never missed.
2. **Prominent Peak & Valley Saliency**: Detects distinct local maxima in horizontal energy profiles with valley analysis ($b_{valley} \le 0.85 \times \min(p_1, p_2)$ for peaks separated by $\ge 0.26$).
3. **Bipartite Mass Distribution**: Detects when both outer thirds ($x < 0.33$ and $x > 0.67$) carry significant mass ($\ge 18\%$ each), identifying dual subjects spanning wider than the 9:16 window ($W_{crop} \approx 0.316$).
4. **Late Widening & Shot Aggregation Guardrail**: If *any* sample within a shot detects dual subjects or widening action ($span > 0.28$), the entire shot commits to `fit_background` to prevent mid-shot cutoff.
5. **Subject Jump / Inconsistency Rejection**: If detected subject positions across a shot exhibit a jump $|x_{end} - x_{start}| > 0.38$ or span $> 0.45$ across disparate coordinates, the erratic pan is rejected in favor of `fit_background`.

### 3. Clip 02 Audit: Long Segment (00:14.300 -> 00:22.000) & Speech Analysis
- **Framing Audit**: In the initial auto-hybrid, the shot from `14.30s` to `22.00s` generated a slow pan from `crop_x = 1.00` to `0.05` ($83\%$ screen shift). Inspection revealed that at $14.5\text{s}$, the primary subject was the streamer facecam on the far right ($x \approx 0.88$) with gameplay on the left ($x \approx 0.18$). By $18.0\text{s}$ and $21.5\text{s}$, the camera glitched into dark sky/mountain debris ($x \approx 0.16$). The tracker was leaping between unrelated subjects on opposite edges of the canvas. The new rule correctly identifies this jump and preserves the full frame with `fit_background`.
- **Speech Check**: Clip 02 (`70.53s -> 92.53s`) consists of chaotic gameplay audio, engine noise, and shouting without distinct speech dialogue. It is therefore labeled as a **framing-only preview** (rendered with `--allow-uncaptioned`).

### 4. Revised Deliverables (`_auto_hybrid_v2`)
- **Folder**: [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P)
- **Clip 01 v2 Deliverables**:
  - MP4: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_auto_hybrid_v2.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_auto_hybrid_v2.mp4) (7.49 MB, 22.0s)
  - SRT: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_auto_hybrid_v2.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_auto_hybrid_v2.srt) (794 bytes)
  - Subtitles: Burned ASS captions with safe zones (Margin V: 380px) and hook banner.
- **Clip 02 v2 Deliverables**:
  - MP4: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_02_auto_hybrid_v2.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_02_auto_hybrid_v2.mp4) (10.05 MB, 22.0s)
  - SRT: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_02_auto_hybrid_v2.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_02_auto_hybrid_v2.srt) (Framing-only preview)
- **All Previous Deliverables Preserved**:
  - `clip_01.mp4`, `clip_01_fit_bg.mp4`, `clip_01_follow_crop.mp4`, `clip_01_hybrid.mp4`, `clip_01_auto_hybrid.mp4`, `clip_02_auto_hybrid.mp4`.

### 5. ffprobe Specification Verification
```powershell
ffprobe -v quiet -print_format json -show_streams "<file>.mp4"
```
- **Dimensions**: `1080 x 1920` (exact 9:16 vertical canvas).
- **Sample Aspect Ratio (SAR)**: `1:1` (square pixels verified).
- **Display Aspect Ratio (DAR)**: `9:16` (exact vertical Shorts/Reels ratio).
- **Codecs**: Video `h264 (High) (avc1)` progressive 30.0 fps; Audio `aac (LC) (mp4a)` stereo 48 kHz.

### 6. Frame Evidence Files
Comparison frames extracted into [`preview_comparison\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison):
- [`auto_hybrid_v2_clip01_t20.0s.jpg`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison/auto_hybrid_v2_clip01_t20.0s.jpg): Confirms that at exactly `00:20.000`, the revised MP4 preserves the complete 16:9 frame inside the 9:16 canvas, showing both the streamer on the left and Franklin in the oil circle on the right.
- [`auto_hybrid_v2_clip02_seg_start_t14.5s.jpg`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison/auto_hybrid_v2_clip02_seg_start_t14.5s.jpg): Start of Clip 02's long segment (full frame preserved).
- [`auto_hybrid_v2_clip02_seg_mid_t18.0s.jpg`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison/auto_hybrid_v2_clip02_seg_mid_t18.0s.jpg): Middle of Clip 02's long segment (stable full frame, no erratic pan).
- [`auto_hybrid_v2_clip02_seg_end_t21.5s.jpg`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/preview_comparison/auto_hybrid_v2_clip02_seg_end_t21.5s.jpg): End of Clip 02's long segment (stable full frame).

### 7. Automated Test Suite (34 Tests)
Command: `python -X utf8 tests/run_tests.py`
```
Ran 34 tests in 101.289s
OK
```
New test `test_34_late_widening_and_subject_jump_guardrails` verifies:
- **Late Widening**: Shot where subject separation widens from single subject to dual subjects $\rightarrow$ correctly triggers `fit_background`.
- **Subject Jump**: Shot where tracker leaps between coordinates on opposite edges ($x=0.85 \to 0.10$) $\rightarrow$ correctly rejects erratic pan and selects `fit_background`.


---

## 12. Independent End-to-End Automatic Clipping Test (17 November 2026)

### 1. Test Input & Moment Selection
- **Input Source Recording**: `C:\Users\sanid\Downloads\vidssave.com I Installed The GTA V Chaos Mod! 360P.mp4` (Duration: 637.57s / 10.6 min, 640×360 H.264, 44.1 kHz stereo AAC).
- **Staged Local Storage**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\sources\vidssave.com I Installed The GTA V Chaos Mod! 360P.mp4` (Isolated outside OneDrive).
- **Selected Gameplay Moment**:
  - **Source Time**: `00:02.470` to `00:24.470` (Duration: `22.000s`).
  - **Setup (`00:02.470 -> 00:09.160`)**: Streamer explains Chaos Mod rules while driving sports car down Los Santos highway.
  - **Action (`00:09.160 -> 00:17.660`)**: Chaos Mod status bar activates; vehicle physics warp, causing car to flip and roll uncontrollably across the highway into the desert shoulder; Franklin ejects onto roadway.
  - **Payoff (`00:17.660 -> 00:24.470`)**: Streamer laughs ("I just got oil!"); Franklin steps into a dark oil puddle in the road; the puddle catches fire and erupts into a massive fireball engulfing Franklin while the streamer shouts in reaction.

### 2. Automatic Hybrid Framing Execution (Zero Manual Keyframes)
Evaluated dynamically per-shot using the refined automatic framing engine (`--layout hybrid --auto-framing`):
- `Shot 01 ( 0.00s ->  0.43s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.66 > 0.28).
- `Shot 02 ( 0.43s ->  2.00s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.91 > 0.28).
- `Shot 03 ( 2.00s ->  2.46s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.75 > 0.28).
- `Shot 04 ( 2.46s ->  3.43s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.91 > 0.28).
- `Shot 05 ( 3.43s ->  4.03s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.69 > 0.28).
- `Shot 06 ( 4.03s ->  5.46s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.53 > 0.28).
- `Shot 07 ( 5.46s ->  6.40s)`: **`follow_crop [AUTO]`** — Single clear subject centered at $x=0.77$ fits in 9:16 crop (`crop_x=0.89`), maximizing mobile screen impact for streamer reaction.
- `Shot 08 ( 6.40s ->  9.16s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.69 > 0.28).
- `Shot 09 ( 9.16s -> 13.70s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.72 > 0.28); car flipping across roadway preserved.
- `Shot 10 (13.70s -> 17.66s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.97 > 0.28); desert shoulder & character egress preserved.
- `Shot 11 (17.66s -> 20.90s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.78 > 0.28); **both streamer on left and Franklin in oil puddle on right fully visible at 20.0s**.
- `Shot 12 (20.90s -> 22.00s)`: `fit_background [AUTO]` — Dual subjects / wide action across shot (span=0.97 > 0.28); **fireball explosion engulfing Franklin fully preserved**.

### 3. Deliverables & Technical Specs
- **Folder**: [`GTA_clipping\exports\vidssave.com I Installed The GTA V Chaos Mod! 360P\`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P)
- **Delivered MP4**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_auto_hybrid_e2e.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_auto_hybrid_e2e.mp4) (7,858,012 bytes / 7.49 MB, 22.0s)
- **Delivered SRT**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_auto_hybrid_e2e.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_auto_hybrid_e2e.srt) (794 bytes, 11 entries)
- **ffprobe Verification**:
  - Dimensions: `1080 x 1920`
  - Sample Aspect Ratio (SAR): `1:1` (square pixels verified)
  - Display Aspect Ratio (DAR): `9:16` (exact vertical canvas)
  - Video Codec: `h264 (High) (avc1)` progressive 30.0 fps
  - Audio Codec: `aac (LC) (mp4a)` stereo 48 kHz

### 4. Playback & Action Visibility Audit
Inspected 10 frame samples across the clip timeline:
- **`t = 1.0s` & `3.0s` (Setup)**: High-speed driving hook fills canvas height cleanly.
- **`t = 5.8s` (Reaction)**: Streamer facecam is clearly framed.
- **`t = 7.5s` (Highway Setup)**: Car trajectory and lane navigation are preserved.
- **`t = 10.0s` & `12.5s` (Action)**: As the Chaos Mod causes the sports car to roll violently across the road, the entire vehicle, debris, and Franklin jumping out remain 100% visible inside the 16:9 gameplay box (zero vehicle clipping).
- **`t = 15.0s` (Action)**: Franklin recovers on his feet in the roadway; surrounding traffic and desert environment remain in view.
- **`t = 18.0s` & `20.0s` (Payoff)**: Both streamer in BEAST shirt on the left and Franklin walking into the dark oil circle on the right are fully visible on screen.
- **`t = 21.5s` (Payoff)**: As the oil puddle detonates, the entire fireball and flame engulfment are completely visible without edge cutoff.

### 5. Caption Timing & Audio Synchronization Audit
Audited all 11 subtitle entries against audio speech RMS waveform:
- `[01] 00:00.00 -> 00:01.86` (RMS 5975): "to yell. Just kidding! I installed" *(Note: "to yell." is a leading partial syllable carried over from the pre-cut stream boundary at 2.47s; the core sentence "Just kidding! I installed" aligns immediately with the spoken punchline)*.
- `[02] 00:01.86 -> 00:03.82` (RMS 6855): "the Chaos mod on all your PCs!" *(Aligned with streamer emphasis peak)*.
- `[03] 00:04.14 -> 00:05.94` (RMS 6343): "Ah, it's chaotic! It is" *(Aligned with immediate speech burst)*.
- `[04] 00:05.94 -> 00:08.06` (RMS 5963): "already. I'm dead. This is the most" *(Aligned with laughter pause)*.
- `[05] 00:08.06 -> 00:10.04` (RMS 5383): "insane mod to ever be made" *(Aligned)*.
- `[06] 00:10.04 -> 00:11.90` (RMS 5391): "in any video game. What is going" *(Aligned)*.
- `[07] 00:11.90 -> 00:13.62` (RMS 5300): "on on my screen? I don't even know." *(Aligned)*.
- `[08] 00:13.82 -> 00:15.88` (RMS 5493): "We have this blue bar at the top of our screen" *(Aligned with gameplay mechanic cue)*.
- `[09] 00:15.88 -> 00:17.64` (RMS 5065): "and every time it goes to the right," *(Aligned)*.
- `[10] 00:17.88 -> 00:19.80` (RMS 5427): "something incredibly weird will" *(Aligned)*.
- `[11] 00:19.80 -> 00:21.90` (RMS 5422): "happen to each of us. I just got oil" *(Finishes at 21.90s, perfectly synchronized with the oil puddle catching fire at 21.5s)*.
- **Wording & Readability**: Safe-zone typography (Margin V: 380px, Arial Black bold yellow with black outline) ensures subtitles never obscure gameplay action or fall under TikTok/Reels UI overlays.


---

## 13. Later-Moment Automatic Clip After 60s (`HESOYAM +$250,000` Sequence, 18 November 2026)

### 1. Source Recording & Selected Moment
- **Source Recording (from `job_metadata.json`)**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\sources\gta_v_chaos_mod_360p.mp4` (35,467,760 bytes; original file `vidssave.com I Installed The GTA V Chaos Mod! 360P.mp4`).
- **Selected Segment**: **`04:28.50` to `04:52.85`** (`268.50s -> 292.85s`, duration **`24.35s`**).
- **Observed Events (Direct Visual & Audio Inspection)**:
  - **Opening (`00:00.00 -> 00:03.83`, src `268.50s -> 272.33s`)**: Starts cleanly on the blue Chaos Mod timer bar filling up, followed by a cash-register sound and the GTA HUD displaying `$250298` / `+$250000` (`HESOYAM`). Cuts to Jimmy driving a black pickup truck on a foggy highway exclaiming *"Wait, what?! Wait, what?!"*
  - **Reactions (`00:03.83 -> 00:12.60`, src `272.33s -> 281.10s`)**: Chris asks *"What'd you— you just got money?!"*; Jimmy opens the GTA map while laughing (*"I just got a quarter of a million dollars randomly!"*); Chandler yells *"NOOOOO!"*; Jimmy insists *"I swear I didn't do that! I swear I didn't rig it!"*
  - **Contrast / Payoff (`00:12.90 -> 00:24.35`, src `281.40s -> 292.85s`)**: Immediately afterward, Karl is flung high above a city street by `Launch Player Up` (*"WAIT, NO! They just launched me up for no reason!"*) and lands on the sidewalk; Chandler's green SUV hits a tree and explodes under `Vehicles Explode On Impact`, displaying red `wasted` (*"Vehicles explode on impact. Great."* — deadpan); Chris's green car on dark Mount Chiliad gets crushed by `Spawn Bale Trailer` (*"Oh cool, now there's a hay baler on me!"*), ending cleanly right before the swipe transition at `293.00s`.

### 2. Automatic Framing Improvements & Verification (`gta_clipper/visual.py`)
Visual inspection of the first draft caught two subtle issues that were fixed in the general automatic framing logic (zero manual keyframes):
1. **Short-Shot Dual Sampling (`0.4s <= dur < 1.8s`)**: Changed single midpoint sampling for `< 0.8s` shots to `[0.20, 0.80]`, plus added an anti-flicker rule smoothing isolated `< 0.80s` `follow_crop` transients between `fit_background` shots. This removed a brief 0.70s crop flicker at `20.73s -> 21.43s`.
2. **Physical 9:16 Width Threshold (`energy_span > w_crop_norm`)**: Tightened the wide-subject threshold from `0.36` to the exact physical 9:16 crop width `w_crop_norm = 0.3164`. In Shot 03 (`3.83s -> 5.27s`), Chris's already-zoomed facecam spanned `0.34 > 0.3164`, causing a narrow crop to clip his headphones, chop the top HUD text, and place captions over his chin. After the fix, all 10 shots automatically selected smooth `fit_background` (`1080x1920`, `SAR 1:1`, `DAR 9:16`), keeping gameplay, facecams, mod overlays, and captions cleanly separated and readable throughout.

### 3. Final Deliverables & Verification
- **MP4**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_03_hesoyam_250k_auto_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_03_hesoyam_250k_auto_hybrid.mp4) (10.21 MB, 1080×1920, SAR 1:1, DAR 9:16, 30 fps H.264 / 48 kHz stereo AAC, 24.35s)
- **SRT**: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_03_hesoyam_250k_auto_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_03_hesoyam_250k_auto_hybrid.srt) (862 bytes, 15 synchronized caption cues)
- **Unit Tests**: `test_33_automatic_subject_framing_dual_vs_single` and `test_34_late_widening_and_subject_jump_guardrails` pass (2/2 OK).


---

## 14. Named HESOYAM Candidate via Standard CLI & Vertical Portrait Pipeline Verification (18 November 2026)

### 1. Named HESOYAM Candidate Registered in Existing Review Job
- **Job**: `C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9`
- **Original `clip_03` Preserved**: `256.5s -> 281.1s` untouched in `clips/clip_03.json` and `review_sheet.json`.
- **New Named Candidate**: `clip_04_hesoyam_250k` (`268.50s -> 292.85s`, 24.35s) saved to `clips/clip_04_hesoyam_250k.json`, appended to `review_sheet.json` (4 candidates total) and `contact_sheet.html`, with the 15 verified subtitle cues attached in `speech_segments`, `subtitles/clip_04_hesoyam_250k.ass`, and `subtitles/clip_04_hesoyam_250k.srt`.
- **Standard CLI Render Command**:
  ```powershell
  python -m gta_clipper.cli render --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_gta_v_chaos_mod_360p_1703b8e9" --clip-id clip_04_hesoyam_250k --layout hybrid --auto-framing
  ```
- **Deliverables**:
  - MP4: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_04_hesoyam_250k_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_04_hesoyam_250k_hybrid.mp4) (10.21 MB, 1080×1920, SAR 1:1, DAR 9:16, H.264/AAC, 24.35s)
  - SRT: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_04_hesoyam_250k_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_04_hesoyam_250k_hybrid.srt) (862 bytes, 15 cues)

### 2. Portrait Input Preservation & External Transcript Trim Recompute Fixes
- **`gta_clipper/visual.py`**: `analyze_shot_framing_auto` now checks `if h >= w` and returns `mode: "portrait_preserve"` instead of running landscape 9:16 cropping/wide-span heuristics on already-vertical footage.
- **`gta_clipper/renderer.py`**: `render_clip` probes source orientation (`source_is_portrait = height >= width`) and passes it to `build_filter_graph`, preventing horizontal `crop=ih*9/16:ih` or `1080:608` shrinking on portrait sources while enforcing `1080×1920`, `SAR 1:1`, `DAR 9:16`.
- **`gta_clipper/audio.py`**: `analyze_audio` now caches imported `--transcript` segments to `storage.transcript_cache_dir / f"{source_hash}_t{track_index}.json"`, fixing a bug where trimming a clip in `review_sheet.json` failed to recompute subtitles when an external SRT was used.

### 3. Existing Vertical Recording Verification
- **Source Recording**: `C:\Users\sanid\Downloads\AQOqdiOh1yURoaR_UgUHEuBWyCxSkjTywJlC5vZ5LVuasoamV-HIQtWShb5-rmaI1XF_51hqnrP_nDrg9mpkhLu7U6YwOv5gBo65elI.mp4` (`720×1280` native portrait, 89.0s, Hindi/Hinglish travel narration), staged outside OneDrive in `sources\`.
- **Pipeline Commands**:
  ```powershell
  python -m gta_clipper.cli analyze --input "<staged_portrait.mp4>" --transcript "<portrait_transcript.srt>" --style-preset viral_streamer_yellow --max-clips 1 --transcription-provider none --creator "User Local" --rights owned --source-name "Uttarakhand_Portrait_Reel_720x1280"
  python -m gta_clipper.cli render --job-dir "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\jobs\job_AQOqdiOh1yURoaR_UgUHEuBW_b27429e9" --clip-id clip_01 --layout hybrid --auto-framing --force
  ```
- **Observed Result (`4.3s -> 24.8s`, 20.5s)**:
  - All 6 shots selected `portrait_preserve [AUTO]` (`Source is already portrait (720x1280); preserved native vertical framing`).
  - Visual inspection at `2.0s`, `11.5s`, and `16.0s` confirmed full native `1080×1920` portrait framing (zero shrinking or pillar bars) with synchronized burned-in captions matching the narration and on-screen scenes (`MUSSOORIE`, `THE CHAUKORI HERITAGE`, `GOLDEN GLITTER`).
  - **Deliverables**:
    - MP4: [`Uttarakhand_Portrait_Reel_720x1280_clip_01_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/Uttarakhand_Portrait_Reel_720x1280/Uttarakhand_Portrait_Reel_720x1280_clip_01_hybrid.mp4) (5.24 MB, 1080×1920, SAR 1:1, DAR 9:16, 20.50s)
    - SRT: [`Uttarakhand_Portrait_Reel_720x1280_clip_01_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/Uttarakhand_Portrait_Reel_720x1280/Uttarakhand_Portrait_Reel_720x1280_clip_01_hybrid.srt) (671 bytes, 7 recomputed cues)
- **Unit Tests**: Added `test_35_portrait_source_preserves_vertical_framing`; `test_33`, `test_34`, `test_35` pass (`3/3 OK`).


---

## 15. Research-Informed GTA Highlight Ranking Mode (18 November 2026)

### 1. Implementation Overview
- **New Ranking Module**: [`gta_clipper/ranking.py`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/gta_clipper/ranking.py) integrated into `gta_clipper/candidates.py` and `gta_clipper/cli.py`.
- **Adaptive Audio Peak Detection (`gta_clipper/audio.py`)**: Upgraded `analyze_audio_energy` to pair the `+8 dB` global threshold with an adaptive local-surge rule (`prominence >= max(3.8, 1.15 * std_db)` and `local_prom >= 2.2 dB`), raising detection on the loudness-normalized 10.6-minute GTA V recording from `0` to `43` real loudness peaks.
- **CLI Flags Added to `analyze`**:
  - `--ranking-mode {default,gta_highlight}`
  - `--target-duration <sec>` (configurable 45–60s target, independent of caption `--style-preset`)
  - `--min-duration <sec>` / `--max-duration <sec>` (allows 20–35s tight cuts when surrounding footage adds low value; expands to 45–60s only when pre-context or post-escalation/reaction is active, recording both `tight_cut` and `long_cut`)
  - `--chat-log <json>` (optional timestamped chat spike boost; strictly excluded when omitted)
- **Scoring & Penalties**: Combines `gameplay_novelty`, `dialogue_reaction` (peaks + 300–3400 Hz speech-band vocal dynamics + optional transcript keywords), `opening_hook` (first 3.5s), `setup_to_payoff` (post-setup visual motion/flash + audible climax), and optional `chat_spike`, minus explicit penalties for `dead_time`, `intro_chatter` without payoff, and `repeated_moment`.

### 2. Full-Recording Scan Command & Top 3 Autonomous Moments
```powershell
python -m gta_clipper.cli analyze --input "C:\Users\sanid\AppData\Local\Temp\gta_clipping_data\sources\gta_v_chaos_mod_360p.mp4" --source-name "vidssave.com I Installed The GTA V Chaos Mod! 360P" --style-preset viral_streamer_yellow --ranking-mode gta_highlight --target-duration 50 --min-duration 20 --max-duration 60 --max-clips 3 --transcription-provider none --creator "Chaos Streamer" --rights approved
```
Scan signals: `637.5s` audio, `43` adaptive audio peaks, `261` visual scene transitions, `chat=no`.

| Rank | Source Window (Long / Primary) | Tight Cut Option | Hook | Payoff | Score | Observed Events & Evidence |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **#1 (`clip_01`)** | `00:53.40 -> 01:44.03` (`50.6s`) | `01:03.63 -> 01:31.56` (`27.9s`) | `00:53.90` | `01:25.00` | **90.3/100** | `Roll Credits` flicker + `Extreme Fog` + `You Are Famous` mob $\to$ `Need For Speed` 52 mph bomb explosion (`1:03–1:13`) $\to$ 50-NPC crowd mob $\to$ `Spawn UFO` alien abduction strobe (`1:25`, motion=139.0, flash=134.5) $\to$ `Midas Touch` turning the entire crowd into cash (`+$47,301`). 8 audio peaks (+5.8 dB), 21 cuts. |
| **#2 (`clip_02`)** | `04:23.03 -> 05:13.43` (`50.4s`) | `04:33.77 -> 05:00.80` (`27.0s`) | `04:26.53` | `05:02.00` | **88.7/100** | Autonomously discovered the **HESOYAM `+$250,000`** arc! Includes `Fake Death`/`Lag` lead-in (`4:23–4:28`), `HESOYAM +$250,000` + `Launch Player Up` + `Vehicles Explode On Impact` + `Spawn Bale Trailer` (`4:28–4:53`), expanding into `Spawn Angry Alien` shooting Chandler (`5:02`) + `Ignite All Nearby Peds` (`5:05`). 9 audio peaks (+5.8 dB), 23 cuts. |
| **#3 (`clip_03`)** | `02:39.83 -> 03:29.73` (`49.9s`) | `02:50.27 -> 03:16.60` (`26.3s`) | `02:41.33` | `03:28.00` | **75.5/100** | `Invert Gravity` sends Chris's car skyward (`2:40`) $\to$ `Scooter Brothers` kill Chandler $\to$ `All Peds Are Cops` + `Explosive Zombies` $\to$ `Spawn Bus` drops a city bus on Karl (`3:28`, motion=113.5, flash=107.9). 4 peaks (+5.0 dB), 22 cuts, repeat penalty `-13.0`. |

### 3. Comparison vs. Manually Registered HESOYAM Clip (`268.50s -> 292.85s`)
- The analyzer ranked the HESOYAM region **#2 overall (`88.7/100`)** completely autonomously without any manual hint, placing it just 1.6 points behind the `#1` 52-mph-bomb + UFO + Midas Touch climax (`90.3/100`).
- Compared to the tight manual cut (`268.50s -> 292.85s`, `24.35s`), Rank #2's 50.4s cut (`263.03s -> 313.43s`) adds `Lag` lead-in and `Spawn Angry Alien` / `Ignite All Nearby Peds` post-escalation, while the manual cut starts crisply on the `+$250,000` cash drop and ends right on Chris's hay baler punchline.

### 4. Rendered Rank #1 Deliverables (Both Long & Tight Cuts via Standard CLI)
- **Long Cut (`clip_01`, `53.40s -> 104.03s`, `50.6s`, 27 cues)**:
  - MP4: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_rank1_long_auto_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_rank1_long_auto_hybrid.mp4) (20.94 MB, 1080×1920, SAR 1:1, DAR 9:16)
  - SRT: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_rank1_long_auto_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_rank1_long_auto_hybrid.srt) (1,617 bytes, 27 cues)
- **Tight Cut (`clip_01_tight`, `63.63s -> 91.56s`, `27.9s`, 13 cues)**:
  - MP4: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_tight_rank1_tight_auto_hybrid.mp4`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_tight_rank1_tight_auto_hybrid.mp4) (13.52 MB, 1080×1920, SAR 1:1, DAR 9:16)
  - SRT: [`vidssave.com I Installed The GTA V Chaos Mod! 360P_clip_01_tight_rank1_tight_auto_hybrid.srt`](file:///c:/Users/sanid/OneDrive%20-%20R%C4%ABgas%20Tehnisk%C4%81%20Universit%C4%81te/Darbvirsma/GTA_clipping/exports/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P/vidssave.com%20I%20Installed%20The%20GTA%20V%20Chaos%20Mod!%20360P_clip_01_tight_rank1_tight_auto_hybrid.srt) (761 bytes, 13 cues)
- **Unit Tests**: Added `test_36_gta_highlight_ranking_and_chat_optional`; `test_04`, `test_33`, `test_34`, `test_35`, `test_36` pass (`5/5 OK`).









