# Antigravity prompt — GTA VI clipping MVP

Copy the task below into Antigravity with the shared `GTA_clipping` folder open.

## Task

Build and verify a Windows-first local tool for making Shorts and Reels from one long gaming recording. GTA VI is the first use case. Keep game-specific categories in a configuration file so this tool can work with other games later. The person operating it should be able to point it at a creator-supplied file, review suggested clips, tweak the timing and layout, and export the clips they select.

### 1. Work in the shared folder

- Inspect the root, check for AGENTS.md and current changes, and preserve anything already present. Record implementation progress, current commands, what was tested, and open items in `CURRENT_RUN.md` so Codex can review the same folder. Keep source recordings, Whisper models, credentials, caches and exports outside OneDrive by default, in a configurable local data directory.
- Verify the environment before installing anything. On 17 November 2026 the folder had no visible project files or Git repository. Python 3.13.9, FFmpeg, ffprobe and Node were on PATH. `whisper-cli` and `yt-dlp` were not found on PATH. Check the installed FFmpeg build for the required encoders and subtitle filter. Document any additional installation with official sources and a pinned version.
- Implement a small Python CLI with `doctor`, `analyze` and `render` commands. Use FFmpeg/ffprobe and whisper.cpp as external commands. Prefer standard-library Python for orchestration. Use a local HTML contact sheet or simple local preview with editable per-clip JSON for the first review experience. No hosted service or paid API needs to be configured to run the core pipeline.

### 2. Import and analyze

- Accept a local MP4 or MKV. Ask the operator to record source creator, source identifier or URL, and whether the footage is owned, supplied by a creator, or otherwise approved for use. Include intended account/platforms, permission reference and known limits in the job metadata. Keep production use tied to the relevant streamer, game and music rights. Prefer a creator-supplied original file, OBS recording or platform-provided export. Treat optional URL ingest as a later adapter for sources whose download is permitted.
- Extract mono 16 kHz PCM for transcription. Use whisper.cpp locally and cache timestamped segments. Use timed tokens or words only if the selected tool build yields usable timing. Fall back to phrase captions if timings are unreliable. If speech is missing, still generate visual candidates.
- Produce candidates from two independent signals. **Speech** can use transcript boundaries, reactions and changes in audio energy. **Visual** can use scene, motion and audio cues plus manually provided markers. Treat scene changes as prompts to inspect frames. They do not establish that a stunt or NPC interaction happened. Show frame previews for visual candidates. Leave room for an optional second pass using sampled frames and transcript if manual review shows it would help. Keep video and transcripts local by default.
- Rank candidates on an immediate hook, clear payoff, enough context to stand alone, compatibility with a vertical crop and confidence in the evidence. Include the cue, reason, confidence, source start/end times, proposed layout and any spoiler or music-review flags. Deduplicate overlaps while retaining different categories. Use clear evidence, such as a timestamped quotation, a frame or a manual marker, for each suggestion. Allow 3–5 candidates when supported and fewer when the footage yields less.
- Start with three content presets: **unexpected gameplay/stunt**, **NPC or game-mechanic experiment**, and **creator reaction with context**. Use about 15–35 seconds as an initial editing range. Expose duration and pre/post-roll so the editor can keep the full setup and payoff. Keep one simple research CSV template with platform, URL, creator, date, duration, visible metrics and observation date, opening seconds, on-screen hook, caption style, layout, payoff time, original commentary and spoiler flag. Record missing metrics as unavailable.

### 3. Review and render

- Show source timestamps and frame previews. Let the editor change in/out points, speech text, hook, spoiler flag and layout. Provide centered or manual crop and a fit-with-background option for wide gameplay. Use optional picture-in-picture only when a facecam is present and the crop preserves important game information. Give the operator a way to reject each clip and override the crop when the gameplay target or UI is at an edge.
- Export a clean 1080×1920 H.264/AAC MP4 with a high-contrast caption style and generous margins. Generate ASS for burned subtitles and an editable SRT where speech exists. Work with sentence fragments of at most two lines as the default. Verify start/end timing and spelling before final render. Include per-clip proposed title and description, source credit, and a plain-text posting caption. Use the gameplay sound where appropriate, with controls for muting audio tracks if separate audio is available. Flag music baked into a mixed track for review. Flag leaks, isolated cutscenes, major spoilers and questionable audio for editor review before public release.
- Use an output manifest and stable IDs per job and clip. Cache analysis by input and settings, handle paths with spaces and non-ASCII characters, and write final files atomically. Re-running should reuse valid results and avoid duplicate exports. Fail with an actionable error if a tool/model is missing, a selected range is invalid or a render fails.
- Use FFmpeg for the initial rendering. Try HyperFrames in a later rendering experiment if custom animations or branding prove worth maintaining. Keep timing and layout data independent of the renderer.

### 4. Verify and hand off

- Create a synthetic test source with a visual event and no dialogue. Run a second smoke test with a short owned or authorized source containing speech if available. If no real recording is present, use synthetic speech to exercise transcription and state what still needs real-footage validation.
- Exercise the normal CLI entry points. Confirm a visual-only clip can be proposed. Use ffprobe to verify 1080×1920, codec, duration and audio when present. Visually inspect the opening frame, caption legibility and the payoff. Try an input path with spaces and non-ASCII characters, a second run of the same job, and an invalid time range. Confirm the configurable data directory contains the large outputs and that the review files show why each clip was selected.
- Provide the exact commands you ran, a short README with setup and usage, versions detected, output locations and measured runtime. An actual source stream and a short reference file can be supplied separately. Do not claim detection accuracy, throughput, virality, or publishing support without testing it.
- Stop this build pass at reviewed and exportable clips. Plan publishing as a follow-up capability: first native/manual posting, then an opt-in YouTube OAuth upload that explicitly sets private visibility and stores the upload receipt per clip/account. Follow with Meta's professional-account Reel publishing flow if needed. Keep TikTok manual for this personal utility. No account login, account linking, public upload or posting during the MVP.

## References for the build

- [FFmpeg](https://github.com/FFmpeg/FFmpeg), [whisper.cpp](https://github.com/ggml-org/whisper.cpp), [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [HyperFrames](https://github.com/heygen-com/hyperframes)
- [SupoClip](https://github.com/FujiwaraChoki/supoclip) and [AutoClip](https://github.com/zhouxiaoka/autoclip_mvp) for design references
- [Rockstar footage policy](https://support.rockstargames.com/articles/7bNaeoMFTV0iUDGhStTXvz/policy-on-posting-copyrighted-rockstar-games-material), [YouTube terms](https://www.youtube.com/t/terms) and [YouTube channel monetization policy](https://support.google.com/youtube/answer/1311392)
- [YouTube upload API](https://developers.google.com/youtube/data/reference/rest/v3/videos/insert), [Instagram Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) and [TikTok Direct Post guidelines](https://developers.tiktok.com/doc/content-sharing-guidelines/)

Begin by inspecting the folder and implementing the local import-to-export path. If any dependency blocks the speech test, finish and demonstrate the visual-only path and document how to enable speech.
