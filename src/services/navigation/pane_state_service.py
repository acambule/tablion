from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir

from models.pane_tab_state import TabState


class PaneStateService:
    def clone_states(self, states: list[TabState]) -> list[TabState]:
        return [self.clone_state(state) for state in states]

    def clone_state(self, state: TabState) -> TabState:
        return TabState(
            title=state.title,
            path=state.path,
            pinned=state.pinned,
            view_mode=state.view_mode,
            icon_zoom_percent=int(getattr(state, "icon_zoom_percent", 100)),
            history=list(state.history),
            scroll_value=max(0, int(getattr(state, "scroll_value", 0) or 0)),
            selected_paths=list(state.selected_paths),
        )

    def capture_state(
        self,
        state: TabState,
        *,
        current_path: str,
        view_mode: str,
        icon_zoom_percent: int,
        selected_paths: list[str],
        scroll_value: int,
    ) -> None:
        state.path = QDir.cleanPath(current_path)
        state.view_mode = view_mode
        state.icon_zoom_percent = max(50, min(300, int(icon_zoom_percent)))
        state.scroll_value = max(0, int(scroll_value or 0))
        state.selected_paths = list(selected_paths)

    def serialize_states(self, states: list[TabState]) -> list[dict]:
        return [self.serialize_state(state) for state in states]

    def serialize_state(self, state: TabState) -> dict:
        return {
            "title": state.title,
            "path": state.path,
            "pinned": state.pinned,
            "view_mode": state.view_mode,
            "icon_zoom_percent": state.icon_zoom_percent,
            "history": list(state.history),
            "scroll_value": state.scroll_value,
            "selected_paths": list(state.selected_paths),
        }

    def deserialize_states(self, raw_tabs, default_path: str) -> list[TabState]:
        if not isinstance(raw_tabs, list):
            return []

        restored_states: list[TabState] = []
        clean_default = QDir.cleanPath(default_path or QDir.homePath())
        if not QDir(clean_default).exists():
            clean_default = QDir.homePath()

        for tab in raw_tabs:
            if not isinstance(tab, dict):
                continue

            path = QDir.cleanPath(str(tab.get("path") or clean_default))
            if not QDir(path).exists():
                path = clean_default

            title = str(tab.get("title") or (Path(path).name or path))
            view_mode = str(tab.get("view_mode") or "details")
            if view_mode not in {"details", "list", "icons"}:
                view_mode = "details"

            raw_zoom = tab.get("icon_zoom_percent", 100)
            try:
                icon_zoom_percent = int(raw_zoom)
            except (TypeError, ValueError):
                icon_zoom_percent = 100
            icon_zoom_percent = max(50, min(300, icon_zoom_percent))

            clean_history = self._normalize_existing_paths(tab.get("history"))
            clean_selected = self._normalize_existing_paths(tab.get("selected_paths"))

            try:
                scroll_value = int(tab.get("scroll_value") or 0)
            except (TypeError, ValueError):
                scroll_value = 0

            restored_states.append(
                TabState(
                    title=title,
                    path=path,
                    pinned=bool(tab.get("pinned", False)),
                    view_mode=view_mode,
                    icon_zoom_percent=icon_zoom_percent,
                    history=clean_history,
                    scroll_value=max(0, scroll_value),
                    selected_paths=clean_selected,
                )
            )

        return restored_states

    def _normalize_existing_paths(self, raw_values) -> list[str]:
        normalized: list[str] = []
        if not isinstance(raw_values, list):
            return normalized

        for item in raw_values:
            clean_item = QDir.cleanPath(str(item))
            if QDir(clean_item).exists():
                normalized.append(clean_item)
        return normalized
