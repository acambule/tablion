import os
import posixpath
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

from localization import app_tr
from domain.filesystem import PaneLocation


class PathBar(QWidget):
    pathActivated = Signal(object)
    pathOpenInNewTab = Signal(object)

    def __init__(self, parent=None, bar_height=32, show_edit_button=True):
        super().__init__(parent)
        self._show_edit_button = show_edit_button
        self._current_path = os.path.expanduser("~")
        self._current_location = PaneLocation(kind="local", path=self._current_path)
        self._remote_root_label = ""
        self._remote_subdirectory_provider = None
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
        self._crumb_parts = []
        self._overflow_button = None
        self._overflow_entries = []
        self._crumb_press_pos = QPoint()
        self._crumb_drag_button = None
        self._outside_click_cancel_active = False

        self._crumbs_widget = QWidget(self)
        self._crumbs_widget.setObjectName("crumbsSurface")
        self._crumbs_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._crumbs_widget.setMinimumWidth(0)
        self._crumbs_widget.setMinimumHeight(self._bar_height)
        self._crumbs_widget.setMaximumHeight(self._bar_height)
        self._crumbs_layout = QHBoxLayout(self._crumbs_widget)
        self._crumbs_layout.setContentsMargins(6, 0, 6, 0)
        self._crumbs_layout.setSpacing(2)
        self._crumbs_widget.installEventFilter(self)

        self._edit = QLineEdit(self)
        self._edit.setPlaceholderText(app_tr("PathBar", "Pfad eingeben …"))
        self._edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._edit.setMinimumWidth(0)
        self._edit.setMinimumHeight(self._bar_height)
        self._edit.setMaximumHeight(self._bar_height)
        self._edit.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
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
        self._surface.setMinimumWidth(0)
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
        self._edit_button.setToolTip(app_tr("PathBar", "Pfad bearbeiten"))
        self._edit_button.setAutoRaise(True)
        self._edit_button.setFixedSize(self._bar_height, self._bar_height)
        self._edit_button.clicked.connect(self.start_edit_mode)

        self._accept_button = QToolButton(self)
        self._accept_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        self._accept_button.setToolTip(app_tr("PathBar", "Übernehmen"))
        self._accept_button.setAutoRaise(True)
        self._accept_button.setFixedSize(self._bar_height, self._bar_height)
        self._accept_button.clicked.connect(self._accept_edit_mode)
        self._accept_button.hide()

        self._cancel_button = QToolButton(self)
        self._cancel_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton))
        self._cancel_button.setToolTip(app_tr("PathBar", "Abbrechen"))
        self._cancel_button.setAutoRaise(True)
        self._cancel_button.setFixedSize(self._bar_height, self._bar_height)
        self._cancel_button.clicked.connect(self._cancel_edit_mode)
        self._cancel_button.hide()

        stack_host = QWidget(self)
        stack_host.setLayout(self._stack)
        stack_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        stack_host.setMinimumWidth(0)
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

    def retranslate_ui_texts(self):
        self._edit.setPlaceholderText(app_tr("PathBar", "Pfad eingeben …"))
        self._edit_button.setToolTip(app_tr("PathBar", "Pfad bearbeiten"))
        self._accept_button.setToolTip(app_tr("PathBar", "Übernehmen"))
        self._cancel_button.setToolTip(app_tr("PathBar", "Abbrechen"))

    def current_path(self):
        return self._current_path

    def set_remote_subdirectory_provider(self, provider):
        self._remote_subdirectory_provider = provider

    def set_location(self, location: PaneLocation | str, root_label: str = ""):
        if isinstance(location, PaneLocation):
            self._current_location = location
            self._remote_root_label = root_label if location.is_remote else ""
            self.set_path(location.path)
            return
        normalized_path = self._normalize_local_path(str(location or ""))
        self._current_location = PaneLocation(kind="local", path=normalized_path)
        self._remote_root_label = ""
        self.set_path(str(location or ""))

    def set_path(self, path):
        normalized_path = self._normalize_remote_path(path) if self._current_location.is_remote else self._normalize_local_path(path)
        self._current_path = normalized_path
        self._edit.setText(normalized_path)
        self._render_breadcrumbs()
        self._update_edit_availability()

    def _update_edit_availability(self):
        allow_edit = self._show_edit_button and self._current_location.is_local
        self._edit_button.setVisible(allow_edit and self._stack.currentWidget() is self._crumbs_widget)
        self._accept_button.setVisible(allow_edit and self._stack.currentWidget() is self._edit)
        self._cancel_button.setVisible(allow_edit and self._stack.currentWidget() is self._edit)

    def start_edit_mode(self):
        if self._current_location.is_remote:
            return
        self._edit.setText(self._current_path)
        self._set_mode("edit")
        self._edit.setFocus()
        self._edit.selectAll()
        self._update_completions(self._edit.text(), force_popup=False)

    def _exit_edit_mode(self):
        self._set_mode("breadcrumbs")

    def _accept_edit_mode(self):
        if self._current_location.is_remote:
            target_path = PaneLocation(
                kind="remote",
                path=self._normalize_remote_path(self._edit.text()),
                remote_id=self._current_location.remote_id,
            )
        else:
            target_path = self._normalize_local_path(self._edit.text())
        if target_path:
            self.pathActivated.emit(target_path)
        self._exit_edit_mode()

    def _cancel_edit_mode(self):
        self._edit.setText(self._current_path)
        self._exit_edit_mode()

    def _set_mode(self, mode):
        is_edit_mode = mode == "edit"
        if is_edit_mode and self._current_location.is_remote:
            is_edit_mode = False
        self._stack.setCurrentWidget(self._edit if is_edit_mode else self._crumbs_widget)
        allow_edit = self._show_edit_button and self._current_location.is_local
        self._edit_button.setVisible(not is_edit_mode and allow_edit)
        self._accept_button.setVisible(is_edit_mode and allow_edit)
        self._cancel_button.setVisible(is_edit_mode and allow_edit)
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
        if self._current_location.is_remote:
            return
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
                    if isinstance(target_path, str) and target_path and os.path.isdir(target_path):
                        self._start_path_drag(watched, target_path)
                        self._crumb_drag_button = None
                        return True

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._crumb_drag_button = None

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                target_path = self._crumb_paths.get(watched)
                if target_path:
                    self.pathOpenInNewTab.emit(target_path)
                    return True

        if watched in self._crumb_arrow_buttons:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._show_subdirectory_menu(watched)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                target_path = self._crumb_arrow_paths.get(watched)
                if target_path:
                    self.pathOpenInNewTab.emit(target_path)
                    return True

        if watched is self._overflow_button:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._show_overflow_menu()
                return True

        if watched == self._crumbs_widget and event.type() == QEvent.Type.MouseButtonPress:
            clicked_widget = self._crumbs_widget.childAt(event.position().toPoint())
            if (
                self._current_location.is_local
                and clicked_widget not in self._crumb_buttons
                and clicked_widget not in self._crumb_arrow_buttons
                and clicked_widget is not self._overflow_button
            ):
                self.start_edit_mode()
                return True

        if watched == self._edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel_edit_mode()
                return True

        return super().eventFilter(watched, event)

    def _render_breadcrumbs(self):
        self._crumb_buttons.clear()
        self._crumb_arrow_buttons.clear()
        self._crumb_paths.clear()
        self._crumb_arrow_paths.clear()
        self._crumb_parts.clear()
        self._overflow_entries = []
        while self._crumbs_layout.count():
            item = self._crumbs_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._overflow_button = None

        parts = self._split_location()
        self._crumb_parts = list(parts)
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
            if self._current_location.is_remote and index == 0 and self._remote_root_label:
                button.setToolTip(self._remote_root_label)
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

        self._overflow_button = QToolButton(self._crumbs_widget)
        self._overflow_button.setText("…")
        self._overflow_button.setAutoRaise(True)
        self._overflow_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._overflow_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._overflow_button.setMinimumHeight(self._bar_height)
        self._overflow_button.setMaximumHeight(self._bar_height)
        self._overflow_button.installEventFilter(self)
        self._overflow_button.hide()
        if self._crumb_buttons:
            self._crumbs_layout.insertWidget(1, self._overflow_button)
        else:
            self._crumbs_layout.addWidget(self._overflow_button)
        self._crumbs_layout.addStretch(1)
        self._update_breadcrumb_overflow()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_breadcrumb_overflow()

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(160)
        return hint

    def _update_breadcrumb_overflow(self):
        if not self._crumb_buttons or self._overflow_button is None:
            return

        for button in self._crumb_buttons:
            button.show()
        for arrow in self._crumb_arrow_buttons:
            arrow.show()
        self._overflow_button.hide()
        self._overflow_entries = []

        available_width = self._crumbs_widget.width()
        if available_width <= 0:
            return

        margins = self._crumbs_layout.contentsMargins()
        spacing = self._crumbs_layout.spacing()
        total_width = margins.left() + margins.right()
        for button in self._crumb_buttons:
            total_width += button.sizeHint().width()
        for arrow in self._crumb_arrow_buttons:
            total_width += arrow.sizeHint().width()
        if self._crumb_buttons or self._crumb_arrow_buttons:
            total_width += spacing * (len(self._crumb_buttons) + len(self._crumb_arrow_buttons) - 1)

        if total_width <= available_width or len(self._crumb_buttons) <= 2:
            self.updateGeometry()
            return

        overflow_width = self._overflow_button.sizeHint().width() + spacing
        root_width = self._crumb_buttons[0].sizeHint().width()
        block_widths = []
        for index in range(1, len(self._crumb_buttons)):
            width = self._crumb_arrow_buttons[index - 1].sizeHint().width() + self._crumb_buttons[index].sizeHint().width() + spacing
            block_widths.append(width)

        visible_tail: list[int] = []
        used_width = margins.left() + margins.right() + root_width + overflow_width
        for block_index in range(len(block_widths) - 1, -1, -1):
            block_width = block_widths[block_index]
            if not visible_tail or used_width + block_width <= available_width:
                visible_tail.insert(0, block_index)
                used_width += block_width

        hidden_indices = [index for index in range(len(block_widths)) if index not in visible_tail]
        if not hidden_indices:
            self.updateGeometry()
            return

        for hidden_index in hidden_indices:
            self._crumb_arrow_buttons[hidden_index].hide()
            self._crumb_buttons[hidden_index + 1].hide()

        self._overflow_entries = [
            self._crumb_parts[hidden_index + 1]
            for hidden_index in hidden_indices
            if hidden_index + 1 < len(self._crumb_parts)
        ]
        self._overflow_button.show()
        self.updateGeometry()

    def _show_overflow_menu(self):
        if self._overflow_button is None or not self._overflow_entries:
            return
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu::item {"
            " padding: 2px 14px;"
            " min-height: 18px;"
            "}"
        )
        for label, target in self._overflow_entries:
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, target_path=target: self.pathActivated.emit(target_path))
        menu.exec(self._overflow_button.mapToGlobal(QPoint(0, self._overflow_button.height())))

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

        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu::item {"
            " padding: 2px 14px;"
            " min-height: 18px;"
            "}"
        )
        if self._current_location.is_remote:
            subdirectories = self._list_remote_subdirectories(base_path)
        else:
            subdirectories = [(name, os.path.join(base_path, name)) for name in self._list_subdirectories(base_path)]
        if not subdirectories:
            action = menu.addAction(app_tr("PathBar", "(Keine Unterordner)"))
            action.setEnabled(False)
        else:
            visible = subdirectories[: self._max_primary_subdir_items]
            for name, target_path in visible:
                action = menu.addAction(name)
                action.triggered.connect(lambda checked=False, target=target_path: self.pathActivated.emit(target))

            remaining = subdirectories[self._max_primary_subdir_items :]
            if remaining:
                more_menu = menu.addMenu(app_tr("PathBar", "Weitere…"))
                more_menu.setStyleSheet(
                    "QMenu::item {"
                    " padding: 2px 14px;"
                    " min-height: 18px;"
                    "}"
                )
                for name, target_path in remaining:
                    action = more_menu.addAction(name)
                    action.triggered.connect(lambda checked=False, target=target_path: self.pathActivated.emit(target))

        menu.exec(arrow_button.mapToGlobal(QPoint(0, arrow_button.height())))

    def _list_remote_subdirectories(self, location):
        if self._remote_subdirectory_provider is None or not isinstance(location, PaneLocation):
            return []
        try:
            entries = list(self._remote_subdirectory_provider(location))
        except Exception:
            return []

        results = []
        for entry in entries:
            if len(entry) != 2:
                continue
            label, target = entry
            label_text = str(label or "").strip()
            if not label_text:
                continue
            results.append((label_text, target))
        results.sort(key=lambda item: item[0].lower())
        return results

    def _split_location(self):
        if self._current_location.is_remote:
            return self._split_remote_location()
        return self._split_local_path(self._current_path)

    def _split_local_path(self, path):
        normalized = self._normalize_local_path(path)
        root = Path(normalized).anchor or os.path.sep
        parts = [(root, root)]

        current = Path(root)
        for segment in Path(normalized).parts:
            if segment in (root, os.path.sep):
                continue
            current = current / segment
            parts.append((segment, str(current)))

        return parts

    def _split_remote_location(self):
        normalized = self._normalize_remote_path(self._current_location.path)
        parts = [("/", PaneLocation(kind="remote", path="/", remote_id=self._current_location.remote_id))]
        if normalized == "/":
            return parts

        current = "/"
        for segment in [segment for segment in normalized.split("/") if segment]:
            current = posixpath.join(current, segment)
            parts.append(
                (
                    segment,
                    PaneLocation(kind="remote", path=current, remote_id=self._current_location.remote_id),
                )
            )
        return parts

    def _normalize_local_path(self, path):
        if not path:
            return self._current_path
        expanded = os.path.expanduser(path)
        return os.path.normpath(expanded)

    def _normalize_remote_path(self, path):
        raw = str(path or "").strip()
        if not raw:
            return "/"
        normalized = posixpath.normpath(raw)
        if not normalized.startswith("/"):
            normalized = f"/{normalized}"
        return normalized

    def _start_path_drag(self, source_widget, path):
        mime_data = QMimeData()
        url = QUrl.fromLocalFile(path)
        encoded_uri = bytes(url.toEncoded()).decode("utf-8")
        mime_data.setUrls([url])
        mime_data.setData("text/uri-list", (encoded_uri + "\n").encode("utf-8"))

        drag = QDrag(source_widget)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)
