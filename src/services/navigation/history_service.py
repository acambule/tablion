from __future__ import annotations

from domain.filesystem import PaneLocation

class HistoryService:
    def can_go_back(self, history: list[PaneLocation]) -> bool:
        return bool(history)

    def record_navigation(
        self,
        history: list[PaneLocation],
        current_location: PaneLocation | None,
        target_location: PaneLocation,
        push_history: bool,
    ) -> list[PaneLocation]:
        if not push_history:
            return list(history)
        if current_location is None:
            return list(history)
        if target_location == current_location:
            return list(history)
        return [*history, current_location]

    def pop_previous(self, history: list[PaneLocation]) -> tuple[list[PaneLocation], PaneLocation | None]:
        if not history:
            return [], None
        next_history = list(history)
        previous_location = next_history.pop()
        return next_history, previous_location
