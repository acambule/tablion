import os
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, Signal, QMimeData, QUrl, QPoint, QStringListModel
from PySide6.QtGui import QIcon, QDrag
from PySide6.QtWidgets import (
    QApplication,
    QCompleter,
    QHBoxLayout,
    QLineEdit,
    QMenu,
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
        self._max_primary_subdir_items = 18

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(self._bar_height)
        self.setMaximumHeight(self._bar_height)

        self._stack = QStackedLayout()
        self._crumb_buttons = []
        self._crumb_arrow_buttons = []
        self._crumb_paths = {}
        self._crumb_arrow_paths = {}
        self._crumb_press_pos = QPoint()
        self._crumb_drag_button = None
        self._outside_click_cancel_active = False

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
        self._edit.textEdited.connect(self._on_edit_text_edited)
        self._edit.installEventFilter(self)

        self._completion_model = QStringListModel(self)
        self._completer = QCompleter(self._completion_model, self)
        self._completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchStartsWith)
        self._completer.activated[str].connect(self._on_completion_activated)
        self._edit.setCompleter(self._completer)

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
        self._update_completions(self._edit.text(), force_popup=False)

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
        self._set_outside_click_cancel(is_edit_mode)

    def _set_outside_click_cancel(self, active):
        app = QApplication.instance()
        if app is None:
            return

        if active and not self._outside_click_cancel_active:
            app.installEventFilter(self)
            self._outside_click_cancel_active = True
            return

        if not active and self._outside_click_cancel_active:
            app.removeEventFilter(self)
            self._outside_click_cancel_active = False

    def _is_inside_widget(self, widget, global_pos):
        if widget is None:
            return False
        local_pos = widget.mapFromGlobal(global_pos)
        return widget.rect().contains(local_pos)

    def _event_global_pos(self, event):
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        return None

    def _on_return_pressed(self):
        self._accept_edit_mode()

    def _on_edit_text_edited(self, text):
        self._update_completions(text, force_popup=True)

    def _expanded_path(self, value):
        if not value:
            return ""
        return os.path.expanduser(value)

    def _completion_context(self, text):
        raw_text = text or ""
        expanded_text = self._expanded_path(raw_text)
        if not expanded_text:
            return ("", "")

        if expanded_text.endswith(os.path.sep):
            return (expanded_text, "")

        base_dir = os.path.dirname(expanded_text)
        fragment = os.path.basename(expanded_text)
        return (base_dir, fragment)

    def _list_directory_candidates(self, base_dir, fragment):
        if not base_dir:
            return []
        try:
            if not os.path.isdir(base_dir):
                return []
        except OSError:
            return []

        fragment_lower = fragment.lower()
        candidates = []
        try:
            with os.scandir(base_dir) as entries:
                for entry in entries:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                    except OSError:
                        continue

                    name = entry.name
                    if fragment and not name.lower().startswith(fragment_lower):
                        continue
                    candidates.append(name)
        except OSError:
            return []

        candidates.sort(key=str.lower)
        return candidates

    def _update_completions(self, text, force_popup):
        base_dir, fragment = self._completion_context(text)
        names = self._list_directory_candidates(base_dir, fragment)

        expanded_text = self._expanded_path(text)
        if expanded_text.endswith(os.path.sep):
            prefix = expanded_text
        else:
            prefix = (base_dir + os.path.sep) if base_dir else ""

        values = [prefix + name for name in names]
        self._completion_model.setStringList(values)
        self._completer.setCompletionPrefix(prefix + fragment)

        if force_popup and values:
            self._completer.complete()

    def _on_completion_activated(self, value):
        if not value:
            return
        selected = self._expanded_path(value)
        if not selected.endswith(os.path.sep):
            selected = selected + os.path.sep
        self._edit.setText(selected)
        self._edit.setCursorPosition(len(selected))
        self._update_completions(selected, force_popup=True)

    def eventFilter(self, watched, event):
        app = QApplication.instance()
        if (
            self._outside_click_cancel_active
            and app is not None
            and event.type() == QEvent.Type.MouseButtonPress
        ):
            global_pos = self._event_global_pos(event)
            if global_pos is None:
                return False

            popup = self._completer.popup() if self._completer else None
            if self._is_inside_widget(self, global_pos):
                return False
            if self._is_inside_widget(popup, global_pos):
                return False

            self._cancel_edit_mode()
            return False

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

        if watched in self._crumb_arrow_buttons:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._show_subdirectory_menu(watched)
                return True

        if watched == self._crumbs_widget and event.type() == QEvent.Type.MouseButtonPress:
            clicked_widget = self._crumbs_widget.childAt(event.position().toPoint())
            if clicked_widget not in self._crumb_buttons and clicked_widget not in self._crumb_arrow_buttons:
                self.start_edit_mode()
                return True

        if watched == self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_edit_mode()
                return True

        return super().eventFilter(watched, event)

    def _render_breadcrumbs(self, path):
        self._crumb_buttons.clear()
        self._crumb_arrow_buttons.clear()
        self._crumb_paths.clear()
        self._crumb_arrow_paths.clear()
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
                arrow_button = QToolButton(self._crumbs_widget)
                arrow_button.setText("›")
                arrow_button.setAutoRaise(True)
                arrow_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                arrow_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                arrow_button.setMinimumHeight(self._bar_height)
                arrow_button.setMaximumHeight(self._bar_height)
                arrow_button.installEventFilter(self)
                self._crumbs_layout.addWidget(arrow_button)
                self._crumb_arrow_buttons.append(arrow_button)
                self._crumb_arrow_paths[arrow_button] = target_path

        self._crumbs_layout.addStretch(1)

    def _list_subdirectories(self, parent_path):
        try:
            if not os.path.isdir(parent_path):
                return []
        except OSError:
            return []

        names = []
        try:
            with os.scandir(parent_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            names.append(entry.name)
                    except OSError:
                        continue
        except OSError:
            return []

        return sorted(names, key=str.lower)

    def _show_subdirectory_menu(self, arrow_button):
        base_path = self._crumb_arrow_paths.get(arrow_button)
        if not base_path:
            return

        subdirectories = self._list_subdirectories(base_path)
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu::item {"
            " padding: 2px 14px;"
            " min-height: 18px;"
            "}"
        )
        if not subdirectories:
            action = menu.addAction("(Keine Unterordner)")
            action.setEnabled(False)
        else:
            visible = subdirectories[: self._max_primary_subdir_items]
            for name in visible:
                target_path = os.path.join(base_path, name)
                action = menu.addAction(name)
                action.triggered.connect(lambda checked=False, target=target_path: self.pathActivated.emit(target))

            remaining = subdirectories[self._max_primary_subdir_items :]
            if remaining:
                more_menu = menu.addMenu("Weitere…")
                more_menu.setStyleSheet(
                    "QMenu::item {"
                    " padding: 2px 14px;"
                    " min-height: 18px;"
                    "}"
                )
                for name in remaining:
                    target_path = os.path.join(base_path, name)
                    action = more_menu.addAction(name)
                    action.triggered.connect(lambda checked=False, target=target_path: self.pathActivated.emit(target))

        menu.exec(arrow_button.mapToGlobal(QPoint(0, arrow_button.height())))

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
        url = QUrl.fromLocalFile(path)
        encoded_uri = bytes(url.toEncoded()).decode("utf-8")

        mime_data.setData("text/uri-list", (encoded_uri + "\r\n").encode("utf-8"))

        drag = QDrag(source_widget)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)
