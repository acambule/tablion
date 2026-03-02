import json
import os
from pathlib import Path
from typing import Optional


class EditorSettings:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._tablion_editor: Optional[str] = None
        self._application_double_click_behavior = "start"
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

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "tablion_editor": self._tablion_editor,
            "application_double_click_behavior": self._application_double_click_behavior,
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
