from __future__ import annotations

from dataclasses import dataclass, field

from domain.filesystem import PaneLocation


@dataclass(frozen=True)
class DragPayload:
    local_paths: list[str] = field(default_factory=list)
    remote_locations: list[PaneLocation] = field(default_factory=list)
    operation: str = "copy"
    ark_reference: tuple[str, str] | None = None

    @property
    def has_local_paths(self) -> bool:
        return bool(self.local_paths)

    @property
    def has_remote_locations(self) -> bool:
        return bool(self.remote_locations)

    @property
    def has_ark_reference(self) -> bool:
        return self.ark_reference is not None

    @property
    def is_empty(self) -> bool:
        return not (self.has_local_paths or self.has_remote_locations or self.has_ark_reference)


@dataclass(frozen=True)
class DragDropContext:
    payload: DragPayload
    target_dir: str
