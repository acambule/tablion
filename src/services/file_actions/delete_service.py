from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QDir

from localization import app_tr


@dataclass
class DeleteExecutionResult:
    deleted_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class DeleteService:
    def existing_paths(self, paths: list[str]) -> list[str]:
        existing: list[str] = []
        for target in paths:
            clean_target = QDir.cleanPath(str(target))
            if clean_target and Path(clean_target).exists():
                existing.append(clean_target)
        return existing

    def build_confirmation(self, existing_paths: list[str], permanent: bool) -> tuple[str, str]:
        if len(existing_paths) == 1:
            target_label = Path(existing_paths[0]).name or existing_paths[0]
            if permanent:
                message = app_tr("PaneController", "'{target}' dauerhaft löschen?").format(target=target_label)
            else:
                message = app_tr("PaneController", "'{target}' in den Papierkorb verschieben?").format(target=target_label)
        else:
            if permanent:
                message = app_tr("PaneController", "{count} Elemente dauerhaft löschen?").format(count=len(existing_paths))
            else:
                message = app_tr("PaneController", "{count} Elemente in den Papierkorb verschieben?").format(count=len(existing_paths))

        title = (
            app_tr("PaneController", "Dauerhaft löschen")
            if permanent
            else app_tr("PaneController", "In den Papierkorb verschieben")
        )
        return title, message

    def execute(self, paths: list[str], *, permanent: bool, file_operations) -> DeleteExecutionResult:
        result = DeleteExecutionResult()
        for target in paths:
            try:
                file_operations.delete(target, permanent=permanent)
                result.deleted_paths.append(target)
            except RuntimeError as error:
                result.errors.append(str(error))
            except (FileNotFoundError, OSError, ValueError):
                continue
        return result
