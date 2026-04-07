from __future__ import annotations


class HistoryService:
    def can_go_back(self, history: list[str]) -> bool:
        return bool(history)

    def record_navigation(self, history: list[str], current_path: str, target_path: str, push_history: bool) -> list[str]:
        if not push_history:
            return list(history)
        if not current_path or target_path == current_path:
            return list(history)
        return [*history, current_path]

    def pop_previous(self, history: list[str]) -> tuple[list[str], str | None]:
        if not history:
            return [], None
        next_history = list(history)
        previous_path = next_history.pop()
        return next_history, previous_path
