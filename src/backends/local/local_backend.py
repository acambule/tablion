from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDir

from domain.filesystem.backend import FileSystemBackend
from domain.filesystem.entry import FileSystemEntry
from domain.filesystem.location import PaneLocation


class LocalFileSystemBackend(FileSystemBackend):
    @property
    def kind(self) -> str:
        return "local"

    def normalize_directory_path(self, raw_path: str) -> str | None:
        candidate = QDir.cleanPath(str(raw_path or "").strip())
        if not candidate or not QDir(candidate).exists():
            return None
        return candidate

    def create_location(self, raw_path: str) -> PaneLocation | None:
        normalized = self.normalize_directory_path(raw_path)
        if not normalized:
            return None
        return PaneLocation(kind="local", path=normalized)

    def get_parent_location(self, location: PaneLocation) -> PaneLocation | None:
        if not location.is_local:
            return None

        current = QDir.cleanPath(location.path)
        parent = QDir.cleanPath(str(Path(current).parent))
        if not parent or parent == current:
            return None
        return self.create_location(parent)

    def get_display_name(self, location: PaneLocation) -> str:
        clean_path = QDir.cleanPath(location.path)
        return Path(clean_path).name or clean_path

    def describe_location(self, location: PaneLocation) -> FileSystemEntry | None:
        if not location.is_local:
            return None

        path = Path(location.path)
        if not path.exists():
            return None

        stat_result = path.stat()
        modified_at = datetime.fromtimestamp(stat_result.st_mtime)
        return FileSystemEntry(
            name=path.name or str(path),
            location=location,
            is_dir=path.is_dir(),
            size=None if path.is_dir() else stat_result.st_size,
            modified_at=modified_at,
            mime_type=None,
        )
