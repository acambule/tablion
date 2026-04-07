from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable


@dataclass
class SelectionRestoreRequest:
    selected_paths: list[str] = field(default_factory=list)
    scroll_value: int = 0


class SelectionRestoreService:
    def __init__(self):
        self._pending = SelectionRestoreRequest()

    def remember(self, selected_paths: list[str] | None, scroll_value: int = 0) -> None:
        self._pending = SelectionRestoreRequest(
            selected_paths=list(selected_paths or []),
            scroll_value=max(0, int(scroll_value or 0)),
        )

    def remember_single_path(self, path: str) -> None:
        clean_path = str(path or "").strip()
        self._pending = SelectionRestoreRequest(
            selected_paths=[clean_path] if clean_path else [],
            scroll_value=self._pending.scroll_value,
        )

    def has_pending(self) -> bool:
        return bool(self._pending.selected_paths or self._pending.scroll_value)

    def consume(
        self,
        *,
        index_for_path: Callable[[str], object],
        select_index: Callable[[object], None],
        set_scroll_value: Callable[[int], None],
    ) -> None:
        pending = self._pending
        self._pending = SelectionRestoreRequest()

        if pending.selected_paths:
            first_path = pending.selected_paths[0]
            index = index_for_path(first_path)
            select_index(index)

        set_scroll_value(pending.scroll_value)
