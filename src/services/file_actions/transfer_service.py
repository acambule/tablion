from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDir, QMimeData, QUrl

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

    def extract_paths_from_mime(
        self,
        mime_data,
        *,
        internal_drag_mime_type: str,
        clipboard_mime_type: str,
        ark_dnd_service_mime: str,
        ark_dnd_path_mime: str,
        logger: Callable[[str], None] | None = None,
    ) -> list[str]:
        if mime_data is None:
            return []

        format_list = list(mime_data.formats())
        has_relevant = any(
            mime_data.hasFormat(mime_name)
            for mime_name in (
                internal_drag_mime_type,
                clipboard_mime_type,
                ark_dnd_service_mime,
                ark_dnd_path_mime,
                "text/uri-list",
                "application/x-kde4-urilist",
                "application/x-kde-urilist",
                "x-special/gnome-copied-files",
            )
        ) or mime_data.hasUrls()
        if has_relevant and logger is not None:
            logger(f"DND extract_paths_from_mime: incoming_formats={format_list}")

        paths: list[str] = []

        def append_uri_paths(raw_uri_list, log_label):
            if not raw_uri_list:
                return
            for line in raw_uri_list.splitlines():
                candidate = line.strip()
                if not candidate or candidate.startswith("#") or candidate in {"copy", "cut"}:
                    continue
                url = QUrl(candidate)
                if not url.isValid() or not url.isLocalFile():
                    continue
                path = QDir.cleanPath(url.toLocalFile())
                if path:
                    paths.append(path)
            if logger is not None:
                logger(f"DND extract_paths_from_mime: {log_label}={raw_uri_list!r}")

        if mime_data.hasFormat(internal_drag_mime_type):
            raw_internal_paths = bytes(mime_data.data(internal_drag_mime_type)).decode("utf-8", errors="ignore")
            for line in raw_internal_paths.splitlines():
                candidate = QDir.cleanPath(line.strip())
                if candidate:
                    paths.append(candidate)
            if raw_internal_paths.strip() and logger is not None:
                logger(f"DND extract_paths_from_mime: internal_paths={paths[:5]}")
            unique_paths = list(dict.fromkeys(paths))
            if logger is not None:
                logger(f"DND extract_paths_from_mime: resolved_paths={unique_paths[:5]} count={len(unique_paths)}")
            return unique_paths

        if mime_data.hasFormat(clipboard_mime_type):
            raw = bytes(mime_data.data(clipboard_mime_type)).decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                for item in parsed:
                    path = QDir.cleanPath(str(item))
                    if path:
                        paths.append(path)

        if mime_data.hasUrls():
            for url in mime_data.urls():
                if not url.isLocalFile():
                    continue
                path = QDir.cleanPath(url.toLocalFile())
                if path:
                    paths.append(path)
            if paths and logger is not None:
                logger(f"DND extract_paths_from_mime: urls_paths={paths[:5]}")

        if mime_data.hasFormat("text/uri-list"):
            append_uri_paths(bytes(mime_data.data("text/uri-list")).decode("utf-8", errors="ignore"), "uri_list_raw")
        if mime_data.hasFormat("application/x-kde4-urilist"):
            append_uri_paths(bytes(mime_data.data("application/x-kde4-urilist")).decode("utf-8", errors="ignore"), "kde4_uri_list_raw")
        if mime_data.hasFormat("application/x-kde-urilist"):
            append_uri_paths(bytes(mime_data.data("application/x-kde-urilist")).decode("utf-8", errors="ignore"), "kde_uri_list_raw")
        if mime_data.hasFormat("x-special/gnome-copied-files"):
            append_uri_paths(bytes(mime_data.data("x-special/gnome-copied-files")).decode("utf-8", errors="ignore"), "gnome_uri_list_raw")

        unique_paths = list(dict.fromkeys(paths))
        if has_relevant and logger is not None:
            logger(f"DND extract_paths_from_mime: resolved_paths={unique_paths[:5]} count={len(unique_paths)}")
        return unique_paths

    def extract_operation_from_mime(self, mime_data, *, operation_mime_type: str) -> str:
        if mime_data is None:
            return "copy"
        if not mime_data.hasFormat(operation_mime_type):
            return "copy"

        raw = bytes(mime_data.data(operation_mime_type)).decode("utf-8", errors="ignore").strip().lower()
        return "cut" if raw == "cut" else "copy"

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
