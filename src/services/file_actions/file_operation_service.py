from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from localization import app_tr


@dataclass(frozen=True)
class FileOperationSummary:
    operation: str
    requested_count: int
    completed_count: int
    error_count: int
    errors: list[str]


class FileOperationWorker(QObject):
    progressChanged = Signal(int, int, str)
    finished = Signal(dict)

    def __init__(self, file_operations, operation: str, tasks, parent=None):
        super().__init__(parent)
        self._file_operations = file_operations
        self._operation = operation
        self._tasks = list(tasks)

    def run(self):
        total = len(self._tasks)
        completed = 0
        errors: list[str] = []

        for index, task in enumerate(self._tasks, start=1):
            label = self.progress_label(self._operation, task.name)
            self.progressChanged.emit(index - 1, total, label)

            try:
                if self._operation == "move":
                    self._file_operations.move(task.source_path, task.target_path, overwrite=False)
                else:
                    self._file_operations.copy(task.source_path, task.target_path, overwrite=False)
                completed += 1
            except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
                errors.append(str(error))

            self.progressChanged.emit(index, total, label)

        self.finished.emit(
            {
                "operation": self._operation,
                "requested_count": total,
                "completed_count": completed,
                "error_count": len(errors),
                "errors": errors,
            }
        )

    @staticmethod
    def progress_label(operation: str, name: str) -> str:
        if operation == "move":
            return app_tr("PaneController", "Verschiebe: {name}").format(name=name)
        return app_tr("PaneController", "Kopiere: {name}").format(name=name)


class FileOperationService:
    def dialog_title(self, operation: str) -> str:
        if operation == "move":
            return app_tr("PaneController", "Elemente verschieben")
        return app_tr("PaneController", "Elemente kopieren")

    def dialog_label(self, operation: str, count: int, target: str) -> str:
        if operation == "move":
            return app_tr("PaneController", "Verschiebe {count} Element(e) nach {target}...").format(
                count=count,
                target=target,
            )
        return app_tr("PaneController", "Kopiere {count} Element(e) nach {target}...").format(
            count=count,
            target=target,
        )

    def success_feedback(self, operation: str, completed_count: int) -> str:
        if operation == "move":
            return app_tr("PaneController", "{count} Element(e) verschoben").format(count=completed_count)
        return app_tr("PaneController", "{count} Element(e) kopiert").format(count=completed_count)
