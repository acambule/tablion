from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QModelIndex, QMimeData, Qt
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel

from localization import app_tr
from domain.filesystem import PaneLocation


@dataclass(frozen=True)
class RemoteFileItem:
    name: str
    location: PaneLocation
    is_dir: bool
    size: int | None = None
    modified_at: datetime | None = None
    web_url: str = ""


class RemoteFileTreeModel(QStandardItemModel):
    REMOTE_CLIPBOARD_MIME_TYPE = "application/x-tablion-remote-locations"
    ROLE_PATH = Qt.ItemDataRole.UserRole + 100
    ROLE_IS_DIR = Qt.ItemDataRole.UserRole + 101
    ROLE_WEB_URL = Qt.ItemDataRole.UserRole + 102
    ROLE_CHILDREN_LOADED = Qt.ItemDataRole.UserRole + 103
    ROLE_PLACEHOLDER = Qt.ItemDataRole.UserRole + 104

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_location = PaneLocation(kind="remote", path="/", remote_id=None)
        self._update_headers()

    def set_directory_entries(self, location: PaneLocation, entries: list[RemoteFileItem]) -> None:
        self.clear()
        self._current_location = location
        self._update_headers()
        for entry in entries:
            row_items = self._build_row(entry)
            self.appendRow(row_items)
        self.sort(0, Qt.SortOrder.AscendingOrder)

    def set_children_for_index(self, parent_index: QModelIndex, entries: list[RemoteFileItem]) -> None:
        if not parent_index.isValid():
            return
        parent_item = self.itemFromIndex(parent_index.siblingAtColumn(0))
        if parent_item is None:
            return
        parent_item.removeRows(0, parent_item.rowCount())
        for entry in entries:
            parent_item.appendRow(self._build_row(entry))
        parent_item.setData(True, self.ROLE_CHILDREN_LOADED)

    def children_loaded(self, index: QModelIndex) -> bool:
        if not index.isValid():
            return False
        item = self.itemFromIndex(index.siblingAtColumn(0))
        return bool(item.data(self.ROLE_CHILDREN_LOADED)) if item is not None else False

    def filePath(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        return str(index.siblingAtColumn(0).data(self.ROLE_PATH) or "")

    def isDir(self, index: QModelIndex) -> bool:
        if not index.isValid():
            return False
        return bool(index.siblingAtColumn(0).data(self.ROLE_IS_DIR))

    def fileUrl(self, index: QModelIndex) -> str:
        if not index.isValid():
            return ""
        return str(index.siblingAtColumn(0).data(self.ROLE_WEB_URL) or "")

    def currentLocation(self) -> PaneLocation:
        return self._current_location

    def mimeTypes(self) -> list[str]:
        return [self.REMOTE_CLIPBOARD_MIME_TYPE]

    def mimeData(self, indexes) -> QMimeData | None:
        mime_data = QMimeData()
        payload: list[dict[str, str]] = []
        seen_paths: set[str] = set()
        for index in indexes:
            if not index.isValid() or index.column() != 0:
                continue

            path = str(index.data(self.ROLE_PATH) or "").strip()
            is_placeholder = bool(index.data(self.ROLE_PLACEHOLDER))
            if not path or path in seen_paths or path == "/" or is_placeholder:
                continue
            seen_paths.add(path)
            payload.append(
                {
                    "kind": "remote",
                    "path": path,
                    "remote_id": str(self._current_location.remote_id or ""),
                }
            )

        if payload:
            mime_data.setData(self.REMOTE_CLIPBOARD_MIME_TYPE, json.dumps(payload).encode("utf-8"))
        return mime_data

    def supportedDragActions(self):
        return Qt.DropAction.CopyAction | Qt.DropAction.MoveAction

    def flags(self, index: QModelIndex):
        default_flags = super().flags(index)
        if not index.isValid():
            return default_flags
        if bool(index.siblingAtColumn(0).data(self.ROLE_PLACEHOLDER)):
            return default_flags & ~Qt.ItemFlag.ItemIsDragEnabled
        return default_flags | Qt.ItemFlag.ItemIsDragEnabled

    def _update_headers(self) -> None:
        self.setHorizontalHeaderLabels(
            [
                app_tr("PaneController", "Name"),
                app_tr("PaneController", "Größe"),
                app_tr("PaneController", "Typ"),
                app_tr("PaneController", "Geändert"),
            ]
        )

    def _build_row(self, entry: RemoteFileItem) -> list[QStandardItem]:
        name_item = QStandardItem(self._icon_for_entry(entry), entry.name)
        name_item.setData(entry.location.path, self.ROLE_PATH)
        name_item.setData(entry.is_dir, self.ROLE_IS_DIR)
        name_item.setData(entry.web_url, self.ROLE_WEB_URL)
        name_item.setData(False, self.ROLE_CHILDREN_LOADED)
        name_item.setEditable(False)

        size_item = QStandardItem(self._size_text(entry))
        size_item.setData(entry.location.path, self.ROLE_PATH)
        size_item.setData(entry.is_dir, self.ROLE_IS_DIR)
        size_item.setEditable(False)

        type_item = QStandardItem(app_tr("PaneController", "Ordner") if entry.is_dir else (Path(entry.name).suffix.lstrip(".").upper() or app_tr("PaneController", "Datei")))
        type_item.setData(entry.location.path, self.ROLE_PATH)
        type_item.setData(entry.is_dir, self.ROLE_IS_DIR)
        type_item.setEditable(False)

        modified_item = QStandardItem(entry.modified_at.strftime("%d.%m.%y %H:%M") if entry.modified_at else "")
        modified_item.setData(entry.location.path, self.ROLE_PATH)
        modified_item.setData(entry.is_dir, self.ROLE_IS_DIR)
        modified_item.setEditable(False)
        if entry.is_dir:
            name_item.appendRow(self._placeholder_row(entry.location))
        return [name_item, size_item, type_item, modified_item]

    def _placeholder_row(self, location: PaneLocation) -> list[QStandardItem]:
        placeholder = QStandardItem("")
        placeholder.setData(location.path, self.ROLE_PATH)
        placeholder.setData(True, self.ROLE_PLACEHOLDER)
        placeholder.setEditable(False)
        return [placeholder, QStandardItem(""), QStandardItem(""), QStandardItem("")]

    def _icon_for_entry(self, entry: RemoteFileItem) -> QIcon:
        if entry.is_dir:
            return QIcon.fromTheme("folder-cloud") or QIcon.fromTheme("folder")
        suffix = Path(entry.name).suffix.lower()
        theme_name = {
            ".pdf": "application-pdf",
            ".png": "image-png",
            ".jpg": "image-jpeg",
            ".jpeg": "image-jpeg",
            ".svg": "image-svg+xml",
            ".txt": "text-plain",
            ".md": "text-markdown",
        }.get(suffix, "text-x-generic")
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = QIcon.fromTheme("text-x-generic")
        return icon

    def _size_text(self, entry: RemoteFileItem) -> str:
        if entry.is_dir or entry.size is None:
            return ""
        size = float(entry.size)
        for unit in ["Bytes", "KiB", "MiB", "GiB", "TiB"]:
            if size < 1024.0 or unit == "TiB":
                if unit == "Bytes":
                    return f"{int(size)} {unit}"
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return ""
