import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QSizePolicy, QSplitter, QVBoxLayout, QWidget

from controllers.pane_controller import PaneController


class GroupWorkspaceWidget(QWidget):
    currentPathChanged = Signal(str)
    navigationStateChanged = Signal(bool, bool)
    groupRequested = Signal()

    def __init__(self, file_system_model, parent=None):
        super().__init__(parent)
        self.widget = self
        self._model = file_system_model
        self._split_mode = "single"
        self._active_slot = "primary"
        self._is_active_group = False
        self._panes = {}

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)

        self._panes["primary"] = self._create_pane(clone_from_primary=False)
        self._panes["primary"].widget.setParent(self)
        self._panes["primary"].widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._layout.addWidget(self._panes["primary"].widget, 1)

        self.tree_view = self._panes["primary"].tree_view

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._render()

    def _create_pane(self, clone_from_primary=True):
        pane = PaneController(self._model, parent=self)
        pane.widget.setParent(None)
        pane.widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        pane.currentPathChanged.connect(lambda path, source=pane: self._on_pane_path_changed(source, path))
        pane.navigationStateChanged.connect(
            lambda can_back, can_up, source=pane: self._on_pane_navigation_changed(source, can_back, can_up)
        )
        pane.filesystemMutationCommitted.connect(lambda source=pane: self._on_pane_filesystem_mutation(source))
        pane.groupRequested.connect(self.groupRequested.emit)

        if clone_from_primary and "primary" in self._panes:
            pane.import_state(self._panes["primary"].export_state())
        return pane

    def _on_pane_path_changed(self, source, path):
        self._update_active_slot_from_focus()
        if source is self._active_pane():
            self.currentPathChanged.emit(path)

    def _on_pane_navigation_changed(self, source, can_back, can_up):
        self._update_active_slot_from_focus()
        if source is self._active_pane():
            self.navigationStateChanged.emit(can_back, can_up)

    def _on_pane_filesystem_mutation(self, source):
        pane_by_slot = self._pane_by_slot()
        if len(pane_by_slot) <= 1:
            return

        for pane in pane_by_slot.values():
            if pane is source:
                continue
            if hasattr(pane, "refresh_current_directory"):
                pane.refresh_current_directory()

    def _is_focus_in_pane(self, pane):
        pane_widget = getattr(pane, "widget", None)
        if pane_widget is None or not shiboken6.isValid(pane_widget):
            return False
        focused_widget = QApplication.focusWidget()
        if focused_widget is None or not shiboken6.isValid(focused_widget):
            return False
        return pane_widget.isAncestorOf(focused_widget)

    def _active_pane(self):
        pane_by_slot = self._pane_by_slot()
        if len(pane_by_slot) <= 1:
            return pane_by_slot.get("primary")

        self._update_active_slot_from_focus(pane_by_slot)
        return pane_by_slot.get(self._active_slot, pane_by_slot.get("primary"))

    def _update_active_slot_from_focus(self, pane_by_slot=None):
        pane_by_slot = pane_by_slot or self._pane_by_slot()
        for slot, pane in pane_by_slot.items():
            if self._is_focus_in_pane(pane):
                self._active_slot = slot
                return
        if self._active_slot not in pane_by_slot:
            self._active_slot = "primary"

    def _pane_by_slot(self):
        panes = {"primary": self._panes.get("primary")}
        if self._split_mode in {"2-split", "4-split"}:
            secondary = self._panes.get("secondary")
            if secondary:
                panes["secondary"] = secondary
        if self._split_mode == "4-split":
            tertiary = self._panes.get("tertiary")
            quaternary = self._panes.get("quaternary")
            if tertiary:
                panes["tertiary"] = tertiary
            if quaternary:
                panes["quaternary"] = quaternary
        return {slot: pane for slot, pane in panes.items() if pane is not None}

    def _set_pane_dimmed(self, pane, is_active):
        pane_widget = getattr(pane, "widget", None)
        if pane_widget is None or not shiboken6.isValid(pane_widget):
            return

        tree_widget = getattr(pane, "tree_view", None)
        if tree_widget is None or not shiboken6.isValid(tree_widget):
            tree_widget = pane_widget
        tree_viewport = tree_widget.viewport() if hasattr(tree_widget, "viewport") else None

        if is_active:
            pane_widget.setGraphicsEffect(None)
            tree_widget.setGraphicsEffect(None)
            if tree_viewport is not None and shiboken6.isValid(tree_viewport):
                tree_viewport.setGraphicsEffect(None)
            return

        pane_effect = pane_widget.graphicsEffect()
        if not isinstance(pane_effect, QGraphicsOpacityEffect):
            pane_effect = QGraphicsOpacityEffect(pane_widget)
            pane_widget.setGraphicsEffect(pane_effect)
        pane_effect.setOpacity(0.9)

        tree_effect = tree_widget.graphicsEffect()
        if not isinstance(tree_effect, QGraphicsOpacityEffect):
            tree_effect = QGraphicsOpacityEffect(tree_widget)
            tree_widget.setGraphicsEffect(tree_effect)
        tree_effect.setOpacity(0.8)

        if tree_viewport is not None and shiboken6.isValid(tree_viewport):
            viewport_effect = tree_viewport.graphicsEffect()
            if not isinstance(viewport_effect, QGraphicsOpacityEffect):
                viewport_effect = QGraphicsOpacityEffect(tree_viewport)
                tree_viewport.setGraphicsEffect(viewport_effect)
            viewport_effect.setOpacity(0.78)

    def _clear_layout(self):
        pane_widgets = []
        for pane in self._panes.values():
            pane_widget = getattr(pane, "widget", None)
            if pane_widget is not None and shiboken6.isValid(pane_widget):
                pane_widgets.append(pane_widget)

        while self._layout.count() > 0:
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue

            if isinstance(widget, QSplitter):
                for pane_widget in pane_widgets:
                    if pane_widget == widget:
                        continue
                    if widget.isAncestorOf(pane_widget):
                        pane_widget.setParent(None)

            if widget in pane_widgets:
                widget.setParent(None)
                widget.setVisible(False)
            else:
                widget.setParent(None)
                widget.deleteLater()

    def _render(self):
        self._clear_layout()

        primary = self._panes.get("primary")
        if not primary:
            return

        pane_by_slot = self._pane_by_slot()
        for pane in pane_by_slot.values():
            pane.widget.setVisible(False)

        if self._split_mode == "2-split" and "secondary" in pane_by_slot:
            split_host = QSplitter(Qt.Orientation.Horizontal, self)
            split_host.setChildrenCollapsible(False)

            pane_by_slot["primary"].widget.setParent(split_host)
            pane_by_slot["secondary"].widget.setParent(split_host)
            self._layout.addWidget(split_host, 1)

            pane_by_slot["primary"].widget.setVisible(True)
            pane_by_slot["secondary"].widget.setVisible(True)
            split_host.setSizes([1, 1])

            pane_by_slot["primary"].optimize_columns()
            pane_by_slot["secondary"].optimize_columns()
            self.refresh_active_highlight()
            return

        if self._split_mode == "4-split" and {"secondary", "tertiary", "quaternary"}.issubset(pane_by_slot):
            root_splitter = QSplitter(Qt.Orientation.Vertical, self)
            root_splitter.setChildrenCollapsible(False)
            top_splitter = QSplitter(Qt.Orientation.Horizontal, root_splitter)
            bottom_splitter = QSplitter(Qt.Orientation.Horizontal, root_splitter)
            top_splitter.setChildrenCollapsible(False)
            bottom_splitter.setChildrenCollapsible(False)

            pane_by_slot["primary"].widget.setParent(top_splitter)
            pane_by_slot["secondary"].widget.setParent(top_splitter)
            pane_by_slot["tertiary"].widget.setParent(bottom_splitter)
            pane_by_slot["quaternary"].widget.setParent(bottom_splitter)

            self._layout.addWidget(root_splitter, 1)
            for pane in pane_by_slot.values():
                pane.widget.setVisible(True)

            root_splitter.setSizes([1, 1])
            top_splitter.setSizes([1, 1])
            bottom_splitter.setSizes([1, 1])

            for pane in pane_by_slot.values():
                pane.optimize_columns()
            self.refresh_active_highlight()
            return

        pane_by_slot["primary"].widget.setParent(self)
        self._layout.addWidget(pane_by_slot["primary"].widget, 1)
        pane_by_slot["primary"].widget.setVisible(True)
        pane_by_slot["primary"].optimize_columns()
        self.refresh_active_highlight()

    def _ensure_split_pane(self, slot):
        if slot in self._panes:
            return self._panes[slot]
        pane = self._create_pane(clone_from_primary=True)
        self._panes[slot] = pane
        return pane

    def set_group_active(self, is_active):
        self._is_active_group = bool(is_active)
        self.refresh_active_highlight()

    def set_split_mode(self, mode):
        if mode not in {"single", "2-split", "4-split"}:
            return

        if mode in {"2-split", "4-split"}:
            self._ensure_split_pane("secondary")
        if mode == "4-split":
            self._ensure_split_pane("tertiary")
            self._ensure_split_pane("quaternary")

        self._split_mode = mode
        self._active_slot = "primary"
        self._render()
        self._emit_active_state()

    def export_split_state(self):
        payload = {"split_mode": self._split_mode}
        if self._split_mode in {"2-split", "4-split"} and "secondary" in self._panes:
            payload["secondary_pane"] = self._panes["secondary"].export_state()
        if self._split_mode == "4-split":
            if "tertiary" in self._panes:
                payload["tertiary_pane"] = self._panes["tertiary"].export_state()
            if "quaternary" in self._panes:
                payload["quaternary_pane"] = self._panes["quaternary"].export_state()
        return payload

    def restore_split_state(self, split_mode, secondary_state=None, tertiary_state=None, quaternary_state=None):
        mode = "single"
        if split_mode == "2-split":
            mode = "2-split"
        elif split_mode == "4-split":
            mode = "4-split"

        if mode in {"2-split", "4-split"}:
            secondary = self._ensure_split_pane("secondary")
            if isinstance(secondary_state, dict):
                secondary.import_state(secondary_state)
        if mode == "4-split":
            tertiary = self._ensure_split_pane("tertiary")
            quaternary = self._ensure_split_pane("quaternary")
            if isinstance(tertiary_state, dict):
                tertiary.import_state(tertiary_state)
            if isinstance(quaternary_state, dict):
                quaternary.import_state(quaternary_state)

        self._split_mode = mode
        self._active_slot = "primary"
        self._render()
        self._emit_active_state()

    def refresh_active_highlight(self):
        pane_by_slot = self._pane_by_slot()
        if not pane_by_slot:
            return

        if not self._is_active_group:
            for pane in pane_by_slot.values():
                self._set_pane_dimmed(pane, False)
            return

        if self._split_mode == "single" or len(pane_by_slot) <= 1:
            self._set_pane_dimmed(pane_by_slot["primary"], True)
            return

        self._update_active_slot_from_focus(pane_by_slot)
        for slot, pane in pane_by_slot.items():
            self._set_pane_dimmed(pane, slot == self._active_slot)

    def _emit_active_state(self):
        pane = self._active_pane()
        if pane is None:
            return
        self.currentPathChanged.emit(pane.current_path())
        self.navigationStateChanged.emit(pane.can_go_back(), pane.can_go_up())

    def optimize_columns(self):
        for pane in self._pane_by_slot().values():
            pane.optimize_columns()

    def current_path(self):
        pane = self._active_pane()
        return pane.current_path() if pane else ""

    def can_go_back(self):
        pane = self._active_pane()
        return bool(pane and pane.can_go_back())

    def can_go_up(self):
        pane = self._active_pane()
        return bool(pane and pane.can_go_up())

    def navigate_back(self):
        pane = self._active_pane()
        if pane:
            pane.navigate_back()

    def navigate_up(self):
        pane = self._active_pane()
        if pane:
            pane.navigate_up()

    def navigate_to(self, path, push_history=True):
        pane = self._active_pane()
        if pane:
            pane.navigate_to(path, push_history=push_history)

    def refresh_current_directory(self):
        pane = self._active_pane()
        if pane is None:
            return
        if pane and hasattr(pane, "refresh_current_directory"):
            pane.refresh_current_directory()

    def export_state(self):
        return self._panes["primary"].export_state()

    def import_state(self, state_data):
        self._panes["primary"].import_state(state_data)
        self._emit_active_state()

    def replace_tabs(self, states, active_index=0):
        self._panes["primary"].replace_tabs(states, active_index=active_index)
        self._emit_active_state()

    def move_tabs_out_and_reset(self, default_path):
        result = self._panes["primary"].move_tabs_out_and_reset(default_path)
        self._emit_active_state()
        return result
