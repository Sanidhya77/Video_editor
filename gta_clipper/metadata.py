"""Job metadata and rights management.
Tracks streamer attribution, platform targeting, permissions, and rights limits.
"""

from __future__ import annotations
import dataclasses
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import List, Optional, Dict, Any


SUPPORTED_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi"}


@dataclasses.dataclass
class JobMetadata:
    job_id: str
    source_file: str
    source_file_name: str
    source_file_size_bytes: int
    source_hash: str
    game_id: str
    source_creator: str
    source_identifier: str
    footage_rights: str  # "owned" | "creator_supplied" | "approved" | "fair_use_review"
    permission_reference: str
    intended_platforms: List[str]
    intended_accounts: List[str]
    known_limits: str
    created_at: str
    notes: Optional[str] = None
    original_source_name: Optional[str] = None
    original_source_file: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> JobMetadata:
        fields = {f.name for f in dataclasses.fields(cls)}
        clean_data = {k: v for k, v in data.items() if k in fields}
        return cls(**clean_data)


def compute_file_fingerprint(path: Path) -> str:
    """Computes a stable hash based on file size and head/tail chunks."""
    if not path.is_file():
        raise FileNotFoundError(f"Source file not found: {path}")

    size = path.stat().st_size
    hasher = hashlib.sha256()
    hasher.update(str(size).encode("utf-8"))

    with open(path, "rb") as f:
        # Read first 128KB
        head = f.read(128 * 1024)
        hasher.update(head)
        # Read last 128KB if large enough
        if size > 256 * 1024:
            f.seek(-128 * 1024, 2)
            tail = f.read(128 * 1024)
            hasher.update(tail)

    return hasher.hexdigest()[:16]


def create_job_metadata(
    source_path: Path | str,
    source_creator: str = "Unknown Creator",
    source_identifier: str = "Local Ingest",
    footage_rights: str = "creator_supplied",
    permission_reference: str = "Pending Review",
    intended_platforms: Optional[List[str]] = None,
    intended_accounts: Optional[List[str]] = None,
    known_limits: str = "No story spoilers; check radio music rights",
    game_id: str = "gtavi",
    notes: Optional[str] = None,
    original_source_name: Optional[str] = None,
    original_source_file: Optional[str] = None,
) -> JobMetadata:
    """Validates input media and creates a JobMetadata instance."""
    path = Path(source_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Input media file does not exist: {path}")

    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported video format: {ext}. Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    file_hash = compute_file_fingerprint(path)
    # Clean stem for stable readable ID
    clean_stem = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in path.stem)[:24]
    job_id = f"job_{clean_stem}_{file_hash[:8]}"

    if intended_platforms is None:
        intended_platforms = ["tiktok", "instagram_reels", "youtube_shorts"]
    if intended_accounts is None:
        intended_accounts = ["@main_shorts"]

    return JobMetadata(
        job_id=job_id,
        source_file=str(path),
        source_file_name=path.name,
        source_file_size_bytes=path.stat().st_size,
        source_hash=file_hash,
        game_id=game_id,
        source_creator=source_creator,
        source_identifier=source_identifier,
        footage_rights=footage_rights,
        permission_reference=permission_reference,
        intended_platforms=intended_platforms,
        intended_accounts=intended_accounts,
        known_limits=known_limits,
        created_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
        original_source_name=original_source_name or path.stem,
        original_source_file=original_source_file or str(path),
    )


def save_job_metadata(job: JobMetadata, dest_dir: Path) -> Path:
    """Saves JobMetadata as JSON atomically."""
    dest_file = dest_dir / "job_metadata.json"
    temp_file = dest_dir / "job_metadata.json.tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(job.to_dict(), f, indent=2, ensure_ascii=False)
    temp_file.replace(dest_file)
    return dest_file


def load_job_metadata(job_dir: Path) -> JobMetadata:
    """Loads JobMetadata from job directory."""
    meta_file = job_dir / "job_metadata.json"
    if not meta_file.is_file():
        raise FileNotFoundError(f"job_metadata.json not found in {job_dir}")
    with open(meta_file, "r", encoding="utf-8") as f:
        return JobMetadata.from_dict(json.load(f))
