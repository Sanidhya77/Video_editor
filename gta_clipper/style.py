"""Style preset management, reference extraction, and multi-reference composition.
Derives reusable, editable style presets from reference links, local files, or notes.
"""

from __future__ import annotations
import dataclasses
import json
from pathlib import Path
import re
from typing import Dict, Any, Optional, List

from .visual import probe_video, detect_scene_changes


COLOR_MAP = {
    "yellow": "&H0000FFFF",
    "bright_yellow": "&H0000FFFF",
    "white": "&H00FFFFFF",
    "cyan": "&H00FFFF00",
    "lime": "&H0000FF00",
    "green": "&H0000FF00",
    "red": "&H000000FF",
    "pink": "&H00CBC0FF",
    "orange": "&H0000A5FF",
    "black": "&H00000000",
}


@dataclasses.dataclass
class StylePreset:
    preset_id: str
    name: str
    source_reference: Optional[str] = None
    reference_notes: Optional[str] = None

    # Editing & Pacing
    typical_length: float = 22.0
    min_duration: float = 15.0
    max_duration: float = 35.0
    cut_pace: str = "rapid"  # "rapid" | "moderate" | "single_take"

    # Layout & Framing
    layout_mode: str = "center_crop"  # "center_crop" | "fit_background" | "pip" | "manual_crop"
    crop_x_offset_pct: float = 0.5
    pip_position: str = "top_right"
    zoom_factor: float = 1.0

    # Subtitle Typography & Positioning
    font_name: str = "Arial Black"
    font_size: int = 68
    primary_color: str = "&H0000FFFF"  # Default bold yellow
    secondary_color: str = "&H0000FFFF"
    outline_color: str = "&H00000000"  # Solid black
    outline_width: float = 4.5
    shadow_depth: float = 2.0
    alignment: int = 2  # Bottom-center
    margin_v: int = 380  # Safe zone above TikTok/Reels UI
    margin_h: int = 60
    highlight_mode: str = "phrase"  # "phrase" | "timed_word"
    max_lines: int = 2
    uppercase: bool = True

    # Hook Banner
    hook_style: str = "top_banner"  # "top_banner" | "center_card" | "none"
    hook_font_size: int = 72
    hook_color: str = "&H0000FFFF"
    hook_duration: float = 3.0

    # Visible Evidence vs Inference
    observed_traits: Dict[str, Any] = dataclasses.field(default_factory=dict)
    inferred_traits: Dict[str, Any] = dataclasses.field(default_factory=dict)
    unknown_traits: List[str] = dataclasses.field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StylePreset:
        return cls(**data)

    def save(self, dest_path: Path) -> Path:
        """Saves style preset to JSON."""
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
        return dest_path


def parse_style_from_notes(
    notes: str,
    preset_id: str = "custom_notes",
    name: str = "Custom Reference Preset",
    source_reference: Optional[str] = None,
) -> StylePreset:
    """Parses user-supplied style notes/descriptions to populate a StylePreset."""
    notes_lower = notes.lower()
    observed: Dict[str, Any] = {}
    inferred: Dict[str, Any] = {}
    unknown: List[str] = []

    # Typography color
    primary_color = "&H0000FFFF"  # Default yellow
    if "white" in notes_lower:
        primary_color = COLOR_MAP["white"]
        observed["primary_color"] = "White (#FFFFFF)"
    elif "yellow" in notes_lower:
        primary_color = COLOR_MAP["yellow"]
        observed["primary_color"] = "Yellow (#00FFFF in ASS)"
    elif "cyan" in notes_lower or "blue" in notes_lower:
        primary_color = COLOR_MAP["cyan"]
        observed["primary_color"] = "Cyan"
    elif "green" in notes_lower or "lime" in notes_lower:
        primary_color = COLOR_MAP["lime"]
        observed["primary_color"] = "Lime Green"
    else:
        inferred["primary_color"] = "Default high-contrast yellow"

    # Font name
    font_name = "Arial Black"
    if "montserrat" in notes_lower:
        font_name = "Montserrat"
        observed["font_name"] = "Montserrat"
    elif "impact" in notes_lower:
        font_name = "Impact"
        observed["font_name"] = "Impact"
    elif "arial" in notes_lower:
        font_name = "Arial Black"
        observed["font_name"] = "Arial Black"
    else:
        inferred["font_name"] = "Arial Black (Windows standard bold)"

    # Layout mode
    layout_mode = "center_crop"
    if "pip" in notes_lower or "facecam" in notes_lower or "webcam" in notes_lower:
        layout_mode = "pip"
        observed["layout_mode"] = "Picture-in-Picture (facecam + gameplay)"
    elif "fit" in notes_lower or "background" in notes_lower or "blur" in notes_lower:
        layout_mode = "fit_background"
        observed["layout_mode"] = "Fit with blurred background"
    elif "manual" in notes_lower or "offset" in notes_lower:
        layout_mode = "manual_crop"
        observed["layout_mode"] = "Manual crop"
    else:
        layout_mode = "center_crop"
        inferred["layout_mode"] = "Center 9:16 crop"

    # Pacing & typical length
    dur_match = re.search(r"(\d+)\s*(?:s|sec|seconds)", notes_lower)
    typical_length = 22.0
    if dur_match:
        val = float(dur_match.group(1))
        if 10.0 <= val <= 60.0:
            typical_length = val
            observed["typical_length"] = f"{typical_length}s"
    else:
        inferred["typical_length"] = "22.0s (Shorts sweet spot)"

    cut_pace = "rapid"
    if "single take" in notes_lower or "continuous" in notes_lower or "uncut" in notes_lower:
        cut_pace = "single_take"
        observed["cut_pace"] = "Single continuous take"
    elif "fast" in notes_lower or "rapid" in notes_lower or "quick cuts" in notes_lower:
        cut_pace = "rapid"
        observed["cut_pace"] = "Rapid cuts"
    else:
        inferred["cut_pace"] = "Rapid cuts"

    # Subtitle highlight mode
    highlight_mode = "phrase"
    if "word by word" in notes_lower or "timed word" in notes_lower or "karaoke" in notes_lower:
        highlight_mode = "timed_word"
        observed["highlight_mode"] = "Timed word-by-word highlights"
    else:
        highlight_mode = "phrase"
        inferred["highlight_mode"] = "Stable phrase captions (max 2 lines)"

    # Hook placement
    hook_style = "top_banner"
    if "no hook" in notes_lower:
        hook_style = "none"
        observed["hook_style"] = "None"
    elif "center hook" in notes_lower:
        hook_style = "center_card"
        observed["hook_style"] = "Center title card"
    else:
        hook_style = "top_banner"
        inferred["hook_style"] = "Top headline banner"

    # Record unknown traits not covered by notes
    unknown.extend([
        "exact_subtitle_outline_thickness_px",
        "exact_video_bitrate",
        "color_grading_lut"
    ])

    return StylePreset(
        preset_id=preset_id,
        name=name,
        source_reference=source_reference or "Manual Style Notes",
        reference_notes=notes,
        typical_length=typical_length,
        min_duration=max(15.0, typical_length - 5.0),
        max_duration=min(35.0, typical_length + 8.0),
        cut_pace=cut_pace,
        layout_mode=layout_mode,
        crop_x_offset_pct=0.5,
        font_name=font_name,
        font_size=68,
        primary_color=primary_color,
        secondary_color="&H0000FFFF",
        outline_color="&H00000000",
        outline_width=4.5,
        shadow_depth=2.0,
        alignment=2,
        margin_v=380,
        margin_h=60,
        highlight_mode=highlight_mode,
        max_lines=2,
        uppercase=True,
        hook_style=hook_style,
        hook_font_size=72,
        hook_color="&H0000FFFF",
        hook_duration=3.0,
        observed_traits=observed,
        inferred_traits=inferred,
        unknown_traits=unknown,
    )


def extract_style_from_local_media(
    video_path: Path,
    notes: Optional[str] = None,
    preset_id: Optional[str] = None,
    name: Optional[str] = None,
) -> StylePreset:
    """Inspects a local authorized reference MP4 to extract measurable editing parameters."""
    if not video_path.is_file():
        raise FileNotFoundError(f"Reference video file not found: {video_path}")

    # Base preset from notes if supplied
    base_notes = notes or f"Extracted from reference file: {video_path.name}"
    pid = preset_id or f"ref_{video_path.stem[:18]}"
    pname = name or f"Style from {video_path.name}"

    preset = parse_style_from_notes(base_notes, preset_id=pid, name=pname, source_reference=str(video_path))

    # Probe actual video properties
    info = probe_video(video_path)
    preset.typical_length = round(info.duration, 1)
    preset.min_duration = max(12.0, round(info.duration * 0.7, 1))
    preset.max_duration = min(35.0, round(info.duration * 1.2, 1))
    preset.observed_traits["actual_reference_duration"] = f"{info.duration:.1f}s"
    preset.observed_traits["reference_dimensions"] = f"{info.width}x{info.height}"
    preset.observed_traits["reference_fps"] = f"{info.fps:.2f}"

    # Analyze scene transitions for cut pace
    scene_cuts = detect_scene_changes(video_path, threshold=0.32)
    cut_count = len(scene_cuts)
    preset.observed_traits["detected_scene_cuts"] = cut_count

    if cut_count >= 4:
        preset.cut_pace = "rapid"
        preset.observed_traits["cut_pace"] = f"Rapid ({cut_count} cuts in {info.duration:.1f}s)"
    elif 1 <= cut_count < 4:
        preset.cut_pace = "moderate"
        preset.observed_traits["cut_pace"] = f"Moderate ({cut_count} cuts in {info.duration:.1f}s)"
    else:
        preset.cut_pace = "single_take"
        preset.observed_traits["cut_pace"] = "Single take / continuous sequence"

    return preset


def merge_style_presets(
    caption_preset: StylePreset,
    layout_pacing_preset: StylePreset,
    new_id: str = "merged_preset",
    new_name: str = "Merged Reference Style",
) -> StylePreset:
    """Merges two references: one controlling captions and the other controlling layout/pacing."""
    merged = StylePreset(
        preset_id=new_id,
        name=new_name,
        source_reference=f"Captions: {caption_preset.name} | Layout/Pacing: {layout_pacing_preset.name}",
        reference_notes=(
            f"Captions derived from [{caption_preset.name}]. "
            f"Pacing & Layout derived from [{layout_pacing_preset.name}]."
        ),
        # Pacing & Layout from layout_pacing_preset
        typical_length=layout_pacing_preset.typical_length,
        min_duration=layout_pacing_preset.min_duration,
        max_duration=layout_pacing_preset.max_duration,
        cut_pace=layout_pacing_preset.cut_pace,
        layout_mode=layout_pacing_preset.layout_mode,
        crop_x_offset_pct=layout_pacing_preset.crop_x_offset_pct,
        pip_position=layout_pacing_preset.pip_position,
        zoom_factor=layout_pacing_preset.zoom_factor,
        hook_style=layout_pacing_preset.hook_style,
        hook_duration=layout_pacing_preset.hook_duration,
        # Subtitle Typography from caption_preset
        font_name=caption_preset.font_name,
        font_size=caption_preset.font_size,
        primary_color=caption_preset.primary_color,
        secondary_color=caption_preset.secondary_color,
        outline_color=caption_preset.outline_color,
        outline_width=caption_preset.outline_width,
        shadow_depth=caption_preset.shadow_depth,
        alignment=caption_preset.alignment,
        margin_v=caption_preset.margin_v,
        margin_h=caption_preset.margin_h,
        highlight_mode=caption_preset.highlight_mode,
        max_lines=caption_preset.max_lines,
        uppercase=caption_preset.uppercase,
        hook_font_size=caption_preset.hook_font_size,
        hook_color=caption_preset.hook_color,
        # Merged observation tracking
        observed_traits={
            "captions_source": caption_preset.name,
            "captions_traits": caption_preset.observed_traits,
            "layout_source": layout_pacing_preset.name,
            "layout_traits": layout_pacing_preset.observed_traits,
        },
        inferred_traits={
            "caption_inferences": caption_preset.inferred_traits,
            "layout_inferences": layout_pacing_preset.inferred_traits,
        },
        unknown_traits=list(set(caption_preset.unknown_traits + layout_pacing_preset.unknown_traits)),
    )
    return merged
