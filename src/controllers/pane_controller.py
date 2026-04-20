import os
import shlex
import json
import hashlib
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QDateTime, QDir, QEvent, QObject, QRect, QSize, Qt, QTimer, Signal, QPoint, QMimeData, QUrl, QModelIndex, QProcess, QThread, QItemSelectionModel
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QDesktopServices, QIcon, QDrag, QKeySequence, QPen
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication, QAbstractItemDelegate, QAbstractItemView, QFileDialog, QHBoxLayout, QInputDialog, QLineEdit, QListView, QMenu, QMessageBox, QProgressDialog, QSizePolicy, QStackedWidget, QStyle, QStyledItemDelegate, QTabBar, QToolButton, QToolTip, QTreeView, QTreeWidget, QTreeWidgetItem, QWidget, QRubberBand

try:
    from PySide6.QtDBus import QDBusConnection, QDBusMessage, QDBusPendingCallWatcher
except ImportError:
    QDBusConnection = None
    QDBusMessage = None
    QDBusPendingCallWatcher = None

from localization import app_tr, ask_yes_no
from debug_log import debug_log, debug_mime_data
from backends.local import LocalFileSystemBackend
from controllers.remote_drive_controller import RemoteDriveController
from controllers.view_adapters import IconViewAdapter, TreeViewAdapter
from domain.filesystem import PaneLocation
from models.file_operations import FileOperations
from models.remote_external_drag_model import RemoteExternalDragModel
from models.remote_file_tree_model import RemoteFileItem, RemoteFileTreeModel
from services.file_actions import (
    ArkDropService,
    ArchiveService,
    BatchRenameService,
    CreationService,
    DeleteService,
    DropService,
    DropUiService,
    FileOperationService,
    FileOperationWorker,
    LinkService,
    OpenService,
    TransferService,
    TrashRestoreService,
)
from services.dragdrop import (
    DragDropContext,
    DragMimeCodec,
    DragPayload,
    DragSessionService,
    DragVisualService,
    DropExecutionService,
    DropTargetService,
    RemoteDragGuard,
)
from services.navigation import HistoryService, PaneNavigationService, PaneStateService, SelectionRestoreService
from services.transfer import RemoteTransferCoordinator, RemoteTransferService
from widgets.batch_rename_dialog import BatchRenameDialog
from widgets.path_bar import PathBar
from widgets.properties_dialog import PropertiesDialog
from utils.open_with import applications_for_path
from models.pane_tab_state import TabState


class RecursiveSearchWorker(QObject):
    finished = Signal(list)

    def __init__(self, root_path, query, parent=None):
        super().__init__(parent)
        self._root_path = QDir.cleanPath(str(root_path))
        self._query = str(query or "").strip().lower()

    def run(self):
        results = []
        if not self._root_path or not self._query or not Path(self._root_path).exists():
            self.finished.emit(results)
            return

        for dir_path, dir_names, file_names in os.walk(self._root_path):
            for name in dir_names:
                if self._query in name.lower():
                    results.append((QDir.cleanPath(str(Path(dir_path) / name)), True))
            for name in file_names:
                if self._query in name.lower():
                    results.append((QDir.cleanPath(str(Path(dir_path) / name)), False))

        results.sort(key=lambda item: item[0].lower())
        self.finished.emit(results)


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
    _REMOTE_EXPORT_STAGING_MAX_AGE_SECONDS = 7 * 24 * 60 * 60

    currentPathChanged = Signal(str)
    navigationStateChanged = Signal(bool, bool)
    groupRequested = Signal()
    filesystemMutationCommitted = Signal()
    operationFeedback = Signal(str)
    _CLIPBOARD_MIME_TYPE = "application/x-tablion-copy-paths"
    _CLIPBOARD_OPERATION_MIME_TYPE = "application/x-tablion-clipboard-operation"
    _REMOTE_CLIPBOARD_MIME_TYPE = "application/x-tablion-remote-locations"
    _INTERNAL_DRAG_MIME_TYPE = "application/x-tablion-internal-paths"
    _ARK_DND_SERVICE_MIME = "application/x-kde-ark-dndextract-service"
    _ARK_DND_PATH_MIME = "application/x-kde-ark-dndextract-path"
    _ARCHIVE_SAVE_FILTERS = (
        ("ZIP (*.zip)", ".zip"),
        ("TAR.GZ (*.tar.gz)", ".tar.gz"),
        ("TAR.XZ (*.tar.xz)", ".tar.xz"),
        ("TAR.BZ2 (*.tar.bz2)", ".tar.bz2"),
        ("TAR (*.tar)", ".tar"),
    )
    _BASE_FILE_FILTER = QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot

    def prepare_for_dispose(self):
        if getattr(self, "_dispose_prepared", False):
            return
        self._dispose_prepared = True

        if self._file_operation_progress_dialog is not None:
            try:
                self._file_operation_progress_dialog.close()
            except RuntimeError:
                pass
        self._stop_file_operation_thread(wait_forever=True)
        self._cleanup_file_operation_state()

        if self._search_thread is not None:
            try:
                self._search_thread.quit()
                self._search_thread.wait()
            except RuntimeError:
                pass
            self._search_thread = None
            self._search_worker = None

        self._ark_drop_watchers.clear()

        if self._selection_rubber_band is not None:
            try:
                self._selection_rubber_band.hide()
            except RuntimeError:
                pass
        self._selection_rubber_origin = None
        self._selection_rubber_viewport = None

        for view in (self.tree_view, self.icon_view):
            if view is None:
                continue
            try:
                view.removeEventFilter(self)
            except RuntimeError:
                pass

            try:
                viewport = view.viewport()
            except RuntimeError:
                viewport = None
            if viewport is not None:
                try:
                    viewport.removeEventFilter(self)
                except RuntimeError:
                    pass

        if self.tab_bar is not None:
            try:
                self.tab_bar.removeEventFilter(self)
            except RuntimeError:
                pass

        if self.search_line_edit is not None:
            try:
                self.search_line_edit.removeEventFilter(self)
            except RuntimeError:
                pass

        try:
            QApplication.clipboard().dataChanged.disconnect(self.on_clipboard_data_changed)
        except (TypeError, RuntimeError):
            pass
        if self.model is not None:
            try:
                self.model.fileRenamed.disconnect(self.on_model_file_renamed)
            except (TypeError, RuntimeError):
                pass
            if getattr(self, "_directory_loaded_handler", None) is not None:
                try:
                    self.model.directoryLoaded.disconnect(self._directory_loaded_handler)
                except (TypeError, RuntimeError):
                    pass
                self._directory_loaded_handler = None

    def __init__(
        self,
        file_system_model,
        parent=None,
        editor_settings=None,
        remote_drive_controller: RemoteDriveController | None = None,
        local_office_web_session_store=None,
    ):
        super().__init__(parent)
        loader = QUiLoader()
        pane_ui_path = Path(__file__).resolve().parent.parent / "ui" / "pane.ui"
        self.widget = loader.load(str(pane_ui_path))
        if self.widget is None:
            raise RuntimeError(f"Konnte Pane UI nicht laden: {pane_ui_path}")
        self.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.model = file_system_model
        self._remote_drive_controller = remote_drive_controller
        self._remote_model = RemoteFileTreeModel(self)
        self._remote_external_drag_model = RemoteExternalDragModel(
            remote_clipboard_mime_type=self._REMOTE_CLIPBOARD_MIME_TYPE,
            clipboard_operation_mime_type=self._CLIPBOARD_OPERATION_MIME_TYPE,
            parent=self,
        )
        self._remote_external_drag_model.setRootPath(QDir.rootPath())
        self._remote_external_drag_model.setReadOnly(False)
        self._remote_external_drag_model.setFilter(QDir.Filter.AllEntries | QDir.NoDotAndDotDot)
        self.file_operations = FileOperations()
        self._local_backend = LocalFileSystemBackend()
        self._open_service = OpenService()
        self._delete_service = DeleteService()
        self._batch_rename_service = BatchRenameService()
        self._archive_service = ArchiveService()
        self._ark_drop_service = ArkDropService()
        self._creation_service = CreationService()
        self._file_operation_service = FileOperationService()
        self._drop_service = DropService()
        self._drop_ui_service = DropUiService()
        self._link_service = LinkService()
        self._transfer_service = TransferService()
        self._trash_restore_service = TrashRestoreService()
        self._navigation_service = PaneNavigationService(self._local_backend)
        self._history_service = HistoryService()
        self._pane_state_service = PaneStateService()
        self._selection_restore_service = SelectionRestoreService()
        self._drag_mime_codec = DragMimeCodec(
            self._transfer_service,
            clipboard_mime_type=self._CLIPBOARD_MIME_TYPE,
            clipboard_operation_mime_type=self._CLIPBOARD_OPERATION_MIME_TYPE,
            remote_clipboard_mime_type=self._REMOTE_CLIPBOARD_MIME_TYPE,
            internal_drag_mime_type=self._INTERNAL_DRAG_MIME_TYPE,
            ark_dnd_service_mime=self._ARK_DND_SERVICE_MIME,
            ark_dnd_path_mime=self._ARK_DND_PATH_MIME,
        )
        self._remote_drag_guard = RemoteDragGuard()
        self._drag_visual_service = DragVisualService()
        self._drag_session_service = DragSessionService(
            self._drag_mime_codec,
            self._drag_visual_service,
            self._remote_drag_guard,
            build_external_remote_mime_data=self._build_external_remote_drag_mime_data,
        )
        self._drop_target_service = DropTargetService(self._drop_service)
        self._drop_execution_service = DropExecutionService(self._drop_service)
        self._remote_transfer_service = RemoteTransferService()
        self._remote_transfer_coordinator = RemoteTransferCoordinator(self._remote_transfer_service)
        self.path_bar = None
        self.btn_search = None
        self.btn_view_mode = None
        self.view_mode_actions = {}
        self.view_mode_icons = {}
        self._action_reset_view = None
        self._action_show_hidden_files = None
        self._editor_settings = editor_settings
        self._local_office_web_session_store = local_office_web_session_store
        self.tab_states: list[TabState] = []
        self.active_tab_index = -1
        self._restoring_tab_switch = False
        self._tab_drag_index = -1
        self._tab_drag_start_pos = QPoint()
        self._tab_reorder_drag_active = False
        self._pending_reordered_tab_apply = False
        self._pin_icon = QIcon.fromTheme("pin")
        if self._pin_icon.isNull():
            self._pin_icon = QIcon.fromTheme("emblem-favorite")
        if self._pin_icon.isNull():
            self._pin_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)

        self.current_directory = QDir.homePath()
        self.current_location = PaneLocation(kind="local", path=self.current_directory)
        self.filetree_view_mode = "details"
        self._pending_root_path = None
        self._pending_created_item_path = None
        self._drop_target_index = QModelIndex()
        self._drop_target_is_root = False
        self._cut_paths: set[str] = set()
        self.tree_view_adapter = None
        self.icon_view_adapter = None
        self._selection_rubber_band = None
        self._selection_rubber_origin = None
        self._selection_rubber_viewport = None
        self._file_operation_thread = None
        self._file_operation_worker = None
        self._file_operation_progress_dialog = None
        self._pending_file_operation = None
        self._search_thread = None
        self._search_worker = None
        self._ark_drop_watchers = set()
        self._dispose_prepared = False
        self._directory_loaded_handler = None
        configured_columns = getattr(self._editor_settings, "visible_file_tree_columns", [0, 1, 2, 3])
        self._visible_tree_columns = self._normalize_visible_tree_columns(configured_columns)

        self.tab_bar_host = self.widget.findChild(QWidget, "tabBarHost")
        self.tab_bar = None
        self.tree_view = self.widget.findChild(QTreeView, "fileTree")
        self.icon_view = None
        self.view_stack = None
        self.btn_nav_back = self.widget.findChild(QToolButton, "btnPaneNavBack")
        self.btn_nav_up = self.widget.findChild(QToolButton, "btnPaneNavUp")
        self.path_bar_container = self.widget.findChild(QWidget, "pathBarContainer")
        self.btn_view_mode = self.widget.findChild(QToolButton, "btnViewMode")
        self.search_bar_widget = None
        self.search_line_edit = None
        self.search_results_view = None

        if not self.tab_bar_host or not self.tree_view or not self.path_bar_container:
            raise RuntimeError("Pane UI ist unvollständig (tabBar/treeView/pathBarContainer fehlt)")

        self.setup_tab_bar_host()

        self._default_icon_size = self.tree_view.iconSize()
        self._default_indentation = self.tree_view.indentation()
        self.icon_zoom_percent = 100
        self._show_hidden_files = bool(getattr(self._editor_settings, "show_hidden_files", False))

        self.setup_tree_view()
        self.setup_navigation_buttons()
        self.setup_path_bar()
        self.setup_view_mode_button()
        self.setup_tab_bar()
        self.setup_search_ui()
        self.set_show_hidden_files(self._show_hidden_files, persist=False, refresh=False)

        self.add_tab("Tab 1", self.current_location)

    def _active_file_model(self):
        if self.current_location is not None and self.current_location.is_remote:
            return self._remote_model
        return self.model

    def _apply_browser_model(self, model) -> None:
        if self.tree_view is not None and self.tree_view.model() is not model:
            self.tree_view.setModel(model)
        if self.icon_view is not None and self.icon_view.model() is not model:
            self.icon_view.setModel(model)
            self.icon_view.setModelColumn(0)

        if self.tree_view_adapter is not None:
            self.tree_view_adapter.file_model = model
        if self.icon_view_adapter is not None:
            self.icon_view_adapter.file_model = model
        if getattr(self, "_drop_target_delegate", None) is not None:
            self._drop_target_delegate._file_model = model
        if getattr(self, "_icon_view_delegate", None) is not None:
            self._icon_view_delegate._file_model = model

    def _set_remote_view_interaction_enabled(self, enabled: bool) -> None:
        for view in (self.tree_view, self.icon_view):
            if view is None:
                continue
            view.setDragEnabled(enabled)
            view.setAcceptDrops(enabled)
            view.viewport().setAcceptDrops(enabled)
            view.setDropIndicatorShown(enabled)

    def _path_bar_root_label_for_location(self, location: PaneLocation) -> str:
        if location.is_remote and self._remote_drive_controller is not None:
            return self._remote_drive_controller.display_name_for_location(location)
        return ""

    def _treat_remote_dot_entries_as_hidden(self) -> bool:
        return bool(getattr(self._editor_settings, "treat_dot_entries_as_hidden_remote", False))

    def _is_remote_hidden_entry(self, entry) -> bool:
        if not self._treat_remote_dot_entries_as_hidden():
            return False
        name = str(getattr(entry, "name", "") or "").strip()
        return bool(name) and name.startswith(".") and name not in {".", ".."}

    def _filtered_remote_entries(self, entries):
        filtered = []
        for entry in entries or []:
            is_hidden = self._is_remote_hidden_entry(entry)
            if is_hidden and not self._show_hidden_files:
                continue
            if is_hidden and not getattr(entry, "is_hidden", False):
                entry = RemoteFileItem(
                    name=entry.name,
                    location=entry.location,
                    is_dir=entry.is_dir,
                    size=entry.size,
                    modified_at=entry.modified_at,
                    web_url=entry.web_url,
                    is_hidden=True,
                )
            filtered.append(entry)
        return filtered

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
        self._apply_tree_header_translations()
        header = self.tree_view.header()
        if header is not None:
            header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            header.customContextMenuRequested.connect(self.on_tree_header_context_menu)
        self.tree_view.expanded.connect(self.on_tree_item_expanded)
        self.tree_view.setSortingEnabled(True)
        self.tree_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        if hasattr(self.tree_view, "setSelectionRectVisible"):
            self.tree_view.setSelectionRectVisible(True)
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

        self._directory_loaded_handler = self._on_model_directory_loaded
        self.model.directoryLoaded.connect(self._directory_loaded_handler)
        QTimer.singleShot(300, self.optimize_columns)

    def _on_model_directory_loaded(self, path):
        try:
            if self._dispose_prepared or self.tree_view is None:
                return

            if not self._pending_root_path:
                if QDir.cleanPath(path) == QDir.cleanPath(self.current_location.path):
                    self.apply_current_sort()
                    self.optimize_columns()
                return

            requested = QDir.cleanPath(self._pending_root_path)
            loaded = QDir.cleanPath(path)
            if loaded != requested:
                return

            root_index = self.model.index(self._pending_root_path)
            if root_index.isValid():
                self.tree_view.collapseAll()
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

    def _edit_index_if_alive(self, view, index):
        if self._dispose_prepared or view is None:
            return
        try:
            view.edit(index)
        except RuntimeError:
            return

    def _restore_active_view_focus_if_alive(self):
        if self._dispose_prepared:
            return
        active_view = self.active_item_view()
        if active_view is None:
            return
        try:
            active_view.setFocus(Qt.FocusReason.OtherFocusReason)
        except RuntimeError:
            return

    def _restore_index_for_path(self, path: str):
        return self.model.index(path)

    def _restore_select_index(self, index) -> None:
        if not getattr(index, "isValid", lambda: False)():
            return
        adapter = self.active_view_adapter()
        if adapter is not None:
            adapter.select_single_index(index, focus=False)

    def _restore_scroll_value(self, value: int) -> None:
        active_view = self.active_item_view()
        scrollbar = active_view.verticalScrollBar() if active_view is not None else None
        if scrollbar:
            scrollbar.setValue(value)

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
        if hasattr(self.icon_view, "setSelectionRectVisible"):
            self.icon_view.setSelectionRectVisible(True)
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
        self.path_bar.pathOpenInNewTab.connect(lambda path: self.open_path_in_new_tab(path, activate=True))
        self.path_bar.set_remote_subdirectory_provider(self._path_bar_remote_subdirectories)
        self.path_bar_container.layout().addWidget(self.path_bar)

    def setup_navigation_buttons(self):
        style = self.widget.style()
        if self.btn_nav_back is not None:
            self.btn_nav_back.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
            self.btn_nav_back.setText("")
            self.btn_nav_back.setToolTip(app_tr("PaneController", "Zurück"))
            self.btn_nav_back.setAutoRaise(True)
            self.btn_nav_back.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_nav_back.clicked.connect(self.navigate_back)

        if self.btn_nav_up is not None:
            self.btn_nav_up.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent))
            self.btn_nav_up.setText("")
            self.btn_nav_up.setToolTip(app_tr("PaneController", "Eine Ebene nach oben"))
            self.btn_nav_up.setAutoRaise(True)
            self.btn_nav_up.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_nav_up.clicked.connect(self.navigate_up)

        self.update_navigation_buttons()

    def _path_bar_remote_subdirectories(self, location: PaneLocation):
        if self._remote_drive_controller is None or location is None or not location.is_remote:
            return []
        return self._remote_drive_controller.list_subdirectory_targets(location)

    def setup_search_ui(self):
        pane_top_bar = self.widget.findChild(QWidget, "paneTopBar")
        if pane_top_bar is not None and pane_top_bar.layout() is not None:
            self.btn_search = QToolButton(pane_top_bar)
            search_icon = QIcon.fromTheme("edit-find")
            if search_icon.isNull():
                search_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
            self.btn_search.setIcon(search_icon)
            self.btn_search.setIconSize(QSize(20, 20))
            self.btn_search.setText("")
            self.btn_search.setToolTip(app_tr("PaneController", "Suchen"))
            self.btn_search.setAutoRaise(True)
            self.btn_search.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            pane_top_bar.layout().insertWidget(pane_top_bar.layout().count() - 1, self.btn_search)
            self.btn_search.clicked.connect(self.toggle_search_bar)

        root_layout = self.widget.layout()
        if root_layout is None:
            return

        self.search_bar_widget = QWidget(self.widget)
        self.search_bar_widget.setVisible(False)
        search_layout = QHBoxLayout(self.search_bar_widget)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(6)

        self.search_line_edit = QLineEdit(self.search_bar_widget)
        self.search_line_edit.setPlaceholderText(app_tr("PaneController", "Dateien und Ordner rekursiv suchen"))
        self.search_line_edit.returnPressed.connect(self.start_recursive_search)
        self.search_line_edit.installEventFilter(self)

        close_button = QToolButton(self.search_bar_widget)
        close_button.setIcon(self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogCloseButton))
        close_button.setToolTip(app_tr("PaneController", "Suche schließen"))
        close_button.setAutoRaise(True)
        close_button.clicked.connect(self.close_search_bar)

        search_layout.addWidget(self.search_line_edit, 1)
        search_layout.addWidget(close_button)
        root_layout.insertWidget(2, self.search_bar_widget)

        self.search_results_view = QTreeWidget(self.widget)
        self.search_results_view.setRootIsDecorated(False)
        self.search_results_view.setItemsExpandable(False)
        self.search_results_view.setAlternatingRowColors(True)
        self.search_results_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.search_results_view.setHeaderLabels(
            [
                app_tr("PaneController", "Name"),
                app_tr("PaneController", "Pfad"),
                app_tr("PaneController", "Typ"),
            ]
        )
        self.search_results_view.itemActivated.connect(
            lambda item, _column: self.on_search_result_activated(item)
        )
        self.search_results_view.itemDoubleClicked.connect(
            lambda item, _column: self.on_search_result_activated(item)
        )
        if self.view_stack is not None:
            self.view_stack.addWidget(self.search_results_view)

    def setup_view_mode_button(self):
        if not self.btn_view_mode:
            return

        icon = QIcon.fromTheme("view-list-details")
        if icon.isNull():
            icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)

        self.btn_view_mode.setIcon(icon)
        self.btn_view_mode.setIconSize(QSize(22, 22))
        self.btn_view_mode.setText("")
        self.btn_view_mode.setToolTip(app_tr("PaneController", "Ansicht"))
        self.btn_view_mode.setAutoRaise(True)
        self.btn_view_mode.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.btn_view_mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        menu = QMenu(self.btn_view_mode)
        self.btn_view_mode.setMenu(menu)
        menu.aboutToShow.connect(self.sync_hidden_files_action_state)

        action_group = QActionGroup(self.btn_view_mode)
        action_group.setExclusive(True)

        details_icon = QIcon.fromTheme("view-list-details")
        if details_icon.isNull():
            details_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        details_action = menu.addAction(details_icon, app_tr("PaneController", "Details"))
        details_action.setData("details")
        details_action.setCheckable(True)
        details_action.setChecked(True)
        action_group.addAction(details_action)

        list_icon = QIcon.fromTheme("view-list-text")
        if list_icon.isNull():
            list_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        list_action = menu.addAction(list_icon, app_tr("PaneController", "Liste"))
        list_action.setData("list")
        list_action.setCheckable(True)
        action_group.addAction(list_action)

        icons_icon = QIcon.fromTheme("view-grid")
        if icons_icon.isNull():
            icons_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        icons_action = menu.addAction(icons_icon, app_tr("PaneController", "Icons"))
        icons_action.setData("icons")
        icons_action.setCheckable(True)
        action_group.addAction(icons_action)

        menu.addSeparator()
        action_show_hidden = menu.addAction(app_tr("PaneController", "Versteckte Dateien anzeigen"))
        action_show_hidden.setCheckable(True)
        action_show_hidden.setChecked(self._show_hidden_files)
        self._action_show_hidden_files = action_show_hidden

        reset_icon = QIcon.fromTheme("view-refresh")
        if reset_icon.isNull():
            reset_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        action_reset_view = menu.addAction(reset_icon, app_tr("PaneController", "Standard"))
        self._action_reset_view = action_reset_view

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
        action_show_hidden.triggered.connect(lambda checked: self.set_show_hidden_files(bool(checked)))
        action_reset_view.triggered.connect(self.reset_view_to_default)

    def _apply_tree_header_translations(self):
        if self.model is not None:
            # Header strings come from FileSystemModel.headerData(); emit update on language changes.
            self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)
        if self._remote_model is not None:
            self._remote_model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)

    def _normalize_visible_tree_columns(self, columns):
        active_model = self._active_file_model()
        normalized = []
        if isinstance(columns, list):
            for item in columns:
                try:
                    index = int(item)
                except (TypeError, ValueError):
                    continue
                if active_model is None or index < 0 or index >= active_model.columnCount():
                    continue
                if index not in normalized:
                    normalized.append(index)
        if not normalized:
            return [0]
        return sorted(normalized)

    def _persist_visible_tree_columns(self):
        if self._editor_settings is None:
            return
        if hasattr(self._editor_settings, "update_visible_file_tree_columns"):
            self._editor_settings.update_visible_file_tree_columns(self._visible_tree_columns)

    def _apply_visible_tree_columns(self):
        active_model = self._active_file_model()
        if self.tree_view is None or active_model is None:
            return

        if self.filetree_view_mode != "details":
            return

        visible = set(self._visible_tree_columns)
        for column in range(active_model.columnCount()):
            self.tree_view.setColumnHidden(column, column not in visible)

    def _tree_column_label(self, column: int) -> str:
        active_model = self._active_file_model()
        if active_model is None:
            return str(column)
        value = active_model.headerData(column, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        return str(value) if value is not None else str(column)

    def on_tree_header_context_menu(self, pos):
        active_model = self._active_file_model()
        if self.tree_view is None or active_model is None:
            return

        header = self.tree_view.header()
        if header is None:
            return

        menu = QMenu(header)
        actions_by_column = {}
        visible_columns = set(self._visible_tree_columns)
        visible_count = len(visible_columns)

        for column in range(active_model.columnCount()):
            action = menu.addAction(self._tree_column_label(column))
            action.setCheckable(True)
            is_visible = column in visible_columns
            action.setChecked(is_visible)
            if is_visible and visible_count <= 1:
                action.setEnabled(False)
            actions_by_column[action] = column

        selected_action = menu.exec(header.mapToGlobal(pos))
        if selected_action not in actions_by_column:
            return

        selected_column = actions_by_column[selected_action]
        if selected_action.isChecked():
            if selected_column not in self._visible_tree_columns:
                self._visible_tree_columns.append(selected_column)
        else:
            self._visible_tree_columns = [col for col in self._visible_tree_columns if col != selected_column]

        self._visible_tree_columns = self._normalize_visible_tree_columns(self._visible_tree_columns)
        self._persist_visible_tree_columns()
        self._apply_visible_tree_columns()
        self.optimize_columns()

    def on_tree_item_expanded(self, index):
        if (
            self._dispose_prepared
            or self.current_location is None
            or not self.current_location.is_remote
            or self._remote_drive_controller is None
        ):
            return
        if not index.isValid() or self.tree_view is None or self.tree_view.model() is not self._remote_model:
            return
        if not self._remote_model.isDir(index) or self._remote_model.children_loaded(index):
            return

        child_path = self._remote_model.filePath(index)
        if not child_path:
            return

        location = PaneLocation(
            kind="remote",
            path=child_path,
            remote_id=self.current_location.remote_id,
        )
        try:
            entries = self._remote_drive_controller.list_directory(location)
        except Exception as error:
            self.show_operation_feedback(str(error))
            return

        self._remote_model.set_children_for_index(index, self._filtered_remote_entries(entries))
        self.apply_current_sort()
        self.optimize_columns()

    def retranslate_ui_texts(self):
        if self.btn_nav_back is not None:
            self.btn_nav_back.setToolTip(app_tr("PaneController", "Zurück"))
        if self.btn_nav_up is not None:
            self.btn_nav_up.setToolTip(app_tr("PaneController", "Eine Ebene nach oben"))
        if self.btn_search is not None:
            self.btn_search.setToolTip(app_tr("PaneController", "Suchen"))
        if self.btn_view_mode is not None:
            self.btn_view_mode.setToolTip(app_tr("PaneController", "Ansicht"))

        details_action = self.view_mode_actions.get("details")
        if details_action is not None:
            details_action.setText(app_tr("PaneController", "Details"))
        list_action = self.view_mode_actions.get("list")
        if list_action is not None:
            list_action.setText(app_tr("PaneController", "Liste"))
        icons_action = self.view_mode_actions.get("icons")
        if icons_action is not None:
            icons_action.setText(app_tr("PaneController", "Icons"))
        if self._action_show_hidden_files is not None:
            self._action_show_hidden_files.setText(app_tr("PaneController", "Versteckte Dateien anzeigen"))
        if self._action_reset_view is not None:
            self._action_reset_view.setText(app_tr("PaneController", "Standard"))

        if self.path_bar is not None and hasattr(self.path_bar, "retranslate_ui_texts"):
            self.path_bar.retranslate_ui_texts()
        if self.search_line_edit is not None:
            self.search_line_edit.setPlaceholderText(app_tr("PaneController", "Dateien und Ordner rekursiv suchen"))
        if self.search_results_view is not None:
            self.search_results_view.setHeaderLabels(
                [
                    app_tr("PaneController", "Name"),
                    app_tr("PaneController", "Pfad"),
                    app_tr("PaneController", "Typ"),
                ]
            )

        self._apply_tree_header_translations()
        self._apply_visible_tree_columns()
        self.optimize_columns()

    def setup_tab_bar(self):
        self.tab_bar.setMovable(True)
        self.tab_bar.setExpanding(False)
        self.tab_bar.tabCloseRequested.connect(self.close_tab)
        self.set_show_tab_close_icons(bool(getattr(self._editor_settings, "show_file_tab_close_icons", False)))
        self.tab_bar.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.tab_bar.currentChanged.connect(self.on_tab_changed)
        self.tab_bar.tabMoved.connect(self.on_tab_moved)
        self.tab_bar.installEventFilter(self)

    def set_show_tab_close_icons(self, enabled: bool):
        self.tab_bar.setTabsClosable(bool(enabled))
        self.tab_bar.setStyleSheet(
            "QTabBar::close-button {"
            " subcontrol-position: right;"
            " margin-left: 8px;"
            " width: 12px;"
            " height: 12px;"
            "}"
        )

    def _tab_menu_icon(self, theme_name, fallback_pixmap):
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = self.widget.style().standardIcon(fallback_pixmap)
        return icon

    def add_tab(self, title, path):
        if isinstance(path, PaneLocation):
            location = path if path.is_remote else self._resolve_local_location(path.path)
        else:
            location = self._resolve_local_location(path)
        if location is None:
            fallback_path = path.path if isinstance(path, PaneLocation) else path
            location = self._pane_state_service.make_location(QDir.cleanPath(str(fallback_path or "")))

        tab_title = self._navigation_service.display_name_for_location(location)
        if location.is_remote and self._remote_drive_controller is not None:
            tab_title = self._remote_drive_controller.display_name_for_location(location)
        if not str(tab_title or "").strip():
            tab_title = title

        state = TabState(title=tab_title, location=location)
        self.tab_states.append(state)
        index = self.tab_bar.addTab(tab_title)
        self.update_tab_visual(index)

        if self.active_tab_index == -1:
            self.active_tab_index = index
            self.tab_bar.setCurrentIndex(index)
            self.apply_tab_state(state, push_history=False)

    def _resolve_local_location(self, path) -> PaneLocation | None:
        return self._navigation_service.resolve_directory_location(str(path or ""))

    def _set_current_location(self, location: PaneLocation) -> None:
        self.current_location = location
        self.current_directory = location.path

    def _is_local_context(self) -> bool:
        return bool(self.current_location and self.current_location.is_local)

    def open_path_in_new_tab(self, path, activate=True):
        if isinstance(path, PaneLocation):
            location = path if path.is_remote else self._resolve_local_location(path.path)
        else:
            location = self._resolve_local_location(path)
        if location is None:
            return

        tab_title = self._navigation_service.display_name_for_location(location)
        if location.is_remote and self._remote_drive_controller is not None:
            tab_title = self._remote_drive_controller.display_name_for_location(location)
        state = TabState(title=tab_title, location=location)
        self.tab_states.append(state)
        self.update_tab_visual(self.tab_bar.addTab(tab_title))
        if activate:
            self.tab_bar.setCurrentIndex(len(self.tab_states) - 1)

    def _middle_click_opens_foreground_tab(self) -> bool:
        if self._editor_settings is None:
            return False
        behavior = str(getattr(self._editor_settings, "middle_click_new_tab_behavior", "background") or "background").strip().lower()
        return behavior == "foreground"

    def close_tab(self, index):
        if len(self.tab_states) <= 1:
            return
        if index < 0 or index >= len(self.tab_states):
            return
        if self.tab_states[index].pinned:
            return

        if self.active_tab_index >= 0 and self.active_tab_index < len(self.tab_states):
            self.capture_tab_state(self.active_tab_index)

        removing_active = index == self.active_tab_index
        self.tab_bar.blockSignals(True)
        self._restoring_tab_switch = True
        try:
            self.tab_states.pop(index)
            self.tab_bar.removeTab(index)

            if removing_active:
                new_index = min(index, len(self.tab_states) - 1)
                self.active_tab_index = new_index
                self.tab_bar.setCurrentIndex(new_index)
            elif index < self.active_tab_index:
                self.active_tab_index -= 1
                self.tab_bar.setCurrentIndex(self.active_tab_index)
        finally:
            self._restoring_tab_switch = False
            self.tab_bar.blockSignals(False)

        if removing_active and 0 <= self.active_tab_index < len(self.tab_states):
            self.apply_tab_state(self.tab_states[self.active_tab_index], push_history=False)

    def on_tab_changed(self, new_index):
        if new_index < 0 or new_index >= len(self.tab_states):
            return
        if self._restoring_tab_switch:
            return
        if self._tab_reorder_drag_active:
            self.active_tab_index = new_index
            self._pending_reordered_tab_apply = True
            return

        if self.active_tab_index >= 0 and self.active_tab_index < len(self.tab_states):
            self.capture_tab_state(self.active_tab_index)

        self.active_tab_index = new_index
        target_state = self.tab_states[new_index]
        self.apply_tab_state(target_state, push_history=False)

    def on_tab_moved(self, from_index, to_index):
        if from_index == to_index:
            return
        if from_index < 0 or to_index < 0:
            return
        if from_index >= len(self.tab_states) or to_index >= len(self.tab_states):
            return

        moved_state = self.tab_states.pop(from_index)
        self.tab_states.insert(to_index, moved_state)

        if self.active_tab_index == from_index:
            self.active_tab_index = to_index
        elif from_index < self.active_tab_index <= to_index:
            self.active_tab_index -= 1
        elif to_index <= self.active_tab_index < from_index:
            self.active_tab_index += 1

        start = min(from_index, to_index)
        end = max(from_index, to_index)
        for index in range(start, end + 1):
            self.update_tab_visual(index)

        current_index = self.tab_bar.currentIndex()
        if 0 <= current_index < len(self.tab_states):
            self.active_tab_index = current_index
            if self._tab_reorder_drag_active:
                self._pending_reordered_tab_apply = True
            else:
                self.apply_tab_state(self.tab_states[current_index], push_history=False)

    def _finalize_tab_reorder_if_needed(self) -> None:
        if not self._pending_reordered_tab_apply:
            return
        self._pending_reordered_tab_apply = False
        current_index = self.tab_bar.currentIndex()
        if current_index < 0 or current_index >= len(self.tab_states):
            return
        self.active_tab_index = current_index
        self.apply_tab_state(self.tab_states[current_index], push_history=False)

    def eventFilter(self, watched, event):
        if watched == self.search_line_edit and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.close_search_bar()
                return True

        if watched == self.tab_bar:
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._tab_drag_index = self.tab_bar.tabAt(event.position().toPoint())
                self._tab_drag_start_pos = event.position().toPoint()
                self._tab_reorder_drag_active = self._tab_drag_index != -1
                self._pending_reordered_tab_apply = False

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
                    self.add_tab(f"{app_tr('PaneController', 'Tab')} {new_index}", self.current_location)
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
                self._tab_reorder_drag_active = False
                self._finalize_tab_reorder_if_needed()

            if event.type() == QEvent.Type.ContextMenu:
                tab_index = self.tab_bar.tabAt(event.pos())
                if tab_index != -1:
                    self.tab_bar.setCurrentIndex(tab_index)

                menu = QMenu(self.tab_bar)
                action_new_tab = menu.addAction(
                    self._tab_menu_icon("tab-new", QStyle.StandardPixmap.SP_FileIcon),
                    app_tr("PaneController", "Neuer Tab"),
                )
                action_close = menu.addAction(
                    self._tab_menu_icon("window-close", QStyle.StandardPixmap.SP_DialogCloseButton),
                    app_tr("PaneController", "Tab schließen"),
                )
                action_close.setEnabled(
                    tab_index != -1
                    and len(self.tab_states) > 1
                    and not self.tab_states[tab_index].pinned
                )

                menu.addSeparator()
                action_group = menu.addAction(
                    self._tab_menu_icon("view-split-left-right", QStyle.StandardPixmap.SP_ComputerIcon),
                    app_tr("PaneController", "Gruppieren"),
                )

                chosen_action = menu.exec(event.globalPos())
                if chosen_action == action_new_tab:
                    new_index = len(self.tab_states) + 1
                    self.add_tab(f"{app_tr('PaneController', 'Tab')} {new_index}", self.current_location)
                    self.tab_bar.setCurrentIndex(len(self.tab_states) - 1)
                    return True
                if chosen_action == action_close and tab_index != -1:
                    self.close_tab(tab_index)
                    return True
                if chosen_action == action_group:
                    self.groupRequested.emit()
                    return True
                return True

        watched_views = tuple(view for view in (self.tree_view, self.icon_view) if view is not None)
        try:
            watched_viewports = tuple(view.viewport() for view in watched_views)
        except RuntimeError:
            return False

        if watched in watched_views:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    current_view = self.active_item_view()
                    if current_view is not None and current_view.state() == QAbstractItemView.State.EditingState:
                        return False
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
                    self.refresh_current_directory(force_rescan=True)
                    return True
                if event.key() == Qt.Key.Key_H and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self.toggle_show_hidden_files()
                    return True
                if event.key() == Qt.Key.Key_F2:
                    if self.selected_count() > 0:
                        self.rename_current_item()
                        return True
                    return False
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.activate_selection()
                    return True
                if event.matches(QKeySequence.StandardKey.New):
                    self.create_file()
                    return True
                required_modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
                if event.key() == Qt.Key.Key_N and (event.modifiers() & required_modifiers) == required_modifiers:
                    self.create_folder()
                    return True

        if watched in watched_viewports:
            watched_view = self.active_item_view()
            for view in watched_views:
                try:
                    if view.viewport() is watched:
                        watched_view = view
                        break
                except RuntimeError:
                    continue
            if watched_view is None:
                return False
            if event.type() == QEvent.Type.KeyPress:
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    if watched_view is not None and watched_view.state() == QAbstractItemView.State.EditingState:
                        return False
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
                    self.refresh_current_directory(force_rescan=True)
                    return True
                if event.key() == Qt.Key.Key_H and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                    self.toggle_show_hidden_files()
                    return True
                if event.key() == Qt.Key.Key_F2:
                    if self.selected_count() > 0:
                        self.rename_current_item()
                        return True
                    return False
                if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                    self.activate_selection()
                    return True
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
                selection_model = watched_view.selectionModel()
                is_selected_index = bool(selection_model is not None and index.isValid() and selection_model.isSelected(index))
                has_multi_select_modifier = bool(
                    event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
                )
                if (
                    self.current_location is not None
                    and self.current_location.is_remote
                    and index.isValid()
                    and not has_multi_select_modifier
                ):
                    model = watched_view.model() if hasattr(watched_view, "model") else None
                    if is_selected_index:
                        drag_locations = self._selected_remote_locations_from_view(watched_view)
                    else:
                        clicked_location = self._remote_location_from_index(index, model)
                        drag_locations = [clicked_location] if clicked_location is not None else []
                    self._drag_session_service.arm_remote_drag(
                        source_view=watched_view,
                        start_pos=event.position().toPoint(),
                        locations=drag_locations,
                    )
                    return False
                self._drag_session_service.clear_remote_drag()
                if (not index.isValid() or not is_selected_index) and not has_multi_select_modifier:
                    watched_view.clearSelection()
                    watched_view.setCurrentIndex(QModelIndex())
                    self._selection_rubber_origin = event.position().toPoint()
                    self._selection_rubber_viewport = watched_view.viewport()
                    if self._selection_rubber_band is None:
                        self._selection_rubber_band = QRubberBand(QRubberBand.Shape.Rectangle, watched_view.viewport())
                        self._selection_rubber_band.setStyleSheet(
                            "QRubberBand {"
                            " border: 1px solid rgba(140, 210, 255, 220);"
                            " background-color: rgba(80, 170, 230, 56);"
                            "}"
                        )
                    elif self._selection_rubber_band.parent() is not watched_view.viewport():
                        self._selection_rubber_band.setParent(watched_view.viewport())
                        self._selection_rubber_band.setStyleSheet(
                            "QRubberBand {"
                            " border: 1px solid rgba(140, 210, 255, 220);"
                            " background-color: rgba(80, 170, 230, 56);"
                            "}"
                        )
                    self._selection_rubber_band.setGeometry(QRect(self._selection_rubber_origin, QSize()))
                    self._selection_rubber_band.raise_()
                    self._selection_rubber_band.show()
                    return False

            if event.type() == QEvent.Type.MouseMove and (event.buttons() & Qt.MouseButton.LeftButton):
                if (
                    self.current_location is not None
                    and self.current_location.is_remote
                    and self._drag_session_service.should_start_remote_drag(
                        source_view=watched_view,
                        current_pos=event.position().toPoint(),
                        drag_distance=QApplication.startDragDistance(),
                    )
                ):
                    self._start_remote_selection_drag(watched_view)
                    self._drag_session_service.clear_remote_drag()
                    return True
                if (
                    self._selection_rubber_band is not None
                    and self._selection_rubber_origin is not None
                    and self._selection_rubber_viewport is watched_view.viewport()
                ):
                    rubber_rect = QRect(self._selection_rubber_origin, event.position().toPoint()).normalized()
                    self._selection_rubber_band.setGeometry(rubber_rect)

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                handled_remote_press = self._drag_session_service.release_was_guarded()
                if self._selection_rubber_band is not None:
                    self._selection_rubber_band.hide()
                self._selection_rubber_origin = None
                self._selection_rubber_viewport = None
                self._drag_session_service.clear_remote_drag()
                if handled_remote_press:
                    return True

            if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                index = watched_view.indexAt(event.position().toPoint())
                if not index.isValid():
                    return False

                active_model = watched_view.model()
                if active_model is None or not hasattr(active_model, "filePath") or not hasattr(active_model, "isDir"):
                    return False
                path = str(active_model.filePath(index) or "").strip()
                if not path:
                    return False
                if self.current_location.is_local and not Path(QDir.cleanPath(path)).exists():
                    return False
                if not active_model.isDir(index):
                    return False

                target = path
                if self.current_location is not None and self.current_location.is_remote:
                    target = PaneLocation(kind="remote", path=path, remote_id=self.current_location.remote_id)
                self.open_path_in_new_tab(target, activate=self._middle_click_opens_foreground_tab())
                return True

            if event.type() == QEvent.Type.DragEnter:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(
                    event,
                    source_paths,
                    target_dir,
                    mime_data=event.mimeData(),
                    source_widget=event.source(),
                )
                if self.can_accept_tree_drop(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_paths=source_paths,
                    target_dir=target_dir,
                ):
                    event.setDropAction(drop_action)
                    self.update_drop_target_visual(event.position().toPoint(), drop_action)
                    event.accept()
                    return True

            if event.type() == QEvent.Type.DragMove:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(
                    event,
                    source_paths,
                    target_dir,
                    mime_data=event.mimeData(),
                    source_widget=event.source(),
                )
                if self.can_accept_tree_drop(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_paths=source_paths,
                    target_dir=target_dir,
                ):
                    event.setDropAction(drop_action)
                    self.update_drop_target_visual(event.position().toPoint(), drop_action)
                    event.accept()
                    return True
                self.clear_drop_target_visual()

            if event.type() == QEvent.Type.DragLeave:
                self.clear_drop_target_visual()
                if self._selection_rubber_band is not None:
                    self._selection_rubber_band.hide()
                self._selection_rubber_origin = None
                self._selection_rubber_viewport = None
                return True

            if event.type() == QEvent.Type.Drop:
                source_paths, target_dir = self.resolve_drop_context(
                    event.mimeData(),
                    event.position().toPoint(),
                    event.source(),
                    source_view=watched_view,
                )
                drop_action = self.resolve_drop_action(
                    event,
                    source_paths,
                    target_dir,
                    mime_data=event.mimeData(),
                    source_widget=event.source(),
                )
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
                    if self._selection_rubber_band is not None:
                        self._selection_rubber_band.hide()
                    self._selection_rubber_origin = None
                    self._selection_rubber_viewport = None
                    event.accept()
                    return True
                self.clear_drop_target_visual()

        return super().eventFilter(watched, event)

    def active_item_view(self):
        if self.view_stack is not None and self.search_results_view is not None:
            if self.view_stack.currentWidget() is self.search_results_view:
                return self.search_results_view
        if self.filetree_view_mode == "icons" and self.icon_view is not None:
            return self.icon_view
        return self.tree_view

    def active_view_adapter(self):
        if self.view_stack is not None and self.search_results_view is not None:
            if self.view_stack.currentWidget() is self.search_results_view:
                return None
        if self.filetree_view_mode == "icons" and self.icon_view_adapter is not None:
            return self.icon_view_adapter
        return self.tree_view_adapter

    def toggle_search_bar(self):
        if self.search_bar_widget is None:
            return
        if self.search_bar_widget.isVisible():
            self.close_search_bar()
            return
        self.search_bar_widget.setVisible(True)
        if self.search_line_edit is not None:
            self.search_line_edit.setFocus()
            self.search_line_edit.selectAll()

    def close_search_bar(self):
        if self.search_bar_widget is not None:
            self.search_bar_widget.setVisible(False)
        if self.search_line_edit is not None:
            self.search_line_edit.clear()
        QTimer.singleShot(0, self._restore_active_view_focus_if_alive)
        if self.search_results_view is not None:
            self.search_results_view.clear()
        if self.view_stack is not None and self.search_results_view is not None:
            if self.view_stack.currentWidget() is self.search_results_view:
                if self.filetree_view_mode == "icons" and self.icon_view is not None:
                    self.view_stack.setCurrentWidget(self.icon_view)
                else:
                    self.view_stack.setCurrentWidget(self.tree_view)

    def start_recursive_search(self):
        if not self._local_context_required(app_tr("PaneController", "Suche")):
            return
        if self.search_line_edit is None:
            return

        search_text = self.search_line_edit.text().strip()
        if not search_text:
            self.close_search_bar()
            return

        if self._search_thread is not None:
            self.show_operation_feedback(app_tr("PaneController", "Suche läuft bereits"))
            return

        self.show_operation_feedback(
            app_tr("PaneController", "Suche in {path} gestartet").format(path=self.current_location.path)
        )

        self._search_thread = QThread(self)
        self._search_worker = RecursiveSearchWorker(self.current_location.path, search_text)
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_recursive_search_finished)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.finished.connect(self._search_worker.deleteLater)
        self._search_thread.start()

    def _on_recursive_search_finished(self, results):
        if self.search_results_view is None:
            return

        self.search_results_view.clear()
        for path, is_dir in results:
            name = Path(path).name or path
            type_label = (
                app_tr("PaneController", "Ordner")
                if is_dir
                else (Path(path).suffix.lstrip(".").upper() or app_tr("PaneController", "Datei"))
            )
            item = QTreeWidgetItem([name, path, type_label])
            item.setData(0, Qt.ItemDataRole.UserRole, path)
            item.setData(0, Qt.ItemDataRole.UserRole + 1, is_dir)

            model_index = self.model.index(path)
            if model_index.isValid():
                item.setIcon(0, self.model.fileIcon(model_index))

            self.search_results_view.addTopLevelItem(item)

        self.search_results_view.resizeColumnToContents(0)
        self.search_results_view.resizeColumnToContents(2)
        total_width = self.search_results_view.viewport().width()
        if total_width > 0:
            self.search_results_view.setColumnWidth(0, max(self.search_results_view.columnWidth(0), int(total_width * 0.28)))
            self.search_results_view.setColumnWidth(1, max(self.search_results_view.columnWidth(1), int(total_width * 0.52)))
        if self.view_stack is not None:
            self.view_stack.setCurrentWidget(self.search_results_view)

        if results:
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Treffer gefunden").format(count=len(results))
            )
        else:
            self.show_operation_feedback(app_tr("PaneController", "Keine Treffer gefunden"))

        if self._search_thread is not None:
            self._search_thread.quit()
            self._search_thread.wait()
            self._search_thread.deleteLater()
            self._search_thread = None
        self._search_worker = None

    def on_search_result_activated(self, item):
        if item is None:
            return

        path = QDir.cleanPath(str(item.data(0, Qt.ItemDataRole.UserRole) or ""))
        is_dir = bool(item.data(0, Qt.ItemDataRole.UserRole + 1))
        if not path or not Path(path).exists():
            return

        self.close_search_bar()
        if is_dir:
            self.navigate_to(path)
            return

        if self._open_local_file_via_office_web(path):
            return
        self._open_service.open_default(path)

    _EDITABLE_EXTENSIONS = {
        ".desktop",
        ".sh",
        ".txt",
        ".md",
        ".py",
        ".js",
        ".ts",
        ".css",
        ".json",
        ".xml",
        ".html",
        ".yaml",
        ".yml",
        ".cfg",
        ".ini",
        ".log",
    }
    _APPLICATION_LAUNCH_EXTENSIONS = {
        ".desktop",
        ".sh",
        ".appimage",
        ".run",
    }
    _LOCAL_OFFICE_WEB_EXTENSIONS = {
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
    }

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

    def _is_editable_selection(self):
        paths = self.selected_paths()
        if not paths:
            return False
        suffix = Path(paths[0]).suffix.lower()
        return suffix in self._EDITABLE_EXTENSIONS

    def _selected_archive_path(self) -> str | None:
        paths = [QDir.cleanPath(str(path)) for path in self.selected_paths()]
        return self._archive_service.selected_archive_path(paths, file_operations=self.file_operations)

    def _single_selected_existing_path(self) -> str | None:
        paths = self.selected_paths()
        if len(paths) != 1:
            return None
        clean_path = QDir.cleanPath(str(paths[0]))
        if not clean_path or not Path(clean_path).exists():
            return None
        return clean_path

    def _single_selected_remote_location(self) -> PaneLocation | None:
        if self.current_location is None or not self.current_location.is_remote:
            return None
        paths = self.selected_paths()
        if len(paths) != 1:
            return None
        clean_path = QDir.cleanPath(str(paths[0]))
        if not clean_path or clean_path == "/":
            return None
        return PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id)

    def _selected_remote_locations(self) -> list[PaneLocation]:
        if self.current_location is None or not self.current_location.is_remote:
            return []
        locations: list[PaneLocation] = []
        for raw_path in self.selected_paths():
            clean_path = QDir.cleanPath(str(raw_path))
            if not clean_path or clean_path == "/":
                continue
            locations.append(
                PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id)
            )
        return locations

    def _remote_location_from_index(self, index: QModelIndex, model=None) -> PaneLocation | None:
        if self.current_location is None or not self.current_location.is_remote or not index.isValid():
            return None
        active_model = model
        if active_model is None and hasattr(self, "current_view") and self.current_view is not None:
            active_model = self.current_view.model()
        if active_model is None or not hasattr(active_model, "filePath"):
            return None
        clean_path = QDir.cleanPath(str(active_model.filePath(index) or ""))
        if not clean_path or clean_path == "/":
            return None
        return PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id)

    def _selected_remote_locations_from_view(self, view) -> list[PaneLocation]:
        if self.current_location is None or not self.current_location.is_remote or view is None:
            return []
        selection_model = view.selectionModel() if hasattr(view, "selectionModel") else None
        model = view.model() if hasattr(view, "model") else None
        if selection_model is None or model is None or not hasattr(model, "filePath"):
            return []

        indexes = []
        if hasattr(selection_model, "selectedRows"):
            indexes = list(selection_model.selectedRows(0))
        elif hasattr(selection_model, "selectedIndexes"):
            indexes = [index for index in selection_model.selectedIndexes() if index.column() == 0]

        locations: list[PaneLocation] = []
        seen_paths: set[str] = set()
        for index in indexes:
            if not index.isValid():
                continue
            clean_path = QDir.cleanPath(str(model.filePath(index) or ""))
            if not clean_path or clean_path == "/" or clean_path in seen_paths:
                continue
            seen_paths.add(clean_path)
            locations.append(
                PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id)
            )
        return locations

    def _build_remote_clipboard_mime_data(self, locations: list[PaneLocation], *, operation: str) -> QMimeData:
        return self._drag_mime_codec.build_remote_mime_data(locations, operation=operation)

    def _remote_export_staging_root(self) -> Path:
        staging_root = Path.home() / "Downloads" / ".tablion-dnd"
        staging_root.mkdir(parents=True, exist_ok=True)
        return staging_root

    def _remote_export_staging_name(self, location: PaneLocation) -> str:
        source_name = PurePosixPath(str(location.path or "/")).name.strip() or "Element"
        suffixes = PurePosixPath(source_name).suffixes
        suffix = "".join(suffixes)
        stem = source_name[: -len(suffix)] if suffix else source_name
        stem = stem or source_name
        digest = hashlib.sha1(
            f"{location.remote_id or ''}|{location.path or ''}".encode("utf-8")
        ).hexdigest()[:12]
        return f"{stem}.{digest}{suffix}" if suffix else f"{stem}.{digest}"

    def _cleanup_remote_export_staging(self, staging_root: Path, *, keep_paths: set[Path] | None = None) -> None:
        keep_paths = {path.resolve() for path in (keep_paths or set())}
        now = QDateTime.currentSecsSinceEpoch()
        for candidate in staging_root.iterdir():
            try:
                resolved_candidate = candidate.resolve()
            except OSError:
                resolved_candidate = candidate
            if resolved_candidate in keep_paths:
                continue
            try:
                age_seconds = now - int(candidate.stat().st_mtime)
            except OSError:
                continue
            if age_seconds < self._REMOTE_EXPORT_STAGING_MAX_AGE_SECONDS:
                continue
            try:
                self._remote_drive_controller._remove_local_path(candidate)
                debug_log(f"Remote export staging cleanup removed: {candidate}")
            except Exception as error:
                debug_log(f"Remote export staging cleanup failed for {candidate}: {error}")

    def _stage_remote_location_for_external_drag(self, location: PaneLocation, staging_root: Path) -> Path:
        if self._remote_drive_controller is None:
            raise RuntimeError("Remote drive controller is unavailable")
        stable_name = self._remote_export_staging_name(location)
        local_path = self._remote_drive_controller.transfer_item_to_local(
            location,
            staging_root,
            target_name=stable_name,
            overwrite=True,
        )
        return Path(local_path)

    def _build_external_remote_drag_mime_data(self, locations: list[PaneLocation], *, operation: str) -> QMimeData:
        staged_paths: list[str] = []
        if self._remote_drive_controller is not None:
            staging_root = self._remote_export_staging_root()
            for location in locations:
                if not location.is_remote:
                    continue
                try:
                    local_path = self._stage_remote_location_for_external_drag(location, staging_root)
                except Exception as error:
                    debug_log(
                        "Remote external DND staging failed: "
                        f"path={location.path!r} remote_id={location.remote_id!r} error={error}"
                    )
                    continue
                staged_paths.append(QDir.cleanPath(str(local_path)))
            self._cleanup_remote_export_staging(
                staging_root,
                keep_paths={Path(path) for path in staged_paths},
            )

        debug_log(
            "Remote external mime build request: "
            f"location_count={len(locations)} staged_paths={staged_paths[:10]} operation={operation}"
        )

        base_mime_data = None
        if staged_paths:
            staged_indexes = []
            for staged_path in staged_paths:
                index = self.model.index(staged_path)
                if index.isValid():
                    staged_indexes.append(index)
            if staged_indexes:
                try:
                    base_mime_data = self.model.mimeData(staged_indexes)
                except Exception as error:
                    debug_log(
                        "Remote external DND native mime build failed: "
                        f"paths={staged_paths[:5]!r} error={error}"
                    )

        mime_data = self._drag_mime_codec.build_remote_mime_data(
            locations,
            operation=operation,
            external_local_paths=staged_paths,
            base_mime_data=base_mime_data,
        )
        debug_mime_data("Remote external mime build result", mime_data)
        return mime_data

    def _start_native_remote_export_drag(self, source_view, locations: list[PaneLocation]) -> bool:
        if source_view is None or not locations:
            debug_log(
                "Remote native export drag aborted early: "
                f"source_view={type(source_view).__name__ if source_view is not None else None} locations={len(locations) if locations is not None else 0}"
            )
            return False

        staging_root = self._remote_export_staging_root()
        debug_log(
            "Remote native export drag start: "
            f"source_view={type(source_view).__name__} staging_root={staging_root} locations={[location.path for location in locations[:10]]}"
        )

        staged_indexes = []
        for location in locations:
            if not location.is_remote or self._remote_drive_controller is None:
                continue
            try:
                local_path = self._stage_remote_location_for_external_drag(location, staging_root)
            except Exception as error:
                debug_log(
                    "Remote native export staging failed: "
                    f"path={location.path!r} remote_id={location.remote_id!r} error={error}"
                )
                return False
            index = self._remote_external_drag_model.index(QDir.cleanPath(str(local_path)))
            if not index.isValid():
                debug_log(
                    "Remote native export staging index invalid: "
                    f"path={str(local_path)!r}"
                )
                return False
            staged_indexes.append(index)

        self._cleanup_remote_export_staging(
            staging_root,
            keep_paths={Path(self._remote_external_drag_model.filePath(index)) for index in staged_indexes},
        )

        debug_log(
            "Remote native export staged selection: "
            f"count={len(staged_indexes)} paths={[self._remote_external_drag_model.filePath(index) for index in staged_indexes[:10]]}"
        )

        if not staged_indexes:
            return False

        remote_payload = json.dumps(
            [
                {
                    "kind": location.kind,
                    "path": location.path,
                    "remote_id": location.remote_id,
                }
                for location in locations
                if location.is_remote and location.remote_id
            ]
        ).encode("utf-8")
        self._remote_external_drag_model.configure_remote_payload(
            remote_payload,
            operation=b"copy",
        )
        staging_root_index = self._remote_external_drag_model.index(str(staging_root))
        staged_names = [Path(self._remote_external_drag_model.filePath(index)).name for index in staged_indexes]
        original_name_filters = list(self._remote_external_drag_model.nameFilters())
        original_name_filter_disables = self._remote_external_drag_model.nameFilterDisables()
        helper_view = None

        try:
            self._remote_external_drag_model.setNameFilterDisables(False)
            self._remote_external_drag_model.setNameFilters(staged_names)
            if isinstance(source_view, QListView):
                helper_view = QListView(self.widget)
                helper_view.setViewMode(source_view.viewMode())
                helper_view.setResizeMode(source_view.resizeMode())
                helper_view.setMovement(source_view.movement())
                helper_view.setWrapping(source_view.isWrapping())
                helper_view.setWordWrap(source_view.wordWrap())
                helper_view.setSpacing(source_view.spacing())
            else:
                helper_view = QTreeView(self.widget)
                helper_view.setRootIsDecorated(source_view.rootIsDecorated() if hasattr(source_view, "rootIsDecorated") else True)
                header = helper_view.header()
                if header is not None and hasattr(source_view, "header") and source_view.header() is not None:
                    header.setVisible(source_view.header().isVisible())
            helper_view.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            helper_view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
            helper_view.setDragEnabled(True)
            helper_view.setAcceptDrops(False)
            helper_view.setDropIndicatorShown(False)
            helper_view.setDefaultDropAction(Qt.DropAction.CopyAction)
            helper_view.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
            helper_view.setModel(self._remote_external_drag_model)
            if hasattr(helper_view, "setModelColumn"):
                helper_view.setModelColumn(0)
            if staging_root_index.isValid() and hasattr(helper_view, "setRootIndex"):
                helper_view.setRootIndex(staging_root_index)
            current_index = staged_indexes[0]

            mime_data = self._remote_external_drag_model.mimeData(staged_indexes)
            drag_source = helper_view.viewport() if hasattr(helper_view, "viewport") else helper_view
            drag = QDrag(drag_source)
            drag.setMimeData(mime_data)
            preview = self._drag_visual_service.build_remote_drag_pixmap(self.widget, locations)
            if preview is not None:
                drag.setPixmap(preview)
                drag.setHotSpot(QPoint(14, 14))
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
            return True
        except Exception as error:
            debug_log(f"Remote native export drag start failed: {error}")
            return False
        finally:
            self._remote_external_drag_model.setNameFilters(original_name_filters)
            self._remote_external_drag_model.setNameFilterDisables(original_name_filter_disables)
            if helper_view is not None:
                helper_view.deleteLater()

    def _extract_remote_locations_from_mime(self, mime_data) -> list[PaneLocation]:
        return self._drag_mime_codec.extract_remote_locations(mime_data)

    def _download_remote_file_for_open(self, location: PaneLocation) -> str | None:
        if self._remote_drive_controller is None:
            return None
        try:
            cached_path = self._remote_drive_controller.download_file_to_cache(location)
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Remote-Datei konnte nicht geladen werden"),
                str(error),
            )
            return None
        return str(cached_path)

    def _selected_remote_file_url(self, location: PaneLocation) -> str:
        active_view = self.active_item_view()
        active_model = active_view.model() if active_view is not None else None
        adapter = self.active_view_adapter()
        index = adapter.current_or_selected_index() if adapter is not None else QModelIndex()
        if (
            active_model is None
            or not index.isValid()
            or not hasattr(active_model, "fileUrl")
            or not hasattr(active_model, "filePath")
        ):
            return ""
        model_path = QDir.cleanPath(str(active_model.filePath(index) or ""))
        if model_path != QDir.cleanPath(location.path):
            return ""
        return str(active_model.fileUrl(index) or "").strip()

    def _open_url_via_rule(self, path_hint: str, remote_url: str) -> bool:
        if self._editor_settings is None:
            return False
        rule = self._editor_settings.remote_open_rule_for(path_hint)
        if not rule:
            return False
        command = str(rule.get("command") or "").strip()
        arguments = str(rule.get("arguments") or "").strip()
        if not command:
            return False
        if arguments:
            argument_text = (
                arguments.replace("{url}", remote_url)
                .replace("{path}", path_hint)
                .replace("{name}", Path(path_hint).name)
            )
            args = shlex.split(argument_text)
        else:
            args = [remote_url]
        try:
            return bool(QProcess.startDetached(command, args))
        except Exception:
            return False

    def _open_remote_file_via_rule(self, location: PaneLocation) -> bool:
        remote_url = self._selected_remote_file_url(location)
        if not remote_url:
            return False
        return self._open_url_via_rule(location.path, remote_url)

    def _local_office_web_editing_enabled_for(self, path: str) -> bool:
        if self._editor_settings is None or self._remote_drive_controller is None:
            return False
        if not self._editor_settings.local_office_web_editing_enabled:
            return False
        if not self._editor_settings.local_office_web_connection_id:
            return False
        return Path(path).suffix.lower() in self._LOCAL_OFFICE_WEB_EXTENSIONS

    def _open_local_file_via_office_web(self, path: str) -> bool:
        if not self._local_office_web_editing_enabled_for(path):
            return False
        existing_session = None
        if self._local_office_web_session_store is not None:
            try:
                existing_session = self._local_office_web_session_store.find_session(
                    local_path=path,
                    connection_id=self._editor_settings.local_office_web_connection_id,
                )
            except Exception:
                existing_session = None
        try:
            upload_result = self._remote_drive_controller.upload_local_file_for_web_editing(
                connection_id=self._editor_settings.local_office_web_connection_id,
                local_path=path,
                remote_folder_path=self._editor_settings.local_office_web_temp_folder,
                preferred_remote_path=existing_session.remote_path if existing_session is not None else None,
            )
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Office-Web-Bearbeitung fehlgeschlagen"),
                str(error),
            )
            return True

        remote_url = str(upload_result.get("web_url") or "").strip()
        if self._local_office_web_session_store is not None:
            try:
                local_mtime = 0.0
                try:
                    local_mtime = Path(path).stat().st_mtime
                except OSError:
                    local_mtime = 0.0
                self._local_office_web_session_store.add_session(
                    local_path=path,
                    connection_id=str(upload_result.get("connection_id") or self._editor_settings.local_office_web_connection_id),
                    remote_path=str(upload_result.get("remote_path") or ""),
                    web_url=remote_url,
                    local_mtime_at_opened=local_mtime,
                    remote_modified_at=float(upload_result.get("remote_modified_at") or 0.0),
                )
            except Exception:
                pass
        if not remote_url:
            return True
        if self._open_url_via_rule(path, remote_url):
            return True
        QDesktopServices.openUrl(QUrl(remote_url))
        return True

    def _open_remote_file_in_browser(self, location: PaneLocation) -> bool:
        remote_url = self._selected_remote_file_url(location)
        if not remote_url:
            return False
        QDesktopServices.openUrl(QUrl(remote_url))
        return True

    def _archive_creation_sources(self) -> list[str]:
        paths = [QDir.cleanPath(str(path)) for path in self.selected_paths()]
        return self._archive_service.archive_creation_sources(paths)

    def _default_archive_target_path(self, sources: list[str], suffix: str) -> str:
        default_target = self._archive_service.default_archive_target_path(sources, suffix)
        if sources:
            return default_target
        return str(Path(self.current_location.path) / f"{app_tr('PaneController', 'Archiv')}{suffix}")

    def _local_context_required(self, action_label: str) -> bool:
        if self._is_local_context():
            return True
        self.show_operation_feedback(
            app_tr("PaneController", "{action} wird für Remote-Kontexte noch nicht unterstützt").format(
                action=action_label
            )
        )
        return False

    def _archive_suffix_for_filter(self, selected_filter: str) -> str:
        return self._archive_service.archive_suffix_for_filter(selected_filter, self._ARCHIVE_SAVE_FILTERS)

    def show_hidden_files(self) -> bool:
        if self.model is None:
            return self._show_hidden_files
        return bool(self.model.filter() & QDir.Filter.Hidden)

    def sync_hidden_files_action_state(self):
        current_value = self.show_hidden_files()
        self._show_hidden_files = current_value
        if self._action_show_hidden_files is not None:
            self._action_show_hidden_files.setChecked(current_value)

    def set_show_hidden_files(self, value: bool, persist: bool = True, refresh: bool = True):
        normalized = bool(value)
        self._show_hidden_files = normalized

        current_filter = self.model.filter() if self.model is not None else self._BASE_FILE_FILTER
        next_filter = current_filter | QDir.Filter.Hidden if normalized else current_filter & ~QDir.Filter.Hidden
        next_filter |= self._BASE_FILE_FILTER
        if self.model is not None and next_filter != current_filter:
            self.model.setFilter(next_filter)

        if self._action_show_hidden_files is not None:
            self._action_show_hidden_files.setChecked(normalized)
        if persist and self._editor_settings is not None:
            self._editor_settings.update_show_hidden_files(normalized)
        if refresh:
            self.refresh_current_directory(preserve_focus=True, force_rescan=True)

    def toggle_show_hidden_files(self):
        self.set_show_hidden_files(not self.show_hidden_files())

    def open_selected_with_application(self, application) -> None:
        target_path = self._single_selected_existing_path()
        if target_path is None:
            return
        if self._open_service.open_with_application(application, target_path):
            return
        QMessageBox.warning(
            self.widget,
            app_tr("PaneController", "Öffnen mit fehlgeschlagen"),
            app_tr("PaneController", "Die Anwendung konnte nicht gestartet werden."),
        )

    def show_selected_properties(self):
        target_path = self._single_selected_existing_path()
        if target_path is None:
            return
        dialog = PropertiesDialog(self.widget, target_path)
        dialog.propertiesChanged.connect(self._on_properties_dialog_path_changed)
        dialog.exec()

    def _on_properties_dialog_path_changed(self, new_path: str):
        self._selection_restore_service.remember_single_path(QDir.cleanPath(new_path))
        self.refresh_current_directory(preserve_focus=True, force_rescan=True)
        self.filesystemMutationCommitted.emit()

    def _is_application_target(self, path: str) -> bool:
        return self._open_service.is_application_target(path, self._APPLICATION_LAUNCH_EXTENSIONS)

    def activate_selection(self):
        paths = self.selected_paths()
        if not paths:
            return
        target = QDir.cleanPath(str(paths[0]))
        if self.current_location is not None and self.current_location.is_remote:
            remote_location = self._single_selected_remote_location()
            if remote_location is None:
                return
            active_model = self.active_item_view().model() if self.active_item_view() is not None else None
            index = self.active_view_adapter().current_or_selected_index() if self.active_view_adapter() is not None else QModelIndex()
            if active_model is not None and index.isValid() and hasattr(active_model, "isDir") and active_model.isDir(index):
                self.navigate_to(remote_location)
                return
            if self._open_remote_file_via_rule(remote_location):
                return
            if self._open_remote_file_in_browser(remote_location):
                return
            cached_path = self._download_remote_file_for_open(remote_location)
            if cached_path:
                self._open_service.open_default(cached_path)
            return
        target_path = Path(target)
        if not target_path.exists():
            return
        if target_path.is_dir():
            self.navigate_to(target)
            return
        if self._open_local_file_via_office_web(target):
            return
        if self._is_application_target(target):
            behavior = "start"
            if self._editor_settings is not None:
                behavior = self._editor_settings.application_double_click_behavior
            if behavior == "edit" and target_path.suffix.lower() in self._EDITABLE_EXTENSIONS:
                self.open_selection_in_editor()
                return
        self._open_service.open_default(target)

    def open_selection_in_editor(self):
        if self.current_location is not None and self.current_location.is_remote:
            remote_location = self._single_selected_remote_location()
            if remote_location is None:
                return
            if self._open_remote_file_via_rule(remote_location):
                return
            if not self._open_remote_file_in_browser(remote_location):
                cached_path = self._download_remote_file_for_open(remote_location)
                if not cached_path:
                    return
                editor_cmd = None
                if self._editor_settings is not None:
                    editor_cmd = self._editor_settings.preferred_editor()
                self._open_service.open_in_editor(cached_path, preferred_editor=editor_cmd)
            return

        paths = self.selected_paths()
        if not paths:
            return
        target = QDir.cleanPath(str(paths[0]))
        path_obj = Path(target)
        if not path_obj.exists():
            return
        if path_obj.is_dir():
            return

        editor_cmd = None
        if self._editor_settings is not None:
            editor_cmd = self._editor_settings.preferred_editor()
        self._open_service.open_in_editor(target, preferred_editor=editor_cmd)

    def extract_selected_archive(self, destination: str | None = None):
        if not self._local_context_required(app_tr("PaneController", "Entpacken")):
            return
        archive_path = self._selected_archive_path()
        if archive_path is None:
            return

        archive_obj = Path(archive_path)
        target_directory = QDir.cleanPath(destination or str(archive_obj.parent))

        try:
            extracted_targets = self._archive_service.extract_archive(
                archive_path,
                target_directory,
                file_operations=self.file_operations,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Entpacken fehlgeschlagen"),
                str(error),
            )
            return

        self.refresh_current_directory(preserve_focus=True, force_rescan=True)
        self.filesystemMutationCommitted.emit()

        extracted_count = len(extracted_targets)
        if extracted_count == 1:
            self.show_operation_feedback(
                app_tr("PaneController", "Archiv entpackt: {name}").format(name=extracted_targets[0].name)
            )
            return

        self.show_operation_feedback(
            app_tr("PaneController", "Archiv entpackt: {count} Elemente").format(count=extracted_count)
        )

    def extract_selected_archive_to_directory(self):
        archive_path = self._selected_archive_path()
        if archive_path is None:
            return

        start_directory = str(Path(archive_path).parent)
        selected_directory = QFileDialog.getExistingDirectory(
            self.widget,
            app_tr("PaneController", "Zielordner zum Entpacken wählen"),
            start_directory,
        )
        if not selected_directory:
            return

        self.extract_selected_archive(selected_directory)

    def create_archive_from_selection(self):
        if not self._local_context_required(app_tr("PaneController", "Archivierung")):
            return
        source_paths = self._archive_creation_sources()
        if not source_paths:
            return

        default_suffix = ".zip"
        file_filters = ";;".join(label for label, _ in self._ARCHIVE_SAVE_FILTERS)
        default_target = self._default_archive_target_path(source_paths, default_suffix)
        selected_path, selected_filter = QFileDialog.getSaveFileName(
            self.widget,
            app_tr("PaneController", "Archiv speichern unter"),
            default_target,
            file_filters,
            self._ARCHIVE_SAVE_FILTERS[0][0],
        )
        if not selected_path:
            return

        suffix = self._archive_suffix_for_filter(selected_filter)
        archive_path = self._archive_service.build_archive_path(selected_path, suffix)

        try:
            self._archive_service.create_archive(
                source_paths,
                archive_path,
                file_operations=self.file_operations,
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Archiv erstellen fehlgeschlagen"),
                str(error),
            )
            return

        self.refresh_current_directory(preserve_focus=True, force_rescan=True)
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback(
            app_tr("PaneController", "Archiv erstellt: {name}").format(name=archive_path.name)
        )

    def copy_selection_to_clipboard(self):
        if self.current_location is not None and self.current_location.is_remote:
            locations = self._selected_remote_locations()
            if not locations:
                return
            QApplication.clipboard().setMimeData(
                self._build_remote_clipboard_mime_data(locations, operation="copy")
            )
            self.clear_cut_state()
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Remote-Element(e) kopiert").format(count=len(locations))
            )
            return

        source_paths = self.selected_paths()
        if not source_paths:
            return

        mime_data = self._transfer_service.build_clipboard_mime_data(
            source_paths,
            path_mime_type=self._CLIPBOARD_MIME_TYPE,
            operation_mime_type=self._CLIPBOARD_OPERATION_MIME_TYPE,
            operation="copy",
        )
        QApplication.clipboard().setMimeData(mime_data)
        self.clear_cut_state()
        self.show_operation_feedback(
            app_tr("PaneController", "{count} Element(e) kopiert").format(count=len(source_paths))
        )

    def cut_selection_to_clipboard(self):
        if self.current_location is not None and self.current_location.is_remote:
            locations = self._selected_remote_locations()
            if not locations:
                return
            QApplication.clipboard().setMimeData(
                self._build_remote_clipboard_mime_data(locations, operation="cut")
            )
            self._cut_paths = {location.path for location in locations}
            self.update_cut_visual_state()
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Remote-Element(e) ausgeschnitten").format(count=len(locations))
            )
            return

        source_paths = self.selected_paths()
        if not source_paths:
            return

        mime_data = self._transfer_service.build_clipboard_mime_data(
            source_paths,
            path_mime_type=self._CLIPBOARD_MIME_TYPE,
            operation_mime_type=self._CLIPBOARD_OPERATION_MIME_TYPE,
            operation="cut",
        )
        QApplication.clipboard().setMimeData(mime_data)
        self._cut_paths = set(source_paths)
        self.update_cut_visual_state()
        self.show_operation_feedback(
            app_tr("PaneController", "{count} Element(e) ausgeschnitten").format(count=len(source_paths))
        )

    def extract_paths_from_mime(self, mime_data):
        return self._drag_mime_codec.extract_local_paths(mime_data, logger=debug_log)

    def extract_operation_from_mime(self, mime_data):
        return self._drag_mime_codec.extract_operation(mime_data)

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

    def extract_ark_drop_reference(self, mime_data):
        return self._drop_service.extract_ark_drop_reference(
            mime_data,
            service_mime=self._ARK_DND_SERVICE_MIME,
            path_mime=self._ARK_DND_PATH_MIME,
            logger=debug_log,
        )

    def resolve_drop_target_directory(self, pos=None, source_view=None):
        current_path = self.current_location.path
        if source_view is self.icon_view and self.icon_view_adapter is not None:
            return self.icon_view_adapter.resolve_drop_target_directory(pos, current_path)

        adapter = self.active_view_adapter()
        if adapter is None:
            return QDir.cleanPath(current_path)
        return adapter.resolve_drop_target_directory(pos, current_path)

    def _build_file_operation_tasks(self, source_paths, target_directory, operation):
        normalized_sources = [QDir.cleanPath(str(source)) for source in source_paths]
        normalized_target = QDir.cleanPath(target_directory)
        tasks = self._transfer_service.build_file_operation_tasks(
            normalized_sources,
            normalized_target,
            operation,
        )
        return [
            FileOperationTask(task.source_path, task.target_path, task.name)
            for task in tasks
        ]

    def _cleanup_file_operation_state(self):
        if self._file_operation_progress_dialog is not None:
            try:
                self._file_operation_progress_dialog.close()
            except RuntimeError:
                pass
            self._file_operation_progress_dialog.deleteLater()
            self._file_operation_progress_dialog = None

        if self._file_operation_thread is not None and not self._file_operation_thread.isRunning():
            self._file_operation_thread.deleteLater()
            self._file_operation_thread = None

        self._file_operation_worker = None
        self._pending_file_operation = None

    def _stop_file_operation_thread(self, wait_forever=False):
        thread = self._file_operation_thread
        if thread is None:
            return

        try:
            thread.quit()
            if wait_forever:
                thread.wait()
            else:
                thread.wait(3000)
        except RuntimeError:
            return

    def _on_file_operation_progress(self, value, maximum, label):
        dialog = self._file_operation_progress_dialog
        if dialog is None:
            return
        dialog.setMaximum(maximum)
        dialog.setValue(value)
        dialog.setLabelText(label)

    def _on_file_operation_finished(self, result):
        metadata = self._pending_file_operation or {}
        dialog = self._file_operation_progress_dialog
        if dialog is not None:
            dialog.setValue(dialog.maximum())

        completed_count = int(result.get("completed_count", 0) or 0)
        error_messages = list(result.get("errors", []) or [])
        operation = result.get("operation", metadata.get("operation", "copy"))

        self._cleanup_file_operation_state()

        if completed_count > 0:
            self.refresh_current_directory(preserve_focus=True)
            self.optimize_columns()
            self.filesystemMutationCommitted.emit()

            if metadata.get("clear_clipboard_on_success"):
                clipboard = QApplication.clipboard()
                clipboard.clear(mode=clipboard.Mode.Clipboard)
                self.clear_cut_state()

            self.show_operation_feedback(
                self._file_operation_service.success_feedback(operation, completed_count)
            )

        if error_messages:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Dateioperation unvollständig"),
                error_messages[0],
            )

    def _start_file_operation(self, source_paths, target_directory, operation, clear_clipboard_on_success=False):
        if self._file_operation_thread is not None:
            self.show_operation_feedback(app_tr("PaneController", "Dateioperation bereits aktiv"))
            return False

        tasks = self._build_file_operation_tasks(source_paths, target_directory, operation)
        if not tasks:
            return False

        destination_name = Path(QDir.cleanPath(target_directory)).name or QDir.cleanPath(target_directory)
        dialog_title = self._file_operation_service.dialog_title(operation)
        label_text = self._file_operation_service.dialog_label(operation, len(tasks), destination_name)

        self._pending_file_operation = {
            "operation": operation,
            "clear_clipboard_on_success": clear_clipboard_on_success,
        }

        self._file_operation_progress_dialog = QProgressDialog(self.widget)
        self._file_operation_progress_dialog.setWindowTitle(dialog_title)
        self._file_operation_progress_dialog.setLabelText(label_text)
        self._file_operation_progress_dialog.setRange(0, len(tasks))
        self._file_operation_progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._file_operation_progress_dialog.setMinimumDuration(0)
        self._file_operation_progress_dialog.setAutoClose(False)
        self._file_operation_progress_dialog.setAutoReset(False)
        self._file_operation_progress_dialog.setCancelButton(None)
        self._file_operation_progress_dialog.setValue(0)
        self._file_operation_progress_dialog.show()

        self._file_operation_thread = QThread(self)
        self._file_operation_worker = FileOperationWorker(self.file_operations, operation, tasks)
        self._file_operation_worker.moveToThread(self._file_operation_thread)
        self._file_operation_thread.started.connect(self._file_operation_worker.run)
        self._file_operation_worker.progressChanged.connect(self._on_file_operation_progress)
        self._file_operation_worker.finished.connect(self._on_file_operation_finished)
        self._file_operation_worker.finished.connect(self._file_operation_thread.quit)
        self._file_operation_thread.finished.connect(self._file_operation_worker.deleteLater)
        self._file_operation_thread.start()
        return True

    def copy_paths_to_directory(self, source_paths, target_directory):
        return self._start_file_operation(source_paths, target_directory, "copy")

    def duplicate_selection(self):
        if self.current_location is not None and self.current_location.is_remote:
            locations = self._selected_remote_locations()
            if not locations or self._remote_drive_controller is None:
                return False
            try:
                duplicated = self._remote_drive_controller.copy_items(locations, self.current_location)
            except Exception as error:
                QMessageBox.warning(
                    self.widget,
                    app_tr("PaneController", "Duplizieren fehlgeschlagen"),
                    str(error),
                )
                return False

            if duplicated:
                self.refresh_current_directory(preserve_focus=True)
                self.show_operation_feedback(
                    app_tr("PaneController", "{count} Remote-Element(e) dupliziert").format(
                        count=len(duplicated)
                    )
                )
                return True
            return False

        source_paths = self.selected_paths()
        if not source_paths:
            return False

        clean_sources = [QDir.cleanPath(str(source)) for source in source_paths]
        duplicate_result = self._transfer_service.duplicate_paths(
            clean_sources,
            file_operations=self.file_operations,
        )
        changes_applied = bool(duplicate_result.duplicated_paths)

        if changes_applied:
            self.refresh_current_directory(preserve_focus=True)
            self.filesystemMutationCommitted.emit()
            self.optimize_columns()
            self.show_operation_feedback(
                self._transfer_service.duplicate_feedback(len(duplicate_result.duplicated_paths))
            )

        return changes_applied

    def move_paths_to_directory(self, source_paths, target_directory):
        return self._start_file_operation(source_paths, target_directory, "move")

    def link_paths_to_directory(self, source_paths, target_directory):
        if not source_paths:
            return False

        clean_sources = [QDir.cleanPath(str(source)) for source in source_paths]
        target_dir = QDir.cleanPath(target_directory)
        created_links = self._link_service.create_links(clean_sources, target_dir)
        changes_applied = bool(created_links)

        if changes_applied:
            self.refresh_current_directory()
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Verknüpfung(en) erstellt").format(count=len(created_links))
            )
        return changes_applied

    def delete_selected_paths(self, permanent=None):
        if self.current_location is not None and self.current_location.is_remote:
            self._delete_selected_remote_paths()
            return

        selected = self.selected_paths()
        if not selected:
            return

        existing_selected = self._delete_service.existing_paths(selected)
        if not existing_selected:
            self.refresh_current_directory(preserve_focus=True)
            self.show_operation_feedback(app_tr("PaneController", "Element bereits entfernt"))
            return

        if permanent is None:
            permanent = self._delete_service.resolve_permanent_default(self.current_location.path)

        title, message = self._delete_service.build_confirmation(existing_selected, permanent)
        confirmed = ask_yes_no(
            self.widget,
            title,
            message,
            default_no=True,
        )
        if not confirmed:
            return

        delete_result = self._delete_service.execute(
            existing_selected,
            permanent=permanent,
            file_operations=self.file_operations,
        )
        changes_applied = bool(delete_result.deleted_paths)

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

            self.refresh_current_directory(force_rescan=True)
            self.filesystemMutationCommitted.emit()
            action_text = (
                app_tr("PaneController", "dauerhaft gelöscht")
                if permanent
                else app_tr("PaneController", "in den Papierkorb verschoben")
            )
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Element(e) {action}").format(
                    count=len(delete_result.deleted_paths),
                    action=action_text,
                )
            )

        if delete_result.errors:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Löschen fehlgeschlagen"),
                delete_result.errors[0],
            )

    def _delete_selected_remote_paths(self):
        locations = self._selected_remote_locations()
        if not locations:
            return

        item_labels = [Path(location.path).name or location.path for location in locations]
        if len(item_labels) == 1:
            message = app_tr("PaneController", "'{target}' remote löschen?").format(target=item_labels[0])
        else:
            message = app_tr("PaneController", "{count} Remote-Elemente löschen?").format(
                count=len(item_labels)
            )

        confirmed = ask_yes_no(
            self.widget,
            app_tr("PaneController", "Remote löschen"),
            message,
            default_no=True,
        )
        if not confirmed:
            return

        try:
            deleted = self._remote_drive_controller.delete_items(locations) if self._remote_drive_controller is not None else []
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Löschen fehlgeschlagen"),
                str(error),
            )
            return

        if not deleted:
            return

        for view in (self.tree_view, self.icon_view):
            if view is None:
                continue
            view.clearSelection()
            view.setCurrentIndex(QModelIndex())

        self.refresh_current_directory()
        self.show_operation_feedback(
            app_tr("PaneController", "{count} Remote-Element(e) gelöscht").format(count=len(deleted))
        )

    def restore_selected_from_trash(self):
        selected = self.selected_paths()
        if not selected:
            return

        restore_result = self._trash_restore_service.restore_paths(
            selected,
            file_operations=self.file_operations,
        )

        if restore_result.restored_paths:
            self.refresh_current_directory(preserve_focus=True)
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Element(e) wiederhergestellt").format(
                    count=len(restore_result.restored_paths)
                )
            )

        if restore_result.errors:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Wiederherstellen fehlgeschlagen"),
                restore_result.errors[0],
            )

    def paste_from_clipboard(self, target_directory=None):
        clipboard = QApplication.clipboard()
        mime_data = clipboard.mimeData()
        payload = self._drag_mime_codec.decode_payload(mime_data, logger=debug_log)
        if payload.is_empty:
            return

        destination = target_directory or self.resolve_drop_target_directory()
        self._drop_execution_service.execute_paste(
            payload=payload,
            current_location=self.current_location,
            target_directory=destination,
            paste_local_to_remote=self._paste_local_paths_to_remote,
            paste_remote_to_local=self._paste_remote_paths_to_local,
            paste_remote_to_remote=self._paste_remote_paths_to_remote,
            start_local_file_operation=self._start_file_operation,
            copy_paths_to_directory=self.copy_paths_to_directory,
        )

    def _paste_local_paths_to_remote(
        self,
        source_paths,
        target_directory=None,
        *,
        move: bool = False,
        clear_clipboard_on_success: bool = False,
    ):
        if self.current_location is None or not self.current_location.is_remote or self._remote_drive_controller is None:
            return False
        destination_path = QDir.cleanPath(str(target_directory or self.current_location.path))
        destination = PaneLocation(
            kind="remote",
            path=destination_path,
            remote_id=self.current_location.remote_id,
        )
        try:
            transfer_result = self._remote_transfer_coordinator.transfer_local_to_remote(
                widget=self.widget,
                remote_drive_controller=self._remote_drive_controller,
                file_operations=self.file_operations,
                source_paths=source_paths,
                destination=destination,
                move=move,
            )
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Upload fehlgeschlagen"),
                str(error),
            )
            return False

        if transfer_result.errors:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Upload fehlgeschlagen"),
                transfer_result.errors[0],
            )

        if not transfer_result.completed and not transfer_result.skipped_count:
            return False

        def finalize_local_to_remote():
            self.refresh_current_directory()
            self.filesystemMutationCommitted.emit()
            if move and clear_clipboard_on_success:
                QApplication.clipboard().clear()
                self.clear_cut_state()
            self.show_operation_feedback(
                self._remote_transfer_coordinator.feedback_message(
                    transfer_result,
                    move=move,
                    direction="local_to_remote",
                )
            )

        QTimer.singleShot(0, finalize_local_to_remote)
        return True

    def _paste_remote_paths_to_local(
        self,
        remote_locations,
        target_directory=None,
        *,
        move: bool = False,
        clear_clipboard_on_success: bool = False,
    ):
        if self._remote_drive_controller is None:
            return False

        destination_path = QDir.cleanPath(str(target_directory or self.resolve_drop_target_directory()))
        if not destination_path or not QDir(destination_path).exists():
            return False

        try:
            transfer_result = self._remote_transfer_coordinator.transfer_remote_to_local(
                widget=self.widget,
                remote_drive_controller=self._remote_drive_controller,
                locations=remote_locations,
                destination_directory=destination_path,
                move=move,
            )
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Download fehlgeschlagen"),
                str(error),
            )
            return False

        if transfer_result.errors:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Download fehlgeschlagen"),
                transfer_result.errors[0],
            )

        if not transfer_result.completed and not transfer_result.skipped_count:
            return False

        def finalize_remote_to_local():
            self.refresh_current_directory(preserve_focus=True, force_rescan=True)
            self.filesystemMutationCommitted.emit()
            if move and clear_clipboard_on_success:
                QApplication.clipboard().clear()
                self.clear_cut_state()
            self.show_operation_feedback(
                self._remote_transfer_coordinator.feedback_message(
                    transfer_result,
                    move=move,
                    direction="remote_to_local",
                )
            )

        QTimer.singleShot(0, finalize_remote_to_local)
        if move:
            return True

        return True

    def _paste_remote_paths_to_remote(
        self,
        remote_locations,
        target_directory=None,
        *,
        move: bool = False,
        clear_clipboard_on_success: bool = False,
    ):
        if self.current_location is None or not self.current_location.is_remote or self._remote_drive_controller is None:
            return False

        destination_path = QDir.cleanPath(str(target_directory or self.current_location.path))
        destination_location = PaneLocation(
            kind="remote",
            path=destination_path,
            remote_id=self.current_location.remote_id,
        )
        try:
            transfer_result = self._remote_transfer_coordinator.transfer_remote_to_remote(
                widget=self.widget,
                remote_drive_controller=self._remote_drive_controller,
                locations=remote_locations,
                destination=destination_location,
                move=move,
            )
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Einfügen fehlgeschlagen"),
                str(error),
            )
            return False

        if transfer_result.errors:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Einfügen fehlgeschlagen"),
                transfer_result.errors[0],
            )

        if not transfer_result.completed and not transfer_result.skipped_count:
            return False

        def finalize_remote_to_remote():
            if move and clear_clipboard_on_success:
                QApplication.clipboard().clear()
                self.clear_cut_state()
            self.refresh_current_directory()
            self.show_operation_feedback(
                self._remote_transfer_coordinator.feedback_message(
                    transfer_result,
                    move=move,
                    direction="remote_to_remote",
                )
            )

        QTimer.singleShot(0, finalize_remote_to_remote)
        if move:
            return True

        return True

    def create_folder(self, target_directory=None, base_name=None):
        if self.current_location is not None and self.current_location.is_remote:
            return self._create_remote_folder(target_directory=target_directory, base_name=base_name)

        destination = QDir.cleanPath(target_directory or self.resolve_drop_target_directory())
        candidate = self._creation_service.create_folder(destination, base_name)
        if candidate is None:
            return None

        self._pending_created_item_path = QDir.cleanPath(str(candidate))
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback(app_tr("PaneController", "Ordner erstellt"))

        new_index = self.model.index(str(candidate))
        if new_index.isValid():
            adapter = self.active_view_adapter()
            active_view = self.active_item_view()
            if adapter is not None:
                adapter.select_single_index(new_index, focus=True)
            QTimer.singleShot(0, lambda idx=new_index, view=active_view: self._edit_index_if_alive(view, idx))
            return candidate

        def select_later():
            if self._dispose_prepared:
                return
            later_index = self.model.index(str(candidate))
            if later_index.isValid():
                adapter = self.active_view_adapter()
                active_view = self.active_item_view()
                if adapter is not None:
                    adapter.select_single_index(later_index, focus=True)
                if active_view is not None:
                    self._edit_index_if_alive(active_view, later_index)
            else:
                self._pending_created_item_path = None

        QTimer.singleShot(150, select_later)
        return candidate

    def _create_remote_folder(self, target_directory=None, base_name=None):
        if self.current_location is None or not self.current_location.is_remote or self._remote_drive_controller is None:
            return None

        destination_path = QDir.cleanPath(str(target_directory or self.resolve_drop_target_directory()))
        destination = PaneLocation(
            kind="remote",
            path=destination_path,
            remote_id=self.current_location.remote_id,
        )
        try:
            created_location = self._remote_drive_controller.create_folder(destination, base_name)
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Ordner erstellen fehlgeschlagen"),
                str(error),
            )
            return None

        self.refresh_current_directory()
        self.show_operation_feedback(app_tr("PaneController", "Ordner erstellt"))
        return created_location

    def create_file(self, target_directory=None, base_name=None):
        if self.current_location is not None and self.current_location.is_remote:
            return self._create_remote_file(target_directory=target_directory, base_name=base_name)

        destination = QDir.cleanPath(target_directory or self.resolve_drop_target_directory())
        candidate = self._creation_service.create_file(destination, base_name)
        if candidate is None:
            return None

        self._pending_created_item_path = QDir.cleanPath(str(candidate))
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback(app_tr("PaneController", "Datei erstellt"))

        new_index = self.model.index(str(candidate))
        if new_index.isValid():
            adapter = self.active_view_adapter()
            active_view = self.active_item_view()
            if adapter is not None:
                adapter.select_single_index(new_index, focus=True)
            QTimer.singleShot(0, lambda idx=new_index, view=active_view: self._edit_index_if_alive(view, idx))
            return candidate

        def select_later():
            if self._dispose_prepared:
                return
            later_index = self.model.index(str(candidate))
            if later_index.isValid():
                adapter = self.active_view_adapter()
                active_view = self.active_item_view()
                if adapter is not None:
                    adapter.select_single_index(later_index, focus=True)
                if active_view is not None:
                    self._edit_index_if_alive(active_view, later_index)
            else:
                self._pending_created_item_path = None

        QTimer.singleShot(150, select_later)
        return candidate

    def _create_remote_file(self, target_directory=None, base_name=None):
        if self.current_location is None or not self.current_location.is_remote or self._remote_drive_controller is None:
            return None

        destination_path = QDir.cleanPath(str(target_directory or self.resolve_drop_target_directory()))
        destination = PaneLocation(
            kind="remote",
            path=destination_path,
            remote_id=self.current_location.remote_id,
        )
        try:
            created_location = self._remote_drive_controller.create_file(destination, base_name)
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Datei erstellen fehlgeschlagen"),
                str(error),
            )
            return None

        self.refresh_current_directory()
        self.show_operation_feedback(app_tr("PaneController", "Datei erstellt"))
        return created_location

    def current_or_selected_index(self):
        adapter = self.active_view_adapter()
        if adapter is None:
            return QModelIndex()
        return adapter.current_or_selected_index()

    def rename_current_item(self):
        if self.current_location is not None and self.current_location.is_remote:
            self._rename_current_remote_item()
            return

        if self.selected_count() > 1:
            self.rename_multiple_items()
            return

        index = self.current_or_selected_index()
        if not index.isValid():
            return

        active_view = self.active_item_view()
        if active_view is None:
            return
        active_view.setCurrentIndex(index)
        active_view.edit(index)
        QTimer.singleShot(0, lambda: self._select_name_without_suffix_in_editor(index))

    def _rename_current_remote_item(self):
        if self.selected_count() > 1:
            self.show_operation_feedback(app_tr("PaneController", "Batch-Umbenennen ist für Remote noch nicht verfügbar"))
            return

        location = self._single_selected_remote_location()
        if location is None or self._remote_drive_controller is None:
            return

        current_name = Path(location.path).name or location.path
        new_name, accepted = QInputDialog.getText(
            self.widget,
            app_tr("PaneController", "Remote umbenennen"),
            app_tr("PaneController", "Neuer Name"),
            text=current_name,
        )
        if not accepted:
            return

        new_name = str(new_name or "").strip()
        if not new_name or new_name == current_name:
            return

        try:
            self._remote_drive_controller.rename_item(location, new_name)
        except Exception as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Umbenennen fehlgeschlagen"),
                str(error),
            )
            return

        self.refresh_current_directory()
        self.show_operation_feedback(app_tr("PaneController", "'{name}' umbenannt").format(name=new_name))

    def _select_name_without_suffix_in_editor(self, index):
        if not index.isValid():
            return

        editor = QApplication.focusWidget()
        if not isinstance(editor, QLineEdit):
            return

        try:
            file_name = str(self.model.fileName(index) or "")
        except RuntimeError:
            return

        if not file_name:
            return

        suffix = Path(file_name).suffix
        selection_length = len(file_name) - len(suffix) if suffix else len(file_name)
        if selection_length <= 0:
            selection_length = len(file_name)

        editor.setSelection(0, selection_length)

    def rename_multiple_items(self):
        source_paths = self.selected_paths()
        if len(source_paths) < 2:
            return

        clean_paths = [QDir.cleanPath(str(path)) for path in source_paths if Path(path).exists()]
        if len(clean_paths) < 2:
            return

        sample_name = Path(clean_paths[0]).name
        dialog = BatchRenameDialog(self.widget, sample_name, len(clean_paths))
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        rule_text = dialog.rule_text()
        regex_mode = dialog.regex_enabled()
        if not rule_text:
            return

        try:
            rename_plan = self._build_batch_rename_plan(clean_paths, rule_text, regex_mode=regex_mode)
            self._execute_batch_rename_plan(rename_plan)
            self.refresh_current_directory(preserve_focus=True, force_rescan=True)
            self.filesystemMutationCommitted.emit()
            self.show_operation_feedback(
                app_tr("PaneController", "{count} Element(e) umbenannt").format(count=len(rename_plan))
            )
        except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Umbenennen fehlgeschlagen"),
                str(error),
            )

    def _build_batch_rename_plan(self, source_paths, rule_text, regex_mode=False):
        return self._batch_rename_service.build_plan(source_paths, rule_text, regex_mode=regex_mode)

    def _execute_batch_rename_plan(self, rename_plan):
        self._batch_rename_service.execute_plan(rename_plan)

    def on_model_file_renamed(self, directory_path, _old_name, _new_name):
        renamed_directory = QDir.cleanPath(str(directory_path))
        current_root = QDir.cleanPath(self.current_location.path)

        old_path = QDir.cleanPath(QDir(renamed_directory).filePath(str(_old_name)))
        new_path = QDir.cleanPath(QDir(renamed_directory).filePath(str(_new_name)))

        if self._pending_created_item_path and QDir.cleanPath(self._pending_created_item_path) == old_path:
            self._pending_created_item_path = new_path

        active_state = self.get_active_tab_state()
        if active_state is not None:
            state_path = QDir.cleanPath(str(active_state.location.path))
            if state_path == old_path or state_path.startswith(f"{old_path}/"):
                suffix = state_path[len(old_path):]
                updated_path = QDir.cleanPath(f"{new_path}{suffix}")

                active_state.location = PaneLocation(
                    kind=active_state.location.kind,
                    path=updated_path,
                    remote_id=active_state.location.remote_id,
                )
                self._set_current_location(active_state.location)

                tab_title = Path(updated_path).name or updated_path
                active_state.title = tab_title
                if self.active_tab_index >= 0:
                    self.tab_bar.setTabText(self.active_tab_index, tab_title)
                    self.update_tab_visual(self.active_tab_index)

                if self.path_bar:
                    self.path_bar.set_location(
                        active_state.location,
                        root_label=self._path_bar_root_label_for_location(active_state.location),
                    )

                self.currentPathChanged.emit(updated_path)
                self.emit_navigation_state()
                self.filesystemMutationCommitted.emit()
                return

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

        QTimer.singleShot(0, self._restore_active_view_focus_if_alive)

    def resolve_drop_context(self, mime_data, pos, source_widget=None, source_view=None):
        context = self._drop_target_service.resolve_context(
            mime_data,
            pos=pos,
            source_widget=source_widget,
            source_view=source_view,
            mime_codec=self._drag_mime_codec,
            extract_paths_from_drag_source=self.extract_paths_from_drag_source,
            resolve_drop_target_directory=self.resolve_drop_target_directory,
            ark_reference=self.extract_ark_drop_reference(mime_data),
            logger=debug_log,
        )
        return context.payload.local_paths, context.target_dir

    def can_accept_tree_drop(self, mime_data, pos, source_widget=None, source_paths=None, target_dir=None):
        if source_paths is None or target_dir is None:
            context = self._drop_target_service.resolve_context(
                mime_data,
                pos=pos,
                source_widget=source_widget,
                source_view=None,
                mime_codec=self._drag_mime_codec,
                extract_paths_from_drag_source=self.extract_paths_from_drag_source,
                resolve_drop_target_directory=self.resolve_drop_target_directory,
                ark_reference=self.extract_ark_drop_reference(mime_data),
                logger=debug_log,
            )
        else:
            payload = self._drag_mime_codec.decode_payload(
                mime_data,
                logger=debug_log,
                ark_reference=self.extract_ark_drop_reference(mime_data),
            )
            context = DragDropContext(
                payload=DragPayload(
                    local_paths=source_paths,
                    remote_locations=payload.remote_locations,
                    operation=payload.operation,
                    ark_reference=payload.ark_reference,
                ),
                target_dir=target_dir,
            )
        if context.payload.is_empty:
            self.clear_drop_target_visual()
            return False
        return self._drop_target_service.can_accept_drop(context, current_location=self.current_location)

    def resolve_drop_action(self, event, source_paths=None, target_dir=None, mime_data=None, source_widget=None):
        if source_paths is None or target_dir is None:
            context = self._drop_target_service.resolve_context(
                mime_data,
                pos=None,
                source_widget=source_widget,
                source_view=None,
                mime_codec=self._drag_mime_codec,
                extract_paths_from_drag_source=self.extract_paths_from_drag_source,
                resolve_drop_target_directory=self.resolve_drop_target_directory,
                ark_reference=self.extract_ark_drop_reference(mime_data),
                logger=debug_log,
            )
        else:
            payload = self._drag_mime_codec.decode_payload(
                mime_data,
                logger=debug_log,
                ark_reference=self.extract_ark_drop_reference(mime_data),
            )
            context = DragDropContext(
                payload=DragPayload(
                    local_paths=source_paths,
                    remote_locations=payload.remote_locations,
                    operation=payload.operation,
                    ark_reference=payload.ark_reference,
                ),
                target_dir=target_dir,
            )
        tree_viewport = self.tree_view.viewport() if self.tree_view is not None else None
        icon_viewport = self.icon_view.viewport() if self.icon_view is not None else None
        return self._drop_target_service.resolve_drop_action(
            event=event,
            context=context,
            current_location=self.current_location,
            mime_data=mime_data,
            source_widget=source_widget,
            internal_drag_mime_type=self._INTERNAL_DRAG_MIME_TYPE,
            internal_widgets={self.tree_view, self.icon_view, tree_viewport, icon_viewport, self.tab_bar},
        )

    def _finish_ark_drop(self, watcher=None, error_message=None):
        if watcher is not None:
            self._ark_drop_watchers.discard(watcher)
            try:
                watcher.deleteLater()
            except RuntimeError:
                pass

        if error_message:
            debug_log(f"DND Ark extract failed: {error_message}")
            QMessageBox.warning(
                self.widget,
                app_tr("PaneController", "Ablage fehlgeschlagen"),
                error_message,
            )
            return

        debug_log("DND Ark extract finished successfully")
        self.refresh_current_directory(preserve_focus=True, force_rescan=True)
        self.filesystemMutationCommitted.emit()
        self.show_operation_feedback(app_tr("PaneController", "Archivdateien wurden abgelegt"))

    def extract_ark_drop_to_directory(self, service, object_path, target_dir):
        destination = QDir.cleanPath(target_dir)
        started = self._ark_drop_service.start_extract(
            service=service,
            object_path=object_path,
            destination=destination,
            qdbus_connection=QDBusConnection,
            qdbus_message_cls=QDBusMessage,
            qdbus_pending_call_watcher_cls=QDBusPendingCallWatcher,
            parent=self,
            watcher_store=self._ark_drop_watchers,
            finish_callback=self._finish_ark_drop,
            process_cls=QProcess,
            timer_cls=QTimer,
            logger=debug_log,
        )
        if started:
            return True

        QMessageBox.warning(
            self.widget,
            app_tr("PaneController", "Ablage fehlgeschlagen"),
            app_tr("PaneController", "Ark-Drop wird auf diesem System nicht unterstützt."),
        )
        return False

    def update_drop_target_visual(self, pos, drop_action=None):
        if drop_action is None:
            drop_action = Qt.DropAction.MoveAction

        target_view = self.active_item_view()
        active_model = self._active_file_model()
        highlight_index, highlight_root = self._drop_ui_service.compute_highlight(
            target_view=target_view,
            pos=pos,
            file_model=active_model,
        )

        self._drop_target_index = highlight_index if highlight_index.isValid() else QModelIndex()
        self._drop_target_is_root = highlight_root
        if target_view is self.tree_view:
            self._drop_target_delegate.set_drop_target_index(self._drop_target_index)
            self._drop_target_delegate.set_drop_action(drop_action)
        else:
            self._drop_target_delegate.clear_drop_target_index()
            self._drop_target_delegate.set_drop_action(Qt.DropAction.IgnoreAction)
        if self._drop_target_is_root:
            target_view.viewport().setStyleSheet(self._drop_ui_service.root_stylesheet(drop_action))
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
            context = self._drop_target_service.resolve_context(
                mime_data,
                pos=pos,
                source_widget=source_widget,
                source_view=None,
                mime_codec=self._drag_mime_codec,
                extract_paths_from_drag_source=self.extract_paths_from_drag_source,
                resolve_drop_target_directory=self.resolve_drop_target_directory,
                ark_reference=self.extract_ark_drop_reference(mime_data),
                logger=debug_log,
            )
        else:
            payload = self._drag_mime_codec.decode_payload(
                mime_data,
                logger=debug_log,
                ark_reference=self.extract_ark_drop_reference(mime_data),
            )
            context = DragDropContext(
                payload=DragPayload(
                    local_paths=source_paths,
                    remote_locations=payload.remote_locations,
                    operation=payload.operation,
                    ark_reference=payload.ark_reference,
                ),
                target_dir=target_dir,
            )
        return self._drop_execution_service.execute_drop(
            context=context,
            current_location=self.current_location,
            drop_action=drop_action,
            paste_local_to_remote=self._paste_local_paths_to_remote,
            paste_remote_to_local=self._paste_remote_paths_to_local,
            paste_remote_to_remote=self._paste_remote_paths_to_remote,
            copy_paths_to_directory=self.copy_paths_to_directory,
            move_paths_to_directory=self.move_paths_to_directory,
            link_paths_to_directory=self.link_paths_to_directory,
            ark_callback=self.extract_ark_drop_to_directory,
        )

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

        if self.current_location is not None and self.current_location.is_remote:
            destination_dir = self.resolve_drop_target_directory(pos, source_view=source_view)
            current_index = source_view.indexAt(pos) if source_view is not None and hasattr(source_view, "indexAt") else QModelIndex()
            selected_remote_locations = self._selected_remote_locations()
            has_selection = bool(selected_remote_locations)
            clipboard = QApplication.clipboard()
            clipboard_paths = self.extract_paths_from_mime(clipboard.mimeData())
            remote_clipboard_locations = self._extract_remote_locations_from_mime(clipboard.mimeData())

            action_refresh = menu.addAction(
                self._tab_menu_icon("view-refresh", QStyle.StandardPixmap.SP_BrowserReload),
                app_tr("PaneController", "Aktualisieren"),
            )

            new_folder_icon = QIcon.fromTheme("folder-new")
            if new_folder_icon.isNull():
                new_folder_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
            action_new_folder = menu.addAction(new_folder_icon, app_tr("PaneController", "Neuer Ordner"))
            action_new_folder.setShortcut(QKeySequence("Ctrl+Shift+N"))
            action_new_folder.setShortcutVisibleInContextMenu(True)

            new_file_icon = QIcon.fromTheme("document-new")
            if new_file_icon.isNull():
                new_file_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            action_new_file = menu.addAction(new_file_icon, app_tr("PaneController", "Neue Datei"))
            action_new_file.setShortcut(QKeySequence("Ctrl+N"))
            action_new_file.setShortcutVisibleInContextMenu(True)

            menu.addSeparator()

            duplicate_icon = QIcon.fromTheme("edit-copy")
            if duplicate_icon.isNull():
                duplicate_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            action_duplicate = menu.addAction(duplicate_icon, app_tr("PaneController", "Duplizieren"))
            action_duplicate.setShortcut(QKeySequence("Ctrl+D"))
            action_duplicate.setShortcutVisibleInContextMenu(True)

            copy_icon = QIcon.fromTheme("edit-copy")
            if copy_icon.isNull():
                copy_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
            action_copy = menu.addAction(copy_icon, app_tr("PaneController", "Kopieren"))
            action_copy.setShortcut(QKeySequence.StandardKey.Copy)
            action_copy.setShortcutVisibleInContextMenu(True)

            cut_icon = QIcon.fromTheme("edit-cut")
            if cut_icon.isNull():
                cut_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
            action_cut = menu.addAction(cut_icon, app_tr("PaneController", "Ausschneiden"))
            action_cut.setShortcut(QKeySequence.StandardKey.Cut)
            action_cut.setShortcutVisibleInContextMenu(True)

            paste_icon = QIcon.fromTheme("edit-paste")
            if paste_icon.isNull():
                paste_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
            action_paste = menu.addAction(paste_icon, app_tr("PaneController", "Einfügen"))
            action_paste.setShortcut(QKeySequence.StandardKey.Paste)
            action_paste.setShortcutVisibleInContextMenu(True)

            menu.addSeparator()

            action_open_browser = None
            action_open_local = None
            action_open_local_with = None
            remote_open_with_actions = {}
            active_model = source_view.model() if source_view is not None else None
            if (
                active_model is not None
                and current_index.isValid()
                and hasattr(active_model, "isDir")
                and hasattr(active_model, "fileUrl")
                and not active_model.isDir(current_index)
                and str(active_model.fileUrl(current_index) or "").strip()
            ):
                action_open_browser = menu.addAction(
                    self._tab_menu_icon("document-open", QStyle.StandardPixmap.SP_DialogOpenButton),
                    app_tr("PaneController", "Im Browser öffnen"),
                )
                action_open_local = menu.addAction(
                    self._tab_menu_icon("document-save", QStyle.StandardPixmap.SP_DialogSaveButton),
                    app_tr("PaneController", "Lokal öffnen"),
                )
                remote_path_hint = str(active_model.filePath(current_index) or "").strip()
                remote_applications = applications_for_path(remote_path_hint) if remote_path_hint else []
                if remote_applications:
                    action_open_local_with = menu.addMenu(app_tr("PaneController", "Lokal öffnen mit..."))
                    for application in remote_applications:
                        action = action_open_local_with.addAction(application.icon(), application.display_name)
                        remote_open_with_actions[action] = application

            menu.addSeparator()

            rename_icon = QIcon.fromTheme("edit-rename")
            if rename_icon.isNull():
                rename_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            action_rename = menu.addAction(rename_icon, app_tr("PaneController", "Umbenennen"))
            action_rename.setShortcut(QKeySequence(Qt.Key.Key_F2))
            action_rename.setShortcutVisibleInContextMenu(True)

            delete_icon = QIcon.fromTheme("edit-delete")
            if delete_icon.isNull():
                delete_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            action_delete = menu.addAction(delete_icon, app_tr("PaneController", "Löschen"))
            action_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
            action_delete.setShortcutVisibleInContextMenu(True)

            action_duplicate.setEnabled(has_selection)
            action_copy.setEnabled(has_selection)
            action_cut.setEnabled(has_selection)
            action_rename.setEnabled(current_index.isValid() and has_selection)
            action_delete.setEnabled(has_selection)
            action_paste.setEnabled(bool(clipboard_paths or remote_clipboard_locations) and bool(destination_dir))

            chosen = menu.exec(source_view.viewport().mapToGlobal(pos))
            if chosen == action_refresh:
                self.refresh_current_directory(force_rescan=True)
            elif chosen == action_new_folder:
                self.create_folder(destination_dir)
            elif chosen == action_new_file:
                self.create_file(destination_dir)
            elif chosen == action_duplicate:
                self.duplicate_selection()
            elif chosen == action_copy:
                self.copy_selection_to_clipboard()
            elif chosen == action_cut:
                self.cut_selection_to_clipboard()
            elif chosen == action_paste:
                self.paste_from_clipboard(destination_dir)
            elif chosen == action_open_browser and active_model is not None:
                QDesktopServices.openUrl(QUrl(str(active_model.fileUrl(current_index))))
            elif chosen == action_open_local and active_model is not None:
                remote_location = PaneLocation(kind="remote", path=str(active_model.filePath(current_index) or ""), remote_id=self.current_location.remote_id)
                cached_path = self._download_remote_file_for_open(remote_location)
                if cached_path:
                    self._open_service.open_default(cached_path)
            elif chosen in remote_open_with_actions and active_model is not None:
                remote_location = PaneLocation(kind="remote", path=str(active_model.filePath(current_index) or ""), remote_id=self.current_location.remote_id)
                cached_path = self._download_remote_file_for_open(remote_location)
                if cached_path:
                    application = remote_open_with_actions[chosen]
                    if not self._open_service.open_with_application(application, cached_path):
                        QMessageBox.warning(
                            self.widget,
                            app_tr("PaneController", "Öffnen mit fehlgeschlagen"),
                            app_tr("PaneController", "Die Anwendung konnte nicht gestartet werden."),
                        )
            elif chosen == action_delete:
                self.delete_selected_paths(permanent=None)
            elif chosen == action_rename:
                self.rename_current_item()
            return

        if self._delete_service.is_trash_context(self.current_location.path):
            delete_icon = QIcon.fromTheme("edit-delete")
            if delete_icon.isNull():
                delete_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            action_delete = menu.addAction(delete_icon, app_tr("PaneController", "Löschen"))
            action_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
            action_delete.setShortcutVisibleInContextMenu(True)

            restore_icon = QIcon.fromTheme("edit-undo")
            if restore_icon.isNull():
                restore_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowBack)
            action_restore = menu.addAction(restore_icon, app_tr("PaneController", "Wiederherstellen"))

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

        single_selected_path = self._single_selected_existing_path()
        open_with_actions = {}
        if single_selected_path is not None:
            applications = applications_for_path(single_selected_path)
            if applications:
                open_with_menu = menu.addMenu(app_tr("PaneController", "Öffnen mit..."))
                for application in applications:
                    action = open_with_menu.addAction(application.icon(), application.display_name)
                    open_with_actions[action] = application
                menu.addSeparator()

        new_folder_icon = QIcon.fromTheme("folder-new")
        if new_folder_icon.isNull():
            new_folder_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogNewFolder)
        action_new_folder = menu.addAction(new_folder_icon, app_tr("PaneController", "Neuer Ordner"))
        action_new_folder.setShortcut(QKeySequence("Ctrl+Shift+N"))
        action_new_folder.setShortcutVisibleInContextMenu(True)
        destination_dir = self.resolve_drop_target_directory(pos, source_view=source_view)
        action_new_folder.setEnabled(
            bool(destination_dir)
            and (
                (self.current_location is not None and self.current_location.is_remote)
                or QDir(destination_dir).exists()
            )
        )

        new_file_icon = QIcon.fromTheme("document-new")
        if new_file_icon.isNull():
            new_file_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_new_file = menu.addAction(new_file_icon, app_tr("PaneController", "Neue Datei"))
        action_new_file.setShortcut(QKeySequence("Ctrl+N"))
        action_new_file.setShortcutVisibleInContextMenu(True)
        action_new_file.setEnabled(QDir(destination_dir).exists())

        menu.addSeparator()

        duplicate_icon = QIcon.fromTheme("edit-copy")
        if duplicate_icon.isNull():
            duplicate_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_duplicate = menu.addAction(duplicate_icon, app_tr("PaneController", "Duplizieren"))
        action_duplicate.setShortcut(QKeySequence("Ctrl+D"))
        action_duplicate.setShortcutVisibleInContextMenu(True)

        copy_icon = QIcon.fromTheme("edit-copy")
        if copy_icon.isNull():
            copy_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        action_copy = menu.addAction(copy_icon, app_tr("PaneController", "Kopieren"))
        action_copy.setShortcut(QKeySequence.StandardKey.Copy)
        action_copy.setShortcutVisibleInContextMenu(True)

        cut_icon = QIcon.fromTheme("edit-cut")
        if cut_icon.isNull():
            cut_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_ArrowRight)
        action_cut = menu.addAction(cut_icon, app_tr("PaneController", "Ausschneiden"))
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
        action_paste = menu.addAction(paste_icon, app_tr("PaneController", "Einfügen"))
        action_paste.setShortcut(QKeySequence.StandardKey.Paste)
        action_paste.setShortcutVisibleInContextMenu(True)

        action_create_archive = None
        archive_creation_sources = self._archive_creation_sources()
        if archive_creation_sources:
            archive_icon = QIcon.fromTheme("package-x-generic")
            if archive_icon.isNull():
                archive_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DriveFDIcon)
            action_create_archive = menu.addAction(archive_icon, app_tr("PaneController", "Archiv erstellen..."))

        menu.addSeparator()

        archive_path = self._selected_archive_path()
        action_extract_here = None
        action_extract_to = None
        if archive_path is not None:
            extract_icon = QIcon.fromTheme("archive-extract")
            if extract_icon.isNull():
                extract_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
            extract_menu = menu.addMenu(extract_icon, app_tr("PaneController", "Entpacken"))
            action_extract_here = extract_menu.addAction(app_tr("PaneController", "Hier entpacken"))
            action_extract_to = extract_menu.addAction(app_tr("PaneController", "Entpacken nach..."))
            menu.addSeparator()

        edit_icon = QIcon.fromTheme("accessories-text-editor")
        if edit_icon.isNull():
            edit_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        action_edit = menu.addAction(edit_icon, app_tr("PaneController", "Bearbeiten"))
        action_edit.setEnabled(self._is_editable_selection())

        rename_icon = QIcon.fromTheme("edit-rename")
        if rename_icon.isNull():
            rename_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        action_rename = menu.addAction(rename_icon, app_tr("PaneController", "Umbenennen"))
        action_rename.setShortcut(QKeySequence(Qt.Key.Key_F2))
        action_rename.setShortcutVisibleInContextMenu(True)

        delete_icon = QIcon.fromTheme("edit-delete")
        if delete_icon.isNull():
            delete_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        action_delete = menu.addAction(delete_icon, app_tr("PaneController", "Löschen"))
        action_delete.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        action_delete.setShortcutVisibleInContextMenu(True)
        action_delete.setEnabled(bool(self.selected_paths()))

        menu.addSeparator()

        properties_icon = QIcon.fromTheme("document-properties")
        if properties_icon.isNull():
            properties_icon = self.widget.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView)
        action_properties = menu.addAction(properties_icon, app_tr("PaneController", "Eigenschaften"))
        action_properties.setEnabled(single_selected_path is not None)

        current_index = self.current_or_selected_index()
        action_rename.setEnabled(current_index.isValid() and self.selected_count() > 0)

        clipboard_mime = QApplication.clipboard().mimeData()
        clipboard_paths = self.extract_paths_from_mime(clipboard_mime)
        remote_clipboard_locations = self._extract_remote_locations_from_mime(clipboard_mime)
        action_paste.setEnabled(
            bool(clipboard_paths or remote_clipboard_locations)
            and (
                (self.current_location is not None and self.current_location.is_remote)
                or QDir(destination_dir).exists()
            )
        )

        chosen = menu.exec(source_view.viewport().mapToGlobal(pos))
        if chosen in open_with_actions:
            self.open_selected_with_application(open_with_actions[chosen])
            return
        if chosen == action_properties:
            self.show_selected_properties()
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
        if chosen == action_create_archive:
            self.create_archive_from_selection()
            return
        if chosen == action_paste:
            self.paste_from_clipboard(destination_dir)
            return
        if chosen == action_extract_here:
            self.extract_selected_archive()
            return
        if chosen == action_extract_to:
            self.extract_selected_archive_to_directory()
            return
        if chosen == action_delete:
            self.delete_selected_paths(permanent=None)
            return
        if chosen == action_rename:
            self.rename_current_item()
            return
        if chosen == action_edit:
            self.open_selection_in_editor()
            return

    def start_tab_path_drag(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return

        state = self.tab_states[tab_index]
        path = QDir.cleanPath(state.location.path)
        if not QDir(path).exists():
            return

        mime_data = QMimeData()
        url = QUrl.fromLocalFile(path)
        encoded_uri = bytes(url.toEncoded()).decode("utf-8")
        mime_data.setUrls([url])
        mime_data.setData("text/uri-list", (encoded_uri + "\n").encode("utf-8"))

        drag = QDrag(self.tab_bar)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

    def _start_remote_selection_drag(self, source_view) -> None:
        if self.current_location is None or not self.current_location.is_remote:
            return
        if source_view is None:
            return
        locations = self._drag_session_service.remote_drag_locations()
        if self._start_native_remote_export_drag(source_view, locations):
            return
        self._drag_session_service.start_remote_drag(
            widget=self.widget,
            source_view=source_view,
            locations=locations,
        )

    def can_offer_grouping(self):
        if not self.parent() or not hasattr(self.parent(), "can_offer_grouping"):
            return False
        return bool(self.parent().can_offer_grouping(self))

    def clone_tab_states(self):
        self.capture_tab_state(self.active_tab_index)
        return self._pane_state_service.clone_states(self.tab_states)

    def replace_tabs(self, states, active_index=0):
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count() > 0:
            self.tab_bar.removeTab(self.tab_bar.count() - 1)
        self.tab_states = []
        self.active_tab_index = -1

        for state in states:
            cloned_state = self._pane_state_service.clone_state(state)
            self.tab_states.append(cloned_state)
            index = self.tab_bar.addTab(state.title)
            self.update_tab_visual(index)

        self.tab_bar.blockSignals(False)

        if not self.tab_states:
            self.add_tab("Tab 1", self.current_location)
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
            [TabState(title="Tab 1", location=self._pane_state_service.make_location(clean_default), view_mode="details")],
            active_index=0,
        )
        return exported_states, exported_active_index

    def capture_tab_state(self, tab_index):
        if tab_index < 0 or tab_index >= len(self.tab_states):
            return

        state = self.tab_states[tab_index]

        active_view = self.active_item_view()
        scrollbar = active_view.verticalScrollBar() if active_view is not None else None
        scroll_value = scrollbar.value() if scrollbar else 0
        self._pane_state_service.capture_state(
            state,
            current_path=self.current_location.path,
            view_mode=self.filetree_view_mode,
            icon_zoom_percent=self.icon_zoom_percent,
            selected_paths=self.selected_paths(),
            scroll_value=scroll_value,
        )

    def apply_tab_state(self, state, push_history=False):
        self.icon_zoom_percent = max(50, min(300, int(getattr(state, "icon_zoom_percent", 100))))
        self.apply_view_mode(state.view_mode)
        self.navigate_to(state.location, push_history=push_history)

        self._selection_restore_service.remember(state.selected_paths, state.scroll_value)
        QTimer.singleShot(0, self.apply_pending_restore_state)
        QTimer.singleShot(0, self.optimize_columns)

    def apply_pending_restore_state(self):
        if self._dispose_prepared:
            return
        self._selection_restore_service.consume(
            index_for_path=self._restore_index_for_path,
            select_index=self._restore_select_index,
            set_scroll_value=self._restore_scroll_value,
        )

    def on_tree_double_click(self, index):
        if not index.isValid():
            return

        active_model = self.active_item_view().model() if self.active_item_view() is not None else None
        if active_model is None or not hasattr(active_model, "filePath") or not hasattr(active_model, "isDir"):
            return
        path = active_model.filePath(index)
        clean_path = QDir.cleanPath(str(path))
        if not clean_path:
            return

        if active_model.isDir(index):
            if self.current_location is not None and self.current_location.is_remote:
                self.navigate_to(PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id))
            else:
                self.navigate_to(clean_path)
            return

        if self.current_location.is_remote:
            remote_location = PaneLocation(kind="remote", path=clean_path, remote_id=self.current_location.remote_id)
            if self._open_remote_file_via_rule(remote_location):
                return
            if not self._open_remote_file_in_browser(remote_location):
                cached_path = self._download_remote_file_for_open(remote_location)
                if cached_path:
                    self._open_service.open_default(cached_path)
            return

        if not Path(clean_path).exists():
            return
        if self._open_local_file_via_office_web(clean_path):
            return
        self._open_service.open_default(clean_path)

    def navigate_to(self, path, push_history=True):
        if isinstance(path, PaneLocation):
            location = path if path.is_remote else self._resolve_local_location(path.path)
        else:
            location = self._resolve_local_location(path)
        if location is None:
            return
        target_path = location.path

        if self.view_stack is not None and self.search_results_view is not None:
            if self.view_stack.currentWidget() is self.search_results_view:
                self.close_search_bar()

        active_state = self.get_active_tab_state()
        if active_state is None:
            return

        if active_state.pinned and location != active_state.location:
            tab_title = self._navigation_service.display_name_for_location(location)
            new_state = TabState(title=tab_title, location=location)
            self.tab_states.append(new_state)
            self.update_tab_visual(self.tab_bar.addTab(tab_title))

            new_index = len(self.tab_states) - 1
            if new_index >= 0:
                new_state = self.tab_states[new_index]
                new_state.view_mode = active_state.view_mode
                new_state.icon_zoom_percent = active_state.icon_zoom_percent
                new_state.history = self._history_service.record_navigation(
                    new_state.history,
                    active_state.location,
                    location,
                    push_history,
                )
                self.tab_bar.setCurrentIndex(new_index)
            return

        active_state.history = self._history_service.record_navigation(
            active_state.history,
            active_state.location,
            location,
            push_history,
        )

        active_state.location = location
        self._set_current_location(location)

        tab_title = self._navigation_service.display_name_for_location(location)
        if location.is_remote and self._remote_drive_controller is not None:
            tab_title = self._remote_drive_controller.display_name_for_location(location)
        active_state.title = tab_title
        if self.active_tab_index >= 0:
            self.tab_bar.setTabText(self.active_tab_index, tab_title)
            self.update_tab_visual(self.active_tab_index)

        if location.is_remote:
            self._pending_root_path = None
            if self._remote_drive_controller is None:
                self.show_operation_feedback(
                    app_tr("PaneController", "Remote-Kontexte sind im Pane noch nicht aktiviert")
                )
                return
            try:
                entries = self._remote_drive_controller.list_directory(location)
            except Exception as error:
                self.show_operation_feedback(str(error))
                return
            self._remote_model.set_directory_entries(location, self._filtered_remote_entries(entries))
            self._apply_browser_model(self._remote_model)
            self._set_remote_view_interaction_enabled(True)
            for view in (self.tree_view, self.icon_view):
                if view is None:
                    continue
                view.setDragEnabled(True)
                view.setAcceptDrops(True)
                view.viewport().setAcceptDrops(True)
                view.setDropIndicatorShown(True)
                view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
            if self.tree_view is not None:
                self.tree_view.setRootIndex(QModelIndex())
            if self.icon_view is not None:
                self.icon_view.setRootIndex(QModelIndex())
            if self.path_bar:
                self.path_bar.set_location(
                    location,
                    root_label=self._path_bar_root_label_for_location(location),
                )
            self._apply_tree_header_translations()
            self._apply_visible_tree_columns()
            self.apply_current_sort()
            self.optimize_columns()
            self.currentPathChanged.emit(location.path)
            self.emit_navigation_state()
            return

        self._apply_browser_model(self.model)
        self._set_remote_view_interaction_enabled(True)
        for view in (self.tree_view, self.icon_view):
            if view is None:
                continue
            view.setDragEnabled(True)
            view.setAcceptDrops(True)
            view.viewport().setAcceptDrops(True)
            view.setDropIndicatorShown(True)
            view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self._pending_root_path = target_path
        root_index = self.model.setRootPath(target_path)
        index = root_index if root_index.isValid() else self.model.index(target_path)
        if index.isValid():
            self.tree_view.collapseAll()
            self.tree_view.setRootIndex(index)
            self.tree_view.expand(index)
            if self.icon_view is not None:
                self.icon_view.setRootIndex(index)

        if self.path_bar:
            self.path_bar.set_location(
                location,
                root_label=self._path_bar_root_label_for_location(location),
            )

        self.currentPathChanged.emit(target_path)
        self.emit_navigation_state()

    def navigate_back(self):
        active_state = self.get_active_tab_state()
        if not active_state:
            return
        history, previous_path = self._history_service.pop_previous(active_state.history)
        if previous_path is None:
            return
        active_state.history = history
        self.navigate_to(previous_path, push_history=False)

    def navigate_up(self):
        current_location = self.current_location
        if current_location is None:
            return
        if current_location.is_remote:
            parent_location = self._remote_drive_controller.get_parent_location(current_location) if self._remote_drive_controller is not None else None
        else:
            parent_location = self._navigation_service.get_parent_location(current_location)
        if parent_location is None:
            return
        self.navigate_to(parent_location)

    def can_go_back(self):
        active_state = self.get_active_tab_state()
        return bool(active_state and self._history_service.can_go_back(active_state.history))

    def can_go_up(self):
        current_location = self.current_location
        if current_location is None:
            return False
        if current_location.is_remote:
            if self._remote_drive_controller is None:
                return False
            return self._remote_drive_controller.get_parent_location(current_location) is not None
        return self._navigation_service.get_parent_location(current_location) is not None

    def current_path(self):
        return self.current_location.path

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
            self._apply_visible_tree_columns()
            self.apply_icon_zoom()
            self.optimize_columns()
            return

        self.tree_view.setRootIsDecorated(False)
        self.tree_view.setItemsExpandable(False)
        self.tree_view.setIndentation(0)
        active_model = self._active_file_model()
        for column in range(1, active_model.columnCount() if active_model is not None else 1):
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
        if self._dispose_prepared or self.tree_view is None:
            return
        active_model = self._active_file_model()
        if active_model is None:
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
                for column in range(active_model.columnCount()):
                    self.tree_view.resizeColumnToContents(column)
            else:
                self.tree_view.resizeColumnToContents(0)
        except RuntimeError:
            return

    def apply_current_sort(self):
        if self._dispose_prepared or self.tree_view is None:
            return
        active_model = self._active_file_model()
        if active_model is None:
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
            active_model.sort(section, order)
            self.tree_view.sortByColumn(section, order)
        except RuntimeError:
            return

    def force_resort(self):
        if self._dispose_prepared or self.tree_view is None:
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

    def refresh_current_directory(self, preserve_focus=False, force_rescan=False):
        if self._dispose_prepared:
            return
        focused_widget = QApplication.focusWidget()
        active_view = self.active_item_view()
        should_restore_focus = bool(
            preserve_focus
            or (active_view is not None and focused_widget is not None and active_view.isAncestorOf(focused_widget))
        )

        self.commit_pending_tree_edit()
        if force_rescan and self.current_location is not None and self.current_location.is_local:
            # Force QFileSystemModel cache invalidation by switching root once.
            try:
                self.model.setRootPath(QDir.rootPath())
            except RuntimeError:
                pass
        self.navigate_to(self.current_location, push_history=False)
        self.apply_current_sort()
        self.force_resort()
        QTimer.singleShot(150, self.apply_current_sort)
        QTimer.singleShot(200, self.force_resort)
        if should_restore_focus:
            QTimer.singleShot(0, self._restore_active_view_focus_if_alive)

    def get_active_tab_state(self):
        if self.active_tab_index < 0 or self.active_tab_index >= len(self.tab_states):
            return None
        return self.tab_states[self.active_tab_index]

    def emit_navigation_state(self):
        self.update_navigation_buttons()
        self.navigationStateChanged.emit(self.can_go_back(), self.can_go_up())

    def update_navigation_buttons(self):
        if self.btn_nav_back is not None:
            self.btn_nav_back.setEnabled(self.can_go_back())
        if self.btn_nav_up is not None:
            self.btn_nav_up.setEnabled(self.can_go_up())

    def export_state(self):
        self.capture_tab_state(self.active_tab_index)
        return {
            "active_tab_index": self.active_tab_index,
            "tabs": self._pane_state_service.serialize_states(self.tab_states),
        }

    def export_active_tab_state(self):
        self.capture_tab_state(self.active_tab_index)
        active_state = self.get_active_tab_state()
        if active_state is None:
            return None

        return {
            "active_tab_index": 0,
            "tabs": [self._pane_state_service.serialize_state(active_state)],
        }

    def import_state(self, state_data):
        if not isinstance(state_data, dict):
            return

        raw_tabs = state_data.get("tabs")
        if not isinstance(raw_tabs, list) or not raw_tabs:
            return

        restored_states = self._pane_state_service.deserialize_states(raw_tabs, self.current_location.path)

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
