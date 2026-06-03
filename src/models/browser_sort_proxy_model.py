from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt


class BrowserSortProxyModel(QSortFilterProxyModel):
    """Keep directories grouped above files while preserving column sorting."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortLocaleAware(True)

    def _source_index(self, index: QModelIndex) -> QModelIndex:
        if not index.isValid():
            return QModelIndex()
        return self.mapToSource(index)

    def filePath(self, index: QModelIndex) -> str:
        source_model = self.sourceModel()
        source_index = self._source_index(index)
        if source_model is None or not source_index.isValid() or not hasattr(source_model, "filePath"):
            return ""
        return str(source_model.filePath(source_index) or "")

    def isDir(self, index: QModelIndex) -> bool:
        source_model = self.sourceModel()
        source_index = self._source_index(index)
        if source_model is None or not source_index.isValid() or not hasattr(source_model, "isDir"):
            return False
        return bool(source_model.isDir(source_index))

    def fileUrl(self, index: QModelIndex) -> str:
        source_model = self.sourceModel()
        source_index = self._source_index(index)
        if source_model is None or not source_index.isValid() or not hasattr(source_model, "fileUrl"):
            return ""
        return str(source_model.fileUrl(source_index) or "")

    def currentLocation(self):
        source_model = self.sourceModel()
        if source_model is None or not hasattr(source_model, "currentLocation"):
            return None
        return source_model.currentLocation()

    def mimeTypes(self):
        source_model = self.sourceModel()
        if source_model is None or not hasattr(source_model, "mimeTypes"):
            return super().mimeTypes()
        return source_model.mimeTypes()

    def mimeData(self, indexes):
        source_model = self.sourceModel()
        if source_model is None or not hasattr(source_model, "mimeData"):
            return super().mimeData(indexes)
        source_indexes = [self._source_index(index) for index in indexes if index.isValid()]
        return source_model.mimeData(source_indexes)

    def supportedDragActions(self):
        source_model = self.sourceModel()
        if source_model is None or not hasattr(source_model, "supportedDragActions"):
            return super().supportedDragActions()
        return source_model.supportedDragActions()

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        source_model = self.sourceModel()
        if source_model is not None and hasattr(source_model, "isDir"):
            if left.isValid() and right.isValid():
                left_is_dir = bool(source_model.isDir(left))
                right_is_dir = bool(source_model.isDir(right))
                if left_is_dir != right_is_dir:
                    if self.sortOrder() == Qt.SortOrder.AscendingOrder:
                        return left_is_dir
                    return right_is_dir
        return super().lessThan(left, right)
