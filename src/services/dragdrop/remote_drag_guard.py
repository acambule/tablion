from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint

from domain.filesystem import PaneLocation


@dataclass
class RemoteDragState:
    start_pos: QPoint | None = None
    source_view: object | None = None
    locations: list[PaneLocation] = field(default_factory=list)
    press_armed: bool = False


class RemoteDragGuard:
    def __init__(self):
        self._state = RemoteDragState()

    def arm(self, *, source_view, start_pos: QPoint, locations: list[PaneLocation]) -> None:
        self._state = RemoteDragState(
            start_pos=start_pos,
            source_view=source_view,
            locations=list(locations),
            press_armed=True,
        )

    def should_start_drag(self, *, source_view, current_pos: QPoint, drag_distance: int) -> bool:
        if self._state.start_pos is None or self._state.source_view is not source_view:
            return False
        return (current_pos - self._state.start_pos).manhattanLength() >= drag_distance

    def release_was_guarded(self) -> bool:
        return self._state.press_armed

    def snapshot_locations(self) -> list[PaneLocation]:
        return list(self._state.locations)

    def clear(self) -> None:
        self._state = RemoteDragState()
