from __future__ import annotations

from abc import ABC, abstractmethod

from domain.filesystem.entry import FileSystemEntry
from domain.filesystem.location import PaneLocation


class FileSystemBackend(ABC):
    @property
    @abstractmethod
    def kind(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def normalize_directory_path(self, raw_path: str) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def create_location(self, raw_path: str) -> PaneLocation | None:
        raise NotImplementedError

    @abstractmethod
    def get_parent_location(self, location: PaneLocation) -> PaneLocation | None:
        raise NotImplementedError

    @abstractmethod
    def get_display_name(self, location: PaneLocation) -> str:
        raise NotImplementedError

    @abstractmethod
    def describe_location(self, location: PaneLocation) -> FileSystemEntry | None:
        raise NotImplementedError
