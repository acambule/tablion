from __future__ import annotations

from PySide6.QtCore import QDir, QModelIndex, Qt


class DropUiService:
    def compute_highlight(self, *, target_view, pos, file_model):
        if target_view is None:
            return QModelIndex(), False

        index = target_view.indexAt(pos)
        highlight_index = QModelIndex()
        highlight_root = False

        if index.isValid():
            target_path = QDir.cleanPath(file_model.filePath(index))
            if file_model.isDir(index) and QDir(target_path).exists():
                highlight_index = index
            else:
                parent_index = index.parent()
                if parent_index.isValid():
                    highlight_index = parent_index
                else:
                    highlight_root = True
        else:
            highlight_root = True

        return highlight_index, highlight_root

    def root_stylesheet(self, drop_action) -> str:
        if drop_action == Qt.DropAction.CopyAction:
            return "background-color: rgba(128, 128, 128, 24); border: 1px dashed rgba(110, 110, 110, 120);"
        if drop_action == Qt.DropAction.LinkAction:
            return "background-color: rgba(128, 128, 128, 18); border: 1px dotted rgba(110, 110, 110, 140);"
        return "background-color: rgba(128, 128, 128, 36); border: 1px solid rgba(110, 110, 110, 140);"
