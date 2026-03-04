from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from debug_log import debug_log
from PySide6.QtCore import QDir, QMimeData, Qt, QUrl
from PySide6.QtWidgets import QFileSystemModel


class FileSystemModel(QFileSystemModel):
    INTERNAL_PATHS_MIME = "application/x-tablion-internal-paths"

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

    def _stage_path_for_external_drag(self, source_path: str) -> str:
        source = Path(source_path)
        downloads_dir = Path.home() / "Downloads" / ".tablion-dnd"
        downloads_dir.mkdir(parents=True, exist_ok=True)

        stat = source.stat()
        digest = hashlib.sha1(f"{source_path}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")).hexdigest()[:12]
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target_name = f"{source.name}.{timestamp}.{digest}"
        target = downloads_dir / target_name

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

        export_paths = []
        for path in source_paths:
            try:
                staged_path = self._stage_path_for_external_drag(path)
                export_paths.append(staged_path)
                debug_log(f"DND mimeData: staged '{path}' -> '{staged_path}'")
            except OSError as error:
                export_paths.append(path)
                debug_log(f"DND mimeData: staging failed for '{path}', fallback to original ({error})")

        urls = [QUrl.fromLocalFile(path) for path in export_paths]
        if urls:
            mime_data.setUrls(urls)
            uri_values = [bytes(url.toEncoded()).decode("utf-8") for url in urls]
            mime_data.setData("text/uri-list", ("\r\n".join(uri_values) + "\r\n").encode("utf-8"))
            mime_data.removeFormat("text/plain")
            mime_data.removeFormat("text/plain;charset=utf-8")
            mime_data.removeFormat("text/x-moz-url")
            mime_data.removeFormat("x-special/gnome-copied-files")

        debug_log(
            f"DND mimeData: export_paths={export_paths[:5]} formats={mime_data.formats()}"
        )

        return mime_data

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction
