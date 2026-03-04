from typing import Optional
from pathlib import Path

from PySide6.QtCore import QDir
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QSizePolicy, QTabWidget, QWidget

from debug_log import debug_exception, debug_log
from localization import app_tr, ask_yes_no
from models.editor_settings import EditorSettings
from widgets.manage_tab_groups_dialog import ManageTabGroupsDialog
from widgets.group_workspace_widget import GroupWorkspaceWidget


class GroupController:
    def __init__(
        self,
        *,
        group_tabs: QTabWidget,
        model,
        host_ui: QWidget,
        on_pane_path_changed,
        on_pane_navigation_changed,
        on_pane_group_requested,
        render_active_group,
        update_nav_buttons,
        plain_tabbing_mode=True,
        editor_settings: Optional[EditorSettings] = None,
    ):
        self.group_tabs = group_tabs
        self.model = model
        self.host_ui = host_ui
        self.on_pane_path_changed = on_pane_path_changed
        self.on_pane_navigation_changed = on_pane_navigation_changed
        self.on_pane_group_requested = on_pane_group_requested
        self.render_active_group = render_active_group
        self.update_nav_buttons = update_nav_buttons
        self.plain_tabbing_mode = plain_tabbing_mode
        self.editor_settings = editor_settings

        self.group_panes_by_page = {}

    def _connect_pane_signals(self, pane_controller):
        pane_controller.currentPathChanged.connect(self.on_pane_path_changed)
        pane_controller.navigationStateChanged.connect(self.on_pane_navigation_changed)
        pane_controller.groupRequested.connect(self.on_pane_group_requested)

    def apply_close_icon_settings(self, show_file_tab_close_icons: bool):
        for pane_controller in self.group_panes_by_page.values():
            if hasattr(pane_controller, "apply_close_icon_settings"):
                pane_controller.apply_close_icon_settings(show_file_tab_close_icons)

    def retranslate_panes(self):
        for pane_controller in self.group_panes_by_page.values():
            if hasattr(pane_controller, "retranslate_ui_texts"):
                pane_controller.retranslate_ui_texts()

    def _resolve_group_icon(self, page) -> QIcon:
        if page is None:
            return QIcon()

        raw_value = str(page.property("group_icon") or "").strip()
        if not raw_value:
            return QIcon()

        theme_icon = QIcon.fromTheme(raw_value)
        if not theme_icon.isNull():
            return theme_icon

        candidate = Path(raw_value).expanduser()
        if candidate.exists():
            return QIcon(str(candidate))

        return QIcon()

    def initialize_existing_groups(self):
        for index in range(self.group_tabs.count()):
            page = self.group_tabs.widget(index)
            pane_controller = GroupWorkspaceWidget(
                self.model,
                parent=self.host_ui,
                editor_settings=self.editor_settings,
            )
            pane_controller.widget.setParent(None)
            pane_controller.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.group_panes_by_page[page] = pane_controller
            self._connect_pane_signals(pane_controller)

    def create_group(self, title=None, start_path=None):
        debug_log(f"GroupController.create_group(title={title}, start_path={start_path})")
        start_path = QDir.cleanPath(start_path or QDir.homePath())
        page = QWidget(self.group_tabs)

        pane_controller = GroupWorkspaceWidget(
            self.model,
            parent=self.host_ui,
            editor_settings=self.editor_settings,
        )
        pane_controller.widget.setParent(None)
        pane_controller.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        tab_title = title if title is not None else f"{app_tr('GroupController', 'Gruppe')} {len(self.visible_group_indices()) + 1}"
        index = self.group_tabs.addTab(page, tab_title)
        self.group_panes_by_page[page] = pane_controller
        self._connect_pane_signals(pane_controller)
        pane_controller.navigate_to(start_path, push_history=False)

        self.group_tabs.setCurrentIndex(index)
        self.refresh_group_tabs_presentation()
        self.render_active_group()
        debug_log(f"GroupController.create_group finished index={index}")
        return pane_controller

    def close_group(self, index, confirm=True):
        if self.group_tabs.count() <= 1:
            return
        if index < 0 or index >= self.group_tabs.count():
            return
        if index == 0:
            return

        if confirm:
            group_name = self.group_tabs.tabText(index).strip() or f"{app_tr('GroupController', 'Gruppe')} {index}"
            confirmed = ask_yes_no(
                self.host_ui,
                app_tr("GroupController", "Gruppe löschen"),
                app_tr("GroupController", "Soll die Gruppe '{group_name}' wirklich gelöscht werden?").format(group_name=group_name),
                default_no=True,
            )
            if not confirmed:
                return

        page = self.group_tabs.widget(index)
        pane_controller = self.group_panes_by_page.pop(page, None)
        if pane_controller:
            if hasattr(pane_controller, "prepare_for_dispose"):
                pane_controller.prepare_for_dispose()
            pane_controller.widget.setVisible(False)
            pane_controller.deleteLater()

        self.group_tabs.removeTab(index)
        page.deleteLater()

        self.refresh_group_tabs_presentation()
        if not self.visible_group_indices():
            self.reset_group_zero_to_default()
        self.render_active_group()
        self.update_nav_buttons()

    def clear_visible_groups(self):
        for index in range(self.group_tabs.count() - 1, 0, -1):
            page = self.group_tabs.widget(index)
            pane_controller = self.group_panes_by_page.pop(page, None)
            if pane_controller:
                if hasattr(pane_controller, "prepare_for_dispose"):
                    pane_controller.prepare_for_dispose()
                pane_controller.widget.setVisible(False)
                pane_controller.deleteLater()
            self.group_tabs.removeTab(index)
            page.deleteLater()
        self.render_active_group()

    def rename_group(self, index):
        debug_log(f"GroupController.rename_group start index={index}")
        try:
            if index <= 0 or index >= self.group_tabs.count():
                debug_log("GroupController.rename_group aborted due to invalid index")
                return

            current_name = self.group_tabs.tabText(index).strip() or f"{app_tr('GroupController', 'Gruppe')} {index}"
            page = self.group_tabs.widget(index)
            current_icon = ""
            if page is not None:
                current_icon = str(page.property("group_icon") or "").strip()

            debug_log(f"GroupController.rename_group opening manageTabGoups dialog for current_name={current_name}")
            dialog = ManageTabGroupsDialog(None, current_name, current_icon)
            result = dialog.exec()
            debug_log(f"GroupController.rename_group manageTabGoups result={result}")
            if result != QDialog.DialogCode.Accepted:
                return

            clean_name = dialog.group_name()
            if not clean_name:
                return

            selected_icon = dialog.icon_value()

            if index <= 0 or index >= self.group_tabs.count():
                debug_log("GroupController.rename_group aborted after dialog due to invalid index")
                return
            self.group_tabs.setTabText(index, clean_name)
            page = self.group_tabs.widget(index)
            if page is not None:
                page.setProperty("group_icon", selected_icon)
                self.group_tabs.setTabIcon(index, self._resolve_group_icon(page))
            debug_log(f"GroupController.rename_group success index={index}, new_name={clean_name}")
        except RuntimeError:
            debug_log("GroupController.rename_group caught RuntimeError")
            return
        except Exception as error:
            debug_exception("GroupController.rename_group failed", error)
            return

    def refresh_group_tabs_presentation(self):
        tab_bar = self.group_tabs.tabBar()
        if self.group_tabs.count() > 0:
            self.group_tabs.setTabText(0, f"{app_tr('GroupController', 'Gruppe')} 0")
            self.group_tabs.setTabIcon(0, QIcon())
            tab_bar.setTabVisible(0, False)

        visible_groups = self.visible_group_indices()
        if self.plain_tabbing_mode and not visible_groups:
            if self.group_tabs.currentIndex() != 0:
                self.group_tabs.setCurrentIndex(0)
            tab_bar.hide()
            return

        tab_bar.show()
        for index in visible_groups:
            tab_bar.setTabVisible(index, True)

        for group_number, index in enumerate(visible_groups, start=1):
            text = self.group_tabs.tabText(index).strip()
            if not text:
                self.group_tabs.setTabText(index, f"{app_tr('GroupController', 'Gruppe')} {group_number}")
            page = self.group_tabs.widget(index)
            self.group_tabs.setTabIcon(index, self._resolve_group_icon(page))

    def visible_group_indices(self):
        return list(range(1, self.group_tabs.count()))

    def get_group_zero_pane(self):
        if self.group_tabs.count() == 0:
            return None
        group_zero_page = self.group_tabs.widget(0)
        return self.group_panes_by_page.get(group_zero_page)

    def reset_group_zero_to_default(self):
        group_zero_pane = self.get_group_zero_pane()
        if not group_zero_pane:
            return
        group_zero_pane.replace_tabs([], active_index=0)
        group_zero_pane.navigate_to(QDir.homePath(), push_history=False)
        self.group_tabs.setCurrentIndex(0)

    def can_offer_grouping(self, pane_controller):
        return pane_controller is self.get_group_zero_pane() and not self.visible_group_indices()
