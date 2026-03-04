from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from localization import app_tr


class ManageTabGroupsDialog(QDialog):
    _THEME_ICON_CANDIDATES = [
        "folder", "folder-open", "folder-documents", "folder-download", "folder-pictures", "folder-music",
        "folder-videos", "folder-publicshare", "folder-remote", "folder-sync", "folder-favorites",
        "document-open", "document-save", "document-edit", "document-new", "text-x-generic", "text-x-script",
        "application-x-executable", "application-x-desktop", "applications-system", "applications-development",
        "preferences-system", "preferences-desktop", "preferences-other", "preferences-desktop-theme",
        "utilities-terminal", "system-run", "system-file-manager", "view-list-icons", "view-list-details",
        "go-home", "user-home", "computer", "drive-harddisk", "drive-removable-media", "network-workgroup",
        "cloud", "folder-cloud", "emblem-favorite", "starred", "tag", "bookmark-new", "edit-rename",
    ]

    def __init__(self, parent: QWidget | None, group_name: str, icon_value: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        loader = QUiLoader()
        ui_path = Path(__file__).resolve().parent.parent / "ui" / "manageTabGoups.ui"
        self.ui = loader.load(str(ui_path), self)
        if self.ui is None:
            raise RuntimeError(f"Konnte UI nicht laden: {ui_path}")

        self.setWindowTitle(self.ui.windowTitle())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self.ui)

        self._name_line_edit = self.ui.findChild(QLineEdit, "groupNameLineEdit")
        self._icon_line_edit = self.ui.findChild(QLineEdit, "groupIconLineEdit")
        self._theme_icon_search_line_edit = self.ui.findChild(QLineEdit, "themeIconSearchLineEdit")
        self._theme_icon_list = self.ui.findChild(QListWidget, "themeIconListWidget")
        self._browse_button = self.ui.findChild(QPushButton, "browseIconButton")
        self._button_box = self.ui.findChild(QDialogButtonBox, "buttonBox")

        if self._name_line_edit:
            self._name_line_edit.setText(group_name)
            self._name_line_edit.selectAll()
            self._name_line_edit.setFocus()

        if self._icon_line_edit and icon_value:
            self._icon_line_edit.setText(icon_value)

        self._populate_theme_icons()
        self._select_theme_icon_in_list(self.icon_value())

        if self._theme_icon_search_line_edit:
            self._theme_icon_search_line_edit.textChanged.connect(self._filter_theme_icon_list)
        if self._theme_icon_list:
            self._theme_icon_list.itemClicked.connect(self._on_theme_icon_item_clicked)

        if self._browse_button:
            self._browse_button.setText(app_tr("ManageTabGroupsDialog", "Durchsuchen…"))
            self._browse_button.clicked.connect(self._browse_icon_file)

        if self._button_box:
            ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
            cancel_button = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
            if ok_button:
                ok_button.setText(app_tr("ManageTabGroupsDialog", "OK"))
                ok_button.clicked.connect(lambda: self.done(QDialog.DialogCode.Accepted))
            if cancel_button:
                cancel_button.setText(app_tr("ManageTabGroupsDialog", "Abbrechen"))
                cancel_button.clicked.connect(lambda: self.done(QDialog.DialogCode.Rejected))

    def group_name(self) -> str:
        if not self._name_line_edit:
            return ""
        return self._name_line_edit.text().strip()

    def icon_value(self) -> str:
        if not self._icon_line_edit:
            return ""
        return self._icon_line_edit.text().strip()

    def _browse_icon_file(self) -> None:
        current = self.icon_value()
        start_dir = str(Path(current).expanduser().parent) if current else ""
        selected, _ = QFileDialog.getOpenFileName(
            self,
            app_tr("ManageTabGroupsDialog", "Icon auswählen"),
            start_dir,
            app_tr("ManageTabGroupsDialog", "Bilder (*.png *.svg *.xpm *.jpg *.jpeg *.ico);;Alle Dateien (*)"),
        )
        if not selected or not self._icon_line_edit:
            return
        self._icon_line_edit.setText(selected)

    def _populate_theme_icons(self) -> None:
        if not self._theme_icon_list:
            return
        self._theme_icon_list.clear()
        available_names = []
        for name in self._THEME_ICON_CANDIDATES:
            if QIcon.hasThemeIcon(name):
                available_names.append(name)
        if not available_names:
            available_names = list(self._THEME_ICON_CANDIDATES)

        for name in available_names:
            icon = QIcon.fromTheme(name)
            item = QListWidgetItem(icon, name)
            item.setData(Qt.ItemDataRole.UserRole, name)
            self._theme_icon_list.addItem(item)

    def _filter_theme_icon_list(self, text: str) -> None:
        if not self._theme_icon_list:
            return
        needle = (text or "").strip().lower()
        for row in range(self._theme_icon_list.count()):
            item = self._theme_icon_list.item(row)
            item_text = (item.text() or "").lower()
            item.setHidden(bool(needle) and needle not in item_text)

    def _on_theme_icon_item_clicked(self, item: QListWidgetItem) -> None:
        if not self._icon_line_edit:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
        if name:
            self._icon_line_edit.setText(name)

    def _select_theme_icon_in_list(self, icon_value: str) -> None:
        if not self._theme_icon_list or not icon_value:
            return
        value = icon_value.strip().lower()
        if not value or "/" in value:
            return
        for row in range(self._theme_icon_list.count()):
            item = self._theme_icon_list.item(row)
            if item.text().strip().lower() == value:
                self._theme_icon_list.setCurrentItem(item)
                self._theme_icon_list.scrollToItem(item)
                return
