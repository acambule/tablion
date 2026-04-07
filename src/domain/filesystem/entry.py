from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from domain.filesystem.location import PaneLocation


@dataclass(frozen=True)
class FileSystemEntry:
    name: str
    location: PaneLocation
    is_dir: bool
    size: int | None = None
    modified_at: datetime | None = None
    mime_type: str | None = None
