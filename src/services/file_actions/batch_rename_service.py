from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QDir

from localization import app_tr
from utils.batch_rename import render_batch_rename_name


class BatchRenameService:
    def render_name(self, source_path, rule_text, number, regex_mode=False):
        try:
            return render_batch_rename_name(source_path, rule_text, number, regex_mode=regex_mode)
        except ValueError as error:
            message = str(error).strip()
            if not message:
                message = app_tr("PaneController", "Ungültige Umbenennungsregel")
            raise ValueError(message) from error

    def build_plan(self, source_paths, rule_text, regex_mode=False):
        plan = []
        source_set = {QDir.cleanPath(str(path)) for path in source_paths}
        target_set = set()

        for number, source_path in enumerate(source_paths, start=1):
            source = Path(source_path)
            if not source.exists():
                raise FileNotFoundError(
                    app_tr("PaneController", "Pfad nicht gefunden: {path}").format(path=source_path)
                )

            new_name = self.render_name(source_path, rule_text, number, regex_mode=regex_mode)
            if not new_name:
                raise ValueError(app_tr("PaneController", "Der neue Name darf nicht leer sein"))
            if "/" in new_name or "\\" in new_name:
                raise ValueError(app_tr("PaneController", "Der neue Name darf keinen Pfad enthalten"))

            target_path = QDir.cleanPath(str(source.with_name(new_name)))
            if target_path in target_set:
                raise FileExistsError(
                    app_tr("PaneController", "Mehrere Dateien würden denselben Namen erhalten: {path}").format(
                        path=target_path
                    )
                )

            target_existing = Path(target_path)
            if target_existing.exists() and target_path not in source_set:
                raise FileExistsError(
                    app_tr("PaneController", "Ziel existiert bereits: {path}").format(path=target_path)
                )

            plan.append((QDir.cleanPath(str(source_path)), target_path))
            target_set.add(target_path)

        return plan

    def execute_plan(self, rename_plan):
        if not rename_plan:
            return

        temp_paths = []
        try:
            for index, (source_path, _target_path) in enumerate(rename_plan, start=1):
                source = Path(source_path)
                temp_name = f".tablion-rename-{uuid4().hex}-{index}"
                temp_path = source.with_name(temp_name)
                source.rename(temp_path)
                temp_paths.append((temp_path, source_path))

            for (temp_path, original_source), (_source_path, target_path) in zip(temp_paths, rename_plan):
                temp_path.rename(Path(target_path))
        except Exception:
            for temp_path, original_source in reversed(temp_paths):
                if temp_path.exists() and not Path(original_source).exists():
                    try:
                        temp_path.rename(Path(original_source))
                    except OSError:
                        pass
            raise
