"""Review experience: HTML contact sheet generator and editable JSON review manifests.
Displays speech captions, uncertainty flags, style presets, and thumbnail cues.
"""

from __future__ import annotations
import html
import json
from pathlib import Path
from typing import List, Dict, Any, Optional

from .candidates import CandidateClip
from .metadata import JobMetadata
from .style import StylePreset


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>GTA VI Clipping Review — {job_id}</title>
  <style>
    :root {{
      --bg: #0f111a;
      --card-bg: #1a1d2e;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --cyan: #06b6d4;
      --pink: #ec4899;
      --yellow: #eab308;
      --green: #10b981;
      --red: #ef4444;
      --border: #2e344e;
    }}
    body {{
      background-color: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 24px;
    }}
    .header {{
      border-bottom: 2px solid var(--border);
      padding-bottom: 16px;
      margin-bottom: 24px;
    }}
    .header h1 {{
      margin: 0 0 8px 0;
      color: var(--cyan);
      font-size: 26px;
      letter-spacing: -0.5px;
    }}
    .meta-box {{
      background: #141724;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      font-size: 13px;
      color: var(--muted);
      line-height: 1.5;
      margin-bottom: 24px;
    }}
    .meta-box strong {{
      color: var(--text);
    }}
    .alert-banner {{
      background: #451a03;
      border: 1px solid #b45309;
      color: #fef3c7;
      padding: 12px 16px;
      border-radius: 8px;
      margin-bottom: 20px;
      font-size: 13px;
      line-height: 1.5;
    }}
    .grid {{
      display: flex;
      flex-direction: column;
      gap: 24px;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
    }}
    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 14px;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      text-transform: uppercase;
    }}
    .badge-cat {{ background: #1e3a8a; color: #93c5fd; }}
    .badge-conf {{ background: #065f46; color: #6ee7b7; }}
    .badge-flag {{ background: #7f1d1d; color: #fca5a5; margin-left: 6px; }}
    .badge-warn {{ background: #78350f; color: #fde68a; margin-left: 6px; }}
    .badge-layout {{ background: #4c1d95; color: #d8b4fe; }}
    .badge-style {{ background: #0f766e; color: #99f6e4; margin-left: 6px; }}
    .card h2 {{
      margin: 0 0 6px 0;
      font-size: 19px;
      color: #fff;
    }}
    .time-info {{
      color: var(--yellow);
      font-weight: bold;
      font-size: 14px;
      margin-bottom: 12px;
    }}
    .thumbs-row {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 16px;
    }}
    .thumb-col {{
      background: #111422;
      border-radius: 8px;
      padding: 8px;
      text-align: center;
    }}
    .thumb-label {{
      font-size: 11px;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 6px;
      font-weight: bold;
    }}
    .thumb-img {{
      width: 100%;
      height: 180px;
      object-fit: cover;
      border-radius: 6px;
      background: #000;
      border: 1px solid #334155;
    }}
    .details-box {{
      background: #121526;
      border-radius: 8px;
      padding: 12px;
      font-size: 13px;
      line-height: 1.6;
    }}
    .speech-box {{
      background: #1e1b4b;
      border: 1px solid #4338ca;
      border-radius: 6px;
      padding: 10px 12px;
      margin-top: 10px;
      font-size: 13px;
      color: #e0e7ff;
    }}
    .hook-text {{
      color: var(--pink);
      font-weight: bold;
      font-size: 14px;
    }}
    .cue-info {{
      color: #38bdf8;
    }}
    .instructions {{
      background: #172554;
      border: 1px solid #1e40af;
      border-radius: 8px;
      padding: 14px 18px;
      margin-top: 32px;
      font-size: 13px;
      line-height: 1.5;
    }}
    .instructions code {{
      background: #0f172a;
      padding: 2px 6px;
      border-radius: 4px;
      color: #38bdf8;
      font-family: Consolas, monospace;
    }}
  </style>
</head>
<body>
  <div class="header">
    <h1>GTA VI Clipping MVP — Reference & Caption Review</h1>
    <div>Job ID: <code>{job_id}</code> &bull; Source: <strong>{source_file_name}</strong> &bull; Style: <strong>{style_name}</strong></div>
  </div>

  <div class="meta-box">
    <strong>Creator / Source:</strong> {source_creator} ({source_identifier}) &bull;
    <strong>Rights:</strong> {footage_rights} (Ref: {permission_reference})<br>
    <strong>Target Platforms:</strong> {intended_platforms} &bull;
    <strong>Known Limits:</strong> {known_limits}
  </div>

  {global_alerts_html}

  <div class="grid">
    {cards_html}
  </div>

  <div class="instructions">
    <strong>How to Review & Export:</strong><br>
    1. To adjust in/out timestamps, edit speech captions, change layout, edit hooks, or reject clips, open:
       <br><code>{review_json_path}</code><br>
    2. Once verified, execute the render command:<br>
       <code>python -m gta_clipper.cli render --job-dir "{job_dir}"</code>
  </div>
</body>
</html>
"""

CARD_TEMPLATE = """
  <div class="card" id="{clip_id}">
    <div class="card-top">
      <div>
        <span class="badge badge-cat">{category_name}</span>
        <span class="badge badge-layout">Layout: {proposed_layout}</span>
        {style_badge}
        {flag_badges}
      </div>
      <div>
        <span class="badge badge-conf">Confidence: {confidence_pct}%</span>
      </div>
    </div>
    <h2>{clip_id}: {title}</h2>
    <div class="time-info">
      Time: {start_time:.1f}s &rarr; {end_time:.1f}s (Duration: {duration:.1f}s &bull; Payoff at {payoff_time:.1f}s)
    </div>

    <div class="thumbs-row">
      <div class="thumb-col">
        <div class="thumb-label">Start / Hook Frame</div>
        <img class="thumb-img" src="{start_thumb_rel}" alt="Start Frame">
      </div>
      <div class="thumb-col">
        <div class="thumb-label">Payoff / Action Climax</div>
        <img class="thumb-img" src="{payoff_thumb_rel}" alt="Payoff Frame">
      </div>
      <div class="thumb-col">
        <div class="thumb-label">End / Resolution</div>
        <img class="thumb-img" src="{end_thumb_rel}" alt="End Frame">
      </div>
    </div>

    <div class="details-box">
      <div><strong>On-Screen Hook:</strong> <span class="hook-text">"{hook_text}"</span></div>
      <div><strong>Selection Cue:</strong> <span class="cue-info">{cue}</span></div>
      <div><strong>Evidence:</strong> {evidence_type} &mdash; <em>{evidence_detail}</em></div>
      <div><strong>Reason:</strong> {reason}</div>
      <div style="margin-top: 6px;"><strong>Posting Caption:</strong> <code>{posting_caption}</code></div>

      <div class="speech-box">
        <strong>Synchronized Subtitles:</strong><br>
        {speech_display}
      </div>

      {framing_display}
    </div>
  </div>
"""


def generate_review_artifacts(
    metadata: JobMetadata,
    candidates: List[CandidateClip],
    job_dir: Path,
    style_preset: Optional[StylePreset] = None,
) -> tuple[Path, Path]:
    """Generates editable review_sheet.json and contact_sheet.html."""
    job_dir.mkdir(parents=True, exist_ok=True)
    clips_dir = job_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    # 1. Main review_sheet.json
    review_data = {
        "job_id": metadata.job_id,
        "source_file": metadata.source_file,
        "source_hash": metadata.source_hash,
        "style_preset": style_preset.to_dict() if style_preset else None,
        "total_candidates": len(candidates),
        "clips": [c.to_dict() for c in candidates],
    }

    review_json_path = job_dir / "review_sheet.json"
    temp_json = job_dir / "review_sheet.json.tmp"
    with open(temp_json, "w", encoding="utf-8") as f:
        json.dump(review_data, f, indent=2, ensure_ascii=False)
    temp_json.replace(review_json_path)

    # Per-clip editable JSONs
    for c in candidates:
        clip_file = clips_dir / f"{c.id}.json"
        with open(clip_file, "w", encoding="utf-8") as f:
            json.dump(c.to_dict(), f, indent=2, ensure_ascii=False)

    contact_html_path = refresh_contact_sheet(metadata, candidates, job_dir, style_preset)
    return review_json_path, contact_html_path


def refresh_contact_sheet(
    metadata: JobMetadata,
    candidates: List[CandidateClip],
    job_dir: Path,
    style_preset: Optional[StylePreset] = None,
) -> Path:
    """Refresh the HTML display using an already-saved review sheet."""
    review_json_path = job_dir / "review_sheet.json"

    # Check for global caption alerts
    has_awaiting = any(c.awaiting_captions for c in candidates)
    global_alerts = []
    if has_awaiting:
        global_alerts.append(
            '<div class="alert-banner">'
            '<strong>[!] Attention: Some dialogue clips are AWAITING CAPTIONS.</strong><br>'
            'Whisper model is not yet installed or speech was unverified. '
            'Download Whisper model to <code>models/</code>, or supply an SRT transcript, or edit dialogue before rendering.'
            '</div>'
        )

    # 3. Build HTML Cards
    cards = []
    style_name = style_preset.name if style_preset else "Default"
    style_badge_html = f'<span class="badge badge-style">Style: {html.escape(style_name)}</span>' if style_preset else ""

    for c in candidates:
        flags = []
        if c.awaiting_captions:
            flags.append('<span class="badge badge-flag">AWAITING CAPTIONS</span>')
        if c.uncertain_speech:
            flags.append('<span class="badge badge-warn">CHECK SPEECH ACCURACY</span>')
        if c.is_visual_only:
            flags.append('<span class="badge badge-cat" style="background:#334155;color:#f1f5f9;">SPEECH-FREE CLIP</span>')
        if c.spoiler_flag:
            flags.append('<span class="badge badge-flag">SPOILER REVIEW</span>')
        if c.music_review_flag:
            flags.append('<span class="badge badge-flag">RADIO MUSIC CHECK</span>')

        start_rel = Path(c.preview_frames.get("start", "")).name
        payoff_rel = Path(c.preview_frames.get("payoff", "")).name
        end_rel = Path(c.preview_frames.get("end", "")).name

        # Speech display
        if c.speech_summary:
            speech_display = f'<em>"{html.escape(c.speech_summary)}"</em>'
        elif c.awaiting_captions:
            speech_display = '<span style="color:#f87171;">Awaiting transcription or manual caption entry.</span>'
        else:
            speech_display = '<span style="color:#94a3b8;">No spoken dialogue (visual stunt / ambient audio).</span>'

        # Framing display
        framing_display = ""
        if c.shot_framing:
            rows = []
            for s in c.shot_framing:
                s_mode = s.get("mode", "follow_crop")
                s_src = s.get("crop_source", "auto")
                s_reason = s.get("reason", "")
                badge_bg = "#2563eb" if s_src == "auto" else "#9333ea"
                mode_badge = f'<span style="background:{badge_bg};color:#fff;padding:2px 6px;border-radius:4px;font-size:11px;font-weight:bold;">{s_mode} ({s_src})</span>'
                rows.append(
                    f'<li style="margin-bottom:4px;"><strong>Shot {s.get("shot", 1)}</strong> ({s.get("start", 0.0):.1f}s &rarr; {s.get("end", 0.0):.1f}s): '
                    f'{mode_badge} &mdash; <em>{html.escape(s_reason)}</em></li>'
                )
            framing_display = (
                f'<div style="margin-top:10px;padding:8px 12px;background:#0f172a;border:1px solid #1e293b;border-radius:6px;font-size:12px;">'
                f'<div style="font-weight:bold;margin-bottom:6px;color:#94a3b8;">Shot Framing Breakdown:</div>'
                f'<ul style="margin:0;padding-left:18px;color:#cbd5e1;">{"".join(rows)}</ul>'
                f'</div>'
            )

        cards.append(CARD_TEMPLATE.format(
            clip_id=html.escape(c.id),
            category_name=html.escape(c.category_name),
            proposed_layout=html.escape(c.proposed_layout),
            style_badge=style_badge_html,
            flag_badges=" ".join(flags),
            confidence_pct=int(c.confidence * 100),
            title=html.escape(c.title),
            start_time=c.start_time,
            end_time=c.end_time,
            duration=c.duration,
            payoff_time=c.payoff_time,
            start_thumb_rel=f"thumbnails/{start_rel}" if start_rel else "",
            payoff_thumb_rel=f"thumbnails/{payoff_rel}" if payoff_rel else "",
            end_thumb_rel=f"thumbnails/{end_rel}" if end_rel else "",
            hook_text=html.escape(c.hook_text),
            cue=html.escape(c.cue),
            evidence_type=html.escape(c.evidence_type),
            evidence_detail=html.escape(c.evidence_detail),
            reason=html.escape(c.reason),
            posting_caption=html.escape(c.posting_caption),
            speech_display=speech_display,
            framing_display=framing_display,
        ))

    html_content = HTML_TEMPLATE.format(
        job_id=html.escape(metadata.job_id),
        source_file_name=html.escape(metadata.source_file_name),
        source_creator=html.escape(metadata.source_creator),
        source_identifier=html.escape(metadata.source_identifier),
        footage_rights=html.escape(metadata.footage_rights),
        permission_reference=html.escape(metadata.permission_reference),
        intended_platforms=html.escape(", ".join(metadata.intended_platforms)),
        known_limits=html.escape(metadata.known_limits),
        style_name=html.escape(style_name),
        global_alerts_html="\n".join(global_alerts),
        cards_html="\n".join(cards),
        review_json_path=review_json_path.as_posix(),
        job_dir=job_dir.as_posix(),
    )

    contact_html_path = job_dir / "contact_sheet.html"
    contact_html_path.write_text(html_content, encoding="utf-8")
    return contact_html_path
