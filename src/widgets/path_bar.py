import os
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal, QMimeData, QUrl, QPoint
from PySide6.QtGui import QIcon, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QStackedLayout,
    QStyle,
    QToolButton,
    QWidget,
)


class PathBar(QWidget):
    pathActivated = Signal(str)

    def __init__(self, parent=None, bar_height=32, show_edit_button=True):
        super().__init__(parent)
        self._current_path = os.path.expanduser("~")
        self._bar_height = bar_height

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._bar_height)
        self.setMaximumHeight(self._bar_height)

        self._stack = QStackedLayout()
        self._crumb_buttons = []
        self._crumb_paths = {}
        self._crumb_press_pos = QPoint()
        self._crumb_drag_button = None

        self._crumbs_widget = QWidget(self)
        self._crumbs_widget.setObjectName("crumbsSurface")
        self._crumbs_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._crumbs_widget.setMinimumHeight(self._bar_height)
        self._crumbs_widget.setMaximumHeight(self._bar_height)
        self._crumbs_layout = QHBoxLayout(self._crumbs_widget)
        self._crumbs_layout.setContentsMargins(6, 0, 6, 0)
        self._crumbs_layout.setSpacing(2)
        self._crumbs_widget.installEventFilter(self)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText("Pfad eingeben …")
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit.setMinimumHeight(self._bar_height)
        self._edit.setMaximumHeight(self._bar_height)
        self._edit.returnPressed.connect(self._on_return_pressed)
        self._edit.installEventFilter(self)

        completer_model = QFileSystemModel(self)
        completer_model.setRootPath("")
        completer = QCompleter(completer_model, self)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._edit.setCompleter(completer)

        self._stack.addWidget(self._crumbs_widget)
        self._stack.addWidget(self._edit)

        self._surface = QWidget(self)
        self._surface.setObjectName("pathBarSurface")
        self._surface.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._surface.setMinimumHeight(self._bar_height)
        self._surface.setMaximumHeight(self._bar_height)
        self._surface_layout = QHBoxLayout(self._surface)
        self._surface_layout.setContentsMargins(4, 0, 4, 0)
        self._surface_layout.setSpacing(0)

        self._edit_button = QToolButton(self)
        edit_icon = QIcon.fromTheme("document-edit")
        if edit_icon.isNull():
            edit_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        self._edit_button.setIcon(edit_icon)
        self._edit_button.setToolTip("Pfad bearbeiten")
        self._edit_button.setAutoRaise(True)
        self._edit_button.setFixedSize(self._bar_height, self._bar_height)
        self._edit_button.clicked.connect(self.start_edit_mode)

        self._accept_button = QToolButton(self)
        self._accept_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self._accept_button.setToolTip("Übernehmen")
        self._accept_button.setAutoRaise(True)
        self._accept_button.setFixedSize(self._bar_height, self._bar_height)
        self._accept_button.clicked.connect(self._accept_edit_mode)
        self._accept_button.hide()

        self._cancel_button = QToolButton(self)
        self._cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self._cancel_button.setToolTip("Abbrechen")
        self._cancel_button.setAutoRaise(True)
        self._cancel_button.setFixedSize(self._bar_height, self._bar_height)
        self._cancel_button.clicked.connect(self._cancel_edit_mode)
        self._cancel_button.hide()

        stack_host = QWidget(self)
        stack_host.setLayout(self._stack)
        stack_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        stack_host.setMinimumHeight(self._bar_height)
        stack_host.setMaximumHeight(self._bar_height)

        self._surface_layout.addWidget(stack_host)
        self._surface_layout.addWidget(self._edit_button)
        self._surface_layout.addWidget(self._accept_button)
        self._surface_layout.addWidget(self._cancel_button)
        root_layout.addWidget(self._surface)

        if not show_edit_button:
            self._edit_button.hide()

        self.setStyleSheet(
            "QWidget#pathBarSurface {"
            "  background-color: rgba(120, 120, 120, 0.16);"
            "  border: 1px solid rgba(160, 160, 160, 0.40);"
            "  border-radius: 6px;"
            "}"
            "QToolButton { border: none; background: transparent; padding: 2px 6px; border-radius: 4px; }"
            "QToolButton:hover { background-color: rgba(110, 160, 255, 0.28); }"
            "QLineEdit { padding-left: 6px; padding-right: 6px; }"
        )

        self.set_path(self._current_path)
        self._set_mode("breadcrumbs")

    def current_path(self):
        return self._current_path

    def set_path(self, path):
        normalized_path = self._normalize_path(path)
        self._current_path = normalized_path
        self._edit.setText(normalized_path)
        self._render_breadcrumbs(normalized_path)

    def start_edit_mode(self):
        self._edit.setText(self._current_path)
        self._set_mode("edit")
        self._edit.setFocus()
        self._edit.selectAll()

    def _exit_edit_mode(self):
        self._set_mode("breadcrumbs")

    def _accept_edit_mode(self):
        target_path = self._normalize_path(self._edit.text())
        if target_path:
            self.pathActivated.emit(target_path)
        self._exit_edit_mode()

    def _cancel_edit_mode(self):
        self._edit.setText(self._current_path)
        self._exit_edit_mode()

    def _set_mode(self, mode):
        is_edit_mode = mode == "edit"
        self._stack.setCurrentWidget(self._edit if is_edit_mode else self._crumbs_widget)
        self._edit_button.setVisible(not is_edit_mode)
        self._accept_button.setVisible(is_edit_mode)
        self._cancel_button.setVisible(is_edit_mode)

    def _on_return_pressed(self):
        self._accept_edit_mode()

    def eventFilter(self, watched, event):
        if watched in self._crumb_buttons:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._crumb_press_pos = event.position().toPoint()
                self._crumb_drag_button = watched

            if event.type() == QEvent.Type.MouseMove and self._crumb_drag_button is watched:
                if not (event.buttons() & Qt.MouseButton.LeftButton):
                    return False

                distance = (event.position().toPoint() - self._crumb_press_pos).manhattanLength()
                if distance >= QApplication.startDragDistance():
                    target_path = self._crumb_paths.get(watched)
                    if target_path and os.path.isdir(target_path):
                        self._start_path_drag(watched, target_path)
                        self._crumb_drag_button = None
                        return True

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._crumb_drag_button = None

        if watched == self._crumbs_widget and event.type() == QEvent.Type.MouseButtonPress:
            clicked_widget = self._crumbs_widget.childAt(event.position().toPoint())
            if clicked_widget not in self._crumb_buttons:
                self.start_edit_mode()
                return True

        if watched == self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_edit_mode()
                return True

        return super().eventFilter(watched, event)

    def _render_breadcrumbs(self, path):
        self._crumb_buttons.clear()
        self._crumb_paths.clear()
        while self._crumbs_layout.count():
            item = self._crumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        parts = self._split_path(path)
        for index, (label, target_path) in enumerate(parts):
            button = QToolButton(self._crumbs_widget)
            button.setText(label)
            button.setAutoRaise(True)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            button.setMinimumHeight(self._bar_height)
            button.setMaximumHeight(self._bar_height)
            button.clicked.connect(lambda _, target=target_path: self.pathActivated.emit(target))
            button.installEventFilter(self)
            self._crumbs_layout.addWidget(button)
            self._crumb_buttons.append(button)
            self._crumb_paths[button] = target_path

            if index < len(parts) - 1:
                sep_label = QLabel("›", self._crumbs_widget)
                sep_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                sep_label.setMinimumHeight(self._bar_height)
                sep_label.setMaximumHeight(self._bar_height)
                sep_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
                self._crumbs_layout.addWidget(sep_label)

        self._crumbs_layout.addStretch(1)

    def _split_path(self, path):
        normalized = self._normalize_path(path)
        root = Path(normalized).anchor or os.path.sep
        parts = [(root, root)]

        current = Path(root)
        for segment in Path(normalized).parts:
            if segment in (root, os.path.sep):
                continue
            current = current / segment
            parts.append((segment, str(current)))

        return parts

    def _normalize_path(self, path):
        if not path:
            return self._current_path
        expanded = os.path.expanduser(path)
        return os.path.normpath(expanded)

    def _start_path_drag(self, source_widget, path):
        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path)])

        drag = QDrag(source_widget)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)
