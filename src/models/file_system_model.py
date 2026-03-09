from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from debug_log import debug_log
from PySide6.QtCore import QDir, QMimeData, Qt, QUrl
from PySide6.QtWidgets import QFileSystemModel
from localization import app_tr


class FileSystemModel(QFileSystemModel):
    INTERNAL_PATHS_MIME = "application/x-tablion-internal-paths"

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            translated_headers = {
                0: app_tr("PaneController", "Name"),
                1: app_tr("PaneController", "Größe"),
                2: app_tr("PaneController", "Typ"),
                3: app_tr("PaneController", "Geändert"),
            }
            if section in translated_headers:
                return translated_headers[section]
        return super().headerData(section, orientation, role)

    def mimeTypes(self):
        inherited = [
            mime_name
            for mime_name in super().mimeTypes()
            if mime_name not in {"text/uri-list", self.INTERNAL_PATHS_MIME}
        ]
        return [self.INTERNAL_PATHS_MIME, "text/uri-list"] + inherited

    def _collect_paths(self, indexes):
        paths = []
        seen_paths = set()
        for index in indexes:
            if not index.isValid() or index.column() != 0:
                continue

            raw_path = self.filePath(index)
            if not raw_path:
                continue
            path = QDir.cleanPath(str(Path(raw_path).expanduser()))
            if not path or path in seen_paths:
                continue

            seen_paths.add(path)
            paths.append(path)
        return paths

    def _build_drag_batch_dir(self, source_paths: list[str]) -> Path:
        downloads_dir = Path.home() / "Downloads" / ".tablion-dnd"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        joined = "\n".join(source_paths)
        digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]
        batch_dir = downloads_dir / f"{timestamp}-{digest}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        return batch_dir

    def _next_free_target(self, target: Path) -> Path:
        if not target.exists():
            return target
        stem = target.stem
        suffix = target.suffix
        counter = 2
        while True:
            candidate = target.with_name(f"{stem} {counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _stage_path_for_external_drag(self, source_path: str, batch_dir: Path) -> str:
        source = Path(source_path)
        target = self._next_free_target(batch_dir / source.name)

        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)

        return QDir.cleanPath(str(target))

    def mimeData(self, indexes):
        mime_data = super().mimeData(indexes)
        if mime_data is None:
            mime_data = QMimeData()

        source_paths = self._collect_paths(indexes)
        debug_log(
            f"DND mimeData: selected_rows={len(indexes)} valid_source_paths={len(source_paths)} "
            f"source_paths={source_paths[:5]}"
        )
        if not source_paths:
            return mime_data

        mime_data.setData(self.INTERNAL_PATHS_MIME, "\n".join(source_paths).encode("utf-8"))

        batch_dir = self._build_drag_batch_dir(source_paths)
        export_paths = []
        for path in source_paths:
            try:
                staged_path = self._stage_path_for_external_drag(path, batch_dir)
                export_paths.append(staged_path)
                debug_log(f"DND mimeData: staged '{path}' -> '{staged_path}'")
            except OSError as error:
                export_paths.append(path)
                debug_log(f"DND mimeData: staging failed for '{path}', fallback to original ({error})")

        urls = [QUrl.fromLocalFile(path) for path in export_paths]
        if urls:
            mime_data.setUrls(urls)
            uri_values = [bytes(url.toEncoded()).decode("utf-8") for url in urls]
            # Use LF-only URI list to avoid consumers treating CR as part of filenames.
            uri_list_payload = ("\n".join(uri_values) + "\n").encode("utf-8")
            mime_data.setData("text/uri-list", uri_list_payload)

        debug_log(
            f"DND mimeData: export_paths={export_paths[:5]} formats={mime_data.formats()}"
        )

        return mime_data

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction
