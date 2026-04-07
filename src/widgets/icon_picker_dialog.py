from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from localization import app_tr


class IconPickerDialog(QDialog):
    _CUSTOM_ICON_EXTENSIONS = {".png", ".svg", ".xpm", ".jpg", ".jpeg", ".ico"}
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

    def __init__(self, parent=None, icon_value: str = ""):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.setWindowTitle(app_tr("IconPickerDialog", "Icon auswählen"))
        self.setMinimumSize(620, 520)
        self._original_theme_name = QIcon.themeName()
        self._original_theme_search_paths = QIcon.themeSearchPaths()
        self._known_icon_roots = self._known_icon_locations()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        current_row = QHBoxLayout()
        current_label = QLabel(app_tr("IconPickerDialog", "Aktuelles Icon"), self)
        self._icon_line_edit = QLineEdit(self)
        self._icon_line_edit.setText(icon_value)
        self._browse_button = QPushButton(app_tr("IconPickerDialog", "Durchsuchen…"), self)
        current_row.addWidget(current_label)
        current_row.addWidget(self._icon_line_edit, 1)
        current_row.addWidget(self._browse_button)
        layout.addLayout(current_row)

        help_label = QLabel(
            app_tr("IconPickerDialog", "Du kannst einen Theme-Iconnamen wählen oder eine lokale Bilddatei verwenden."),
            self,
        )
        help_label.setWordWrap(True)
        layout.addWidget(help_label)

        search_row = QHBoxLayout()
        search_label = QLabel(app_tr("IconPickerDialog", "Icons suchen"), self)
        self._search_line_edit = QLineEdit(self)
        self._search_line_edit.setPlaceholderText(app_tr("IconPickerDialog", "Theme-Icons filtern..."))
        search_row.addWidget(search_label)
        search_row.addWidget(self._search_line_edit, 1)
        layout.addLayout(search_row)

        theme_selector_row = QHBoxLayout()
        theme_selector_label = QLabel(app_tr("IconPickerDialog", "Theme"), self)
        self._theme_combo_box = QComboBox(self)
        self._all_themes_check_box = QCheckBox(app_tr("IconPickerDialog", "Alle Themes"), self)
        theme_selector_row.addWidget(theme_selector_label)
        theme_selector_row.addWidget(self._theme_combo_box, 1)
        theme_selector_row.addWidget(self._all_themes_check_box)
        layout.addLayout(theme_selector_row)

        size_row = QHBoxLayout()
        size_label = QLabel(app_tr("IconPickerDialog", "Icon-Größe"), self)
        self._icon_size_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._icon_size_slider.setRange(16, 96)
        self._icon_size_slider.setValue(24)
        self._icon_size_value_label = QLabel("24 px", self)
        size_row.addWidget(size_label)
        size_row.addWidget(self._icon_size_slider, 1)
        size_row.addWidget(self._icon_size_value_label)
        layout.addLayout(size_row)

        theme_label = QLabel(app_tr("IconPickerDialog", "Theme-Icons"), self)
        layout.addWidget(theme_label)
        self._theme_icon_list = QListWidget(self)
        self._theme_icon_list.setIconSize(QSize(24, 24))
        layout.addWidget(self._theme_icon_list, 1)

        custom_label = QLabel(app_tr("IconPickerDialog", "Eigene Icons"), self)
        layout.addWidget(custom_label)
        self._custom_icon_list = QListWidget(self)
        self._custom_icon_list.setIconSize(QSize(24, 24))
        layout.addWidget(self._custom_icon_list, 1)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button:
            ok_button.setText(app_tr("IconPickerDialog", "OK"))
        if cancel_button:
            cancel_button.setText(app_tr("IconPickerDialog", "Abbrechen"))
        layout.addWidget(self._button_box)

        self._populate_theme_selector()
        self._populate_theme_icons()
        self._populate_custom_icons()
        self._select_theme_icon_in_list(icon_value)
        self._select_custom_icon_in_list(icon_value)

        self._search_line_edit.textChanged.connect(self._filter_theme_icon_list)
        self._theme_combo_box.currentIndexChanged.connect(self._on_theme_changed)
        self._all_themes_check_box.toggled.connect(self._on_theme_changed)
        self._icon_size_slider.valueChanged.connect(self._on_icon_size_changed)
        self._theme_icon_list.itemClicked.connect(self._on_theme_icon_item_clicked)
        self._theme_icon_list.itemDoubleClicked.connect(self._on_theme_icon_item_double_clicked)
        self._custom_icon_list.itemClicked.connect(self._on_custom_icon_item_clicked)
        self._custom_icon_list.itemDoubleClicked.connect(self._on_custom_icon_item_double_clicked)
        self._browse_button.clicked.connect(self._browse_icon_file)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

    def icon_value(self) -> str:
        return self._icon_line_edit.text().strip()

    def _browse_icon_file(self) -> None:
        current = self.icon_value()
        default_icon_dir = Path.home() / ".local" / "share" / "icons" / "tablion"
        if current and "/" in current:
            start_dir = str(Path(current).expanduser().parent)
        else:
            start_dir = str(default_icon_dir if default_icon_dir.exists() else default_icon_dir.parent)
        selected, _ = QFileDialog.getOpenFileName(
            self,
            app_tr("IconPickerDialog", "Icon auswählen"),
            start_dir,
            app_tr("IconPickerDialog", "Bilder (*.png *.svg *.xpm *.jpg *.jpeg *.ico);;Alle Dateien (*)"),
        )
        if selected:
            self._icon_line_edit.setText(selected)

    def _populate_theme_icons(self) -> None:
        self._theme_icon_list.clear()
        available_icons = (
            self._discover_icons_for_all_themes()
            if self._all_themes_check_box.isChecked()
            else self._discover_icons_for_selected_theme()
        )
        if not available_icons:
            fallback_theme = self._selected_theme_name()
            available_icons = [
                ("", name, self._icon_from_theme(name, fallback_theme))
                for name in self._THEME_ICON_CANDIDATES
            ]

        for theme_name, icon_name, icon in available_icons:
            display_text = icon_name if not theme_name else f"{icon_name}  [{theme_name}]"
            item = QListWidgetItem(icon, display_text)
            item.setData(Qt.ItemDataRole.UserRole, icon_name)
            if theme_name:
                item.setToolTip(f"{theme_name} / {icon_name}")
            self._theme_icon_list.addItem(item)

    def _filter_theme_icon_list(self, text: str) -> None:
        needle = (text or "").strip().lower()
        for row in range(self._theme_icon_list.count()):
            item = self._theme_icon_list.item(row)
            item.setHidden(bool(needle) and needle not in (item.text() or "").lower())
        for row in range(self._custom_icon_list.count()):
            item = self._custom_icon_list.item(row)
            searchable = " ".join(
                [
                    item.text() or "",
                    str(item.data(Qt.ItemDataRole.UserRole) or ""),
                ]
            ).lower()
            item.setHidden(bool(needle) and needle not in searchable)

    def _on_theme_icon_item_clicked(self, item: QListWidgetItem) -> None:
        name = str(item.data(Qt.ItemDataRole.UserRole) or item.text() or "").strip()
        if name:
            self._icon_line_edit.setText(name)

    def _on_custom_icon_item_clicked(self, item: QListWidgetItem) -> None:
        icon_path = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if icon_path:
            self._icon_line_edit.setText(icon_path)

    def _on_theme_icon_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_theme_icon_item_clicked(item)
        self.accept()

    def _on_custom_icon_item_double_clicked(self, item: QListWidgetItem) -> None:
        self._on_custom_icon_item_clicked(item)
        self.accept()

    def _on_theme_changed(self) -> None:
        self._populate_theme_icons()
        self._select_theme_icon_in_list(self.icon_value())
        self._filter_theme_icon_list(self._search_line_edit.text())

    def _on_icon_size_changed(self, value: int) -> None:
        self._theme_icon_list.setIconSize(QSize(value, value))
        self._custom_icon_list.setIconSize(QSize(value, value))
        self._icon_size_value_label.setText(f"{value} px")

    def _select_theme_icon_in_list(self, icon_value: str) -> None:
        value = (icon_value or "").strip().lower()
        if not value or "/" in value:
            return
        for row in range(self._theme_icon_list.count()):
            item = self._theme_icon_list.item(row)
            stored_value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip().lower()
            if stored_value == value:
                self._theme_icon_list.setCurrentItem(item)
                self._theme_icon_list.scrollToItem(item)
                return

    def _select_custom_icon_in_list(self, icon_value: str) -> None:
        if not icon_value or "/" not in icon_value:
            return
        value = str(Path(icon_value).expanduser())
        for row in range(self._custom_icon_list.count()):
            item = self._custom_icon_list.item(row)
            stored_value = str(item.data(Qt.ItemDataRole.UserRole) or "").strip()
            if stored_value == value:
                self._custom_icon_list.setCurrentItem(item)
                self._custom_icon_list.scrollToItem(item)
                return

    def _populate_theme_selector(self) -> None:
        self._theme_combo_box.clear()
        system_theme_label = app_tr("IconPickerDialog", "Aktuelles System-Theme")
        self._theme_combo_box.addItem(system_theme_label, "")
        for theme_name in self._discover_installed_themes():
            self._theme_combo_box.addItem(theme_name, theme_name)
        current_theme = self._original_theme_name
        index = self._theme_combo_box.findData(current_theme)
        if index < 0:
            index = 0
        self._theme_combo_box.setCurrentIndex(index)

    def _discover_installed_themes(self) -> list[str]:
        themes: set[str] = set()
        for root in self._known_icon_roots:
            if not root.exists() or not root.is_dir():
                continue
            for candidate in root.iterdir():
                if candidate.is_dir() and (candidate / "index.theme").is_file():
                    themes.add(candidate.name)
        return sorted(themes, key=str.lower)

    def _discover_icons_for_selected_theme(self) -> list[tuple[str, str, QIcon]]:
        available_icons: list[tuple[str, str, QIcon]] = []
        selected_theme = self._selected_theme_name()
        for name in self._THEME_ICON_CANDIDATES:
            icon = self._icon_from_theme(name, selected_theme)
            if not icon.isNull():
                available_icons.append(("", name, icon))
        return available_icons

    def _discover_icons_for_all_themes(self) -> list[tuple[str, str, QIcon]]:
        available_icons: list[tuple[str, str, QIcon]] = []
        seen: set[tuple[str, str]] = set()
        themes = [self._selected_theme_name(), *self._discover_installed_themes()]
        for theme_name in themes:
            display_theme_name = theme_name or app_tr("IconPickerDialog", "Aktuelles System-Theme")
            for name in self._THEME_ICON_CANDIDATES:
                icon = self._icon_from_theme(name, theme_name)
                if icon.isNull():
                    continue
                pair = (display_theme_name, name)
                if pair in seen:
                    continue
                seen.add(pair)
                available_icons.append((display_theme_name, name, icon))
        return available_icons

    def _populate_custom_icons(self) -> None:
        self._custom_icon_list.clear()
        for path in self._discover_custom_icons():
            relative_name = path.name
            try:
                relative_name = str(path.relative_to(self._default_custom_icon_dir()))
            except ValueError:
                pass
            item = QListWidgetItem(QIcon(str(path)), relative_name)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setToolTip(str(path))
            self._custom_icon_list.addItem(item)

    def _discover_custom_icons(self) -> list[Path]:
        icons: list[Path] = []
        seen: set[str] = set()
        base_dir = self._default_custom_icon_dir()
        root_dir = self._user_icon_root_dir()

        if root_dir.exists() and root_dir.is_dir():
            for path in sorted(root_dir.iterdir()):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self._CUSTOM_ICON_EXTENSIONS:
                    continue
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                icons.append(path)

        if base_dir.exists() and base_dir.is_dir():
            for path in sorted(base_dir.rglob("*")):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self._CUSTOM_ICON_EXTENSIONS:
                    continue
                key = str(path)
                if key in seen:
                    continue
                seen.add(key)
                icons.append(path)
        return icons

    def _known_icon_locations(self) -> list[Path]:
        locations: list[Path] = []
        seen: set[str] = set()
        candidates: list[str] = []
        candidates.extend(QIcon.themeSearchPaths())
        for data_root in QStandardPaths.standardLocations(QStandardPaths.StandardLocation.GenericDataLocation):
            candidates.append(str(Path(data_root) / "icons"))
        candidates.extend(
            [
                str(Path.home() / ".icons"),
                str(Path.home() / ".local" / "share" / "icons"),
                "/usr/share/icons",
                "/usr/local/share/icons",
                "/var/lib/flatpak/exports/share/icons",
                str(Path.home() / ".local" / "share" / "flatpak" / "exports" / "share" / "icons"),
            ]
        )
        for candidate in candidates:
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            locations.append(path)
        return locations

    def _default_custom_icon_dir(self) -> Path:
        return self._user_icon_root_dir() / "tablion"

    def _user_icon_root_dir(self) -> Path:
        return Path.home() / ".local" / "share" / "icons"

    def _selected_theme_name(self) -> str:
        return str(self._theme_combo_box.currentData() or self._original_theme_name or "")

    def _icon_from_theme(self, name: str, theme_name: str) -> QIcon:
        merged_search_paths = list(self._original_theme_search_paths)
        for root in self._known_icon_roots:
            root_str = str(root)
            if root_str not in merged_search_paths:
                merged_search_paths.append(root_str)
        previous_theme = QIcon.themeName()
        previous_search_paths = QIcon.themeSearchPaths()
        try:
            QIcon.setThemeSearchPaths(merged_search_paths)
            QIcon.setThemeName(theme_name or self._original_theme_name)
            return QIcon.fromTheme(name)
        finally:
            QIcon.setThemeSearchPaths(previous_search_paths)
            QIcon.setThemeName(previous_theme)
