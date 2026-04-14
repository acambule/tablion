from __future__ import annotations

import base64
import json
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QSize, Signal
from PySide6.QtGui import QIcon
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from localization import app_tr
from models.editor_settings import EditorSettings
from models.remote_connection_settings import RemoteConnectionDefinition, RemoteConnectionSettings
from models.remote_mount_settings import RemoteMountDefinition, RemoteMountSettings
from remotes.providers.onedrive_auth import OneDriveAuthError, OneDriveAuthService
from remotes.providers.onedrive_client import OneDriveClient
from widgets.icon_picker_dialog import IconPickerDialog


class SettingsDialog(QDialog):
    settingsChanged = Signal()
    languagePreferenceChanged = Signal(str)
    sessionExportRequested = Signal()
    sessionImportRequested = Signal()
    factoryResetRequested = Signal()

    def __init__(
        self,
        parent: QWidget | None,
        editor_settings: EditorSettings,
        remote_connection_settings: RemoteConnectionSettings | None = None,
        remote_mount_settings: RemoteMountSettings | None = None,
    ):
        super().__init__(parent)
        self._editor_settings = editor_settings
        self._remote_connection_settings = remote_connection_settings
        self._remote_mount_settings = remote_mount_settings
        self._one_drive_auth_service = OneDriveAuthService()
        self._one_drive_client = OneDriveClient()
        self._connection_rows: list[dict] = []
        self._mount_rows: list[dict] = []
        self._remote_open_rule_rows: list[dict] = []
        self._team_options_by_connection: dict[str, list[dict]] = {}
        self._connection_form_sync_guard = False
        self._mount_form_sync_guard = False
        self._remote_open_rule_form_sync_guard = False

        loader = QUiLoader()
        ui_path = Path(__file__).resolve().parent.parent / "ui" / "settings.ui"
        self.ui = loader.load(str(ui_path), self)
        if self.ui is None:
            raise RuntimeError(f"Konnte UI nicht laden: {ui_path}")

        self.setWindowTitle(self.ui.windowTitle())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(0)
        layout.addWidget(self.ui)
        min_size = self.ui.minimumSize()
        if min_size.width() > 0 and min_size.height() > 0:
            self.setMinimumSize(min_size)
        elif self.ui.size().width() > 0 and self.ui.size().height() > 0:
            self.setMinimumSize(QSize(self.ui.size().width(), self.ui.size().height()))
        self.resize(
            max(self.minimumWidth(), int(getattr(self._editor_settings, "settings_dialog_width", 920))),
            max(self.minimumHeight(), int(getattr(self._editor_settings, "settings_dialog_height", 620))),
        )

        self._default_editor_line_edit = self.ui.findChild(QLineEdit, "defaultEditorLineEdit")
        self._language_preference_combo = self.ui.findChild(QComboBox, "languagePreferenceCombo")
        self._group_creation_behavior_combo = self.ui.findChild(QComboBox, "groupCreationBehaviorCombo")
        self._middle_click_tab_behavior_combo = self.ui.findChild(QComboBox, "middleClickTabBehaviorCombo")
        self._app_double_click_behavior_combo = self.ui.findChild(QComboBox, "appDoubleClickBehaviorCombo")
        self._show_group_tab_close_icons_checkbox = self.ui.findChild(QCheckBox, "showGroupTabCloseIconsCheckBox")
        self._show_file_tab_close_icons_checkbox = self.ui.findChild(QCheckBox, "showFileTabCloseIconsCheckBox")
        self._button_box = self.ui.findChild(QDialogButtonBox, "buttonBox")
        self._categories_list = self.ui.findChild(QListWidget, "categoriesList")
        self._category_stack = self.ui.findChild(QStackedWidget, "categoryStack")
        self._splitter = self.ui.findChild(QSplitter, "splitter")
        self._export_session_button = self.ui.findChild(QPushButton, "exportSessionButton")
        self._import_session_button = self.ui.findChild(QPushButton, "importSessionButton")
        self._reset_workspace_button = self.ui.findChild(QPushButton, "resetWorkspaceButton")

        self._connection_provider_combo = None
        self._connection_display_name_line_edit = None
        self._connection_tenant_line_edit = None
        self._connection_client_id_line_edit = None
        self._connection_status_label = None
        self._connection_table = None

        self._mount_connection_combo = None
        self._mount_display_name_line_edit = None
        self._mount_scope_combo = None
        self._mount_root_path_line_edit = None
        self._mount_icon_name_line_edit = None
        self._mount_icon_browse_button = None
        self._mount_team_combo = None
        self._mount_team_load_button = None
        self._mount_table = None
        self._mount_status_label = None
        self._remote_clouds_page = None
        self._remote_clouds_tabs = None
        self._remote_open_extensions_line_edit = None
        self._remote_open_command_line_edit = None
        self._remote_open_arguments_line_edit = None
        self._remote_open_rules_table = None
        self._local_office_web_enabled_checkbox = None
        self._local_office_web_connection_combo = None
        self._local_office_web_temp_folder_line_edit = None
        self._remote_dot_hidden_checkbox = None

        if self._categories_list and self._category_stack:
            self._categories_list.currentRowChanged.connect(self._category_stack.setCurrentIndex)

        self._setup_remote_clouds_page()
        self._load_connection_rows()
        self._load_mount_rows()
        self._load_remote_open_rule_rows()
        self._rebuild_connection_table()
        self._rebuild_mount_table()
        self._rebuild_mount_connection_combo()
        self._rebuild_remote_open_rules_table()
        self._rebuild_local_office_web_connection_combo()
        self._configure_splitter()

        if self._categories_list and self._category_stack:
            self._categories_list.setCurrentRow(0)

        if self._default_editor_line_edit:
            stored = self._editor_settings.tablion_editor
            if stored:
                self._default_editor_line_edit.setText(stored)

        if self._app_double_click_behavior_combo:
            self._app_double_click_behavior_combo.setCurrentIndex(1 if self._editor_settings.application_double_click_behavior == "edit" else 0)

        if self._language_preference_combo:
            language_map = {"system": 0, "de": 1, "en": 2}
            self._language_preference_combo.setCurrentIndex(language_map.get(self._editor_settings.language_preference, 0))

        if self._group_creation_behavior_combo:
            behavior_map = {"default_tab": 0, "copy_tabs": 1}
            self._group_creation_behavior_combo.setCurrentIndex(behavior_map.get(self._editor_settings.group_creation_behavior, 0))

        if self._middle_click_tab_behavior_combo:
            behavior_map = {"background": 0, "foreground": 1}
            self._middle_click_tab_behavior_combo.setCurrentIndex(
                behavior_map.get(self._editor_settings.middle_click_new_tab_behavior, 0)
            )

        if self._show_group_tab_close_icons_checkbox:
            self._show_group_tab_close_icons_checkbox.setChecked(self._editor_settings.show_group_tab_close_icons)

        if self._show_file_tab_close_icons_checkbox:
            self._show_file_tab_close_icons_checkbox.setChecked(self._editor_settings.show_file_tab_close_icons)
        if self._local_office_web_enabled_checkbox is not None:
            self._local_office_web_enabled_checkbox.setChecked(
                self._editor_settings.local_office_web_editing_enabled
            )
        if self._local_office_web_temp_folder_line_edit is not None:
            self._local_office_web_temp_folder_line_edit.setText(
                self._editor_settings.local_office_web_temp_folder
            )
        if self._local_office_web_connection_combo is not None:
            connection_index = self._local_office_web_connection_combo.findData(
                self._editor_settings.local_office_web_connection_id
            )
            if connection_index >= 0:
                self._local_office_web_connection_combo.setCurrentIndex(connection_index)
        if self._remote_dot_hidden_checkbox is not None:
            self._remote_dot_hidden_checkbox.setChecked(
                bool(getattr(self._editor_settings, "treat_dot_entries_as_hidden_remote", False))
            )

        if self._button_box:
            apply_button = self._button_box.button(QDialogButtonBox.StandardButton.Apply)
            ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
            cancel_button = self._button_box.button(QDialogButtonBox.StandardButton.Cancel)
            if cancel_button:
                cancel_button.setText(app_tr("SettingsDialog", "Abbrechen"))
            if apply_button:
                apply_button.setText(app_tr("SettingsDialog", "Anwenden"))
                apply_button.clicked.connect(self._on_apply)
            if ok_button:
                ok_button.setText(app_tr("SettingsDialog", "OK"))
            self._button_box.accepted.connect(self._on_accepted)
            self._button_box.rejected.connect(self.reject)

        if self._export_session_button:
            self._export_session_button.clicked.connect(self.sessionExportRequested.emit)
        if self._import_session_button:
            self._import_session_button.clicked.connect(self.sessionImportRequested.emit)
        if self._reset_workspace_button:
            self._reset_workspace_button.clicked.connect(self.factoryResetRequested.emit)

    def _configure_splitter(self) -> None:
        if self._splitter is None:
            return
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setHandleWidth(max(8, self._splitter.handleWidth()))

        navigation_panel = self.ui.findChild(QWidget, "navigationPanel")
        content_panel = self.ui.findChild(QWidget, "contentPanel")
        if navigation_panel is not None:
            navigation_panel.setMinimumWidth(220)
        if content_panel is not None:
            content_panel.setMinimumWidth(420)

        total_width = max(self.width(), self.minimumWidth(), 920)
        left_width = max(220, min(280, total_width // 4))
        right_width = max(420, total_width - left_width)
        self._splitter.setSizes([left_width, right_width])

    def _setup_remote_clouds_page(self) -> None:
        if self._categories_list is None or self._category_stack is None:
            return

        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        tabs = QTabWidget(page)
        self._remote_clouds_page = page
        self._remote_clouds_tabs = tabs
        tabs.addTab(self._build_connections_tab(), app_tr("SettingsDialog", "Verbindungen"))
        tabs.addTab(self._build_mounts_tab(), app_tr("SettingsDialog", "Einträge"))
        tabs.addTab(self._build_remote_open_tab(), app_tr("SettingsDialog", "Dateizuordnungen"))
        tabs.addTab(self._build_local_office_web_tab(), app_tr("SettingsDialog", "Optionen"))
        layout.addWidget(tabs)

        self._category_stack.addWidget(page)
        remote_item = QListWidgetItem(app_tr("SettingsDialog", "Remote-Clouds"))
        remote_item.setIcon(QIcon.fromTheme("folder-cloud"))
        self._categories_list.addItem(remote_item)

    def _build_connections_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        form_widget = QWidget(page)
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self._connection_provider_combo = QComboBox(form_widget)
        self._connection_provider_combo.addItems(["OneDrive", "Dropbox", "Google Drive"])
        form_layout.addRow(app_tr("SettingsDialog", "Anbieter"), self._connection_provider_combo)

        self._connection_display_name_line_edit = QLineEdit(form_widget)
        form_layout.addRow(app_tr("SettingsDialog", "Name"), self._connection_display_name_line_edit)

        self._connection_tenant_line_edit = QLineEdit(form_widget)
        self._connection_tenant_line_edit.setText("common")
        form_layout.addRow(app_tr("SettingsDialog", "Tenant-ID"), self._connection_tenant_line_edit)

        self._connection_client_id_line_edit = QLineEdit(form_widget)
        form_layout.addRow(app_tr("SettingsDialog", "Client-ID"), self._connection_client_id_line_edit)
        layout.addWidget(form_widget)

        button_row = QHBoxLayout()
        connect_button = QPushButton(app_tr("SettingsDialog", "Mit OneDrive verbinden"), page)
        reconnect_button = QPushButton(app_tr("SettingsDialog", "Verbindung erneuern"), page)
        remove_button = QPushButton(app_tr("SettingsDialog", "Verbindung entfernen"), page)
        button_row.addWidget(connect_button)
        button_row.addWidget(reconnect_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._connection_status_label = QLabel(page)
        self._connection_status_label.setWordWrap(True)
        self._connection_status_label.setContentsMargins(10, 8, 10, 8)
        self._connection_status_label.setStyleSheet(
            "QLabel {"
            " background-color: rgba(120, 120, 120, 0.10);"
            " border: 1px solid rgba(160, 160, 160, 0.28);"
            " border-radius: 6px;"
            " padding: 8px;"
            "}"
        )
        self._connection_status_label.setText(
            app_tr(
                "SettingsDialog",
                "Verbindungen enthalten Authentifizierung und Kontodaten. Einträge im Navigator werden erst aus Einträgen erzeugt.",
            )
        )

        self._connection_table = QTableWidget(page)
        self._connection_table.setColumnCount(5)
        self._connection_table.setHorizontalHeaderLabels(
            [
                app_tr("SettingsDialog", "Anbieter"),
                app_tr("SettingsDialog", "Name"),
                app_tr("SettingsDialog", "Konto"),
                app_tr("SettingsDialog", "Tenant"),
                app_tr("SettingsDialog", "Status"),
            ]
        )
        self._connection_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._connection_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._connection_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._connection_table.verticalHeader().setVisible(False)
        layout.addWidget(self._connection_table, 1)
        self._connection_table.itemSelectionChanged.connect(self._load_selected_connection_into_form)
        layout.addWidget(self._connection_status_label)

        connect_button.clicked.connect(self._connect_new_account)
        reconnect_button.clicked.connect(self._reconnect_selected_connection)
        remove_button.clicked.connect(self._remove_selected_connection)
        return page

    def _build_mounts_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        form_widget = QWidget(page)
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self._mount_connection_combo = QComboBox(form_widget)
        form_layout.addRow(app_tr("SettingsDialog", "Verbindung"), self._mount_connection_combo)

        self._mount_display_name_line_edit = QLineEdit(form_widget)
        form_layout.addRow(app_tr("SettingsDialog", "Name"), self._mount_display_name_line_edit)

        self._mount_scope_combo = QComboBox(form_widget)
        self._mount_scope_combo.addItems(
            [
                app_tr("SettingsDialog", "Persönlich"),
                app_tr("SettingsDialog", "SharePoint"),
                app_tr("SettingsDialog", "Team"),
            ]
        )
        form_layout.addRow(app_tr("SettingsDialog", "Bereich"), self._mount_scope_combo)

        self._mount_root_path_line_edit = QLineEdit(form_widget)
        self._mount_root_path_line_edit.setPlaceholderText("/")
        form_layout.addRow(app_tr("SettingsDialog", "Root-Pfad"), self._mount_root_path_line_edit)

        team_row = QWidget(form_widget)
        team_row_layout = QHBoxLayout(team_row)
        team_row_layout.setContentsMargins(0, 0, 0, 0)
        team_row_layout.setSpacing(6)
        self._mount_team_combo = QComboBox(team_row)
        self._mount_team_combo.setEnabled(False)
        self._mount_team_load_button = QPushButton(app_tr("SettingsDialog", "Teams laden"), team_row)
        team_row_layout.addWidget(self._mount_team_combo, 1)
        team_row_layout.addWidget(self._mount_team_load_button)
        form_layout.addRow(app_tr("SettingsDialog", "Team"), team_row)

        icon_row = QWidget(form_widget)
        icon_row_layout = QHBoxLayout(icon_row)
        icon_row_layout.setContentsMargins(0, 0, 0, 0)
        icon_row_layout.setSpacing(6)
        self._mount_icon_name_line_edit = QLineEdit(icon_row)
        self._mount_icon_name_line_edit.setPlaceholderText("folder-cloud")
        self._mount_icon_browse_button = QPushButton(app_tr("SettingsDialog", "Auswählen…"), icon_row)
        icon_row_layout.addWidget(self._mount_icon_name_line_edit, 1)
        icon_row_layout.addWidget(self._mount_icon_browse_button)
        form_layout.addRow(app_tr("SettingsDialog", "Icon"), icon_row)
        layout.addWidget(form_widget)

        button_row = QHBoxLayout()
        add_button = QPushButton(app_tr("SettingsDialog", "Eintrag hinzufügen"), page)
        remove_button = QPushButton(app_tr("SettingsDialog", "Eintrag entfernen"), page)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self._mount_status_label = QLabel(page)
        self._mount_status_label.setWordWrap(True)
        self._mount_status_label.setText(
            app_tr(
                "SettingsDialog",
                "Einträge bestimmen, was unter Cloud in Tablion sichtbar wird. Mehrere Einträge können dieselbe Verbindung verwenden.",
            )
        )
        layout.addWidget(self._mount_status_label)

        self._mount_table = QTableWidget(page)
        self._mount_table.setColumnCount(5)
        self._mount_table.setHorizontalHeaderLabels(
            [
                app_tr("SettingsDialog", "Verbindung"),
                app_tr("SettingsDialog", "Name"),
                app_tr("SettingsDialog", "Bereich"),
                app_tr("SettingsDialog", "Root"),
                app_tr("SettingsDialog", "Status"),
            ]
        )
        self._mount_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._mount_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._mount_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._mount_table.verticalHeader().setVisible(False)
        layout.addWidget(self._mount_table, 1)

        add_button.clicked.connect(self._add_mount)
        remove_button.clicked.connect(self._remove_selected_mount)
        self._mount_connection_combo.currentIndexChanged.connect(lambda _=0: self._apply_mount_icon_suggestion())
        self._mount_scope_combo.currentIndexChanged.connect(lambda _=0: self._apply_mount_icon_suggestion())
        self._mount_scope_combo.currentIndexChanged.connect(lambda _=0: self._update_mount_scope_dependent_fields())
        self._mount_connection_combo.currentIndexChanged.connect(lambda _=0: self._sync_selected_mount_from_form())
        self._mount_connection_combo.currentIndexChanged.connect(lambda _=0: self._populate_team_combo())
        self._mount_display_name_line_edit.textChanged.connect(lambda _="": self._sync_selected_mount_from_form())
        self._mount_scope_combo.currentIndexChanged.connect(lambda _=0: self._sync_selected_mount_from_form())
        self._mount_root_path_line_edit.textChanged.connect(lambda _="": self._sync_selected_mount_from_form())
        self._mount_icon_name_line_edit.textChanged.connect(lambda _="": self._sync_selected_mount_from_form())
        self._mount_team_combo.currentIndexChanged.connect(lambda _=0: self._sync_selected_mount_from_form())
        self._mount_team_load_button.clicked.connect(self._load_team_options_for_current_connection)
        self._mount_table.itemSelectionChanged.connect(self._load_selected_mount_into_form)
        self._mount_icon_browse_button.clicked.connect(self._pick_mount_icon)
        self._update_mount_scope_dependent_fields()
        return page

    def _build_remote_open_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        form_widget = QWidget(page)
        form_layout = QFormLayout(form_widget)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)

        self._remote_open_extensions_line_edit = QLineEdit(form_widget)
        self._remote_open_extensions_line_edit.setPlaceholderText("docx,xlsx,pptx")
        form_layout.addRow(app_tr("SettingsDialog", "Dateiendungen"), self._remote_open_extensions_line_edit)

        self._remote_open_command_line_edit = QLineEdit(form_widget)
        self._remote_open_command_line_edit.setPlaceholderText("/opt/google/chrome/google-chrome")
        form_layout.addRow(app_tr("SettingsDialog", "Anwendung"), self._remote_open_command_line_edit)

        self._remote_open_arguments_line_edit = QLineEdit(form_widget)
        self._remote_open_arguments_line_edit.setPlaceholderText("--profile-directory=Profile 3 --app-id=... {url}")
        form_layout.addRow(app_tr("SettingsDialog", "Argumente"), self._remote_open_arguments_line_edit)
        layout.addWidget(form_widget)

        button_row = QHBoxLayout()
        add_button = QPushButton(app_tr("SettingsDialog", "Regel hinzufügen"), page)
        remove_button = QPushButton(app_tr("SettingsDialog", "Regel entfernen"), page)
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        info_label = QLabel(
            app_tr(
                "SettingsDialog",
                "Remote-Dateien koennen anhand ihrer Endung einer Anwendung zugeordnet werden. In den Argumenten wird {url} durch die Remote-URL ersetzt.",
            ),
            page,
        )
        info_label.setWordWrap(True)
        info_label.setContentsMargins(10, 8, 10, 8)
        info_label.setStyleSheet(
            "QLabel {"
            " background-color: rgba(120, 120, 120, 0.10);"
            " border: 1px solid rgba(160, 160, 160, 0.28);"
            " border-radius: 6px;"
            " padding: 8px;"
            "}"
        )
        layout.addWidget(info_label)

        self._remote_open_rules_table = QTableWidget(page)
        self._remote_open_rules_table.setColumnCount(3)
        self._remote_open_rules_table.setHorizontalHeaderLabels(
            [
                app_tr("SettingsDialog", "Dateiendungen"),
                app_tr("SettingsDialog", "Anwendung"),
                app_tr("SettingsDialog", "Argumente"),
            ]
        )
        self._remote_open_rules_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._remote_open_rules_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._remote_open_rules_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._remote_open_rules_table.verticalHeader().setVisible(False)
        self._remote_open_rules_table.itemSelectionChanged.connect(self._load_selected_remote_open_rule_into_form)
        layout.addWidget(self._remote_open_rules_table, 1)

        add_button.clicked.connect(self._add_remote_open_rule)
        remove_button.clicked.connect(self._remove_selected_remote_open_rule)
        self._remote_open_extensions_line_edit.textChanged.connect(lambda _="": self._sync_selected_remote_open_rule_from_form())
        self._remote_open_command_line_edit.textChanged.connect(lambda _="": self._sync_selected_remote_open_rule_from_form())
        self._remote_open_arguments_line_edit.textChanged.connect(lambda _="": self._sync_selected_remote_open_rule_from_form())
        return page

    def _build_local_office_web_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        office_group = QGroupBox(app_tr("SettingsDialog", "Lokale Bearbeitung"), page)
        office_layout = QFormLayout(office_group)
        office_layout.setContentsMargins(12, 12, 12, 12)
        office_layout.setHorizontalSpacing(12)
        office_layout.setVerticalSpacing(12)

        self._local_office_web_enabled_checkbox = QCheckBox(
            app_tr("SettingsDialog", "Lokale Word-/Excel-Dateien ueber persoenliches OneDrive-Web bearbeiten"),
            office_group,
        )
        office_layout.addRow("", self._local_office_web_enabled_checkbox)

        self._local_office_web_connection_combo = QComboBox(office_group)
        office_layout.addRow(app_tr("SettingsDialog", "Persoenliche OneDrive-Verbindung"), self._local_office_web_connection_combo)

        self._local_office_web_temp_folder_line_edit = QLineEdit(office_group)
        self._local_office_web_temp_folder_line_edit.setPlaceholderText("/.tablion-temp")
        office_layout.addRow(app_tr("SettingsDialog", "Temporärer Remote-Ordner"), self._local_office_web_temp_folder_line_edit)
        layout.addWidget(office_group)

        info_label = QLabel(
            app_tr(
                "SettingsDialog",
                "Lokale Office-Dateien werden in das persoenliche OneDrive der gewaehlten Verbindung unter /.tablion-temp oder einem eigenen Unterordner hochgeladen und dann ueber ihre Web-URL in der PWA geoeffnet. Team- oder SharePoint-Ziele werden hier bewusst nicht verwendet.",
            ),
            page,
        )
        info_label.setWordWrap(True)
        info_label.setContentsMargins(10, 8, 10, 8)
        info_label.setStyleSheet(
            "QLabel {"
            " background-color: rgba(120, 120, 120, 0.10);"
            " border: 1px solid rgba(160, 160, 160, 0.28);"
            " border-radius: 6px;"
            " padding: 8px;"
            "}"
        )
        layout.addWidget(info_label)

        remote_display_group = QGroupBox(app_tr("SettingsDialog", "Remote-Anzeige"), page)
        remote_display_layout = QVBoxLayout(remote_display_group)
        remote_display_layout.setContentsMargins(12, 12, 12, 12)
        remote_display_layout.setSpacing(8)

        self._remote_dot_hidden_checkbox = QCheckBox(
            app_tr("SettingsDialog", ".-Notation als versteckte Dateien/Ordner behandeln"),
            remote_display_group,
        )
        remote_display_layout.addWidget(self._remote_dot_hidden_checkbox)

        remote_hint_label = QLabel(
            app_tr(
                "SettingsDialog",
                "Wenn aktiv, werden Remote-Einträge wie .git oder .env über den normalen Schalter für versteckte Dateien behandelt: ausgeblendet oder bei eingeblendeten versteckten Dateien abgedunkelt dargestellt.",
            ),
            remote_display_group,
        )
        remote_hint_label.setWordWrap(True)
        remote_display_layout.addWidget(remote_hint_label)
        layout.addWidget(remote_display_group)

        layout.addStretch(1)
        return page

    def _load_connection_rows(self) -> None:
        self._connection_rows = []
        if self._remote_connection_settings is None:
            return
        for item in self._remote_connection_settings.connections:
            self._connection_rows.append(asdict_like(item))

    def _load_mount_rows(self) -> None:
        self._mount_rows = []
        if self._remote_mount_settings is None:
            return
        for item in self._remote_mount_settings.mounts:
            self._mount_rows.append(asdict_like(item))

    def _load_remote_open_rule_rows(self) -> None:
        self._remote_open_rule_rows = list(getattr(self._editor_settings, "remote_open_rules", []))

    def _rebuild_connection_table(self) -> None:
        if self._connection_table is None:
            return
        selected_row = self._connection_table.currentRow()
        self._connection_table.blockSignals(True)
        self._connection_table.setRowCount(len(self._connection_rows))
        for row, item in enumerate(self._connection_rows):
            values = [
                self._provider_label(item.get("provider")),
                str(item.get("display_name") or ""),
                str(item.get("account_label") or ""),
                str(item.get("tenant_id") or ""),
                app_tr("SettingsDialog", "Verbunden") if item.get("refresh_token") else app_tr("SettingsDialog", "Unvollständig"),
            ]
            for column, value in enumerate(values):
                self._connection_table.setItem(row, column, QTableWidgetItem(value))
        self._connection_table.resizeColumnsToContents()
        self._connection_table.blockSignals(False)
        if self._connection_rows:
            if selected_row < 0 or selected_row >= len(self._connection_rows):
                selected_row = 0
            self._connection_table.selectRow(selected_row)

    def _load_selected_connection_into_form(self) -> None:
        if self._connection_form_sync_guard:
            return
        if (
            self._connection_table is None
            or self._connection_provider_combo is None
            or self._connection_display_name_line_edit is None
            or self._connection_tenant_line_edit is None
            or self._connection_client_id_line_edit is None
        ):
            return

        row = self._connection_table.currentRow()
        if row < 0 or row >= len(self._connection_rows):
            return

        item = self._connection_rows[row]
        self._connection_form_sync_guard = True
        try:
            provider = str(item.get("provider") or "onedrive").strip().lower()
            provider_index = {"onedrive": 0, "dropbox": 1, "gdrive": 2}.get(provider, 0)
            self._connection_provider_combo.setCurrentIndex(provider_index)
            self._connection_display_name_line_edit.setText(str(item.get("display_name") or ""))
            self._connection_tenant_line_edit.setText(str(item.get("tenant_id") or "common") or "common")
            self._connection_client_id_line_edit.setText(str(item.get("client_id") or ""))
            self._update_connection_status_details(item)
        finally:
            self._connection_form_sync_guard = False

    def _update_connection_status_details(self, item: dict | None) -> None:
        if self._connection_status_label is None:
            return
        if not isinstance(item, dict):
            self._connection_status_label.setText(
                app_tr(
                    "SettingsDialog",
                    "Verbindungen enthalten Authentifizierung und Kontodaten. Einträge im Navigator werden erst aus Einträgen erzeugt.",
                )
            )
            return

        token_payload = self._decode_access_token_payload(str(item.get("access_token") or ""))
        scopes = self._token_scopes(token_payload)
        scope_text = ", ".join(scopes) if scopes else app_tr("SettingsDialog", "(Keine Scopes im Token gefunden)")
        expires_at = float(item.get("access_token_expires_at") or 0.0)
        expiry_text = time.strftime("%d.%m.%Y %H:%M", time.localtime(expires_at)) if expires_at > 0 else "?"
        account_label = str(item.get("account_label") or "").strip() or "-"
        drive_id = str(item.get("drive_id") or "").strip() or "-"

        self._connection_status_label.setText(
            app_tr(
                "SettingsDialog",
                "Konto: {account}\nDrive-ID: {drive}\nToken gültig bis: {expires}\nScopes: {scopes}",
            ).format(
                account=account_label,
                drive=drive_id,
                expires=expiry_text,
                scopes=scope_text,
            )
        )

    def _decode_access_token_payload(self, token: str) -> dict:
        raw = str(token or "").strip()
        if not raw or "." not in raw:
            return {}
        parts = raw.split(".")
        if len(parts) < 2:
            return {}
        payload = parts[1]
        padding = "=" * (-len(payload) % 4)
        try:
            decoded = base64.urlsafe_b64decode(payload + padding).decode("utf-8")
            value = json.loads(decoded)
        except (ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def _token_scopes(self, payload: dict) -> list[str]:
        if not isinstance(payload, dict):
            return []
        scopes = str(payload.get("scp") or "").strip().split()
        if scopes:
            return sorted(dict.fromkeys(scope for scope in scopes if scope))
        roles = payload.get("roles")
        if isinstance(roles, list):
            return sorted(dict.fromkeys(str(role).strip() for role in roles if str(role).strip()))
        return []

    def _rebuild_mount_table(self) -> None:
        if self._mount_table is None:
            return
        self._mount_table.blockSignals(True)
        self._mount_table.setRowCount(len(self._mount_rows))
        for row, item in enumerate(self._mount_rows):
            values = [
                self._connection_label(item.get("connection_id")),
                str(item.get("display_name") or ""),
                self._scope_label(item.get("scope")),
                str(item.get("root_path") or "/"),
                app_tr("SettingsDialog", "Aktiv") if item.get("enabled", True) else app_tr("SettingsDialog", "Deaktiviert"),
            ]
            for column, value in enumerate(values):
                self._mount_table.setItem(row, column, QTableWidgetItem(value))
        self._mount_table.resizeColumnsToContents()
        self._mount_table.blockSignals(False)

    def _rebuild_mount_connection_combo(self) -> None:
        if self._mount_connection_combo is None:
            return
        self._mount_connection_combo.clear()
        for item in self._connection_rows:
            label = str(item.get("display_name") or "")
            account = str(item.get("account_label") or "")
            if account:
                label = f"{label} - {account}"
            self._mount_connection_combo.addItem(label, item.get("id"))
        self._apply_mount_icon_suggestion()
        self._populate_team_combo()

    def _rebuild_local_office_web_connection_combo(self) -> None:
        if self._local_office_web_connection_combo is None:
            return
        current_connection_id = str(self._local_office_web_connection_combo.currentData() or "").strip()
        self._local_office_web_connection_combo.clear()
        for item in self._connection_rows:
            if str(item.get("provider") or "").strip().lower() != "onedrive":
                continue
            label = str(item.get("display_name") or "")
            account = str(item.get("account_label") or "")
            if account:
                label = f"{label} - {account}"
            self._local_office_web_connection_combo.addItem(label, item.get("id"))
        preferred_id = self._editor_settings.local_office_web_connection_id if self._editor_settings is not None else ""
        target_id = preferred_id or current_connection_id
        if target_id:
            index = self._local_office_web_connection_combo.findData(target_id)
            if index >= 0:
                self._local_office_web_connection_combo.setCurrentIndex(index)

    def _rebuild_remote_open_rules_table(self) -> None:
        if self._remote_open_rules_table is None:
            return
        selected_row = self._remote_open_rules_table.currentRow()
        self._remote_open_rules_table.blockSignals(True)
        self._remote_open_rules_table.setRowCount(len(self._remote_open_rule_rows))
        for row, item in enumerate(self._remote_open_rule_rows):
            values = [
                str(item.get("extensions") or ""),
                str(item.get("command") or ""),
                str(item.get("arguments") or ""),
            ]
            for column, value in enumerate(values):
                self._remote_open_rules_table.setItem(row, column, QTableWidgetItem(value))
        self._remote_open_rules_table.resizeColumnsToContents()
        self._remote_open_rules_table.blockSignals(False)
        if self._remote_open_rule_rows:
            if selected_row < 0 or selected_row >= len(self._remote_open_rule_rows):
                selected_row = 0
            self._remote_open_rules_table.selectRow(selected_row)

    def _load_selected_remote_open_rule_into_form(self) -> None:
        if self._remote_open_rule_form_sync_guard:
            return
        if (
            self._remote_open_rules_table is None
            or self._remote_open_extensions_line_edit is None
            or self._remote_open_command_line_edit is None
            or self._remote_open_arguments_line_edit is None
        ):
            return
        row = self._remote_open_rules_table.currentRow()
        if row < 0 or row >= len(self._remote_open_rule_rows):
            return
        item = self._remote_open_rule_rows[row]
        self._remote_open_rule_form_sync_guard = True
        try:
            self._remote_open_extensions_line_edit.setText(str(item.get("extensions") or ""))
            self._remote_open_command_line_edit.setText(str(item.get("command") or ""))
            self._remote_open_arguments_line_edit.setText(str(item.get("arguments") or ""))
        finally:
            self._remote_open_rule_form_sync_guard = False

    def _sync_selected_remote_open_rule_from_form(self) -> None:
        if self._remote_open_rule_form_sync_guard:
            return
        if (
            self._remote_open_rules_table is None
            or self._remote_open_extensions_line_edit is None
            or self._remote_open_command_line_edit is None
            or self._remote_open_arguments_line_edit is None
        ):
            return
        row = self._remote_open_rules_table.currentRow()
        if row < 0 or row >= len(self._remote_open_rule_rows):
            return
        self._remote_open_rule_form_sync_guard = True
        try:
            self._remote_open_rule_rows[row] = {
                "extensions": self._remote_open_extensions_line_edit.text().strip(),
                "command": self._remote_open_command_line_edit.text().strip(),
                "arguments": self._remote_open_arguments_line_edit.text().strip(),
            }
            self._rebuild_remote_open_rules_table()
            self._remote_open_rules_table.selectRow(row)
        finally:
            self._remote_open_rule_form_sync_guard = False

    def _provider_label(self, provider: str) -> str:
        mapping = {"onedrive": "OneDrive", "dropbox": "Dropbox", "gdrive": "Google Drive"}
        return mapping.get(str(provider or "").strip().lower(), "OneDrive")

    def _scope_label(self, scope: str) -> str:
        mapping = {
            "personal": app_tr("SettingsDialog", "Persönlich"),
            "sharepoint": app_tr("SettingsDialog", "SharePoint"),
            "team": app_tr("SettingsDialog", "Team"),
        }
        return mapping.get(str(scope or "").strip().lower(), app_tr("SettingsDialog", "Persönlich"))

    def _connection_label(self, connection_id: str) -> str:
        key = str(connection_id or "").strip()
        for item in self._connection_rows:
            if item.get("id") == key:
                label = str(item.get("display_name") or "")
                account = str(item.get("account_label") or "")
                return f"{label} - {account}" if account else label
        return key

    def _suggest_icon_name(self, provider: str, scope: str) -> str:
        provider_key = str(provider or "").strip().lower()
        scope_key = str(scope or "").strip().lower()
        if provider_key == "onedrive":
            if scope_key == "sharepoint":
                return "folder-publicshare"
            if scope_key == "team":
                return "folder-sync"
            return "folder-cloud"
        return "folder-cloud"

    def _apply_mount_icon_suggestion(self) -> None:
        if self._mount_icon_name_line_edit is None:
            return
        if self._mount_icon_name_line_edit.text().strip():
            return
        connection_id = str(self._mount_connection_combo.currentData() or "").strip() if self._mount_connection_combo else ""
        provider = "onedrive"
        for item in self._connection_rows:
            if item.get("id") == connection_id:
                provider = str(item.get("provider") or "onedrive")
                break
        scope_index = self._mount_scope_combo.currentIndex() if self._mount_scope_combo else 0
        scope = ["personal", "sharepoint", "team"][max(0, min(scope_index, 2))]
        self._mount_icon_name_line_edit.setPlaceholderText(self._suggest_icon_name(provider, scope))

    def _current_mount_scope_key(self) -> str:
        scope_index = self._mount_scope_combo.currentIndex() if self._mount_scope_combo else 0
        return ["personal", "sharepoint", "team"][max(0, min(scope_index, 2))]

    def _update_mount_scope_dependent_fields(self) -> None:
        is_team = self._current_mount_scope_key() == "team"
        if self._mount_team_combo is not None:
            self._mount_team_combo.setEnabled(is_team)
        if self._mount_team_load_button is not None:
            self._mount_team_load_button.setEnabled(is_team and bool(self._mount_connection_combo and self._mount_connection_combo.count()))
        self._populate_team_combo()

    def _populate_team_combo(self) -> None:
        if self._mount_team_combo is None:
            return
        self._mount_team_combo.blockSignals(True)
        self._mount_team_combo.clear()
        connection_id = str(self._mount_connection_combo.currentData() or "").strip() if self._mount_connection_combo else ""
        options = self._team_options_by_connection.get(connection_id, [])
        if not options:
            self._mount_team_combo.addItem(app_tr("SettingsDialog", "Keine Teams geladen"), "")
            self._mount_team_combo.setEnabled(False if self._current_mount_scope_key() == "team" else False)
            self._mount_team_combo.blockSignals(False)
            return
        for option in options:
            self._mount_team_combo.addItem(str(option.get("label") or ""), option.get("id"))
        self._mount_team_combo.setEnabled(self._current_mount_scope_key() == "team")
        self._mount_team_combo.blockSignals(False)

    def _load_team_options_for_current_connection(self) -> None:
        connection_id = str(self._mount_connection_combo.currentData() or "").strip() if self._mount_connection_combo else ""
        if not connection_id:
            return
        connection = None
        for item in self._connection_rows:
            if str(item.get("id") or "") == connection_id:
                connection = item
                break
        if connection is None:
            return
        if str(connection.get("provider") or "").strip().lower() != "onedrive":
            return
        try:
            access_token = self._ensure_connection_access_token(connection)
            teams = self._one_drive_client.list_joined_teams(access_token=access_token)
            options: list[dict] = []
            for team in teams:
                team_id = str(team.get("id") or "").strip()
                if not team_id:
                    continue
                drives = self._one_drive_client.list_group_drives(access_token=access_token, group_id=team_id)
                drive_id = ""
                if isinstance(drives, list) and drives:
                    drive_id = str(drives[0].get("id") or "").strip()
                options.append(
                    {
                        "id": team_id,
                        "label": str(team.get("displayName") or "").strip() or team_id,
                        "drive_id": drive_id,
                    }
                )
        except OneDriveAuthError as error:
            QMessageBox.warning(
                self,
                app_tr("SettingsDialog", "Teams konnten nicht geladen werden"),
                str(error),
            )
            return
        self._team_options_by_connection[connection_id] = options
        self._populate_team_combo()

    def _ensure_connection_access_token(self, connection: dict) -> str:
        access_token = str(connection.get("access_token") or "").strip()
        expires_at = float(connection.get("access_token_expires_at") or 0.0)
        if access_token and expires_at > time.time() + 30:
            return access_token
        refresh_token = str(connection.get("refresh_token") or "").strip()
        client_id = str(connection.get("client_id") or "").strip()
        tenant_id = str(connection.get("tenant_id") or "common").strip() or "common"
        if refresh_token and client_id:
            refreshed = self._one_drive_auth_service.refresh_access_token(
                client_id=client_id,
                tenant_id=tenant_id,
                refresh_token=refresh_token,
            )
            connection["access_token"] = refreshed.access_token
            connection["refresh_token"] = refreshed.refresh_token
            connection["access_token_expires_at"] = refreshed.expires_at
            connection["account_label"] = refreshed.account_label
            connection["drive_id"] = refreshed.drive_id
            self._rebuild_connection_table()
            self._rebuild_mount_connection_combo()
            return refreshed.access_token
        raise OneDriveAuthError(
            app_tr("SettingsDialog", "Die Verbindung muss nach Berechtigungsänderungen erneut verbunden werden.")
        )

    def _pick_mount_icon(self) -> None:
        if self._mount_icon_name_line_edit is None:
            return
        current_value = self._mount_icon_name_line_edit.text().strip() or self._mount_icon_name_line_edit.placeholderText().strip()
        dialog = IconPickerDialog(self, current_value)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._mount_icon_name_line_edit.setText(dialog.icon_value())
        self._sync_selected_mount_from_form()

    def _load_selected_mount_into_form(self) -> None:
        if self._mount_form_sync_guard:
            return
        if self._mount_table is None or self._mount_connection_combo is None or self._mount_display_name_line_edit is None:
            return
        row = self._mount_table.currentRow()
        if row < 0 or row >= len(self._mount_rows):
            return
        self._mount_form_sync_guard = True
        item = self._mount_rows[row]
        try:
            connection_index = self._mount_connection_combo.findData(item.get("connection_id"))
            if connection_index >= 0:
                self._mount_connection_combo.setCurrentIndex(connection_index)
            self._mount_display_name_line_edit.setText(str(item.get("display_name") or ""))
            scope = str(item.get("scope") or "personal").strip().lower()
            scope_index = {"personal": 0, "sharepoint": 1, "team": 2}.get(scope, 0)
            if self._mount_scope_combo is not None:
                self._mount_scope_combo.setCurrentIndex(scope_index)
            if self._mount_root_path_line_edit is not None:
                self._mount_root_path_line_edit.setText(str(item.get("root_path") or "/"))
            if self._mount_icon_name_line_edit is not None:
                self._mount_icon_name_line_edit.setText(str(item.get("icon_name") or ""))
                self._apply_mount_icon_suggestion()
            if self._current_mount_scope_key() == "team":
                self._populate_team_combo()
                team_id = str(item.get("team_id") or "").strip()
                if self._mount_team_combo is not None and team_id:
                    team_index = self._mount_team_combo.findData(team_id)
                    if team_index >= 0:
                        self._mount_team_combo.setCurrentIndex(team_index)
        finally:
            self._mount_form_sync_guard = False

    def _sync_selected_mount_from_form(self) -> None:
        if self._mount_form_sync_guard:
            return
        if (
            self._mount_table is None
            or self._mount_connection_combo is None
            or self._mount_display_name_line_edit is None
            or self._mount_scope_combo is None
            or self._mount_root_path_line_edit is None
            or self._mount_icon_name_line_edit is None
        ):
            return
        row = self._mount_table.currentRow()
        if row < 0 or row >= len(self._mount_rows):
            return
        self._mount_form_sync_guard = True

        try:
            connection_id = str(self._mount_connection_combo.currentData() or "").strip()
            if not connection_id:
                return

            connection = None
            for item in self._connection_rows:
                if str(item.get("id") or "") == connection_id:
                    connection = item
                    break
            if connection is None:
                return

            scope = ["personal", "sharepoint", "team"][max(0, min(self._mount_scope_combo.currentIndex(), 2))]
            root_path = self._mount_root_path_line_edit.text().strip() or "/"
            icon_name = self._mount_icon_name_line_edit.text().strip() or self._suggest_icon_name(connection.get("provider", "onedrive"), scope)
            team_id = ""
            team_label = ""
            drive_id = connection.get("drive_id", "")
            if scope == "team" and self._mount_team_combo is not None:
                team_id = str(self._mount_team_combo.currentData() or "").strip()
                team_label = self._mount_team_combo.currentText().strip()
                for option in self._team_options_by_connection.get(connection_id, []):
                    if str(option.get("id") or "") == team_id:
                        drive_id = str(option.get("drive_id") or drive_id).strip()
                        break

            self._mount_rows[row] = {
                **self._mount_rows[row],
                "connection_id": connection_id,
                "provider": connection.get("provider", "onedrive"),
                "display_name": self._mount_display_name_line_edit.text().strip(),
                "icon_name": icon_name,
                "scope": scope,
                "drive_id": drive_id,
                "team_id": team_id,
                "team_label": team_label,
                "root_path": root_path,
            }
            self._rebuild_mount_table()
            self._mount_table.selectRow(row)
        finally:
            self._mount_form_sync_guard = False

    def _connect_new_account(self) -> None:
        if self._connection_display_name_line_edit is None:
            return
        display_name = self._connection_display_name_line_edit.text().strip()
        if not display_name:
            return

        provider_index = self._connection_provider_combo.currentIndex() if self._connection_provider_combo else 0
        provider = ["onedrive", "dropbox", "gdrive"][max(0, min(provider_index, 2))]
        if provider != "onedrive":
            QMessageBox.information(
                self,
                app_tr("SettingsDialog", "Remote-Clouds"),
                app_tr("SettingsDialog", "Aktuell ist nur OneDrive-Authentifizierung implementiert."),
            )
            return

        tenant_id = self._connection_tenant_line_edit.text().strip() if self._connection_tenant_line_edit else "common"
        client_id = self._connection_client_id_line_edit.text().strip() if self._connection_client_id_line_edit else ""
        if not client_id:
            QMessageBox.warning(
                self,
                app_tr("SettingsDialog", "Remote-Clouds"),
                app_tr("SettingsDialog", "Für OneDrive ist eine Client-ID erforderlich."),
            )
            return

        try:
            auth_result = self._one_drive_auth_service.authenticate(
                client_id=client_id,
                tenant_id=tenant_id or "common",
                device_prompt_callback=self._show_onedrive_device_prompt,
            )
        except OneDriveAuthError as error:
            QMessageBox.warning(
                self,
                app_tr("SettingsDialog", "OneDrive-Anmeldung fehlgeschlagen"),
                str(error),
            )
            return

        self._connection_rows.append(
            {
                "id": f"conn-{uuid.uuid4().hex}",
                "provider": provider,
                "display_name": display_name,
                "tenant_id": tenant_id or "common",
                "client_id": client_id,
                "account_label": auth_result.account_label,
                "drive_id": auth_result.drive_id,
                "access_token": auth_result.access_token,
                "refresh_token": auth_result.refresh_token,
                "access_token_expires_at": auth_result.expires_at,
                "enabled": True,
            }
        )
        self._rebuild_connection_table()
        self._rebuild_mount_connection_combo()
        self._rebuild_local_office_web_connection_combo()
        self._apply_mount_icon_suggestion()
        self._connection_display_name_line_edit.clear()
        if self._connection_client_id_line_edit:
            self._connection_client_id_line_edit.clear()

    def _reconnect_selected_connection(self) -> None:
        if self._connection_table is None:
            return
        row = self._connection_table.currentRow()
        if row < 0 or row >= len(self._connection_rows):
            QMessageBox.information(
                self,
                app_tr("SettingsDialog", "Remote-Clouds"),
                app_tr("SettingsDialog", "Bitte zuerst eine Verbindung auswählen."),
            )
            return

        connection = self._connection_rows[row]
        provider = str(connection.get("provider") or "onedrive").strip().lower()
        if provider != "onedrive":
            QMessageBox.information(
                self,
                app_tr("SettingsDialog", "Remote-Clouds"),
                app_tr("SettingsDialog", "Aktuell ist nur OneDrive-Authentifizierung implementiert."),
            )
            return

        client_id = str(connection.get("client_id") or "").strip()
        tenant_id = str(connection.get("tenant_id") or "common").strip() or "common"
        if not client_id:
            QMessageBox.warning(
                self,
                app_tr("SettingsDialog", "Remote-Clouds"),
                app_tr("SettingsDialog", "Für OneDrive ist eine Client-ID erforderlich."),
            )
            return

        try:
            auth_result = self._one_drive_auth_service.authenticate(
                client_id=client_id,
                tenant_id=tenant_id,
                device_prompt_callback=self._show_onedrive_device_prompt,
            )
        except OneDriveAuthError as error:
            QMessageBox.warning(
                self,
                app_tr("SettingsDialog", "OneDrive-Anmeldung fehlgeschlagen"),
                str(error),
            )
            return

        self._connection_rows[row] = {
            **connection,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "account_label": auth_result.account_label,
            "drive_id": auth_result.drive_id,
            "access_token": auth_result.access_token,
            "refresh_token": auth_result.refresh_token,
            "access_token_expires_at": auth_result.expires_at,
            "enabled": True,
        }
        self._team_options_by_connection.pop(str(connection.get("id") or "").strip(), None)
        self._rebuild_connection_table()
        self._rebuild_mount_connection_combo()
        self._rebuild_local_office_web_connection_combo()
        self._rebuild_mount_table()
        self._connection_table.selectRow(row)
        self._update_connection_status_details(self._connection_rows[row])

    def _add_mount(self) -> None:
        if self._mount_connection_combo is None or self._mount_display_name_line_edit is None:
            return
        connection_id = str(self._mount_connection_combo.currentData() or "").strip()
        display_name = self._mount_display_name_line_edit.text().strip()
        if not connection_id or not display_name:
            return

        connection = None
        for item in self._connection_rows:
            if item.get("id") == connection_id:
                connection = item
                break
        if connection is None:
            return

        scope_index = self._mount_scope_combo.currentIndex() if self._mount_scope_combo else 0
        scope = ["personal", "sharepoint", "team"][max(0, min(scope_index, 2))]
        root_path = (self._mount_root_path_line_edit.text().strip() if self._mount_root_path_line_edit else "") or "/"
        team_id = ""
        team_label = ""
        drive_id = connection.get("drive_id", "")
        if scope == "team":
            if self._mount_team_combo is None or not str(self._mount_team_combo.currentData() or "").strip():
                QMessageBox.information(
                    self,
                    app_tr("SettingsDialog", "Remote-Clouds"),
                    app_tr("SettingsDialog", "Bitte zuerst ein Team laden und auswählen."),
                )
                return
            team_id = str(self._mount_team_combo.currentData() or "").strip()
            team_label = self._mount_team_combo.currentText().strip()
            for option in self._team_options_by_connection.get(connection_id, []):
                if str(option.get("id") or "") == team_id:
                    drive_id = str(option.get("drive_id") or drive_id).strip()
                    break

        self._mount_rows.append(
            {
                "connection_id": connection_id,
                "provider": connection.get("provider", "onedrive"),
                "display_name": display_name,
                "icon_name": (
                    self._mount_icon_name_line_edit.text().strip()
                    if self._mount_icon_name_line_edit and self._mount_icon_name_line_edit.text().strip()
                    else self._suggest_icon_name(connection.get("provider", "onedrive"), scope)
                ),
                "scope": scope,
                "drive_id": drive_id,
                "team_id": team_id,
                "team_label": team_label,
                "root_path": root_path,
                "enabled": True,
            }
        )
        self._rebuild_mount_table()
        if self._mount_table is not None and self._mount_rows:
            self._mount_table.selectRow(len(self._mount_rows) - 1)
        if self._mount_root_path_line_edit:
            self._mount_root_path_line_edit.clear()

    def _show_onedrive_device_prompt(self, *, message: str, user_code: str, verification_uri: str, prompt_url: str) -> None:
        detail_lines = []
        if message:
            detail_lines.append(message)
        else:
            detail_lines.append(app_tr("SettingsDialog", "Bitte öffne die Microsoft-Seite und gib dort den folgenden Code ein:"))
            detail_lines.append(user_code)
        if prompt_url:
            detail_lines.extend(["", app_tr("SettingsDialog", "Geöffnete URL:"), prompt_url])
        if verification_uri and verification_uri != prompt_url:
            detail_lines.extend(["", app_tr("SettingsDialog", "Fallback-URL:"), verification_uri])
        QMessageBox.information(self, app_tr("SettingsDialog", "OneDrive-Anmeldung"), "\n".join(detail_lines))

    def _remove_selected_connection(self) -> None:
        if self._connection_table is None:
            return
        row = self._connection_table.currentRow()
        if row < 0 or row >= len(self._connection_rows):
            return
        connection_id = str(self._connection_rows[row].get("id") or "")
        del self._connection_rows[row]
        self._mount_rows = [item for item in self._mount_rows if str(item.get("connection_id") or "") != connection_id]
        self._rebuild_connection_table()
        self._rebuild_mount_connection_combo()
        self._rebuild_local_office_web_connection_combo()
        self._rebuild_mount_table()

    def _remove_selected_mount(self) -> None:
        if self._mount_table is None:
            return
        row = self._mount_table.currentRow()
        if row < 0 or row >= len(self._mount_rows):
            return
        self._mount_form_sync_guard = True
        del self._mount_rows[row]
        self._rebuild_mount_table()
        next_row = min(row, len(self._mount_rows) - 1)
        if next_row >= 0:
            self._mount_table.selectRow(next_row)
        self._mount_form_sync_guard = False

    def _add_remote_open_rule(self) -> None:
        if (
            self._remote_open_extensions_line_edit is None
            or self._remote_open_command_line_edit is None
            or self._remote_open_arguments_line_edit is None
        ):
            return
        extensions = self._remote_open_extensions_line_edit.text().strip()
        command = self._remote_open_command_line_edit.text().strip()
        if not extensions or not command:
            return
        self._remote_open_rule_rows.append(
            {
                "extensions": extensions,
                "command": command,
                "arguments": self._remote_open_arguments_line_edit.text().strip(),
            }
        )
        self._rebuild_remote_open_rules_table()
        if self._remote_open_rules_table is not None and self._remote_open_rule_rows:
            self._remote_open_rules_table.selectRow(len(self._remote_open_rule_rows) - 1)

    def _remove_selected_remote_open_rule(self) -> None:
        if self._remote_open_rules_table is None:
            return
        row = self._remote_open_rules_table.currentRow()
        if row < 0 or row >= len(self._remote_open_rule_rows):
            return
        self._remote_open_rule_form_sync_guard = True
        del self._remote_open_rule_rows[row]
        self._rebuild_remote_open_rules_table()
        next_row = min(row, len(self._remote_open_rule_rows) - 1)
        if next_row >= 0:
            self._remote_open_rules_table.selectRow(next_row)
        self._remote_open_rule_form_sync_guard = False

    def _on_apply(self) -> None:
        old_language = self._editor_settings.language_preference
        self._save_preferences()
        self.settingsChanged.emit()
        new_language = self._editor_settings.language_preference
        if new_language != old_language:
            self.languagePreferenceChanged.emit(new_language)

    def _on_accepted(self) -> None:
        old_language = self._editor_settings.language_preference
        self._save_preferences()
        self.settingsChanged.emit()
        new_language = self._editor_settings.language_preference
        if new_language != old_language:
            self.languagePreferenceChanged.emit(new_language)
        self.accept()

    def _save_preferences(self) -> None:
        self._persist_dialog_size()
        if self._default_editor_line_edit:
            value = self._default_editor_line_edit.text().strip()
            self._editor_settings.update_tablion_editor(value if value else None)
        if self._app_double_click_behavior_combo:
            behavior = "edit" if self._app_double_click_behavior_combo.currentIndex() == 1 else "start"
            self._editor_settings.update_application_double_click_behavior(behavior)
        if self._language_preference_combo:
            index = self._language_preference_combo.currentIndex()
            lang = "system" if index == 0 else ("de" if index == 1 else "en")
            self._editor_settings.update_language_preference(lang)
        if self._group_creation_behavior_combo:
            behavior = "copy_tabs" if self._group_creation_behavior_combo.currentIndex() == 1 else "default_tab"
            self._editor_settings.update_group_creation_behavior(behavior)
        if self._middle_click_tab_behavior_combo:
            behavior = "foreground" if self._middle_click_tab_behavior_combo.currentIndex() == 1 else "background"
            self._editor_settings.update_middle_click_new_tab_behavior(behavior)
        if self._show_group_tab_close_icons_checkbox:
            self._editor_settings.update_show_group_tab_close_icons(self._show_group_tab_close_icons_checkbox.isChecked())
        if self._show_file_tab_close_icons_checkbox:
            self._editor_settings.update_show_file_tab_close_icons(self._show_file_tab_close_icons_checkbox.isChecked())
        self._editor_settings.update_remote_open_rules(self._remote_open_rule_rows)
        self._editor_settings.update_local_office_web_editing(
            enabled=self._local_office_web_enabled_checkbox.isChecked() if self._local_office_web_enabled_checkbox else False,
            connection_id=str(self._local_office_web_connection_combo.currentData() or "").strip() if self._local_office_web_connection_combo else "",
            temp_folder=self._local_office_web_temp_folder_line_edit.text().strip() if self._local_office_web_temp_folder_line_edit else "/.tablion-temp",
        )
        self._editor_settings.update_treat_dot_entries_as_hidden_remote(
            self._remote_dot_hidden_checkbox.isChecked() if self._remote_dot_hidden_checkbox else False
        )
        if self._remote_connection_settings is not None:
            self._remote_connection_settings.replace_all(self._connection_rows)
        if self._remote_mount_settings is not None:
            self._remote_mount_settings.replace_all(self._mount_rows)

    def closeEvent(self, event) -> None:
        self._persist_dialog_size()
        super().closeEvent(event)

    def _persist_dialog_size(self) -> None:
        if self._editor_settings is None:
            return
        self._editor_settings.update_settings_dialog_size(self.width(), self.height())

    def focus_remote_mount(self, mount_id: str) -> bool:
        key = str(mount_id or "").strip()
        if not key or self._categories_list is None or self._category_stack is None or self._mount_table is None:
            return False

        remote_page_index = self._category_stack.indexOf(self._remote_clouds_page) if self._remote_clouds_page is not None else -1
        if remote_page_index >= 0:
            self._categories_list.setCurrentRow(remote_page_index)
            self._category_stack.setCurrentIndex(remote_page_index)

        if self._remote_clouds_tabs is not None:
            self._remote_clouds_tabs.setCurrentIndex(1)

        for row, item in enumerate(self._mount_rows):
            if str(item.get("id") or "").strip() != key:
                continue
            self._mount_table.selectRow(row)
            self._load_selected_mount_into_form()
            self.raise_()
            self.activateWindow()
            return True
        return False

    def focus_remote_clouds(self) -> bool:
        if self._categories_list is None or self._category_stack is None:
            return False

        remote_page_index = self._category_stack.indexOf(self._remote_clouds_page) if self._remote_clouds_page is not None else -1
        if remote_page_index < 0:
            return False

        self._categories_list.setCurrentRow(remote_page_index)
        self._category_stack.setCurrentIndex(remote_page_index)
        if self._remote_clouds_tabs is not None:
            self._remote_clouds_tabs.setCurrentIndex(0)
        self.raise_()
        self.activateWindow()
        return True


def asdict_like(item) -> dict:
    return dict(item.__dict__)
