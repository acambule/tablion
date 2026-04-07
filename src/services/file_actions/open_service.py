from __future__ import annotations

import os
import shlex
from pathlib import Path

from PySide6.QtCore import QProcess, QUrl
from PySide6.QtGui import QDesktopServices

from utils.open_with import launch_with_application


class OpenService:
    def is_application_target(self, path: str, launch_extensions: set[str]) -> bool:
        path_obj = Path(path)
        if path_obj.is_dir():
            return False
        suffix = path_obj.suffix.lower()
        if suffix in launch_extensions:
            return True
        try:
            return path_obj.exists() and os.access(path, os.X_OK)
        except OSError:
            return False

    def open_default(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def open_with_application(self, application, path: str) -> bool:
        return launch_with_application(application, path)

    def open_in_editor(self, path: str, preferred_editor: str | None = None) -> bool:
        editor_cmd = preferred_editor or os.environ.get("TABLION_EDITOR")
        if editor_cmd:
            parts = shlex.split(editor_cmd)
            if parts:
                program, *args = parts
                return QProcess.startDetached(program, [*args, path])

        self.open_default(path)
        return True
