from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QStackedWidget,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from models.editor_settings import EditorSettings


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None, editor_settings: EditorSettings):
        super().__init__(parent)
        self._editor_settings = editor_settings
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

        self._default_editor_line_edit = self.ui.findChild(QLineEdit, "defaultEditorLineEdit")
        self._app_double_click_behavior_combo = self.ui.findChild(QComboBox, "appDoubleClickBehaviorCombo")
        self._button_box = self.ui.findChild(QDialogButtonBox, "buttonBox")
        self._categories_list = self.ui.findChild(QListWidget, "categoriesList")
        self._category_stack = self.ui.findChild(QStackedWidget, "categoryStack")

        if self._categories_list and self._category_stack:
            self._categories_list.currentRowChanged.connect(self._category_stack.setCurrentIndex)
            self._categories_list.setCurrentRow(0)

        if self._default_editor_line_edit:
            stored = self._editor_settings.tablion_editor
            if stored:
                self._default_editor_line_edit.setText(stored)

        if self._app_double_click_behavior_combo:
            behavior = self._editor_settings.application_double_click_behavior
            self._app_double_click_behavior_combo.setCurrentIndex(1 if behavior == "edit" else 0)

        if self._button_box:
            apply_button = self._button_box.button(QDialogButtonBox.StandardButton.Apply)
            if apply_button:
                apply_button.clicked.connect(self._on_apply)
            self._button_box.accepted.connect(self._on_accepted)
            self._button_box.rejected.connect(self.reject)

    def _on_apply(self) -> None:
        self._save_editor_preference()

    def _on_accepted(self) -> None:
        self._save_editor_preference()
        self.accept()

    def _save_editor_preference(self) -> None:
        if self._default_editor_line_edit:
            value = self._default_editor_line_edit.text().strip()
            self._editor_settings.update_tablion_editor(value if value else None)
        if self._app_double_click_behavior_combo:
            behavior = "edit" if self._app_double_click_behavior_combo.currentIndex() == 1 else "start"
            self._editor_settings.update_application_double_click_behavior(behavior)
