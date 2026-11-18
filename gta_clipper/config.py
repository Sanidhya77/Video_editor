"""Configuration and directory management for GTA VI Clipping MVP.
Ensures large media files, models, and caches reside OUTSIDE OneDrive.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Dict, Optional, Tuple


DEFAULT_GAME_ID = "gtavi"


class StorageConfig:
    """Manages local storage paths outside OneDrive."""

    def __init__(self, custom_data_dir: Optional[str | Path] = None):
        self.root = self._resolve_data_dir(custom_data_dir)
        self.models_dir = self.root / "models"
        self.cache_dir = self.root / "cache"
        self.audio_cache_dir = self.cache_dir / "audio"
        self.transcript_cache_dir = self.cache_dir / "transcripts"
        self.jobs_dir = self.root / "jobs"
        self.exports_dir = self.root / "exports"
        self._ensure_directories()

    def _resolve_data_dir(self, custom_dir: Optional[str | Path]) -> Path:
        # 1. Custom CLI override
        if custom_dir:
            p = Path(custom_dir).resolve()
            return p

        # 2. Environment variable override
        env_dir = os.environ.get("GTA_CLIPPING_DATA_DIR")
        if env_dir:
            return Path(env_dir).resolve()

        # 3. Default Windows local appdata (outside OneDrive)
        candidates = []
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            candidates.append(Path(local_app_data) / "gta_clipping")
        candidates.append(Path.home() / ".gta_clipping")
        candidates.append(Path(tempfile.gettempdir()) / "gta_clipping_data")

        for candidate in candidates:
            try:
                candidate.mkdir(parents=True, exist_ok=True)
                test_file = candidate / ".write_test"
                test_file.write_text("ok", encoding="utf-8")
                test_file.unlink()
                return candidate.resolve()
            except (PermissionError, OSError):
                continue

        # Fallback to temp dir if all else fails
        fallback = Path(tempfile.gettempdir()) / "gta_clipping_data"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback.resolve()

    def _ensure_directories(self) -> None:
        for d in [
            self.root,
            self.models_dir,
            self.cache_dir,
            self.audio_cache_dir,
            self.transcript_cache_dir,
            self.jobs_dir,
            self.exports_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)

    def is_outside_onedrive(self) -> bool:
        """Returns True if the data directory is not in a OneDrive folder."""
        path_str = str(self.root).lower()
        return "onedrive" not in path_str

    def get_job_dir(self, job_id: str) -> Path:
        job_path = self.jobs_dir / job_id
        job_path.mkdir(parents=True, exist_ok=True)
        (job_path / "thumbnails").mkdir(parents=True, exist_ok=True)
        return job_path

    def get_export_dir(self, job_id: str) -> Path:
        export_path = self.exports_dir / job_id
        export_path.mkdir(parents=True, exist_ok=True)
        return export_path


def sanitize_windows_filename(name: str) -> str:
    r"""Sanitizes a string for use as a Windows file or folder name.
    Strips invalid characters (< > : " / \ | ? *) and trailing dots/spaces.
    """
    clean = re.sub(r'[<>:"/\\|?*]', '_', name).strip()
    clean = clean.rstrip(". ")
    return clean if clean else "untitled"


def resolve_export_paths(
    metadata: Dict[str, Any] | Any,
    clip_id: str,
    export_outside_onedrive: bool = False,
    custom_export_dir: Optional[Path] = None,
    storage: Optional[StorageConfig] = None,
    repo_root: Optional[Path] = None,
    suffix: Optional[str] = None,
) -> Tuple[Path, str, str]:
    """Resolves export directory and filenames for a finished clip.
    Returns (export_dir, mp4_filename, srt_filename).

    Default location: GTA_clipping/exports/<original-source-video-name>/
    File names: <original-source-video-name>_<clip_id>[_<suffix>].mp4 and .srt

    If two different sources share the same name, distinguishes them by appending source_hash[:8].
    """
    root = repo_root or Path(__file__).resolve().parent.parent
    st = storage or StorageConfig()

    meta_dict = metadata.to_dict() if hasattr(metadata, "to_dict") else metadata
    source_name = (
        meta_dict.get("original_source_name")
        or (Path(meta_dict.get("original_source_file")).stem if meta_dict.get("original_source_file") else None)
        or (Path(meta_dict.get("source_file_name")).stem if meta_dict.get("source_file_name") else None)
        or meta_dict.get("source_identifier")
        or Path(meta_dict.get("source_file", "source")).stem
    )
    if source_name.lower().endswith((".mp4", ".mkv", ".mov", ".avi", ".webm")):
        source_name = Path(source_name).stem

    sanitized_name = sanitize_windows_filename(source_name)
    source_hash = meta_dict.get("source_hash", "")[:8]

    if custom_export_dir:
        dest_dir = Path(custom_export_dir).resolve()
    elif export_outside_onedrive:
        dest_dir = st.exports_dir / sanitized_name
    else:
        dest_dir = root / "exports" / sanitized_name

    # Collision check: if folder exists with manifest from a different source hash
    manifest_file = dest_dir / "job_manifest.json"
    if dest_dir.exists() and manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                existing_manifest = json.load(f)
                existing_hash = existing_manifest.get("source_hash", "")[:8]
                if existing_hash and source_hash and existing_hash != source_hash:
                    sanitized_name = f"{sanitized_name}_{source_hash}"
                    if not custom_export_dir:
                        if export_outside_onedrive:
                            dest_dir = st.exports_dir / sanitized_name
                        else:
                            dest_dir = root / "exports" / sanitized_name
        except Exception:
            pass

    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix_part = f"_{suffix}" if suffix else ""
    mp4_name = f"{sanitized_name}_{clip_id}{suffix_part}.mp4"
    srt_name = f"{sanitized_name}_{clip_id}{suffix_part}.srt"
    return dest_dir, mp4_name, srt_name


def load_game_config(
    game_id: str = DEFAULT_GAME_ID,
    config_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Loads game settings and presets from config/games.json."""
    if not config_path:
        # Default to repo config/games.json
        base_dir = Path(__file__).resolve().parent.parent
        config_path = base_dir / "config" / "games.json"

    if config_path.is_file():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                games = data.get("games", {})
                if game_id in games:
                    return games[game_id]
                elif data.get("default_game") in games:
                    return games[data["default_game"]]
        except Exception:
            pass

    # Built-in fallback preset for GTA VI
    return {
        "id": "gtavi",
        "display_name": "Grand Theft Auto VI",
        "genre": "Open World / Action-Adventure",
        "developer": "Rockstar Games",
        "target_resolution": {"width": 1080, "height": 1920, "aspect_ratio": "9:16"},
        "safe_zones": {"top_margin_px": 180, "bottom_margin_px": 340, "horizontal_margin_px": 60},
        "default_duration_range": {"min_seconds": 15.0, "max_seconds": 35.0, "default_target_seconds": 22.0},
        "categories": [
            {
                "id": "unexpected_gameplay_stunt",
                "name": "Unexpected Gameplay / Stunt",
                "description": "High-speed driving, vehicle flips, near misses, physics anomalies, sudden explosions, or accidental crashes.",
                "target_duration": 22.0,
                "pre_roll": 3.5,
                "post_roll": 3.0,
                "default_layout": "center_crop",
                "suggested_hooks": ["Wait for the ending...", "How did he survive this?!", "Watch till the end 💀"]
            },
            {
                "id": "npc_or_mechanic_experiment",
                "name": "NPC / Game-Mechanic Experiment",
                "description": "Testing AI reactions, police response escalation, physics limits, and crowd behavior.",
                "target_duration": 26.0,
                "pre_roll": 2.5,
                "post_roll": 2.5,
                "default_layout": "center_crop",
                "suggested_hooks": ["Testing GTA 6 NPC logic...", "What happens if you do this in GTA VI?"]
            },
            {
                "id": "creator_reaction_with_context",
                "name": "Creator Reaction with Context",
                "description": "Streamer reaction, shout, laugh, or punchline contextually paired with gameplay setup.",
                "target_duration": 20.0,
                "pre_roll": 4.5,
                "post_roll": 2.5,
                "default_layout": "pip",
                "suggested_hooks": ["His reaction says it all 😭", "Bro was NOT ready for that"]
            }
        ],
        "review_flags": {
            "spoiler": "Story mission cutscenes or ending revelations",
            "music_review": "Licensed in-game radio track playing in background",
            "leak_alert": "Pre-release or leaked development build footage",
            "audio_flag": "Heavy clipping or potential copyrighted sound effect"
        }
    }
