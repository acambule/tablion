from PySide6.QtCore import QDir
from PySide6.QtWidgets import QInputDialog, QSizePolicy, QTabWidget, QWidget

from debug_log import debug_exception, debug_log
from localization import ask_yes_no
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

        self.group_panes_by_page = {}

    def _connect_pane_signals(self, pane_controller):
        pane_controller.currentPathChanged.connect(self.on_pane_path_changed)
        pane_controller.navigationStateChanged.connect(self.on_pane_navigation_changed)
        pane_controller.groupRequested.connect(self.on_pane_group_requested)

    def initialize_existing_groups(self):
        for index in range(self.group_tabs.count()):
            page = self.group_tabs.widget(index)
            pane_controller = GroupWorkspaceWidget(self.model, parent=self.host_ui)
            pane_controller.widget.setParent(None)
            pane_controller.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.group_panes_by_page[page] = pane_controller
            self._connect_pane_signals(pane_controller)

    def create_group(self, title=None, start_path=None):
        debug_log(f"GroupController.create_group(title={title}, start_path={start_path})")
        start_path = QDir.cleanPath(start_path or QDir.homePath())
        page = QWidget(self.group_tabs)

        pane_controller = GroupWorkspaceWidget(self.model, parent=self.host_ui)
        pane_controller.widget.setParent(None)
        pane_controller.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        tab_title = title if title is not None else f"Gruppe {len(self.visible_group_indices()) + 1}"
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
            group_name = self.group_tabs.tabText(index).strip() or f"Gruppe {index}"
            confirmed = ask_yes_no(
                self.host_ui,
                "Gruppe löschen",
                f"Soll die Gruppe '{group_name}' wirklich gelöscht werden?",
                default_no=True,
            )
            if not confirmed:
                return

        page = self.group_tabs.widget(index)
        pane_controller = self.group_panes_by_page.pop(page, None)
        if pane_controller:
            pane_controller.widget.setParent(None)
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
                pane_controller.widget.setParent(None)
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

            current_name = self.group_tabs.tabText(index).strip() or f"Gruppe {index}"
            debug_log(f"GroupController.rename_group opening input dialog for current_name={current_name}")
            clean_name, accepted = QInputDialog.getText(
                self.host_ui,
                "Gruppe umbenennen",
                "Name:",
                text=current_name,
            )
            debug_log(f"GroupController.rename_group input dialog accepted={accepted}")
            if not accepted:
                return

            clean_name = str(clean_name).strip()
            if not clean_name:
                return

            if index <= 0 or index >= self.group_tabs.count():
                debug_log("GroupController.rename_group aborted after dialog due to invalid index")
                return
            self.group_tabs.setTabText(index, clean_name)
            debug_log(f"GroupController.rename_group success index={index}, new_name={clean_name}")
        except RuntimeError:
            debug_log("GroupController.rename_group caught RuntimeError")
            return
        except Exception as error:
            debug_exception("GroupController.rename_group failed", error)
            raise

    def refresh_group_tabs_presentation(self):
        tab_bar = self.group_tabs.tabBar()
        if self.group_tabs.count() > 0:
            self.group_tabs.setTabText(0, "Gruppe 0")
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
                self.group_tabs.setTabText(index, f"Gruppe {group_number}")

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
