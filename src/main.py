# Copyright 2026 Antonio Cambule
# Licensed under the EUPL-1.2-or-later
# https://github.com/acambule/tablion

import sys
import json
import shutil
import traceback
from pathlib import Path
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileSystemModel, QTreeWidget, QSplitter, QWidget, QToolButton, QStyle, QMenu, QTabWidget, QVBoxLayout, QSizePolicy, QMessageBox)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QDir, QEvent, Qt, QTimer, QStandardPaths

from controllers.group_controller import GroupController
from debug_log import debug_exception, debug_log, initialize_debug_log
from localization import setup_localization
from models.navigator import NavigatorManager
from widgets.group_workspace_widget import GroupWorkspaceWidget


APP_NAME = "Tablion"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(None)
        loader = QUiLoader()
        ui_path = Path(__file__).resolve().parent / 'ui' / 'main.ui'
        self.navigator_data_path = Path()
        self.session_data_path = Path()
        self.debug_log_path = Path()
        self.initialize_storage_paths()
        initialize_debug_log(self.debug_log_path)
        debug_log("MainWindow.__init__ started")

        self.group_tabs = None
        self.group_content_host = None
        self.group_controller = None
        self.navigator_manager = None
        self.btn_nav_menu = None
        self.btn_split_view = None
        self.btn_nav_back = None
        self.btn_nav_up = None
        self.action_refresh_tree = None
        self.plain_tabbing_mode = True
        self._persisted_once = False
        self._restored_splitter_sizes = False

        self.ui = loader.load(str(ui_path))
        if self.ui is None:
            raise RuntimeError(f"Konnte UI nicht laden: {ui_path}")
        self.update_window_title(QDir.homePath())

        if self.ui.menuBar():
            self.ui.menuBar().hide()
        self.ui.installEventFilter(self)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.persist_app_state)
            app.focusChanged.connect(self.on_app_focus_changed)

        self.model = QFileSystemModel()
        root_path = QDir.homePath()
        self.model.setRootPath(root_path)
        self.model.setReadOnly(False)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.NoDotAndDotDot)

        self.setup_group_tabs()
        self.setup_navigation_toolbar()
        self.setup_navigator()
        self.setup_shortcuts()
        self.load_session_state()

        QTimer.singleShot(0, self.focus_active_tree_view)

        splitter = self.ui.findChild(QSplitter, "splitter")
        if splitter and not self._restored_splitter_sizes:
            splitter.setSizes([200, 1000])

    def initialize_storage_paths(self):
        app_dir_name = APP_NAME.lower()

        config_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        if not config_root:
            config_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.ConfigLocation)
        config_dir = Path(config_root) if config_root else (Path.home() / '.config' / app_dir_name)

        state_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.StateLocation)
        if not state_root:
            state_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        state_dir = Path(state_root) if state_root else (config_dir / 'state')

        self.navigator_data_path = config_dir / 'navigator.json'
        self.session_data_path = state_dir / 'session.json'
        self.debug_log_path = state_dir / 'debug.log'

        self.migrate_legacy_json_if_needed()

    def migrate_legacy_json_if_needed(self):
        legacy_base = Path(__file__).resolve().parent / 'models'
        migration_map = {
            legacy_base / 'navigator.json': self.navigator_data_path,
            legacy_base / 'session.json': self.session_data_path,
        }

        for legacy_path, target_path in migration_map.items():
            if target_path.exists() or not legacy_path.exists():
                continue

            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(legacy_path, target_path)
            except OSError:
                continue

    def show(self):
        self.ui.show()

    def setup_group_tabs(self):
        self.group_tabs = self.ui.findChild(QTabWidget, "groupTabs")
        self.group_content_host = self.ui.findChild(QWidget, "groupContentHost")
        if not self.group_tabs:
            return
        if not self.group_content_host:
            return

        if self.group_content_host.layout() is None:
            content_layout = QVBoxLayout(self.group_content_host)
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            self.group_content_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.group_tabs.setMovable(True)
        self.group_tabs.setTabsClosable(False)
        self.group_tabs.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self.group_tabs.installEventFilter(self)
        self.group_tabs.tabBar().installEventFilter(self)
        self.group_tabs.tabBar().tabBarDoubleClicked.connect(self.on_group_tab_bar_double_clicked)

        self.group_controller = GroupController(
            group_tabs=self.group_tabs,
            model=self.model,
            host_ui=self.ui,
            on_pane_path_changed=self.on_pane_path_changed,
            on_pane_navigation_changed=self.on_pane_navigation_changed,
            on_pane_group_requested=self.on_pane_group_requested,
            render_active_group=self.render_active_group_pane,
            update_nav_buttons=self.update_nav_buttons,
            plain_tabbing_mode=self.plain_tabbing_mode,
        )
        self.group_controller.initialize_existing_groups()

        self.group_tabs.currentChanged.connect(self.on_group_tab_changed)
        self.group_controller.refresh_group_tabs_presentation()
        self.render_active_group_pane()

        active_pane = self.get_active_pane()
        if active_pane:
            self.update_window_title(active_pane.current_path())
            self.update_nav_buttons()

    def _group_menu_icon(self, theme_name, fallback_pixmap):
        icon = QIcon.fromTheme(theme_name)
        if icon.isNull():
            icon = self.ui.style().standardIcon(fallback_pixmap)
        return icon

    def get_active_pane(self):
        if not self.group_tabs:
            return None
        current_page = self.group_tabs.currentWidget()
        return self.group_controller.group_panes_by_page.get(current_page) if self.group_controller else None

    def get_page_for_pane(self, target_pane):
        if not self.group_controller:
            return None
        for page, pane in self.group_controller.group_panes_by_page.items():
            if pane is target_pane:
                return page
        return None

    def export_split_state_for_page(self, page):
        pane = self.group_controller.group_panes_by_page.get(page) if self.group_controller else None
        if not pane:
            return {"split_mode": "single"}
        return pane.export_split_state()

    def restore_split_state_for_page(self, page, split_mode, secondary_state, tertiary_state=None, quaternary_state=None):
        pane = self.group_controller.group_panes_by_page.get(page) if self.group_controller else None
        if not pane:
            return
        pane.restore_split_state(split_mode, secondary_state, tertiary_state, quaternary_state)

    def update_split_active_highlight(self):
        if not self.group_tabs:
            return

        active_page = self.group_tabs.currentWidget()
        if not self.group_controller:
            return
        for page, pane in self.group_controller.group_panes_by_page.items():
            pane.set_group_active(page == active_page)

    def on_app_focus_changed(self, _old, _new):
        self.update_split_active_highlight()
        active_pane = self.get_active_pane()
        if active_pane:
            self.update_window_title(active_pane.current_path())
            self.update_nav_buttons()

    def on_group_tab_changed(self, _index):
        self.render_active_group_pane()
        self.update_split_active_highlight()
        active_pane = self.get_active_pane()
        if not active_pane:
            return
        self.update_window_title(active_pane.current_path())
        self.update_nav_buttons()

    def render_active_group_pane(self):
        if not self.group_tabs or not self.group_content_host:
            return

        active_page = self.group_tabs.currentWidget()
        if not self.group_controller:
            return
        active_group = self.group_controller.group_panes_by_page.get(active_page)
        if not active_group:
            return

        content_layout = self.group_content_host.layout()
        while content_layout.count() > 0:
            item = content_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)

        for pane in self.group_controller.group_panes_by_page.values():
            pane.widget.setVisible(False)

        active_group.widget.setParent(self.group_content_host)
        active_group.widget.setVisible(True)
        content_layout.addWidget(active_group.widget, 1)
        active_group.optimize_columns()
        self.update_split_active_highlight()

    def set_single_view_mode(self):
        active_pane = self.get_active_pane()
        if not active_pane:
            return
        active_pane.set_split_mode("single")
        self.update_split_active_highlight()
        self.update_nav_buttons()
        self.update_window_title(active_pane.current_path())

    def set_two_split_view_mode(self):
        active_pane = self.get_active_pane()
        if not active_pane:
            return
        active_pane.set_split_mode("2-split")
        self.update_split_active_highlight()
        self.update_nav_buttons()
        self.update_window_title(active_pane.current_path())

    def set_four_split_view_mode(self):
        active_pane = self.get_active_pane()
        if not active_pane:
            return
        active_pane.set_split_mode("4-split")
        self.update_split_active_highlight()
        self.update_nav_buttons()
        self.update_window_title(active_pane.current_path())

    def on_group_tab_bar_double_clicked(self, tab_index):
        debug_log(f"on_group_tab_bar_double_clicked(tab_index={tab_index})")
        if tab_index == -1:
            active_pane = self.get_active_pane()
            start_path = active_pane.current_path() if active_pane else QDir.homePath()
            debug_log(f"Creating group from tab-bar double click with start_path={start_path}")
            self.create_group(start_path=start_path)
            return

        if tab_index > 0:
            debug_log(f"Renaming group from tab-bar double click at index={tab_index}")
            self.rename_group(tab_index)

    def is_group_header_area_click(self, pos):
        if not self.group_tabs:
            return False
        tab_bar = self.group_tabs.tabBar()
        header_height = tab_bar.height() if tab_bar.isVisible() else 30
        return 0 <= pos.y() <= header_height

    def create_group(self, title=None, start_path=None):
        debug_log(f"create_group(title={title}, start_path={start_path})")
        try:
            return self.group_controller.create_group(title=title, start_path=start_path) if self.group_controller else None
        except Exception as error:
            debug_exception("create_group failed", error)
            raise

    def close_group(self, index, confirm=True):
        if self.group_controller:
            self.group_controller.close_group(index, confirm=confirm)

    def clear_visible_groups(self):
        if self.group_controller:
            self.group_controller.clear_visible_groups()

    def rename_group(self, index):
        debug_log(f"rename_group(index={index})")
        if self.group_controller:
            self.group_controller.rename_group(index)

    def refresh_group_tabs_presentation(self):
        if self.group_controller:
            self.group_controller.refresh_group_tabs_presentation()

    def visible_group_indices(self):
        return self.group_controller.visible_group_indices() if self.group_controller else []

    def get_group_zero_pane(self):
        return self.group_controller.get_group_zero_pane() if self.group_controller else None

    def reset_group_zero_to_default(self):
        if self.group_controller:
            self.group_controller.reset_group_zero_to_default()

    def can_offer_grouping(self, pane_controller):
        return self.group_controller.can_offer_grouping(pane_controller) if self.group_controller else False

    def on_pane_group_requested(self):
        source_pane = self.sender()
        if not isinstance(source_pane, GroupWorkspaceWidget):
            return
        if not self.can_offer_grouping(source_pane):
            return

        moved_states, active_index = source_pane.move_tabs_out_and_reset(QDir.homePath())
        if not moved_states:
            return

        active_index = max(0, min(active_index, len(moved_states) - 1))
        start_path = moved_states[active_index].path
        new_group_title = f"Gruppe {len(self.visible_group_indices()) + 1}"
        target_pane = self.create_group(title=new_group_title, start_path=start_path)
        if target_pane:
            target_pane.replace_tabs(moved_states, active_index=active_index)
            self.update_nav_buttons()

    def save_session_state(self):
        if not self.group_tabs:
            return

        group_zero_pane = self.get_group_zero_pane()
        group_zero_state = None
        group_zero_page = None
        if self.group_tabs and self.group_tabs.count() > 0:
            group_zero_page = self.group_tabs.widget(0)
        if group_zero_pane:
            group_zero_state = {
                "pane": group_zero_pane.export_state(),
                **(self.export_split_state_for_page(group_zero_page) if group_zero_page else {"split_mode": "single"}),
            }

        groups_payload = []
        for index in self.visible_group_indices():
            page = self.group_tabs.widget(index)
            pane = self.group_controller.group_panes_by_page.get(page) if self.group_controller else None
            if not pane:
                continue

            groups_payload.append(
                {
                    "title": self.group_tabs.tabText(index).strip() or f"Gruppe {index}",
                    "pane": pane.export_state(),
                    **self.export_split_state_for_page(page),
                }
            )

        payload = {
            "version": 1,
            "active_group_index": self.group_tabs.currentIndex(),
            "group0": group_zero_state,
            "groups": groups_payload,
        }

        window_geometry = self.ui.normalGeometry() if self.ui.isMaximized() else self.ui.geometry()
        payload["window"] = {
            "x": window_geometry.x(),
            "y": window_geometry.y(),
            "width": window_geometry.width(),
            "height": window_geometry.height(),
            "maximized": self.ui.isMaximized(),
        }

        splitter = self.ui.findChild(QSplitter, "splitter")
        if splitter:
            payload["splitter_sizes"] = splitter.sizes()

        self.session_data_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_data_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def load_session_state(self):
        if not self.group_tabs:
            return
        if not self.session_data_path.exists():
            return

        try:
            payload = json.loads(self.session_data_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return

        if not isinstance(payload, dict):
            return

        window_data = payload.get("window")
        if isinstance(window_data, dict):
            try:
                x = int(window_data.get("x", 100))
                y = int(window_data.get("y", 100))
                width = int(window_data.get("width", 1200))
                height = int(window_data.get("height", 800))
                if width > 0 and height > 0:
                    self.ui.setGeometry(x, y, width, height)
                if bool(window_data.get("maximized", False)):
                    self.ui.setWindowState(self.ui.windowState() | Qt.WindowState.WindowMaximized)
            except (TypeError, ValueError):
                pass

        raw_splitter_sizes = payload.get("splitter_sizes")
        splitter = self.ui.findChild(QSplitter, "splitter")
        if splitter and isinstance(raw_splitter_sizes, list):
            try:
                splitter_sizes = [int(size) for size in raw_splitter_sizes if int(size) > 0]
            except (TypeError, ValueError):
                splitter_sizes = []

            if splitter_sizes:
                splitter.setSizes(splitter_sizes)
                self._restored_splitter_sizes = True

        self.clear_visible_groups()

        group_zero_pane = self.get_group_zero_pane()
        group_zero_payload = payload.get("group0")
        if group_zero_pane and isinstance(group_zero_payload, dict):
            if isinstance(group_zero_payload.get("tabs"), list):
                group_zero_pane.import_state(group_zero_payload)
                group_zero_page = self.group_tabs.widget(0) if self.group_tabs.count() > 0 else None
                if group_zero_page is not None:
                    self.restore_split_state_for_page(group_zero_page, "single", None)
            else:
                pane_payload = group_zero_payload.get("pane")
                split_mode = str(group_zero_payload.get("split_mode") or "single")
                secondary_payload = group_zero_payload.get("secondary_pane")
                tertiary_payload = group_zero_payload.get("tertiary_pane")
                quaternary_payload = group_zero_payload.get("quaternary_pane")

                if isinstance(pane_payload, dict):
                    group_zero_pane.import_state(pane_payload)

                group_zero_page = self.group_tabs.widget(0) if self.group_tabs.count() > 0 else None
                if group_zero_page is not None:
                    self.restore_split_state_for_page(
                        group_zero_page,
                        split_mode,
                        secondary_payload,
                        tertiary_payload,
                        quaternary_payload,
                    )

        raw_groups = payload.get("groups")
        if isinstance(raw_groups, list):
            for group_data in raw_groups:
                if not isinstance(group_data, dict):
                    continue

                title = str(group_data.get("title") or "").strip() or None
                pane_data = group_data.get("pane")
                split_mode = str(group_data.get("split_mode") or "single")
                secondary_payload = group_data.get("secondary_pane")
                tertiary_payload = group_data.get("tertiary_pane")
                quaternary_payload = group_data.get("quaternary_pane")

                start_path = QDir.homePath()
                if isinstance(pane_data, dict):
                    tabs = pane_data.get("tabs")
                    if isinstance(tabs, list) and tabs:
                        first_tab = tabs[0]
                        if isinstance(first_tab, dict):
                            candidate = QDir.cleanPath(str(first_tab.get("path") or ""))
                            if candidate and QDir(candidate).exists():
                                start_path = candidate

                pane = self.create_group(title=title, start_path=start_path)
                if pane and isinstance(pane_data, dict):
                    pane.import_state(pane_data)

                if pane:
                    page = self.get_page_for_pane(pane)
                    if page is not None:
                        self.restore_split_state_for_page(
                            page,
                            split_mode,
                            secondary_payload,
                            tertiary_payload,
                            quaternary_payload,
                        )

        raw_active_group_index = payload.get("active_group_index", 0)
        try:
            active_group_index = int(raw_active_group_index)
        except (TypeError, ValueError):
            active_group_index = 0

        active_group_index = max(0, min(active_group_index, self.group_tabs.count() - 1))
        self.group_tabs.setCurrentIndex(active_group_index)
        self.refresh_group_tabs_presentation()
        self.update_nav_buttons()

        active_pane = self.get_active_pane()
        if active_pane:
            self.update_window_title(active_pane.current_path())

    def on_pane_path_changed(self, path):
        if self.sender() != self.get_active_pane():
            return
        self.update_window_title(path)

    def on_pane_navigation_changed(self, _can_back, _can_up):
        if self.sender() != self.get_active_pane():
            return
        self.update_nav_buttons()

    def persist_app_state(self):
        if self._persisted_once:
            return
        self._persisted_once = True

        debug_log("persist_app_state called")
        self.save_session_state()
        if self.navigator_manager:
            self.navigator_manager.save_current_state()

    def eventFilter(self, watched, event):
        try:
            if watched == self.ui and event.type() == QEvent.Type.Close:
                self.persist_app_state()

            if self.group_tabs and watched == self.group_tabs:
                if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                    click_pos = event.position().toPoint()
                    tab_bar = self.group_tabs.tabBar()
                    tab_bar_pos = tab_bar.mapFrom(self.group_tabs, click_pos)
                    clicked_tab = tab_bar.tabAt(tab_bar_pos)
                    if self.is_group_header_area_click(click_pos) and clicked_tab == -1:
                        active_pane = self.get_active_pane()
                        start_path = active_pane.current_path() if active_pane else QDir.homePath()
                        self.create_group(start_path=start_path)
                        return True

            if self.group_tabs and watched == self.group_tabs.tabBar():
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                    tab_bar = self.group_tabs.tabBar()
                    global_pos = event.globalPosition().toPoint()
                    tab_bar_pos = tab_bar.mapFromGlobal(global_pos)
                    tab_index = tab_bar.tabAt(tab_bar_pos)
                    if tab_index > 0:
                        self.close_group(tab_index)
                        return True

                if event.type() == QEvent.Type.ContextMenu:
                    tab_bar = self.group_tabs.tabBar()
                    tab_index = tab_bar.tabAt(event.pos())

                    menu = QMenu(tab_bar)
                    action_new_group = menu.addAction(
                        self._group_menu_icon("folder-new", QStyle.StandardPixmap.SP_FileDialogNewFolder),
                        "Neue Gruppe",
                    )
                    action_rename_group = None
                    if tab_index > 0:
                        action_rename_group = menu.addAction(
                            self._group_menu_icon("edit-rename", QStyle.StandardPixmap.SP_FileDialogDetailedView),
                            "Umbenennen",
                        )
                    action_close_group = None
                    if tab_index > 0:
                        action_close_group = menu.addAction(
                            self._group_menu_icon("window-close", QStyle.StandardPixmap.SP_DialogCloseButton),
                            "Gruppe schließen",
                        )

                    chosen_action = menu.exec(event.globalPos())
                    if chosen_action == action_new_group:
                        active_pane = self.get_active_pane()
                        start_path = active_pane.current_path() if active_pane else QDir.homePath()
                        self.create_group(start_path=start_path)
                        return True
                    if action_rename_group is not None and chosen_action == action_rename_group:
                        self.rename_group(tab_index)
                        return True
                    if action_close_group is not None and chosen_action == action_close_group:
                        self.close_group(tab_index)
                        return True
                    return True

            return super().eventFilter(watched, event)
        except RuntimeError:
            return False

    def setup_navigation_toolbar(self):
        self.btn_nav_menu = self.ui.findChild(QToolButton, "btnNavMenu")
        self.btn_split_view = self.ui.findChild(QToolButton, "btnSplitView")
        self.btn_nav_back = self.ui.findChild(QToolButton, "btnNavBack")
        self.btn_nav_up = self.ui.findChild(QToolButton, "btnNavUp")

        style = self.ui.style()

        if self.btn_nav_menu:
            menu_icon = QIcon.fromTheme("application-menu")
            if menu_icon.isNull():
                menu_icon = style.standardIcon(QStyle.StandardPixmap.SP_TitleBarMenuButton)
            self.btn_nav_menu.setIcon(menu_icon)
            self.btn_nav_menu.setText("")
            self.btn_nav_menu.setToolTip("Menü")
            self.btn_nav_menu.setAutoRaise(True)
            self.btn_nav_menu.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_nav_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

            burger_menu = QMenu(self.btn_nav_menu)
            info_icon = QIcon.fromTheme("help-about")
            if info_icon.isNull():
                info_icon = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
            action_info = burger_menu.addAction(info_icon, "Über / Info")
            action_info.triggered.connect(self.show_about_info)

            burger_menu.addSeparator()

            quit_icon = QIcon.fromTheme("application-exit")
            if quit_icon.isNull():
                quit_icon = style.standardIcon(QStyle.StandardPixmap.SP_TitleBarCloseButton)
            action_quit = burger_menu.addAction(quit_icon, "Beenden")
            action_quit.setShortcut(QKeySequence.StandardKey.Quit)
            action_quit.setShortcutVisibleInContextMenu(True)
            action_quit.triggered.connect(self.quit_application)
            self.btn_nav_menu.setMenu(burger_menu)

        if self.btn_split_view:
            split_icon = QIcon.fromTheme("view-split-left-right")
            if split_icon.isNull():
                split_icon = QIcon.fromTheme("view-grid")
            if split_icon.isNull():
                split_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)

            self.btn_split_view.setIcon(split_icon)
            self.btn_split_view.setText("")
            self.btn_split_view.setToolTip("Split-View")
            self.btn_split_view.setAutoRaise(True)
            self.btn_split_view.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_split_view.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

            split_menu = QMenu(self.btn_split_view)
            action_split_single = split_menu.addAction("Einzelansicht")
            split_menu.addSeparator()
            action_split_2 = split_menu.addAction("2-Split")
            action_split_4 = split_menu.addAction("4-Split")
            action_split_single.triggered.connect(lambda: self.on_split_view_selected("single"))
            action_split_2.triggered.connect(lambda: self.on_split_view_selected("2-split"))
            action_split_4.triggered.connect(lambda: self.on_split_view_selected("4-split"))
            self.btn_split_view.setMenu(split_menu)

        if self.btn_nav_back:
            self.btn_nav_back.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_ArrowBack))
            self.btn_nav_back.setText("")
            self.btn_nav_back.setToolTip("Zurück")
            self.btn_nav_back.setAutoRaise(True)
            self.btn_nav_back.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_nav_back.clicked.connect(self.navigate_back)

        if self.btn_nav_up:
            self.btn_nav_up.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogToParent))
            self.btn_nav_up.setText("")
            self.btn_nav_up.setToolTip("Eine Ebene nach oben")
            self.btn_nav_up.setAutoRaise(True)
            self.btn_nav_up.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.btn_nav_up.clicked.connect(self.navigate_up)

        self.update_nav_buttons()
    
    def setup_navigator(self):
        navigator_widget = self.ui.findChild(QTreeWidget, "treeNavigator")
        if not navigator_widget:
            return

        self.navigator_manager = NavigatorManager(navigator_widget, self.navigator_data_path)
        self.navigator_manager.setup()
        navigator_widget.itemClicked.connect(self.on_nav_click)

    def setup_shortcuts(self):
        self.action_refresh_tree = QAction(self.ui)
        self.action_refresh_tree.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self.action_refresh_tree.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.action_refresh_tree.triggered.connect(self.refresh_active_tree_view)
        self.ui.addAction(self.action_refresh_tree)
    
    def on_nav_click(self, item):
        if not self.navigator_manager:
            return

        path = self.navigator_manager.get_entry_path(item)
        if not path:
            return

        active_pane = self.get_active_pane()
        if active_pane:
            active_pane.navigate_to(path)

    def navigate_back(self):
        active_pane = self.get_active_pane()
        if active_pane:
            active_pane.navigate_back()

    def navigate_up(self):
        active_pane = self.get_active_pane()
        if active_pane:
            active_pane.navigate_up()

    def update_nav_buttons(self):
        active_pane = self.get_active_pane()

        if self.btn_nav_back:
            self.btn_nav_back.setEnabled(bool(active_pane and active_pane.can_go_back()))

        if self.btn_nav_up:
            self.btn_nav_up.setEnabled(bool(active_pane and active_pane.can_go_up()))

    def update_window_title(self, path):
        normalized = QDir.cleanPath(path)
        self.ui.setWindowTitle(f"{normalized} - {APP_NAME}")

    def refresh_active_tree_view(self):
        active_pane = self.get_active_pane()
        if active_pane and hasattr(active_pane, "refresh_current_directory"):
            active_pane.refresh_current_directory()

    def focus_active_tree_view(self):
        active_pane = self.get_active_pane()
        tree_view = getattr(active_pane, "tree_view", None) if active_pane else None
        if tree_view is not None:
            tree_view.setFocus()

    def on_split_view_selected(self, mode):
        if mode == "single":
            self.set_single_view_mode()
            return
        if mode == "2-split":
            self.set_two_split_view_mode()
            return
        if mode == "4-split":
            self.set_four_split_view_mode()
            return

    def closeEvent(self, event):
        debug_log("MainWindow.closeEvent received")
        self.persist_app_state()
        super().closeEvent(event)

    def quit_application(self):
        self.persist_app_state()
        QApplication.instance().quit()

    def show_about_info(self):
        info_text = (
            f"{APP_NAME}\n\n"
            "Ein einfacher Dateimanager auf Basis von PySide6.\n\n"
            f"Navigator-Daten:\n{self.navigator_data_path}\n\n"
            f"Sitzungsdaten:\n{self.session_data_path}"
        )
        QMessageBox.information(self.ui, "Über / Info", info_text)

if __name__ == "__main__":
    def _global_excepthook(exc_type, exc_value, exc_traceback):
        try:
            details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
            debug_log(f"UNHANDLED EXCEPTION: {details}")
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _global_excepthook

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    setup_localization(app)
    project_root = Path(__file__).resolve().parent.parent
    icon_candidates = [
        project_root / "assets" / "tablion-icon.png",
        project_root / "assets" / "tablion-icon.svg",
    ]
    for icon_path in icon_candidates:
        if icon_path.exists():
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                app.setWindowIcon(icon)
                break

    window = MainWindow()
    window.ui.setWindowIcon(app.windowIcon())
    window.show()
    sys.exit(app.exec())
