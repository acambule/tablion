import json
import os
from pathlib import Path
from typing import Optional


class EditorSettings:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._tablion_editor: Optional[str] = None
        self._application_double_click_behavior = "start"
        self._show_group_tab_close_icons = False
        self._show_file_tab_close_icons = False
        self._language_preference = "system"
        self._group_creation_behavior = "default_tab"
        self._middle_click_new_tab_behavior = "background"
        self._visible_file_tree_columns = [0, 1, 2, 3]
        self._show_hidden_files = False
        self._settings_dialog_width = 920
        self._settings_dialog_height = 620
        self._remote_open_rules = []
        self.load()

    @property
    def tablion_editor(self) -> Optional[str]:
        return self._tablion_editor

    def preferred_editor(self) -> Optional[str]:
        env_value = os.environ.get("TABLION_EDITOR")
        if isinstance(env_value, str) and env_value.strip():
            return env_value.strip()
        return self._tablion_editor

    @property
    def application_double_click_behavior(self) -> str:
        return self._application_double_click_behavior

    @property
    def show_group_tab_close_icons(self) -> bool:
        return self._show_group_tab_close_icons

    @property
    def show_file_tab_close_icons(self) -> bool:
        return self._show_file_tab_close_icons

    @property
    def language_preference(self) -> str:
        return self._language_preference

    @property
    def group_creation_behavior(self) -> str:
        return self._group_creation_behavior

    @property
    def middle_click_new_tab_behavior(self) -> str:
        return self._middle_click_new_tab_behavior

    @property
    def visible_file_tree_columns(self) -> list[int]:
        return list(self._visible_file_tree_columns)

    @property
    def show_hidden_files(self) -> bool:
        return self._show_hidden_files

    @property
    def settings_dialog_width(self) -> int:
        return int(self._settings_dialog_width)

    @property
    def settings_dialog_height(self) -> int:
        return int(self._settings_dialog_height)

    @property
    def remote_open_rules(self) -> list[dict]:
        return [dict(item) for item in self._remote_open_rules]

    def _normalize_visible_file_tree_columns(self, value) -> list[int]:
        if not isinstance(value, list):
            return [0, 1, 2, 3]

        normalized = []
        for item in value:
            try:
                column = int(item)
            except (TypeError, ValueError):
                continue
            if column < 0 or column > 3:
                continue
            if column not in normalized:
                normalized.append(column)

        if not normalized:
            return [0]
        return sorted(normalized)

    def _normalize_remote_open_rules(self, value) -> list[dict]:
        if not isinstance(value, list):
            return []
        normalized: list[dict] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            extensions = str(item.get("extensions") or "").strip().lower()
            command = str(item.get("command") or "").strip()
            arguments = str(item.get("arguments") or "").strip()
            if not extensions or not command:
                continue
            normalized.append(
                {
                    "extensions": extensions,
                    "command": command,
                    "arguments": arguments,
                }
            )
        return normalized

    def load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        value = payload.get("tablion_editor")
        self._tablion_editor = value.strip() if isinstance(value, str) and value.strip() else None
        behavior = payload.get("application_double_click_behavior")
        if behavior in {"start", "edit"}:
            self._application_double_click_behavior = behavior
        self._show_group_tab_close_icons = bool(payload.get("show_group_tab_close_icons", False))
        self._show_file_tab_close_icons = bool(payload.get("show_file_tab_close_icons", False))
        language_pref = str(payload.get("language_preference") or "system").strip().lower()
        if language_pref in {"system", "de", "en"}:
            self._language_preference = language_pref
        group_creation_behavior = str(payload.get("group_creation_behavior") or "default_tab").strip().lower()
        if group_creation_behavior in {"default_tab", "copy_tabs"}:
            self._group_creation_behavior = group_creation_behavior
        middle_click_behavior = str(payload.get("middle_click_new_tab_behavior") or "background").strip().lower()
        if middle_click_behavior in {"background", "foreground"}:
            self._middle_click_new_tab_behavior = middle_click_behavior
        self._visible_file_tree_columns = self._normalize_visible_file_tree_columns(
            payload.get("visible_file_tree_columns", [0, 1, 2, 3])
        )
        self._show_hidden_files = bool(payload.get("show_hidden_files", False))
        self._remote_open_rules = self._normalize_remote_open_rules(payload.get("remote_open_rules", []))
        try:
            width = int(payload.get("settings_dialog_width", 920))
        except (TypeError, ValueError):
            width = 920
        try:
            height = int(payload.get("settings_dialog_height", 620))
        except (TypeError, ValueError):
            height = 620
        self._settings_dialog_width = max(720, width)
        self._settings_dialog_height = max(520, height)

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tablion_editor": self._tablion_editor,
            "application_double_click_behavior": self._application_double_click_behavior,
            "show_group_tab_close_icons": self._show_group_tab_close_icons,
            "show_file_tab_close_icons": self._show_file_tab_close_icons,
            "language_preference": self._language_preference,
            "group_creation_behavior": self._group_creation_behavior,
            "middle_click_new_tab_behavior": self._middle_click_new_tab_behavior,
            "visible_file_tree_columns": list(self._visible_file_tree_columns),
            "show_hidden_files": self._show_hidden_files,
            "remote_open_rules": list(self._remote_open_rules),
            "settings_dialog_width": self._settings_dialog_width,
            "settings_dialog_height": self._settings_dialog_height,
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_tablion_editor(self, value: Optional[str]) -> None:
        normalized = value.strip() if isinstance(value, str) and value.strip() else None
        if normalized == self._tablion_editor:
            return
        self._tablion_editor = normalized
        self.save()

    def update_application_double_click_behavior(self, value: str) -> None:
        normalized = value if value in {"start", "edit"} else "start"
        if normalized == self._application_double_click_behavior:
            return
        self._application_double_click_behavior = normalized
        self.save()

    def update_show_group_tab_close_icons(self, value: bool) -> None:
        normalized = bool(value)
        if normalized == self._show_group_tab_close_icons:
            return
        self._show_group_tab_close_icons = normalized
        self.save()

    def update_show_file_tab_close_icons(self, value: bool) -> None:
        normalized = bool(value)
        if normalized == self._show_file_tab_close_icons:
            return
        self._show_file_tab_close_icons = normalized
        self.save()

    def update_language_preference(self, value: str) -> None:
        normalized = str(value or "system").strip().lower()
        if normalized not in {"system", "de", "en"}:
            normalized = "system"
        if normalized == self._language_preference:
            return
        self._language_preference = normalized
        self.save()

    def update_group_creation_behavior(self, value: str) -> None:
        normalized = str(value or "default_tab").strip().lower()
        if normalized not in {"default_tab", "copy_tabs"}:
            normalized = "default_tab"
        if normalized == self._group_creation_behavior:
            return
        self._group_creation_behavior = normalized
        self.save()

    def update_middle_click_new_tab_behavior(self, value: str) -> None:
        normalized = str(value or "background").strip().lower()
        if normalized not in {"background", "foreground"}:
            normalized = "background"
        if normalized == self._middle_click_new_tab_behavior:
            return
        self._middle_click_new_tab_behavior = normalized
        self.save()

    def update_visible_file_tree_columns(self, value) -> None:
        normalized = self._normalize_visible_file_tree_columns(value)
        if normalized == self._visible_file_tree_columns:
            return
        self._visible_file_tree_columns = normalized
        self.save()

    def update_show_hidden_files(self, value: bool) -> None:
        normalized = bool(value)
        if normalized == self._show_hidden_files:
            return
        self._show_hidden_files = normalized
        self.save()

    def update_settings_dialog_size(self, width: int, height: int) -> None:
        normalized_width = max(720, int(width or 920))
        normalized_height = max(520, int(height or 620))
        if (
            normalized_width == self._settings_dialog_width
            and normalized_height == self._settings_dialog_height
        ):
            return
        self._settings_dialog_width = normalized_width
        self._settings_dialog_height = normalized_height
        self.save()

    def update_remote_open_rules(self, rules) -> None:
        normalized = self._normalize_remote_open_rules(rules)
        if normalized == self._remote_open_rules:
            return
        self._remote_open_rules = normalized
        self.save()

    def remote_open_rule_for(self, path: str) -> dict | None:
        suffix = Path(str(path or "")).suffix.lower().lstrip(".")
        if not suffix:
            return None
        for item in self._remote_open_rules:
            extensions = [part.strip().lower().lstrip(".") for part in str(item.get("extensions") or "").split(",")]
            if suffix in {part for part in extensions if part}:
                return dict(item)
        return None
