# Antigravity prompt — Reference Reel to captioned stream clips

Paste everything below into Antigravity with the shared GTA_clipping folder open.

---

Extend the existing GTA clipping MVP. I want to supply **one or two example Reels or Shorts and one raw gaming stream recording**, then get **up to three vertical draft clips** that use a similar editing style and display what the streamer actually says as on-screen subtitles. Prioritize this workflow before campaign tracking or publishing integrations.

## 1. Use the existing project

Read AGENTS.md, CURRENT_RUN.md, README.md and the existing analyze, preview, render and subtitle code. Reuse the existing Python CLI, FFmpeg, local review and data-directory handling. Keep footage, model files, thumbnails, caches and exports outside OneDrive. Keep the current CLI usable and document one simple command or sequence for this workflow.

## 2. Accept a reference link, file or notes

- The default workflow is manual selection. Let me supply a public Instagram Reel or YouTube Short URL, a local reference MP4 I'm allowed to use for analysis, or screenshots and a short style note. A reference URL is usable as visual evidence only if the actual video can be inspected. A search result, title or description can identify a reference but cannot establish what its captions or editing look like.
- Make discovery optional. If Northbridge search is available, use it to suggest up to five public links for a query like "GTA V funny streamer reaction Shorts" or "GTA Online NPC experiment Reel". Show the title, URL and why it might be relevant, then let me pick. Keep the core workflow usable if search is unavailable or a platform blocks access. If playback is unavailable, use my notes or screenshots for the visible style; ask for a playable reference or timing notes if pacing matters.
- Derive a reusable, editable style preset. Capture the opening, typical length, cut pace, gameplay/facecam layout, crop, zoom, subtitle position, size, color, outline, phrase versus timed word highlights, and optional hook placement. Capture only traits you can see or that I explicitly describe. List inferred or unknown values separately. If I give two references, let me choose which one controls captions and which one controls pacing or layout. Use reference media only for style analysis. Every export uses the new recording, its own dialogue and approved assets.
- Use FFmpeg and ASS for the initial style presets. Prefer accurate phrase subtitles and simple stable effects. Add timed-word highlighting only when the transcription provides reliable word boundaries. If a reference effect is unavailable, show the closest supported treatment in the preview.

## 3. Find moments and make the streamer's speech readable

- From my authorized raw MP4 or MKV, suggest distinct moments with an opening, enough context to follow and a payoff. Use the existing speech, visual and audio-energy signals plus optional manually supplied timestamps. Treat motion and loudness as candidate cues. Let me override the in/out times and crop. Keep the important game action visible in the portrait frame. Use the actual facecam region or separate track if present.
- **Required for any clip containing streamer speech: transcribe the streamer's dialogue and burn the readable, synchronized subtitles into the MP4.** Also export an editable SRT. The opening hook text and the social post caption are separate fields. Use the streamer's mic track when available, with an explicit track selector. If the stream has only mixed audio, let me fix speaker attribution and transcript errors in the review step. Flag uncertain sections with game dialogue, music, overlapping voices, slang or low confidence so I can correct the wording. Keep the streamer's original language by default, with an optional language hint for transcription.
- Verify that a local Whisper backend and a real model work on this Windows machine. The existing runner uses whisper-cli; check whether the configured executable and model can actually be found. Offer an optional existing SRT or supported timestamped transcript as a fallback. If speech transcription fails or the model is missing, show the exact setup or import step and keep the candidate awaiting captions. Never export a dialogue clip as finished with empty subtitles or invented dialogue. A genuine speech-free clip can be reviewed separately.
- Reuse the review page so I can see the cut, caption timing/style and framing. Let me correct lines, approve a draft or reject it. Keep captions ideally within one or two readable lines, inside the visible area and clear of important gameplay and platform controls. Recompute caption timings if a clip is trimmed. Render approved drafts as 1080×1920 MP4 with burned subtitles and sidecar SRT.

## 4. Prove it works

- Run the existing tests. Then exercise the normal workflow with a reference style and a short sample that contains real speech if available. If no creator recording is present, use an authorized sample or synthetic speech for the smoke test and label it. Verify from the rendered video that the subtitles are visible, articulate the correct words, and appear at the right time. Use ffprobe for output dimensions. Check that a preset can be reused and that changing the timing or style produces the updated render.
- Test a missing Whisper model, an inaccessible reference URL with manual notes, and a visual-only moment. If a sample has separate speech and game audio tracks, verify the mic selection. Log results, limitations and the exact commands in CURRENT_RUN.md. Provide the file paths to the review page, reusable preset, MP4 and SRT. Report whether the speech test used actual gameplay, another speech sample or synthetic speech. Keep publishing and campaign submission outside this task.

Start by making **one complete captioned example** from the existing workflow. Then complete the reference preset and optional discovery path. If I haven't supplied a reference or stream yet, demonstrate with a clearly labeled fixture and tell me exactly where to add my files.
