from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QMimeData, QUrl

from localization import app_tr


@dataclass(frozen=True)
class FileTransferTask:
    source_path: str
    target_path: str
    name: str


@dataclass
class DuplicateExecutionResult:
    duplicated_paths: list[str] = field(default_factory=list)


class TransferService:
    def build_clipboard_mime_data(self, source_paths: list[str], *, path_mime_type: str, operation_mime_type: str, operation: str) -> QMimeData:
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in source_paths])
        mime_data.setData(path_mime_type, json.dumps(source_paths).encode("utf-8"))
        mime_data.setData(operation_mime_type, operation.encode("utf-8"))
        return mime_data

    def build_file_operation_tasks(self, source_paths, target_directory, operation):
        tasks = []
        target_dir = Path(target_directory)
        if not target_dir.exists():
            return tasks

        for source in source_paths:
            source_path = Path(source)
            if not source_path.exists():
                continue

            target_path = target_dir / source_path.name
            if operation == "copy" and target_path.resolve() == source_path.resolve():
                target_path = self.build_next_duplicate_path(source_path, target_dir)

            if operation == "move":
                try:
                    if target_path.resolve() == source_path.resolve():
                        continue
                except OSError:
                    pass
            if target_path.exists():
                continue

            tasks.append(
                FileTransferTask(
                    source_path=str(source_path),
                    target_path=str(target_path),
                    name=source_path.name,
                )
            )

        return tasks

    def build_next_duplicate_path(self, source_path: Path, target_dir: Path):
        source_name = source_path.name
        if source_path.is_file():
            stem = source_path.stem
            suffix = source_path.suffix
            candidate = target_dir / f"{stem} - Kopie{suffix}"
            counter = 2
            while candidate.exists():
                candidate = target_dir / f"{stem} - Kopie {counter}{suffix}"
                counter += 1
            return candidate

        candidate = target_dir / f"{source_name} - Kopie"
        counter = 2
        while candidate.exists():
            candidate = target_dir / f"{source_name} - Kopie {counter}"
            counter += 1
        return candidate

    def duplicate_paths(self, source_paths, *, file_operations) -> DuplicateExecutionResult:
        result = DuplicateExecutionResult()

        for source in source_paths:
            source_path = Path(source)
            if not source_path.exists():
                continue

            target_dir = source_path.parent
            duplicate_target = self.build_next_duplicate_path(source_path, target_dir)
            try:
                file_operations.copy(source_path, duplicate_target, overwrite=False)
                result.duplicated_paths.append(str(duplicate_target))
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        return result

    def duplicate_feedback(self, count: int) -> str:
        return app_tr("PaneController", "{count} Element(e) dupliziert").format(count=count)
