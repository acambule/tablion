from __future__ import annotations

import grp
import os
import pwd
import stat
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QMimeDatabase
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from localization import app_tr
from utils.open_with import (
    applications_for_path,
    default_application_for_path,
    primary_mime_type_for_path,
    set_default_application_for_mime,
)


def _format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(max(0, size))
    unit = units[0]
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            break
        value /= 1024.0
    if unit == "B":
        return f"{int(value)} {unit}"
    return f"{value:.1f} {unit}"


def _format_timestamp(timestamp: float | None) -> str:
    if timestamp is None:
        return app_tr("PropertiesDialog", "Nicht verfügbar")
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


class PropertiesDialog(QDialog):
    propertiesChanged = Signal(str)

    def __init__(self, parent, target_path: str | Path):
        super().__init__(parent)
        self._target_path = Path(target_path).expanduser().resolve()
        self._selected_application = default_application_for_path(self._target_path)

        self.setWindowTitle(app_tr("PropertiesDialog", "Eigenschaften"))
        self.setWindowModality(Qt.WindowModality.WindowModal)
        self.resize(680, 520)

        self._name_edit = None
        self._path_label = None
        self._type_label = None
        self._icon_label = None
        self._open_with_icon_label = None
        self._open_with_value = None
        self._size_value = None
        self._created_value = None
        self._modified_value = None
        self._accessed_value = None
        self._owner_user_value = None
        self._owner_group_value = None
        self._owner_access_combo = None
        self._group_access_combo = None
        self._others_access_combo = None
        self._group_value = None
        self._others_value = None
        self._execute_value = None
        self._advanced_value = None
        self._mime_db = QMimeDatabase()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        self._tab_widget = QTabWidget(self)
        self._tab_widget.addTab(self._build_general_tab(), app_tr("PropertiesDialog", "Allgemein"))
        self._tab_widget.addTab(self._build_permissions_tab(), app_tr("PropertiesDialog", "Berechtigungen"))
        root_layout.addWidget(self._tab_widget)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
        apply_button = self._button_box.button(QDialogButtonBox.StandardButton.Apply)
        if ok_button is not None:
            ok_button.setText(app_tr("PropertiesDialog", "OK"))
        if cancel_button is not None:
            cancel_button.setText(app_tr("PropertiesDialog", "Abbrechen"))
        if apply_button is not None:
            apply_button.setText(app_tr("PropertiesDialog", "Anwenden"))
        self._button_box.accepted.connect(self._accept_with_apply)
        self._button_box.rejected.connect(self.reject)
        if apply_button is not None:
            apply_button.clicked.connect(self.apply_changes)
        root_layout.addWidget(self._button_box)

        self._refresh_ui()

    def _build_general_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        header_container = QWidget(tab)
        header_container.setMinimumHeight(128)
        header_container_layout = QVBoxLayout(header_container)
        header_container_layout.setContentsMargins(0, 0, 0, 0)
        header_container_layout.setSpacing(0)
        header_container_layout.addStretch(1)

        header_row = QWidget(header_container)
        header_layout = QHBoxLayout(header_row)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(18)

        icon_panel = QWidget(header_row)
        icon_layout = QVBoxLayout(icon_panel)
        icon_layout.setContentsMargins(0, 0, 0, 0)
        icon_layout.setSpacing(6)
        icon_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignHCenter)

        self._icon_label = QLabel(icon_panel)
        self._icon_label.setFixedSize(72, 72)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_layout.addWidget(self._icon_label, 0, Qt.AlignmentFlag.AlignHCenter)

        self._type_label = QLabel(icon_panel)
        self._type_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self._type_label.setWordWrap(True)
        self._type_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._type_label.setMinimumWidth(120)
        icon_layout.addWidget(self._type_label)

        header_layout.addWidget(icon_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        text_panel = QWidget(header_row)
        text_layout = QVBoxLayout(text_panel)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(6)
        text_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._name_edit = QLineEdit(text_panel)
        text_layout.addWidget(self._name_edit)

        self._path_label = QLabel(text_panel)
        self._path_label.setWordWrap(True)
        self._path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._path_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        text_layout.addWidget(self._path_label)

        header_layout.addWidget(text_panel, 1, Qt.AlignmentFlag.AlignVCenter)
        header_container_layout.addWidget(header_row)
        header_container_layout.addStretch(1)
        layout.addWidget(header_container)

        separator_top = QFrame(tab)
        separator_top.setFrameShape(QFrame.Shape.HLine)
        separator_top.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator_top)

        open_with_row = QHBoxLayout()
        open_with_label = QLabel(f"{app_tr('PropertiesDialog', 'Öffnen mit')}:", tab)
        open_with_label.setMinimumWidth(110)
        self._open_with_icon_label = QLabel(tab)
        self._open_with_icon_label.setFixedSize(20, 20)
        self._open_with_icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._open_with_value = QLabel(tab)
        self._open_with_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._open_with_value.setWordWrap(True)
        change_button = QPushButton(app_tr("PropertiesDialog", "Ändern"), tab)
        change_button.clicked.connect(self._show_open_with_menu)
        open_with_row.addWidget(open_with_label)
        open_with_row.addWidget(self._open_with_icon_label)
        open_with_row.addWidget(self._open_with_value, 1)
        open_with_row.addWidget(change_button)
        layout.addLayout(open_with_row)

        separator_mid = QFrame(tab)
        separator_mid.setFrameShape(QFrame.Shape.HLine)
        separator_mid.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(separator_mid)

        info_form = QFormLayout()
        info_form.setSpacing(8)
        self._size_value = QLabel(tab)
        self._created_value = QLabel(tab)
        self._modified_value = QLabel(tab)
        self._accessed_value = QLabel(tab)
        for widget in (self._size_value, self._created_value, self._modified_value, self._accessed_value):
            widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info_form.addRow(f"{app_tr('PropertiesDialog', 'Größe')}:", self._size_value)
        info_form.addRow(f"{app_tr('PropertiesDialog', 'Erstellt')}:", self._created_value)
        info_form.addRow(f"{app_tr('PropertiesDialog', 'Geändert')}:", self._modified_value)
        info_form.addRow(f"{app_tr('PropertiesDialog', 'Letzter Zugriff')}:", self._accessed_value)
        layout.addLayout(info_form)
        layout.addStretch(1)
        return tab

    def _build_permissions_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        access_group = QGroupBox(app_tr("PropertiesDialog", "Zugriffsberechtigungen"), tab)
        access_form = QFormLayout(access_group)
        access_form.setContentsMargins(12, 12, 12, 12)
        access_form.setSpacing(8)

        self._owner_access_combo = QComboBox(access_group)
        self._group_access_combo = QComboBox(access_group)
        self._others_access_combo = QComboBox(access_group)
        for combo in (self._owner_access_combo, self._group_access_combo, self._others_access_combo):
            for label, bits in self._permission_options():
                combo.addItem(label, bits)
            combo.currentIndexChanged.connect(self._update_permission_preview)

        self._execute_value = QLabel(access_group)
        self._advanced_value = QLabel(access_group)
        self._execute_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._advanced_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        access_form.addRow(f"{app_tr('PropertiesDialog', 'Eigentümer')}:", self._owner_access_combo)
        access_form.addRow(f"{app_tr('PropertiesDialog', 'Gruppe')}:", self._group_access_combo)
        access_form.addRow(f"{app_tr('PropertiesDialog', 'Sonstige')}:", self._others_access_combo)
        access_form.addRow(f"{app_tr('PropertiesDialog', 'Ausführen')}:", self._execute_value)
        access_form.addRow(f"{app_tr('PropertiesDialog', 'Erweiterte Berechtigungen')}:", self._advanced_value)
        layout.addWidget(access_group)

        owner_group = QGroupBox(app_tr("PropertiesDialog", "Besitzer"), tab)
        owner_form = QFormLayout(owner_group)
        owner_form.setContentsMargins(12, 12, 12, 12)
        owner_form.setSpacing(8)

        self._owner_user_value = QLabel(owner_group)
        self._owner_group_value = QLabel(owner_group)
        self._owner_user_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._owner_group_value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        owner_form.addRow(f"{app_tr('PropertiesDialog', 'Benutzer')}:", self._owner_user_value)
        owner_form.addRow(f"{app_tr('PropertiesDialog', 'Gruppe')}:", self._owner_group_value)
        layout.addWidget(owner_group)
        layout.addStretch(1)
        return tab

    def _accept_with_apply(self):
        if self.apply_changes():
            self.accept()

    def apply_changes(self) -> bool:
        target_name = self._name_edit.text().strip() if self._name_edit is not None else self._target_path.name
        if not target_name:
            QMessageBox.warning(
                self,
                app_tr("PropertiesDialog", "Eigenschaften"),
                app_tr("PropertiesDialog", "Der Name darf nicht leer sein."),
            )
            return False
        if "/" in target_name or "\\" in target_name:
            QMessageBox.warning(
                self,
                app_tr("PropertiesDialog", "Eigenschaften"),
                app_tr("PropertiesDialog", "Der Name darf keinen Pfad enthalten."),
            )
            return False

        renamed = False
        permissions_changed = False
        if target_name != self._target_path.name:
            new_path = self._target_path.with_name(target_name)
            if new_path.exists():
                QMessageBox.warning(
                    self,
                    app_tr("PropertiesDialog", "Eigenschaften"),
                    app_tr("PropertiesDialog", "Ziel existiert bereits: {path}").format(path=new_path),
                )
                return False
            try:
                self._target_path.rename(new_path)
            except OSError as error:
                QMessageBox.warning(
                    self,
                    app_tr("PropertiesDialog", "Eigenschaften"),
                    app_tr("PropertiesDialog", "Umbenennen fehlgeschlagen: {error}").format(error=error),
                )
                return False
            self._target_path = new_path
            renamed = True

        try:
            current_mode = stat.S_IMODE(self._target_path.stat().st_mode)
            next_mode = self._mode_from_permission_controls(current_mode)
            if next_mode != current_mode:
                os.chmod(self._target_path, next_mode)
                permissions_changed = True
        except OSError as error:
            QMessageBox.warning(
                self,
                app_tr("PropertiesDialog", "Eigenschaften"),
                app_tr("PropertiesDialog", "Berechtigungen konnten nicht gesetzt werden: {error}").format(error=error),
            )
            return False

        self._refresh_ui()
        if renamed or permissions_changed:
            self.propertiesChanged.emit(str(self._target_path))
        return True

    def _show_open_with_menu(self):
        applications = applications_for_path(self._target_path)
        if not applications:
            QMessageBox.information(
                self,
                app_tr("PropertiesDialog", "Eigenschaften"),
                app_tr("PropertiesDialog", "Keine Anwendungen für diesen Dateityp gefunden."),
            )
            return

        button = self.sender()
        if not isinstance(button, QPushButton):
            return

        from PySide6.QtWidgets import QMenu

        menu = QMenu(button)

        for application in applications:
            action = menu.addAction(application.icon(), application.display_name)
            action.triggered.connect(lambda checked=False, app=application: self._set_default_application(app))

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _set_default_application(self, application) -> None:
        mime_type = primary_mime_type_for_path(self._target_path)
        if set_default_application_for_mime(application.desktop_id, mime_type):
            self._selected_application = application
            self._update_open_with_label()
            return

        QMessageBox.warning(
            self,
            app_tr("PropertiesDialog", "Eigenschaften"),
            app_tr("PropertiesDialog", "Standardanwendung konnte nicht gesetzt werden."),
        )

    def _display_type_text(self) -> str:
        if self._target_path.is_dir():
            return app_tr("PropertiesDialog", "Ordner")
        mime_type = self._mime_db.mimeTypeForFile(str(self._target_path), QMimeDatabase.MatchMode.MatchDefault)
        return mime_type.comment() or mime_type.name() or app_tr("PropertiesDialog", "Datei")

    def _icon_for_target(self) -> QIcon:
        if self._target_path.is_dir():
            return QIcon.fromTheme("folder")
        mime_type = self._mime_db.mimeTypeForFile(str(self._target_path), QMimeDatabase.MatchMode.MatchDefault)
        for icon_name in (mime_type.iconName(), mime_type.genericIconName(), "text-x-generic"):
            if not icon_name:
                continue
            icon = QIcon.fromTheme(icon_name)
            if not icon.isNull():
                return icon
        return QIcon.fromTheme("text-x-generic")

    def _created_timestamp(self, stat_result) -> float | None:
        birth = getattr(stat_result, "st_birthtime", None)
        if birth is not None:
            return float(birth)
        return None

    def _directory_entry_count(self) -> int:
        try:
            return sum(1 for _ in self._target_path.iterdir())
        except OSError:
            return 0

    def _permission_options(self) -> list[tuple[str, int]]:
        return [
            (app_tr("PropertiesDialog", "Kein Zugriff"), 0),
            (app_tr("PropertiesDialog", "Nur ausführen"), 1),
            (app_tr("PropertiesDialog", "Nur schreiben"), 2),
            (app_tr("PropertiesDialog", "Schreiben & ausführen"), 3),
            (app_tr("PropertiesDialog", "Nur lesen"), 4),
            (app_tr("PropertiesDialog", "Lesen & ausführen"), 5),
            (app_tr("PropertiesDialog", "Lesen & schreiben"), 6),
            (app_tr("PropertiesDialog", "Vollzugriff"), 7),
        ]

    def _set_combo_bits(self, combo: QComboBox | None, bits: int):
        if combo is None:
            return
        combo.blockSignals(True)
        index = combo.findData(bits)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _combo_bits(self, combo: QComboBox | None) -> int:
        if combo is None:
            return 0
        value = combo.currentData()
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    def _mode_from_permission_controls(self, current_mode: int) -> int:
        base_mode = current_mode & ~0o777
        owner_bits = self._combo_bits(self._owner_access_combo)
        group_bits = self._combo_bits(self._group_access_combo)
        others_bits = self._combo_bits(self._others_access_combo)
        return base_mode | (owner_bits << 6) | (group_bits << 3) | others_bits

    def _update_permission_preview(self):
        owner_bits = self._combo_bits(self._owner_access_combo)
        group_bits = self._combo_bits(self._group_access_combo)
        others_bits = self._combo_bits(self._others_access_combo)

        execute_roles = []
        if owner_bits & 1:
            execute_roles.append(app_tr("PropertiesDialog", "Eigentümer"))
        if group_bits & 1:
            execute_roles.append(app_tr("PropertiesDialog", "Gruppe"))
        if others_bits & 1:
            execute_roles.append(app_tr("PropertiesDialog", "Sonstige"))

        if self._execute_value is not None:
            self._execute_value.setText(
                ", ".join(execute_roles) if execute_roles else app_tr("PropertiesDialog", "Keine")
            )

        permission_text = "".join(
            (
                "r" if owner_bits & 4 else "-",
                "w" if owner_bits & 2 else "-",
                "x" if owner_bits & 1 else "-",
                "r" if group_bits & 4 else "-",
                "w" if group_bits & 2 else "-",
                "x" if group_bits & 1 else "-",
                "r" if others_bits & 4 else "-",
                "w" if others_bits & 2 else "-",
                "x" if others_bits & 1 else "-",
            )
        )
        if self._advanced_value is not None:
            self._advanced_value.setText(permission_text)

    def _owner_name(self, uid: int) -> str:
        try:
            return pwd.getpwuid(uid).pw_name
        except KeyError:
            return str(uid)

    def _group_name(self, gid: int) -> str:
        try:
            return grp.getgrgid(gid).gr_name
        except KeyError:
            return str(gid)

    def _update_open_with_label(self):
        if self._open_with_value is None:
            return
        self._selected_application = default_application_for_path(self._target_path) or self._selected_application
        if self._selected_application is None:
            if self._open_with_icon_label is not None:
                self._open_with_icon_label.clear()
            self._open_with_value.setText(app_tr("PropertiesDialog", "Nicht festgelegt"))
            return
        if self._open_with_icon_label is not None:
            icon = self._selected_application.icon()
            self._open_with_icon_label.setPixmap(icon.pixmap(16, 16))
        self._open_with_value.setText(self._selected_application.display_name)

    def _refresh_ui(self):
        stat_result = self._target_path.stat()

        if self._icon_label is not None:
            icon = self._icon_for_target()
            pixmap = icon.pixmap(64, 64)
            self._icon_label.setPixmap(pixmap)
        if self._name_edit is not None:
            self._name_edit.setText(self._target_path.name)
        if self._type_label is not None:
            self._type_label.setText(self._display_type_text())
        if self._path_label is not None:
            self._path_label.setText(str(self._target_path))

        self._update_open_with_label()

        if self._size_value is not None:
            if self._target_path.is_dir():
                self._size_value.setText(
                    app_tr("PropertiesDialog", "{count} Einträge").format(count=self._directory_entry_count())
                )
            else:
                self._size_value.setText(_format_bytes(stat_result.st_size))
        if self._created_value is not None:
            self._created_value.setText(_format_timestamp(self._created_timestamp(stat_result)))
        if self._modified_value is not None:
            self._modified_value.setText(_format_timestamp(stat_result.st_mtime))
        if self._accessed_value is not None:
            self._accessed_value.setText(_format_timestamp(stat_result.st_atime))

        mode = stat_result.st_mode
        if self._owner_user_value is not None:
            self._owner_user_value.setText(self._owner_name(stat_result.st_uid))
        if self._owner_group_value is not None:
            self._owner_group_value.setText(self._group_name(stat_result.st_gid))

        permission_mode = stat.S_IMODE(mode)
        self._set_combo_bits(self._owner_access_combo, (permission_mode >> 6) & 0b111)
        self._set_combo_bits(self._group_access_combo, (permission_mode >> 3) & 0b111)
        self._set_combo_bits(self._others_access_combo, permission_mode & 0b111)
        self._update_permission_preview()
