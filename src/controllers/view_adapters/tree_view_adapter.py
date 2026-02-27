from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, QItemSelectionModel, Qt
from PySide6.QtWidgets import QTreeView


class TreeViewAdapter:
    def __init__(self, tree_view: QTreeView, file_model):
        self.tree_view = tree_view
        self.file_model = file_model

    def selected_paths(self):
        selection_model = self.tree_view.selectionModel()
        if selection_model is None:
            return []

        paths = []
        for index in selection_model.selectedRows(0):
            if not index.isValid():
                continue
            path = self.file_model.filePath(index)
            if path:
                paths.append(QDir.cleanPath(path))

        if paths:
            return list(dict.fromkeys(paths))

        current_index = self.tree_view.currentIndex()
        if current_index.isValid():
            current_path = self.file_model.filePath(current_index)
            if current_path:
                return [QDir.cleanPath(current_path)]
        return []

    def selected_count(self):
        selection_model = self.tree_view.selectionModel()
        if selection_model is None:
            return 0
        return len(selection_model.selectedRows(0))

    def current_or_selected_index(self):
        selection_model = self.tree_view.selectionModel()
        if selection_model:
            selected_rows = selection_model.selectedRows(0)
            if selected_rows:
                return selected_rows[0]

        current_index = self.tree_view.currentIndex()
        if current_index.isValid():
            return current_index
        return QModelIndex()

    def extract_paths_from_drag_source(self, source_widget):
        if not isinstance(source_widget, QTreeView):
            return []

        source_model = source_widget.model()
        selection_model = source_widget.selectionModel()
        if source_model is None or selection_model is None:
            return []
        if not hasattr(source_model, "filePath"):
            return []

        paths = []
        for index in selection_model.selectedRows(0):
            if not index.isValid():
                continue
            path = source_model.filePath(index)
            if path:
                paths.append(QDir.cleanPath(path))

        return list(dict.fromkeys(paths))

    def resolve_drop_target_directory(self, pos, current_directory):
        if pos is None:
            index = self.tree_view.currentIndex()
        else:
            index = self.tree_view.indexAt(pos)

        if index.isValid():
            target_path = QDir.cleanPath(self.file_model.filePath(index))
            if self.file_model.isDir(index) and Path(target_path).exists():
                return target_path

            parent_index = index.parent()
            if parent_index.isValid():
                parent_path = QDir.cleanPath(self.file_model.filePath(parent_index))
                if Path(parent_path).exists():
                    return parent_path

        return QDir.cleanPath(current_directory)

    def select_single_index(self, index, focus=False):
        if not index.isValid():
            return

        self.tree_view.clearSelection()
        self.tree_view.setCurrentIndex(index)
        selection_model = self.tree_view.selectionModel()
        if selection_model is not None:
            selection_model.select(
                index,
                QItemSelectionModel.SelectionFlag.ClearAndSelect
                | QItemSelectionModel.SelectionFlag.Rows,
            )
        if focus:
            self.tree_view.setFocus(Qt.FocusReason.OtherFocusReason)
