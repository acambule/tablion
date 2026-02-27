from PySide6.QtCore import QDir, QModelIndex, QItemSelectionModel, Qt
from PySide6.QtWidgets import QListView


class IconViewAdapter:
    def __init__(self, icon_view: QListView, file_model):
        self.icon_view = icon_view
        self.file_model = file_model

    def selected_paths(self):
        selection_model = self.icon_view.selectionModel()
        if selection_model is None:
            return []

        paths = []
        for index in selection_model.selectedIndexes():
            if not index.isValid() or index.column() != 0:
                continue
            path = self.file_model.filePath(index)
            if path:
                paths.append(QDir.cleanPath(path))

        if paths:
            return list(dict.fromkeys(paths))

        current_index = self.icon_view.currentIndex()
        if current_index.isValid():
            current_path = self.file_model.filePath(current_index)
            if current_path:
                return [QDir.cleanPath(current_path)]
        return []

    def selected_count(self):
        return len(self.selected_paths())

    def current_or_selected_index(self):
        selection_model = self.icon_view.selectionModel()
        if selection_model:
            selected_indexes = selection_model.selectedIndexes()
            if selected_indexes:
                return selected_indexes[0]

        current_index = self.icon_view.currentIndex()
        if current_index.isValid():
            return current_index
        return QModelIndex()

    def extract_paths_from_drag_source(self, source_widget):
        if not isinstance(source_widget, QListView):
            return []

        source_model = source_widget.model()
        selection_model = source_widget.selectionModel()
        if source_model is None or selection_model is None:
            return []
        if not hasattr(source_model, "filePath"):
            return []

        paths = []
        for index in selection_model.selectedIndexes():
            if not index.isValid() or index.column() != 0:
                continue
            path = source_model.filePath(index)
            if path:
                paths.append(QDir.cleanPath(path))

        return list(dict.fromkeys(paths))

    def resolve_drop_target_directory(self, pos, current_directory):
        if pos is None:
            index = self.icon_view.currentIndex()
        else:
            index = self.icon_view.indexAt(pos)

        if index.isValid():
            target_path = QDir.cleanPath(self.file_model.filePath(index))
            if self.file_model.isDir(index):
                return target_path

        return QDir.cleanPath(current_directory)

    def select_single_index(self, index, focus=False):
        if not index.isValid():
            return

        self.icon_view.clearSelection()
        self.icon_view.setCurrentIndex(index)
        selection_model = self.icon_view.selectionModel()
        if selection_model is not None:
            selection_model.select(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        if focus:
            self.icon_view.setFocus(Qt.FocusReason.OtherFocusReason)
