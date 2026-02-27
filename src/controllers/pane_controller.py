import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QDir, QEvent, QObject, QRect, QSize, Qt, QTimer, Signal, QPoint, QMimeData, QUrl, QModelIndex
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon, QDrag, QKeySequence, QPen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QAbstractItemDelegate, QAbstractItemView, QHBoxLayout, QListView, QMenu, QMessageBox, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QTabBar, QToolButton, QToolTip, QTreeView, QWidget

from localization import ask_yes_no
from controllers.view_adapters import IconViewAdapter, TreeViewAdapter
from models.file_operations import FileOperations
from widgets.path_bar import PathBar


@dataclass
class TabState:
    title: str
    path: str
    pinned: bool = False
    view_mode: str = "details"
    icon_zoom_percent: int = 100
    history: list[str] = field(default_factory=list)
    scroll_value: int = 0
    selected_paths: list[str] = field(default_factory=list)


class DropTargetHighlightDelegate(QStyledItemDelegate):
    def __init__(self, parent=None, file_model=None, enable_drop_highlight=True):
        super().__init__(parent)
        self._file_model = file_model
        self._enable_drop_highlight = enable_drop_highlight
        self._drop_target_index = QModelIndex()
        self._drop_action = Qt.DropAction.IgnoreAction
        self._cut_paths = set()

    def set_drop_target_index(self, index):
        self._drop_target_index = index if index.isValid() else QModelIndex()

    def clear_drop_target_index(self):
        self._drop_target_index = QModelIndex()

    def set_drop_action(self, action):
        self._drop_action = action

    def set_cut_paths(self, paths):
        self._cut_paths = set(paths or [])

    def paint(self, painter, option, index):
        is_cut_item = False
        if self._file_model is not None:
            try:
                model_path = QDir.cleanPath(self._file_model.filePath(index))
                is_cut_item = model_path in self._cut_paths
            except (AttributeError, TypeError):
                is_cut_item = False

        if is_cut_item:
            painter.save()
            painter.setOpacity(0.42)
            super().paint(painter, option, index)
            painter.restore()
        else:
            super().paint(painter, option, index)

        if not self._enable_drop_highlight:
            return
        if not self._drop_target_index.isValid() or index != self._drop_target_index:
            return

        painter.save()
        painter.fillRect(option.rect, QColor(128, 128, 128, 60))
        if self._drop_action == Qt.DropAction.CopyAction:
            pen = QPen(QColor(110, 110, 110, 180), 1, Qt.PenStyle.DashLine)
        elif self._drop_action == Qt.DropAction.LinkAction:
            pen = QPen(QColor(110, 110, 110, 180), 1, Qt.PenStyle.DotLine)
        else:
            pen = QPen(QColor(110, 110, 110, 180), 1, Qt.PenStyle.SolidLine)
        painter.setPen(pen)
        painter.drawRect(option.rect.adjusted(0, 0, -1, -1))
        painter.restore()


class PaneController(QObject):
    currentPathChanged = Signal(str)
    navigationStateChanged = Signal(bool, bool)
    groupRequested = Signal()
    filesystemMutationCommitted = Signal()
    operationFeedback = Signal(str)
    _CLIPBOARD_MIME_TYPE = "application/x-tablion-copy-paths"
    _CLIPBOARD_OPERATION_MIME_TYPE = "application/x-tablion-clipboard-operation"

    def __init__(self, file_system_model, parent=None):
        super().__init__(parent)
        loader = QUiLoader()
        pane_ui_path = Path(__file__).resolve().parent.parent / "ui" / "pane.ui"
        self.widget = loader.load(str(pane_ui_path))
        if self.widget is None:
            raise RuntimeError(f"Konnte Pane UI nicht laden: {pane_ui_path}")
        self.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.model = file_system_model
        self.file_operations = FileOperations()
        self.path_bar = None
        self.btn_view_mode = None
        self.view_mode_actions = {}
        self.view_mode_icons = {}
        self.tab_states: list[TabState] = []
        self.active_tab_index = -1
        self._restoring_tab_switch = False
        self._tab_drag_index = -1
        self._tab_drag_start_pos = QPoint()
        self._pin_icon = QIcon.fromTheme("pin")
        if self._pin_icon.isNull():
            self._pin_icon = QIcon.fromTheme("emblem-favorite")
        if self._pin_icon.isNull():
            self._pin_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)

        self.current_directory = QDir.homePath()
        self.filetree_view_mode = "details"
        self._pending_root_path = None
        self._pending_restore_selection: list[str] = []
        self._pending_restore_scroll = 0
        self._pending_created_item_path = None
        self._drop_target_index = QModelIndex()
        self._drop_target_is_root = False
        self._cut_paths: set[str] = set()
        self.tree_view_adapter = None
        self.icon_view_adapter = None

        self.tab_bar_host = self.widget.findChild(QWidget, "tabBarHost")
        self.tab_bar = None
        self.tree_view = self.widget.findChild(QTreeView, "fileTree")
        self.icon_view = None
        self.view_stack = None
        self.path_bar_container = self.widget.findChild(QWidget, "pathBarContainer")
        self.btn_view_mode = self.widget.findChild(QToolButton, "btnViewMode")

        if not self.tab_bar_host or not self.tree_view or not self.path_bar_container:
            raise RuntimeError("Pane UI ist unvollständig (tabBar/treeView/pathBarContainer fehlt)")

        self.setup_tab_bar_host()

        self._default_icon_size = self.tree_view.iconSize()
        self._default_indentation = self.tree_view.indentation()
        self.icon_zoom_percent = 100

        self.setup_tree_view()
        self.setup_path_bar()
        self.setup_view_mode_button()
        self.setup_tab_bar()

        self.add_tab("Tab 1", QDir.homePath())

    def setup_tab_bar_host(self):
        if self.tab_bar_host.layout() is None:
            host_layout = QHBoxLayout(self.tab_bar_host)
            host_layout.setContentsMargins(0, 0, 0, 0)
            host_layout.setSpacing(0)

        self.tab_bar = QTabBar(self.tab_bar_host)
        self.tab_bar_host.layout().addWidget(self.tab_bar)

    def setup_tree_view(self):
        self.tree_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.tree_view.setModel(self.model)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree_view.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.tree_view.setDragEnabled(True)
        self.tree_view.setAcceptDrops(True)
        self.tree_view.viewport().setAcceptDrops(True)
        self.tree_view.setDropIndicatorShown(True)
        self.tree_view.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.tree_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.tree_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.on_tree_context_menu)
        self.tree_view.installEventFilter(self)
        self.tree_view.viewport().installEventFilter(self)

        self.tree_view_adapter = TreeViewAdapter(self.tree_view, self.model)

        self._drop_target_delegate = DropTargetHighlightDelegate(
            self.tree_view,
            file_model=self.model,
            enable_drop_highlight=True,
        )
        self.tree_view.setItemDelegate(self._drop_target_delegate)
        QApplication.clipboard().dataChanged.connect(self.on_clipboard_data_changed)

        self.action_new_folder_shortcut = QAction(self.tree_view)
        self.action_new_folder_shortcut.setShortcut(QKeySequence("Ctrl+Shift+N"))
        self.action_new_folder_shortcut.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.action_new_folder_shortcut.triggered.connect(self.create_folder)
        self.tree_view.addAction(self.action_new_folder_shortcut)

        self.action_new_file_shortcut = QAction(self.tree_view)
        self.action_new_file_shortcut.setShortcut(QKeySequence("Ctrl+N"))
        self.action_new_file_shortcut.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.action_new_file_shortcut.triggered.connect(self.create_file)
        self.tree_view.addAction(self.action_new_file_shortcut)

        self.action_duplicate_shortcut = QAction(self.tree_view)
        self.action_duplicate_shortcut.setShortcut(QKeySequence("Ctrl+D"))
        self.action_duplicate_shortcut.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.action_duplicate_shortcut.triggered.connect(self.duplicate_selection)
        self.tree_view.addAction(self.action_duplicate_shortcut)

        self.setup_icon_view()
        self.setup_view_stack()

        self.tree_view.doubleClicked.connect(self.on_tree_double_click)
        self.model.fileRenamed.connect(self.on_model_file_renamed)

        delegate = self.tree_view.itemDelegate()
        if delegate is not None:
            delegate.closeEditor.connect(self.on_delegate_close_editor)

        def on_loaded(path):
            try:
                if self.tree_view is None:
                    return

                if not self._pending_root_path:
                    if QDir.cleanPath(path) == QDir.cleanPath(self.current_directory):
                        self.apply_current_sort()
                        self.optimize_columns()
                    return

                requested = QDir.cleanPath(self._pending_root_path)
                loaded = QDir.cleanPath(path)
                if loaded != requested:
                    return

                root_index = self.model.index(self._pending_root_path)
                if root_index.isValid():
                    self.tree_view.setRootIndex(root_index)
                    self.tree_view.expand(root_index)
                    if self.icon_view is not None:
                        self.icon_view.setRootIndex(root_index)

                self.apply_pending_restore_state()
                self._pending_root_path = None
                self.apply_current_sort()
                self.optimize_columns()
            except RuntimeError:
                return

        self.model.directoryLoaded.connect(on_loaded)
        QTimer.singleShot(300, self.optimize_columns)

    def setup_icon_view(self):
        self.icon_view = QListView(self.widget)
        self.icon_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.icon_view.setModel(self.model)
        self.icon_view.setModelColumn(0)
        self.icon_view.setViewMode(QListView.ViewMode.IconMode)
        self.icon_view.setResizeMode(QListView.ResizeMode.Adjust)
        self.icon_view.setMovement(QListView.Movement.Static)
        self.icon_view.setWrapping(True)
        self.icon_view.setWordWrap(True)
        self.icon_view.setSpacing(10)
        self.icon_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.icon_view.setEditTriggers(
            QAbstractItemView.EditTrigger.SelectedClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self.icon_view.setDragEnabled(True)
        self.icon_view.setAcceptDrops(True)
        self.icon_view.viewport().setAcceptDrops(True)
        self.icon_view.setDropIndicatorShown(True)
        self.icon_view.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.icon_view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.icon_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.icon_view.customContextMenuRequested.connect(self.on_tree_context_menu)
        self.icon_view.installEventFilter(self)
        self.icon_view.viewport().installEventFilter(self)
        self.icon_view.doubleClicked.connect(self.on_tree_double_click)

        if self.action_new_folder_shortcut is not None:
            self.icon_view.addAction(self.action_new_folder_shortcut)
        if self.action_new_file_shortcut is not None:
            self.icon_view.addAction(self.action_new_file_shortcut)
        if self.action_duplicate_shortcut is not None:
            self.icon_view.addAction(self.action_duplicate_shortcut)

        self._icon_view_delegate = DropTargetHighlightDelegate(
            self.icon_view,
            file_model=self.model,
            enable_drop_highlight=False,
        )
        self.icon_view.setItemDelegate(self._icon_view_delegate)

        icon_delegate = self.icon_view.itemDelegate()
        if icon_delegate is not None:
            icon_delegate.closeEditor.connect(self.on_delegate_close_editor)

        self.icon_view_adapter = IconViewAdapter(self.icon_view, self.model)

    def update_cut_visual_state(self):
        cut_paths = set(self._cut_paths)
        if hasattr(self, "_drop_target_delegate") and self._drop_target_delegate is not None:
            self._drop_target_delegate.set_cut_paths(cut_paths)
        if hasattr(self, "_icon_view_delegate") and self._icon_view_delegate is not None:
            self._icon_view_delegate.set_cut_paths(cut_paths)

        if self.tree_view is not None:
            self.tree_view.viewport().update()
        if self.icon_view is not None:
            self.icon_view.viewport().update()

    def clear_cut_state(self):
        if not self._cut_paths:
            return
        self._cut_paths.clear()
        self.update_cut_visual_state()

    def on_clipboard_data_changed(self):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        if mime_data is None:
            self.clear_cut_state()
            return

        operation = self.extract_operation_from_mime(mime_data)
        if operation != "cut":
            self.clear_cut_state()

    def show_operation_feedback(self, message, timeout_ms=1400):
        if not message:
            return

        self.operationFeedback.emit(message)
        QToolTip.showText(QCursor.pos(), message, self.active_item_view(), QRect(), timeout_ms)

    def setup_view_stack(self):
        parent_layout = self.widget.layout()
        if parent_layout is None:
            return

        self.view_stack = QStackedWidget(self.widget)
        self.view_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        parent_layout.replaceWidget(self.tree_view, self.view_stack)

        self.tree_view.setParent(self.view_stack)
        self.icon_view.setParent(self.view_stack)
        self.view_stack.addWidget(self.tree_view)
        self.view_stack.addWidget(self.icon_view)
        self.view_stack.setCurrentWidget(self.tree_view)

    def setup_path_bar(self):
        self.path_bar_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.path_bar_container.setMinimumHeight(32)
        self.path_bar_container.setMaximumHeight(32)

        if self.path_bar_container.layout() is None:
            layout = QHBoxLayout(self.path_bar_container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

        self.path_bar = PathBar(self.path_bar_container)
        self.path_bar.pathActivated.connect(self.navigate_to)
        self.path_bar_container.layout().addWidget(self.path_bar)

    def setup_view_mode_button(self):
        if not self.btn_view_mode:
            return

        icon = QIcon.fromTheme("view-list-details")
        if icon.isNull():
            icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)

        self.btn_view_mode.setIcon(icon)
        self.btn_view_mode.setIconSize(QSize(22, 22))
        self.btn_view_mode.setText("")
        self.btn_view_mode.setToolTip("Ansicht")
        self.btn_view_mode.setAutoRaise(True)
        self.btn_view_mode.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_view_mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(self.btn_view_mode)
        self.btn_view_mode.setMenu(menu)

        action_group = QActionGroup(self.btn_view_mode)
        action_group.setExclusive(True)

        details_icon = QIcon.fromTheme("view-list-details")
        if details_icon.isNull():
            details_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        details_action = menu.addAction(details_icon, "Details")
        details_action.setData("details")
        details_action.setCheckable(True)
        details_action.setChecked(True)
        action_group.addAction(details_action)

        list_icon = QIcon.fromTheme("view-list-text")
        if list_icon.isNull():
            list_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        list_action = menu.addAction(list_icon, "Liste")
        list_action.setData("list")
        list_action.setCheckable(True)
        action_group.addAction(list_action)

        icons_icon = QIcon.fromTheme("view-grid")
        if icons_icon.isNull():
            icons_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        icons_action = menu.addAction(icons_icon, "Icons")
        icons_action.setData("icons")
        icons_action.setCheckable(True)
        action_group.addAction(icons_action)

        menu.addSeparator()
        reset_icon = QIcon.fromTheme("view-refresh")
        if reset_icon.isNull():
            reset_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        action_reset_view = menu.addAction(reset_icon, "Standard")

        self.view_mode_actions = {
            "details": details_action,
            "list": list_action,
            "icons": icons_action,
        }
        self.view_mode_icons = {
            "details": details_icon,
            "list": list_icon,
            "icons": icons_icon,
        }

        action_group.triggered.connect(lambda action: self.apply_view_mode(str(action.data())))
        action_reset_view.triggered.connect(self.reset_view_to_default)

    def setup_tab_bar(self):
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.setTabsClosable(False)
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        self.tab_bar.installEventFilter(self)

    def _tab_menu_icon(self, theme_name, fallback_pixmap):
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = self.widget.style().standardIcon(fallback_pixmap)
        return icon

    def add_tab(self, title, path):
        state = TabState(title=title, path=QDir.cleanPath(path))
        self.tab_states.append(state)
        index = self.tab_bar.addTab(title)
        self.update_tab_visual(index)

        if self.active_tab_index == -1:
            self.active_tab_index = index
            self.tab_bar.setCurrentIndex(index)
            self.apply_tab_state(state, push_history=False)

    def close_tab(self, index):
        if len(self.tab_states) <= 1:
            return
        if index < 0 or index >= len(self.tab_states):
            return
        if self.tab_states[index].pinned:
            return

        removing_active = index == self.active_tab_index
        self.tab_states.pop(index)
        self.tab_bar.removeTab(index)

        if removing_active:
            new_index = min(index, len(self.tab_states) - 1)
            self.active_tab_index = new_index
            self.tab_bar.setCurrentIndex(new_index)
            self.apply_tab_state(self.tab_states[new_index], push_history=False)
        elif index < self.active_tab_index:
            self.active_tab_index -= 1

    def on_tab_changed(self, new_index):
        if new_index < 0 or new_index >= len(self.tab_states):
            return
        if self._restoring_tab_switch:
            return

        if self.active_tab_index >= 0 and self.active_tab_index < len(self.tab_states):
            self.capture_tab_state(self.active_tab_index)

        self.active_tab_index = new_index
        target_state = self.tab_states[new_index]
        self.apply_tab_state(target_state, push_history=False)

    def eventFilter(self, watched, event):
        if watched == self.tab_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._tab_drag_index = self.tab_bar.tabAt(event.position().toPoint())
                self._tab_drag_start_pos = event.position().toPoint()

            if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                if self._tab_drag_index != -1:
                    current_pos = event.position().toPoint()
                    drag_distance = (current_pos - self._tab_drag_start_pos).manhattanLength()
                    if drag_distance >= QApplication.startDragDistance() and not self.tab_bar.rect().contains(current_pos):
                        self.start_tab_path_drag(self._tab_drag_index)
                        self._tab_drag_index = -1
                        return True

            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                tab_index = self.tab_bar.tabAt(event.position().toPoint())
                if tab_index == -1:
                    new_index = len(self.tab_states) + 1
                    self.add_tab(f"Tab {new_index}", self.current_directory)
                    self.tab_bar.setCurrentIndex(len(self.tab_states) - 1)
                    return True
                self.toggle_tab_pin(tab_index)
                return True

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                tab_index = self.tab_bar.tabAt(event.position().toPoint())
                if tab_index != -1:
                    self.close_tab(tab_index)
                    return True

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                self._tab_drag_index = -1

            if event.type() == QEvent.Type.ContextMenu:
                tab_index = self.tab_bar.tabAt(event.pos())
                if tab_index != -1:
                    self.tab_bar.setCurrentIndex(tab_index)

                menu = QMenu(self.tab_bar)
                action_new_tab = menu.addAction(
                    self._tab_menu_icon("tab-new", QStyle.StandardPixmap.SP_FileIcon),
                    "Neuer Tab",
                )
                action_close = menu.addAction(
                    self._tab_menu_icon("window-close", QStyle.StandardPixmap.SP_DialogCloseButton),
                    "Tab schließen",
                )
                action_close.setEnabled(
                    tab_index != -1
                    and len(self.tab_states) > 1
                    and not self.tab_states[tab_index].pinned
                )

                action_group = None
                if self.can_offer_grouping():
                    menu.addSeparator()
                    action_group = menu.addAction(
                        self._tab_menu_icon("view-split-left-right", QStyle.StandardPixmap.SP_ComputerIcon),
                        "Gruppieren",
                    )

                chosen_action = menu.exec(event.globalPos())
                if chosen_action == action_new_tab:
                    new_index = len(self.tab_states) + 1
                    self.add_tab(f"Tab {new_index}", self.current_directory)
                    self.tab_bar.setCurrentIndex(len(self.tab_states) - 1)
                    return True
                if chosen_action == action_close and tab_index != -1:
                    self.close_tab(tab_index)
                    return True
                if action_group is not None and chosen_action == action_group:
                    self.groupRequested.emit()
                    return True
                return True

        watched_views = tuple(view for view in (self.tree_view, self.icon_view) if view is not None)
        watched_viewports = tuple(view.viewport() for view in watched_views)

        if watched in watched_views:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Delete:
                    permanent_delete = True if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else None
                    self.delete_selected_paths(permanent=permanent_delete)
                    return True
                if event.matches(QKeySequence.StandardKey.Copy):
                    self.copy_selection_to_clipboard()
                    return True
                if event.matches(QKeySequence.StandardKey.Cut):
                    self.cut_selection_to_clipboard()
                    return True
                if event.matches(QKeySequence.StandardKey.Paste):
                    self.paste_from_clipboard()
                    return True
                if event.key() == Qt.Key.Key_Insert and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self.paste_from_clipboard()
                    return True
                if event.key() == Qt.Key.Key_D and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.duplicate_selection()
                    return True
                if event.key() == Qt.Key.Key_F5:
                    self.refresh_current_directory()
                    return True
                if event.key() == Qt.Key.Key_F2:
                    if self.selected_count() <= 1:
                        self.rename_current_item()
                        return True
                    return False
                if event.matches(QKeySequence.StandardKey.New):
                    self.create_file()
                    return True
                required_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                if event.key() == Qt.Key.Key_N and (event.modifiers() & required_modifiers) == required_modifiers:
                    self.create_folder()
                    return True

        if watched in watched_viewports:
            watched_view = next((view for view in watched_views if view.viewport() is watched), self.active_item_view())
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Delete:
                    permanent_delete = True if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else None
                    self.delete_selected_paths(permanent=permanent_delete)
                    return True
                if event.matches(QKeySequence.StandardKey.Copy):
                    self.copy_selection_to_clipboard()
                    return True
                if event.matches(QKeySequence.StandardKey.Cut):
                    self.cut_selection_to_clipboard()
                    return True
                if event.matches(QKeySequence.StandardKey.Paste):
                    self.paste_from_clipboard()
                    return True
                if event.key() == Qt.Key.Key_Insert and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self.paste_from_clipboard()
                    return True
                if event.key() == Qt.Key.Key_D and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self.duplicate_selection()
                    return True
                if event.key() == Qt.Key.Key_F5:
                    self.refresh_current_directory()
                    return True
                if event.key() == Qt.Key.Key_F2:
                    if self.selected_count() <= 1:
                        self.rename_current_item()
                        return True
                    return False
                if event.matches(QKeySequence.StandardKey.New):
                    self.create_file()
                    return True
                required_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                if event.key() == Qt.Key.Key_N and (event.modifiers() & required_modifiers) == required_modifiers:
                    self.create_folder()
                    return True

            if event.type() == QEvent.Type.Wheel and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                delta = event.angleDelta().y()
                if delta > 0:
                    self.adjust_icon_zoom(10)
                    return True
                if delta < 0:
                    self.adjust_icon_zoom(-10)
                    return True

            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                index = watched_view.indexAt(event.position().toPoint())
                if not index.isValid():
                    watched_view.clearSelection()
                    watched_view.setCurrentIndex(QModelIndex())
                    return True

            if event.type() == QEvent.Type.DragEnter:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(event, source_paths, target_dir)
                if self.can_accept_tree_drop(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_paths=source_paths,
                    target_dir=target_dir,
                ):
                    event.setDropAction(drop_action)
                    self.update_drop_target_visual(event.position().toPoint(), drop_action)
                    event.acceptProposedAction()
                    return True

            if event.type() == QEvent.Type.DragMove:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(event, source_paths, target_dir)
                if self.can_accept_tree_drop(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_paths=source_paths,
                    target_dir=target_dir,
                ):
                    event.setDropAction(drop_action)
                    self.update_drop_target_visual(event.position().toPoint(), drop_action)
                    event.acceptProposedAction()
                    return True
                self.clear_drop_target_visual()

            if event.type() == QEvent.Type.DragLeave:
                self.clear_drop_target_visual()
                return True

            if event.type() == QEvent.Type.Drop:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(event, source_paths, target_dir)
                event.setDropAction(drop_action)
                if self.handle_tree_drop(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    drop_action,
                    source_paths=source_paths,
                    target_dir=target_dir,
                ):
                    self.clear_drop_target_visual()
                    event.acceptProposedAction()
                    return True
                self.clear_drop_target_visual()

        return super().eventFilter(watched, event)

    def active_item_view(self):
        if self.filetree_view_mode == "icons" and self.icon_view is not None:
            return self.icon_view
        return self.tree_view

    def active_view_adapter(self):
        if self.filetree_view_mode == "icons" and self.icon_view_adapter is not None:
            return self.icon_view_adapter
        return self.tree_view_adapter

    def selected_paths(self):
        adapter = self.active_view_adapter()
        if adapter is None:
            return []
        return adapter.selected_paths()

    def selected_count(self):
        adapter = self.active_view_adapter()
        if adapter is None:
            return 0
        return adapter.selected_count()

    def copy_selection_to_clipboard(self):
        source_paths = self.selected_paths()
        if not source_paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in source_paths])
        mime_data.setData(self._CLIPBOARD_MIME_TYPE, json.dumps(source_paths).encode("utf-8"))
        mime_data.setData(self._CLIPBOARD_OPERATION_MIME_TYPE, b"copy")
        QApplication.clipboard().setMimeData(mime_data)
        self.clear_cut_state()
        self.show_operation_feedback(f"{len(source_paths)} Element(e) kopiert")

    def cut_selection_to_clipboard(self):
        source_paths = self.selected_paths()
        if not source_paths:
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path) for path in source_paths])
        mime_data.setData(self._CLIPBOARD_MIME_TYPE, json.dumps(source_paths).encode("utf-8"))
        mime_data.setData(self._CLIPBOARD_OPERATION_MIME_TYPE, b"cut")
        QApplication.clipboard().setMimeData(mime_data)
        self._cut_paths = set(source_paths)
        self.update_cut_visual_state()
        self.show_operation_feedback(f"{len(source_paths)} Element(e) ausgeschnitten")

    def extract_paths_from_mime(self, mime_data):
        if mime_data is None:
            return []

        paths = []
        if mime_data.hasFormat(self._CLIPBOARD_MIME_TYPE):
            raw = bytes(mime_data.data(self._CLIPBOARD_MIME_TYPE)).decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = []
            if isinstance(parsed, list):
                for item in parsed:
                    path = QDir.cleanPath(str(item))
                    if path:
                        paths.append(path)

        if mime_data.hasUrls():
            for url in mime_data.urls():
                if not url.isLocalFile():
                    continue
                path = QDir.cleanPath(url.toLocalFile())
                if path:
                    paths.append(path)

        return list(dict.fromkeys(paths))

    def extract_operation_from_mime(self, mime_data):
        if mime_data is None:
            return "copy"
        if not mime_data.hasFormat(self._CLIPBOARD_OPERATION_MIME_TYPE):
            return "copy"

        raw = bytes(mime_data.data(self._CLIPBOARD_OPERATION_MIME_TYPE)).decode("utf-8", errors="ignore").strip().lower()
        return "cut" if raw == "cut" else "copy"

    def extract_paths_from_drag_source(self, source_widget):
        if self.tree_view_adapter is None and self.icon_view_adapter is None:
            return []

        if self.tree_view_adapter is not None:
            tree_paths = self.tree_view_adapter.extract_paths_from_drag_source(source_widget)
            if tree_paths:
                return tree_paths

        if self.icon_view_adapter is not None:
            return self.icon_view_adapter.extract_paths_from_drag_source(source_widget)

        return []

    def resolve_drop_target_directory(self, pos=None, source_view=None):
        if source_view is self.icon_view and self.icon_view_adapter is not None:
            return self.icon_view_adapter.resolve_drop_target_directory(pos, self.current_directory)

        adapter = self.active_view_adapter()
        if adapter is None:
            return QDir.cleanPath(self.current_directory)
        return adapter.resolve_drop_target_directory(pos, self.current_directory)

    def copy_paths_to_directory(self, source_paths, target_directory):
        if not source_paths:
            return

        target_dir = QDir.cleanPath(target_directory)
        if not QDir(target_dir).exists():
            return

        changes_applied = False
        for source in source_paths:
            source_clean = QDir.cleanPath(source)
            if not Path(source_clean).exists():
                continue

            source_path = Path(source_clean)
            target_path = Path(target_dir) / source_path.name

            if QDir.cleanPath(str(target_path)) == source_clean:
                target_path = self.build_next_duplicate_path(source_path, Path(target_dir))
            if target_path.exists():
                continue

            try:
                self.file_operations.copy(source_path, target_path, overwrite=False)
                changes_applied = True
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        self.optimize_columns()
        if changes_applied:
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(f"{len(source_paths)} Element(e) kopiert")

    def build_next_duplicate_path(self, source_path, target_dir):
        source_name = source_path.name
        if source_path.is_file():
            stem = source_path.stem
            suffix = source_path.suffix
            candidate = target_dir / f"{stem} - Kopie{suffix}"
            counter = 2
            while candidate.exists():
                candidate = target_dir / f"{stem} - Kopie {counter}{suffix}"
                counter += 1
            return candidate

        candidate = target_dir / f"{source_name} - Kopie"
        counter = 2
        while candidate.exists():
            candidate = target_dir / f"{source_name} - Kopie {counter}"
            counter += 1
        return candidate

    def duplicate_selection(self):
        source_paths = self.selected_paths()
        if not source_paths:
            return False

        changes_applied = False
        for source in source_paths:
            source_clean = QDir.cleanPath(source)
            source_path = Path(source_clean)
            if not source_path.exists():
                continue

            target_dir = source_path.parent
            duplicate_target = self.build_next_duplicate_path(source_path, target_dir)
            try:
                self.file_operations.copy(source_path, duplicate_target, overwrite=False)
                changes_applied = True
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        if changes_applied:
            self.refresh_current_directory(preserve_focus=True)
            self.filesystemMutationCommitted.emit()
            self.optimize_columns()
            self.show_operation_feedback(f"{len(source_paths)} Element(e) dupliziert")

        return changes_applied

    def move_paths_to_directory(self, source_paths, target_directory):
        if not source_paths:
            return False

        target_dir = QDir.cleanPath(target_directory)
        if not QDir(target_dir).exists():
            return False

        changes_applied = False
        for source in source_paths:
            source_clean = QDir.cleanPath(source)
            if not Path(source_clean).exists():
                continue

            source_path = Path(source_clean)
            target_path = Path(target_dir) / source_path.name

            if QDir.cleanPath(str(target_path)) == source_clean:
                continue
            if target_path.exists():
                continue

            try:
                self.file_operations.move(source_path, target_path, overwrite=False)
                changes_applied = True
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        if changes_applied:
            self.refresh_current_directory(preserve_focus=True)
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(f"{len(source_paths)} Element(e) verschoben")
        return changes_applied

    def link_paths_to_directory(self, source_paths, target_directory):
        if not source_paths:
            return False

        target_dir = QDir.cleanPath(target_directory)
        if not QDir(target_dir).exists():
            return False

        changes_applied = False
        for source in source_paths:
            source_clean = QDir.cleanPath(source)
            source_path = Path(source_clean)
            if not source_path.exists():
                continue

            target_path = Path(target_dir) / source_path.name
            if target_path.exists():
                continue

            try:
                target_path.symlink_to(source_path)
                changes_applied = True
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        if changes_applied:
            self.refresh_current_directory()
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(f"{len(source_paths)} Verknüpfung(en) erstellt")
        return changes_applied

    def is_trash_context(self):
        current_path = Path(QDir.cleanPath(self.current_directory)).expanduser()

        local_trash_files = (Path.home() / ".local" / "share" / "Trash" / "files").resolve()
        try:
            resolved_current = current_path.resolve()
            if resolved_current == local_trash_files or local_trash_files in resolved_current.parents:
                return True
        except OSError:
            resolved_current = current_path

        parts = resolved_current.parts
        if len(parts) >= 2 and parts[-1] == "files":
            parent_name = parts[-2]
            if parent_name == "Trash" or parent_name.startswith(".Trash-"):
                return True

        return False

    def delete_selected_paths(self, permanent=None):
        selected = self.selected_paths()
        if not selected:
            return

        existing_selected = [target for target in selected if Path(QDir.cleanPath(target)).exists()]
        if not existing_selected:
            self.refresh_current_directory(preserve_focus=True)
            self.show_operation_feedback("Element bereits entfernt")
            return

        if permanent is None:
            permanent = self.is_trash_context()

        if len(existing_selected) == 1:
            target_label = Path(existing_selected[0]).name or existing_selected[0]
            if permanent:
                message = f"'{target_label}' dauerhaft löschen?"
            else:
                message = f"'{target_label}' in den Papierkorb verschieben?"
        else:
            if permanent:
                message = f"{len(existing_selected)} Elemente dauerhaft löschen?"
            else:
                message = f"{len(existing_selected)} Elemente in den Papierkorb verschieben?"

        confirmed = ask_yes_no(
            self.widget,
            "Dauerhaft löschen" if permanent else "In den Papierkorb verschieben",
            message,
            default_no=True,
        )
        if not confirmed:
            return

        changes_applied = False
        delete_errors = []
        for target in existing_selected:
            try:
                self.file_operations.delete(target, permanent=permanent)
                changes_applied = True
            except RuntimeError as error:
                delete_errors.append(str(error))
            except (FileNotFoundError, OSError, ValueError):
                continue

        if changes_applied:
            for view in (self.tree_view, self.icon_view):
                if view is None:
                    continue
                view.clearSelection()
                view.setCurrentIndex(QModelIndex())

            deleted_set = set(existing_selected)
            if deleted_set & self._cut_paths:
                self._cut_paths -= deleted_set
                self.update_cut_visual_state()

            self.refresh_current_directory()
            self.filesystemMutationCommitted.emit()
            action_text = "dauerhaft gelöscht" if permanent else "in den Papierkorb verschoben"
            self.show_operation_feedback(f"{len(existing_selected)} Element(e) {action_text}")

        if delete_errors:
            QMessageBox.warning(
                self.widget,
                "Löschen fehlgeschlagen",
                delete_errors[0],
            )

    def _trash_info_path_for(self, trashed_path):
        trashed = Path(QDir.cleanPath(str(trashed_path))).expanduser()
        parent_dir = trashed.parent
        if parent_dir.name != "files":
            return None

        info_dir = parent_dir.parent / "info"
        return info_dir / f"{trashed.name}.trashinfo"

    def _read_trash_original_path(self, trashed_path):
        info_path = self._trash_info_path_for(trashed_path)
        if info_path is None or not info_path.exists():
            return None

        try:
            with info_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("Path="):
                        raw_value = line.split("=", 1)[1].strip()
                        return Path(unquote(raw_value)).expanduser()
        except OSError:
            return None

        return None

    def _build_restore_target(self, original_path):
        target = Path(original_path)
        if not target.exists():
            return target

        if target.is_file():
            stem = target.stem
            suffix = target.suffix
            candidate = target.with_name(f"{stem} - Wiederhergestellt{suffix}")
            counter = 2
            while candidate.exists():
                candidate = target.with_name(f"{stem} - Wiederhergestellt {counter}{suffix}")
                counter += 1
            return candidate

        candidate = target.with_name(f"{target.name} - Wiederhergestellt")
        counter = 2
        while candidate.exists():
            candidate = target.with_name(f"{target.name} - Wiederhergestellt {counter}")
            counter += 1
        return candidate

    def restore_selected_from_trash(self):
        selected = self.selected_paths()
        if not selected:
            return

        restored_count = 0
        restore_errors = []
        for trashed in selected:
            trashed_path = Path(QDir.cleanPath(trashed))
            if not trashed_path.exists():
                continue

            original_path = self._read_trash_original_path(trashed_path)
            if original_path is None:
                restore_errors.append(f"Wiederherstellen fehlgeschlagen: Metadaten fehlen für '{trashed_path.name}'.")
                continue

            restore_target = self._build_restore_target(original_path)
            try:
                self.file_operations.move(trashed_path, restore_target, overwrite=False)
                info_path = self._trash_info_path_for(trashed_path)
                if info_path is not None and info_path.exists():
                    try:
                        info_path.unlink()
                    except OSError:
                        pass
                restored_count += 1
            except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
                restore_errors.append(f"Wiederherstellen fehlgeschlagen für '{trashed_path.name}': {error}")

        if restored_count > 0:
            self.refresh_current_directory(preserve_focus=True)
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(f"{restored_count} Element(e) wiederhergestellt")

        if restore_errors:
            QMessageBox.warning(
                self.widget,
                "Wiederherstellen fehlgeschlagen",
                restore_errors[0],
            )

    def paste_from_clipboard(self, target_directory=None):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        source_paths = self.extract_paths_from_mime(mime_data)
        if not source_paths:
            return

        destination = target_directory or self.resolve_drop_target_directory()
        operation = self.extract_operation_from_mime(mime_data)
        if operation == "cut":
            moved = self.move_paths_to_directory(source_paths, destination)
            if moved:
                clipboard.clear(mode=clipboard.Mode.Clipboard)
                self.clear_cut_state()
            return

        self.copy_paths_to_directory(source_paths, destination)

    def create_folder(self, target_directory=None, base_name="Neuer Ordner"):
        destination = QDir.cleanPath(target_directory or self.resolve_drop_target_directory())
        if not QDir(destination).exists():
            return None

        candidate = Path(destination) / base_name
        suffix = 2
        while candidate.exists():
            candidate = Path(destination) / f"{base_name} {suffix}"
            suffix += 1

        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except OSError:
            return None

        self._pending_created_item_path = QDir.cleanPath(str(candidate))
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback("Ordner erstellt")

        new_index = self.model.index(str(candidate))
        if new_index.isValid():
            adapter = self.active_view_adapter()
            active_view = self.active_item_view()
            if adapter is not None:
                adapter.select_single_index(new_index, focus=True)
            QTimer.singleShot(0, lambda idx=new_index, view=active_view: view.edit(idx) if view is not None else None)
            return candidate

        def select_later():
            later_index = self.model.index(str(candidate))
            if later_index.isValid():
                adapter = self.active_view_adapter()
                active_view = self.active_item_view()
                if adapter is not None:
                    adapter.select_single_index(later_index, focus=True)
                if active_view is not None:
                    active_view.edit(later_index)
            else:
                self._pending_created_item_path = None

        QTimer.singleShot(150, select_later)
        return candidate

    def create_file(self, target_directory=None, base_name="Neue Datei.txt"):
        destination = QDir.cleanPath(target_directory or self.resolve_drop_target_directory())
        if not QDir(destination).exists():
            return None

        base_stem = Path(base_name).stem or "Neue Datei"
        suffix = Path(base_name).suffix or ".txt"
        candidate = Path(destination) / f"{base_stem}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = Path(destination) / f"{base_stem} {counter}{suffix}"
            counter += 1

        try:
            candidate.touch(exist_ok=False)
        except OSError:
            return None

        self._pending_created_item_path = QDir.cleanPath(str(candidate))
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback("Datei erstellt")

        new_index = self.model.index(str(candidate))
        if new_index.isValid():
            adapter = self.active_view_adapter()
            active_view = self.active_item_view()
            if adapter is not None:
                adapter.select_single_index(new_index, focus=True)
            QTimer.singleShot(0, lambda idx=new_index, view=active_view: view.edit(idx) if view is not None else None)
            return candidate

        def select_later():
            later_index = self.model.index(str(candidate))
            if later_index.isValid():
                adapter = self.active_view_adapter()
                active_view = self.active_item_view()
                if adapter is not None:
                    adapter.select_single_index(later_index, focus=True)
                if active_view is not None:
                    active_view.edit(later_index)
            else:
                self._pending_created_item_path = None

        QTimer.singleShot(150, select_later)
        return candidate

    def current_or_selected_index(self):
        adapter = self.active_view_adapter()
        if adapter is None:
            return QModelIndex()
        return adapter.current_or_selected_index()

    def rename_current_item(self):
        # TODO: Multi-Renaming-Dialog (Batch-Rename) als eigener Workflow.
        if self.selected_count() > 1:
            return

        index = self.current_or_selected_index()
        if not index.isValid():
            return

        active_view = self.active_item_view()
        if active_view is None:
            return
        active_view.setCurrentIndex(index)
        active_view.edit(index)

    def on_model_file_renamed(self, directory_path, _old_name, _new_name):
        renamed_directory = QDir.cleanPath(str(directory_path))
        current_root = QDir.cleanPath(self.current_directory)

        if renamed_directory == current_root or renamed_directory.startswith(f"{current_root}/"):
            self.filesystemMutationCommitted.emit()

    def on_delegate_close_editor(self, _editor, _hint):
        created_path = self._pending_created_item_path
        if created_path:
            cancelled_new_item = _hint == QAbstractItemDelegate.EndEditHint.RevertModelCache
            self._pending_created_item_path = None

            if cancelled_new_item and Path(created_path).exists():
                try:
                    self.file_operations.delete(created_path, permanent=True)
                    self.refresh_current_directory()
                    self.filesystemMutationCommitted.emit()
                except (FileNotFoundError, OSError, ValueError):
                    pass

        QTimer.singleShot(0, lambda: self.active_item_view().setFocus(Qt.FocusReason.OtherFocusReason) if self.active_item_view() is not None else None)

    def resolve_drop_context(self, mime_data, pos, source_widget=None, source_view=None):
        source_paths = self.extract_paths_from_mime(mime_data)
        if not source_paths:
            source_paths = self.extract_paths_from_drag_source(source_widget)
        target_dir = self.resolve_drop_target_directory(pos, source_view=source_view)
        return source_paths, target_dir

    def can_accept_tree_drop(self, mime_data, pos, source_widget=None, source_paths=None, target_dir=None):
        if source_paths is None or target_dir is None:
            source_paths, target_dir = self.resolve_drop_context(mime_data, pos, source_widget)
        if not source_paths:
            self.clear_drop_target_visual()
            return False

        return QDir(target_dir).exists()

    def _is_same_filesystem(self, source_path, target_dir):
        try:
            return Path(source_path).resolve().stat().st_dev == Path(target_dir).resolve().stat().st_dev
        except OSError:
            return False

    def resolve_drop_action(self, event, source_paths=None, target_dir=None):
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return Qt.DropAction.LinkAction
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return Qt.DropAction.CopyAction
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return Qt.DropAction.MoveAction

        if source_paths and target_dir:
            same_fs = all(self._is_same_filesystem(source_path, target_dir) for source_path in source_paths)
            return Qt.DropAction.MoveAction if same_fs else Qt.DropAction.CopyAction

        return Qt.DropAction.MoveAction

    def update_drop_target_visual(self, pos, drop_action=None):
        if drop_action is None:
            drop_action = Qt.DropAction.MoveAction

        target_view = self.active_item_view()
        if target_view is None:
            return

        index = target_view.indexAt(pos)
        highlight_index = QModelIndex()
        highlight_root = False

        if index.isValid():
            target_path = QDir.cleanPath(self.model.filePath(index))
            if self.model.isDir(index) and QDir(target_path).exists():
                highlight_index = index
            else:
                parent_index = index.parent()
                if parent_index.isValid():
                    highlight_index = parent_index
                else:
                    highlight_root = True
        else:
            highlight_root = True

        self._drop_target_index = highlight_index if highlight_index.isValid() else QModelIndex()
        self._drop_target_is_root = highlight_root
        if target_view is self.tree_view:
            self._drop_target_delegate.set_drop_target_index(self._drop_target_index)
            self._drop_target_delegate.set_drop_action(drop_action)
        else:
            self._drop_target_delegate.clear_drop_target_index()
            self._drop_target_delegate.set_drop_action(Qt.DropAction.IgnoreAction)
        if self._drop_target_is_root:
            if drop_action == Qt.DropAction.CopyAction:
                target_view.viewport().setStyleSheet("background-color: rgba(128, 128, 128, 24); border: 1px dashed rgba(110, 110, 110, 120);")
            elif drop_action == Qt.DropAction.LinkAction:
                target_view.viewport().setStyleSheet("background-color: rgba(128, 128, 128, 18); border: 1px dotted rgba(110, 110, 110, 140);")
            else:
                target_view.viewport().setStyleSheet("background-color: rgba(128, 128, 128, 36); border: 1px solid rgba(110, 110, 110, 140);")
        else:
            target_view.viewport().setStyleSheet("")
        target_view.viewport().update()

    def clear_drop_target_visual(self):
        if not self._drop_target_index.isValid() and not self._drop_target_is_root:
            return

        self._drop_target_index = QModelIndex()
        self._drop_target_is_root = False
        self._drop_target_delegate.clear_drop_target_index()
        self._drop_target_delegate.set_drop_action(Qt.DropAction.IgnoreAction)
        for view in (self.tree_view, self.icon_view):
            if view is None:
                continue
            view.viewport().setStyleSheet("")
            view.viewport().update()

    def handle_tree_drop(
        self,
        mime_data,
        pos,
        source_widget=None,
        drop_action=Qt.DropAction.CopyAction,
        source_paths=None,
        target_dir=None,
    ):
        if source_paths is None or target_dir is None:
            source_paths, target_dir = self.resolve_drop_context(mime_data, pos, source_widget)
        if not source_paths:
            return False

        if not QDir(target_dir).exists():
            return False

        if drop_action == Qt.DropAction.LinkAction:
            return self.link_paths_to_directory(source_paths, target_dir)

        if drop_action == Qt.DropAction.MoveAction:
            return self.move_paths_to_directory(source_paths, target_dir)

        self.copy_paths_to_directory(source_paths, target_dir)
        return True

    def on_tree_context_menu(self, pos):
        source_view = self.sender() if isinstance(self.sender(), QAbstractItemView) else self.active_item_view()
        menu = QMenu(source_view)
        menu.setStyleSheet(
            "QMenu::separator {"
            "height: 1px;"
            "background: rgba(120, 120, 120, 180);"
            "margin: 4px 8px;"
            "}"
        )

        if self.is_trash_context():
            delete_icon = QIcon.fromTheme("edit-delete")
            if delete_icon.isNull():
                delete_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            action_delete = menu.addAction(delete_icon, "Löschen")
            action_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
            action_delete.setShortcutVisibleInContextMenu(True)

            restore_icon = QIcon.fromTheme("edit-undo")
            if restore_icon.isNull():
                restore_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
            action_restore = menu.addAction(restore_icon, "Wiederherstellen")

            has_selection = bool(self.selected_paths())
            action_delete.setEnabled(has_selection)
            action_restore.setEnabled(has_selection)

            chosen = menu.exec(source_view.viewport().mapToGlobal(pos))
            if chosen == action_delete:
                self.delete_selected_paths(permanent=True)
                return
            if chosen == action_restore:
                self.restore_selected_from_trash()
                return
            return

        new_folder_icon = QIcon.fromTheme("folder-new")
        if new_folder_icon.isNull():
            new_folder_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        action_new_folder = menu.addAction(new_folder_icon, "Neuer Ordner")
        action_new_folder.setShortcut(QKeySequence("Ctrl+Shift+N"))
        action_new_folder.setShortcutVisibleInContextMenu(True)
        destination_dir = self.resolve_drop_target_directory(pos, source_view=source_view)
        action_new_folder.setEnabled(QDir(destination_dir).exists())

        new_file_icon = QIcon.fromTheme("document-new")
        if new_file_icon.isNull():
            new_file_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_new_file = menu.addAction(new_file_icon, "Neue Datei")
        action_new_file.setShortcut(QKeySequence("Ctrl+N"))
        action_new_file.setShortcutVisibleInContextMenu(True)
        action_new_file.setEnabled(QDir(destination_dir).exists())

        menu.addSeparator()

        duplicate_icon = QIcon.fromTheme("edit-copy")
        if duplicate_icon.isNull():
            duplicate_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_duplicate = menu.addAction(duplicate_icon, "Duplizieren")
        action_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        action_duplicate.setShortcutVisibleInContextMenu(True)

        copy_icon = QIcon.fromTheme("edit-copy")
        if copy_icon.isNull():
            copy_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_copy = menu.addAction(copy_icon, "Kopieren")
        action_copy.setShortcut(QKeySequence.StandardKey.Copy)
        action_copy.setShortcutVisibleInContextMenu(True)

        cut_icon = QIcon.fromTheme("edit-cut")
        if cut_icon.isNull():
            cut_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        action_cut = menu.addAction(cut_icon, "Ausschneiden")
        action_cut.setShortcut(QKeySequence.StandardKey.Cut)
        action_cut.setShortcutVisibleInContextMenu(True)

        selection_model = source_view.selectionModel()
        selected_indexes = selection_model.selectedIndexes() if selection_model is not None else []
        has_selection = bool(selected_indexes)
        action_duplicate.setEnabled(has_selection)
        action_copy.setEnabled(has_selection)
        action_cut.setEnabled(has_selection)

        paste_icon = QIcon.fromTheme("edit-paste")
        if paste_icon.isNull():
            paste_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        action_paste = menu.addAction(paste_icon, "Einfügen")
        action_paste.setShortcut(QKeySequence.StandardKey.Paste)
        action_paste.setShortcutVisibleInContextMenu(True)

        menu.addSeparator()

        rename_icon = QIcon.fromTheme("edit-rename")
        if rename_icon.isNull():
            rename_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        action_rename = menu.addAction(rename_icon, "Umbenennen")
        action_rename.setShortcut(QKeySequence(Qt.Key.Key_F2))
        action_rename.setShortcutVisibleInContextMenu(True)

        delete_icon = QIcon.fromTheme("edit-delete")
        if delete_icon.isNull():
            delete_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        action_delete = menu.addAction(delete_icon, "Löschen")
        action_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        action_delete.setShortcutVisibleInContextMenu(True)
        action_delete.setEnabled(bool(self.selected_paths()))

        menu.addSeparator()

        refresh_icon = QIcon.fromTheme("view-refresh")
        if refresh_icon.isNull():
            refresh_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        action_refresh = menu.addAction(refresh_icon, "Aktualisieren")
        action_refresh.setShortcut(QKeySequence(Qt.Key.Key_F5))
        action_refresh.setShortcutVisibleInContextMenu(True)

        current_index = self.current_or_selected_index()
        action_rename.setEnabled(current_index.isValid() and self.selected_count() <= 1)

        clipboard_paths = self.extract_paths_from_mime(QApplication.clipboard().mimeData())
        action_paste.setEnabled(bool(clipboard_paths) and QDir(destination_dir).exists())

        chosen = menu.exec(source_view.viewport().mapToGlobal(pos))
        if chosen == action_refresh:
            self.refresh_current_directory()
            return
        if chosen == action_new_folder:
            self.create_folder(destination_dir)
            return
        if chosen == action_new_file:
            self.create_file(destination_dir)
            return
        if chosen == action_copy:
            self.copy_selection_to_clipboard()
            return
        if chosen == action_cut:
            self.cut_selection_to_clipboard()
            return
        if chosen == action_duplicate:
            self.duplicate_selection()
            return
        if chosen == action_paste:
            self.paste_from_clipboard(destination_dir)
            return
        if chosen == action_delete:
            self.delete_selected_paths(permanent=None)
            return
        if chosen == action_rename:
            self.rename_current_item()
            return

    def start_tab_path_drag(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return

        state = self.tab_states[tab_index]
        path = QDir.cleanPath(state.path)
        if not QDir(path).exists():
            return

        mime_data = QMimeData()
        mime_data.setUrls([QUrl.fromLocalFile(path)])

        drag = QDrag(self.tab_bar)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

    def can_offer_grouping(self):
        if not self.parent() or not hasattr(self.parent(), "can_offer_grouping"):
            return False
        return bool(self.parent().can_offer_grouping(self))

    def clone_tab_states(self):
        self.capture_tab_state(self.active_tab_index)
        return [
            TabState(
                title=state.title,
                path=state.path,
                pinned=state.pinned,
                view_mode=state.view_mode,
                icon_zoom_percent=getattr(state, "icon_zoom_percent", 100),
                history=list(state.history),
                scroll_value=state.scroll_value,
                selected_paths=list(state.selected_paths),
            )
            for state in self.tab_states
        ]

    def replace_tabs(self, states, active_index=0):
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(self.tab_bar.count() - 1)
        self.tab_states = []
        self.active_tab_index = -1

        for state in states:
            self.tab_states.append(
                TabState(
                    title=state.title,
                    path=QDir.cleanPath(state.path),
                    pinned=bool(getattr(state, "pinned", False)),
                    view_mode=state.view_mode,
                    icon_zoom_percent=int(getattr(state, "icon_zoom_percent", 100)),
                    history=list(state.history),
                    scroll_value=state.scroll_value,
                    selected_paths=list(state.selected_paths),
                )
            )
            index = self.tab_bar.addTab(state.title)
            self.update_tab_visual(index)

        self.tab_bar.blockSignals(False)

        if not self.tab_states:
            self.add_tab("Tab 1", QDir.homePath())
            return

        active_index = max(0, min(active_index, len(self.tab_states) - 1))
        self.active_tab_index = active_index

        self._restoring_tab_switch = True
        self.tab_bar.setCurrentIndex(active_index)
        self._restoring_tab_switch = False

        self.apply_tab_state(self.tab_states[active_index], push_history=False)

    def move_tabs_out_and_reset(self, default_path):
        exported_states = self.clone_tab_states()
        exported_active_index = self.active_tab_index if self.active_tab_index >= 0 else 0

        clean_default = QDir.cleanPath(default_path)
        self.replace_tabs(
            [TabState(title="Tab 1", path=clean_default, view_mode="details")],
            active_index=0,
        )
        return exported_states, exported_active_index

    def capture_tab_state(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return

        state = self.tab_states[tab_index]
        state.path = self.current_directory
        state.view_mode = self.filetree_view_mode
        state.icon_zoom_percent = self.icon_zoom_percent

        active_view = self.active_item_view()
        scrollbar = active_view.verticalScrollBar() if active_view is not None else None
        if scrollbar:
            state.scroll_value = scrollbar.value()

        state.selected_paths = self.selected_paths()

    def apply_tab_state(self, state, push_history=False):
        self.icon_zoom_percent = max(50, min(300, int(getattr(state, "icon_zoom_percent", 100))))
        self.apply_view_mode(state.view_mode)
        self.navigate_to(state.path, push_history=push_history)

        self._pending_restore_selection = list(state.selected_paths)
        self._pending_restore_scroll = state.scroll_value
        QTimer.singleShot(0, self.apply_pending_restore_state)
        QTimer.singleShot(0, self.optimize_columns)

    def apply_pending_restore_state(self):
        if self._pending_restore_selection:
            first_path = self._pending_restore_selection[0]
            index = self.model.index(first_path)
            if index.isValid():
                adapter = self.active_view_adapter()
                if adapter is not None:
                    adapter.select_single_index(index, focus=False)

        active_view = self.active_item_view()
        scrollbar = active_view.verticalScrollBar() if active_view is not None else None
        if scrollbar:
            scrollbar.setValue(self._pending_restore_scroll)

        self._pending_restore_selection = []
        self._pending_restore_scroll = 0

    def on_tree_double_click(self, index):
        if not index.isValid():
            return

        path = self.model.filePath(index)
        if self.model.isDir(index):
            self.navigate_to(path)
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def navigate_to(self, path, push_history=True):
        target_path = QDir.cleanPath(path)
        if not QDir(target_path).exists():
            return

        active_state = self.get_active_tab_state()
        if active_state is None:
            return

        if active_state.pinned and target_path != active_state.path:
            tab_title = Path(target_path).name or target_path
            self.add_tab(tab_title, target_path)

            new_index = len(self.tab_states) - 1
            if new_index >= 0:
                new_state = self.tab_states[new_index]
                new_state.view_mode = active_state.view_mode
                new_state.icon_zoom_percent = active_state.icon_zoom_percent
                if push_history and active_state.path:
                    new_state.history.append(active_state.path)
                self.tab_bar.setCurrentIndex(new_index)
            return

        if push_history and target_path != active_state.path:
            active_state.history.append(active_state.path)

        active_state.path = target_path
        self.current_directory = target_path

        tab_title = Path(target_path).name or target_path
        active_state.title = tab_title
        if self.active_tab_index >= 0:
            self.tab_bar.setTabText(self.active_tab_index, tab_title)
            self.update_tab_visual(self.active_tab_index)

        self._pending_root_path = target_path
        root_index = self.model.setRootPath(target_path)
        index = root_index if root_index.isValid() else self.model.index(target_path)
        if index.isValid():
            self.tree_view.setRootIndex(index)
            self.tree_view.expand(index)
            if self.icon_view is not None:
                self.icon_view.setRootIndex(index)

        if self.path_bar:
            self.path_bar.set_path(target_path)

        self.currentPathChanged.emit(target_path)
        self.emit_navigation_state()

    def navigate_back(self):
        active_state = self.get_active_tab_state()
        if not active_state or not active_state.history:
            return

        previous_path = active_state.history.pop()
        self.navigate_to(previous_path, push_history=False)

    def navigate_up(self):
        current = QDir.cleanPath(self.current_directory)
        parent = QDir.cleanPath(str(Path(current).parent))
        if parent == current:
            return
        self.navigate_to(parent)

    def can_go_back(self):
        active_state = self.get_active_tab_state()
        return bool(active_state and active_state.history)

    def can_go_up(self):
        current = QDir.cleanPath(self.current_directory)
        parent = QDir.cleanPath(str(Path(current).parent))
        return parent != current

    def current_path(self):
        return self.current_directory

    def current_view_mode(self):
        return self.filetree_view_mode

    def apply_view_mode(self, mode):
        if mode not in {"details", "list", "icons"}:
            return

        self.filetree_view_mode = mode
        active_state = self.get_active_tab_state()
        if active_state:
            active_state.view_mode = mode

        if mode in self.view_mode_actions:
            self.view_mode_actions[mode].setChecked(True)
        if self.btn_view_mode and mode in self.view_mode_icons:
            self.btn_view_mode.setIcon(self.view_mode_icons[mode])

        if mode == "icons":
            if self.view_stack is not None and self.icon_view is not None:
                self.view_stack.setCurrentWidget(self.icon_view)
            self.apply_icon_zoom()
            self.optimize_columns()
            return

        if self.view_stack is not None:
            self.view_stack.setCurrentWidget(self.tree_view)

        if mode == "details":
            self.tree_view.setRootIsDecorated(True)
            self.tree_view.setItemsExpandable(True)
            self.tree_view.setIndentation(self._default_indentation)
            for column in range(self.model.columnCount()):
                self.tree_view.setColumnHidden(column, False)
            self.apply_icon_zoom()
            self.optimize_columns()
            return

        self.tree_view.setRootIsDecorated(False)
        self.tree_view.setItemsExpandable(False)
        self.tree_view.setIndentation(0)
        for column in range(1, self.model.columnCount()):
            self.tree_view.setColumnHidden(column, True)

        self.apply_icon_zoom()

        self.optimize_columns()

    def _base_icon_size_px(self):
        if self.filetree_view_mode == "icons":
            return 48
        return max(12, self._default_icon_size.width())

    def apply_icon_zoom(self):
        base_px = self._base_icon_size_px()
        icon_px = int(round(base_px * (self.icon_zoom_percent / 100.0)))
        icon_px = max(12, min(256, icon_px))
        self.tree_view.setIconSize(QSize(icon_px, icon_px))
        if self.icon_view is not None:
            self.icon_view.setIconSize(QSize(icon_px, icon_px))
            self.icon_view.setGridSize(QSize(icon_px + 48, icon_px + 44))

        active_state = self.get_active_tab_state()
        if active_state is not None:
            active_state.icon_zoom_percent = self.icon_zoom_percent

    def adjust_icon_zoom(self, delta_percent):
        try:
            delta = int(delta_percent)
        except (TypeError, ValueError):
            return

        new_zoom = max(50, min(300, self.icon_zoom_percent + delta))
        if new_zoom == self.icon_zoom_percent:
            return

        self.icon_zoom_percent = new_zoom
        self.apply_icon_zoom()
        self.optimize_columns()

    def reset_view_to_default(self):
        self.icon_zoom_percent = 100
        self.apply_view_mode("details")

    def optimize_columns(self):
        if self.tree_view is None:
            return

        if self.filetree_view_mode == "icons":
            if self.icon_view is not None:
                try:
                    self.icon_view.update()
                except RuntimeError:
                    return
            return

        try:
            if self.filetree_view_mode == "details":
                for column in range(self.model.columnCount()):
                    self.tree_view.resizeColumnToContents(column)
            else:
                self.tree_view.resizeColumnToContents(0)
        except RuntimeError:
            return

    def apply_current_sort(self):
        if self.tree_view is None:
            return

        try:
            header = self.tree_view.header()
        except RuntimeError:
            return
        if header is None:
            return

        section = header.sortIndicatorSection()
        order = header.sortIndicatorOrder()
        try:
            self.model.sort(section, order)
            self.tree_view.sortByColumn(section, order)
        except RuntimeError:
            return

    def force_resort(self):
        if self.tree_view is None:
            return

        try:
            header = self.tree_view.header()
        except RuntimeError:
            return
        if header is None:
            return

        section = header.sortIndicatorSection()
        order = header.sortIndicatorOrder()
        opposite_order = (
            Qt.SortOrder.DescendingOrder
            if order == Qt.SortOrder.AscendingOrder
            else Qt.SortOrder.AscendingOrder
        )

        try:
            self.tree_view.sortByColumn(section, opposite_order)
            self.tree_view.sortByColumn(section, order)
        except RuntimeError:
            return

    def commit_pending_tree_edit(self):
        focused_widget = QApplication.focusWidget()
        if focused_widget is None:
            return
        active_view = self.active_item_view()
        if active_view is not None and active_view.isAncestorOf(focused_widget):
            focused_widget.clearFocus()

    def refresh_current_directory(self, preserve_focus=False):
        focused_widget = QApplication.focusWidget()
        active_view = self.active_item_view()
        should_restore_focus = bool(
            preserve_focus
            or (active_view is not None and focused_widget is not None and active_view.isAncestorOf(focused_widget))
        )

        self.commit_pending_tree_edit()
        self.navigate_to(self.current_directory, push_history=False)
        self.apply_current_sort()
        self.force_resort()
        QTimer.singleShot(150, self.apply_current_sort)
        QTimer.singleShot(200, self.force_resort)
        if should_restore_focus:
            QTimer.singleShot(
                0,
                lambda: self.active_item_view().setFocus(Qt.FocusReason.OtherFocusReason)
                if self.active_item_view() is not None
                else None,
            )

    def get_active_tab_state(self):
        if self.active_tab_index < 0 or self.active_tab_index >= len(self.tab_states):
            return None
        return self.tab_states[self.active_tab_index]

    def emit_navigation_state(self):
        self.navigationStateChanged.emit(self.can_go_back(), self.can_go_up())

    def export_state(self):
        self.capture_tab_state(self.active_tab_index)
        return {
            "active_tab_index": self.active_tab_index,
            "tabs": [
                {
                    "title": state.title,
                    "path": state.path,
                    "pinned": state.pinned,
                    "view_mode": state.view_mode,
                    "icon_zoom_percent": state.icon_zoom_percent,
                    "history": list(state.history),
                    "scroll_value": state.scroll_value,
                    "selected_paths": list(state.selected_paths),
                }
                for state in self.tab_states
            ],
        }

    def import_state(self, state_data):
        if not isinstance(state_data, dict):
            return

        raw_tabs = state_data.get("tabs")
        if not isinstance(raw_tabs, list) or not raw_tabs:
            return

        restored_states: list[TabState] = []
        for tab in raw_tabs:
            if not isinstance(tab, dict):
                continue

            path = QDir.cleanPath(str(tab.get("path") or QDir.homePath()))
            if not QDir(path).exists():
                path = QDir.homePath()

            title = str(tab.get("title") or (Path(path).name or path))
            view_mode = str(tab.get("view_mode") or "details")
            if view_mode not in {"details", "list", "icons"}:
                view_mode = "details"

            raw_zoom = tab.get("icon_zoom_percent", 100)
            try:
                icon_zoom_percent = int(raw_zoom)
            except (TypeError, ValueError):
                icon_zoom_percent = 100
            icon_zoom_percent = max(50, min(300, icon_zoom_percent))

            history = tab.get("history")
            clean_history = []
            if isinstance(history, list):
                for item in history:
                    clean_item = QDir.cleanPath(str(item))
                    if QDir(clean_item).exists():
                        clean_history.append(clean_item)

            selected_paths = tab.get("selected_paths")
            clean_selected = []
            if isinstance(selected_paths, list):
                for item in selected_paths:
                    clean_item = QDir.cleanPath(str(item))
                    if QDir(clean_item).exists():
                        clean_selected.append(clean_item)

            scroll_value = int(tab.get("scroll_value") or 0)

            restored_states.append(
                TabState(
                    title=title,
                    path=path,
                    pinned=bool(tab.get("pinned", False)),
                    view_mode=view_mode,
                    icon_zoom_percent=icon_zoom_percent,
                    history=clean_history,
                    scroll_value=max(0, scroll_value),
                    selected_paths=clean_selected,
                )
            )

        if not restored_states:
            return

        raw_active_index = state_data.get("active_tab_index", 0)
        try:
            active_index = int(raw_active_index)
        except (TypeError, ValueError):
            active_index = 0

        active_index = max(0, min(active_index, len(restored_states) - 1))
        self.replace_tabs(restored_states, active_index=active_index)

    def toggle_tab_pin(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return
        state = self.tab_states[tab_index]
        state.pinned = not state.pinned
        self.update_tab_visual(tab_index)

    def update_tab_visual(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return
        state = self.tab_states[tab_index]
        self.tab_bar.setTabText(tab_index, state.title)
        self.tab_bar.setTabIcon(tab_index, self._pin_icon if state.pinned else QIcon())
