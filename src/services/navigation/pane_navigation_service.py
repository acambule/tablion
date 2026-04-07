from __future__ import annotations

from domain.filesystem.backend import FileSystemBackend
from domain.filesystem.location import PaneLocation


class PaneNavigationService:
    def __init__(self, backend: FileSystemBackend):
        self._backend = backend

    def resolve_directory_location(self, raw_path: str) -> PaneLocation | None:
        return self._backend.create_location(raw_path)

    def get_parent_location(self, location: PaneLocation) -> PaneLocation | None:
        return self._backend.get_parent_location(location)

    def display_name_for_location(self, location: PaneLocation) -> str:
        return self._backend.get_display_name(location)
