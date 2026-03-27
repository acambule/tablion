from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from localization import app_tr
from utils.batch_rename import batch_rename_help_text, render_batch_rename_name


class BatchRenameDialog(QDialog):
    def __init__(self, parent: QWidget | None, sample_name: str, file_count: int):
        super().__init__(parent)
        self.setWindowTitle(app_tr("BatchRenameDialog", "Mehrfach umbenennen"))
        self.setModal(True)
        self.resize(520, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(4)

        title_label = QLabel(app_tr("BatchRenameDialog", "Neuer Name oder Regel"))
        layout.addWidget(title_label)

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(4)

        self._regex_button = QToolButton(self)
        self._regex_button.setCheckable(True)
        self._regex_button.setAutoRaise(True)
        self._regex_button.setToolTip(app_tr("BatchRenameDialog", "Regex-Modus ein- oder ausschalten"))
        self._regex_button.toggled.connect(self._on_regex_toggled)
        input_row.addWidget(self._regex_button)
        self._input_left_spacing = input_row.spacing()

        self._rule_edit = QLineEdit(self)
        self._rule_edit.setPlaceholderText(app_tr("BatchRenameDialog", "z. B. Rechnung oder {stem}_{n}{ext}"))
        input_row.addWidget(self._rule_edit)

        self._help_button = QToolButton(self)
        self._help_button.setAutoRaise(True)
        self._help_button.setToolTip(batch_rename_help_text())
        self._help_button.setStyleSheet("QToolTip { padding: 4px; }")
        info_icon = QIcon.fromTheme("help-about")
        if info_icon.isNull():
            info_icon = self.style().standardIcon(self.style().StandardPixmap.SP_MessageBoxInformation)
        self._help_button.setIcon(info_icon)
        self._help_button.setCursor(Qt.CursorShape.WhatsThisCursor)
        input_row.addWidget(self._help_button)
        layout.addLayout(input_row)

        layout.addSpacing(4)

        self._preview_frame = QFrame(self)
        self._preview_frame.setFrameShape(QFrame.Shape.StyledPanel)
        preview_layout = QVBoxLayout(self._preview_frame)
        preview_layout.setContentsMargins(8, 6, 8, 6)
        preview_layout.setSpacing(0)

        self._preview_label = QLabel(sample_name)
        self._preview_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._preview_label.setWordWrap(True)
        preview_layout.addWidget(self._preview_label)

        self._info_label = QLabel(
            app_tr("BatchRenameDialog", "Es werden {count} Dateien nach dem Muster umbenannt.").format(
                count=file_count
            )
        )
        self._info_label.setWordWrap(True)
        preview_layout.addSpacing(4)
        preview_layout.addWidget(self._info_label)

        layout.addWidget(self._preview_frame)
        layout.addSpacing(6)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        ok_button = button_box.button(QDialogButtonBox.StandardButton.Ok)
        cancel_button = button_box.button(QDialogButtonBox.StandardButton.Cancel)
        if ok_button is not None:
            ok_button.setText(app_tr("BatchRenameDialog", "OK"))
        if cancel_button is not None:
            cancel_button.setText(app_tr("BatchRenameDialog", "Abbrechen"))
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self._sample_name = str(sample_name or "")
        self._file_count = max(0, int(file_count))
        self._rule_edit.textChanged.connect(self._update_preview)
        self._on_regex_toggled(False)
        self._apply_editor_alignment()
        self._apply_info_label_color()
        self._update_preview()
        self._rule_edit.setFocus()

    def rule_text(self) -> str:
        return self._rule_edit.text().strip()

    def regex_enabled(self) -> bool:
        return self._regex_button.isChecked()

    def _on_regex_toggled(self, enabled: bool) -> None:
        icon_name = "code-context" if enabled else "character-set"
        fallback = (
            self.style().StandardPixmap.SP_MessageBoxInformation
            if enabled
            else self.style().StandardPixmap.SP_FileDialogDetailedView
        )
        icon = QIcon.fromTheme(icon_name)
        if icon.isNull():
            icon = self.style().standardIcon(fallback)
        self._regex_button.setIcon(icon)
        if enabled:
            self._rule_edit.setPlaceholderText(app_tr("BatchRenameDialog", "(.*) (\\d{2}) (\\d{4}) => {g1} {g3} {g2} {month_name_de:g2}{ext}"))
        else:
            self._rule_edit.setPlaceholderText(app_tr("BatchRenameDialog", "z. B. Rechnung oder {stem}_{n}{ext}"))
        self._apply_editor_alignment()
        self._update_preview()

    def _render_preview(self, text: str) -> str:
        file_name = self._sample_name
        if not file_name:
            return ""
        try:
            return render_batch_rename_name(file_name, text, 1, regex_mode=self.regex_enabled())
        except ValueError as error:
            return str(error)

    def _update_preview(self) -> None:
        self._preview_label.setText(self._render_preview(self.rule_text()))

    def _apply_editor_alignment(self) -> None:
        left_offset = self._regex_button.sizeHint().width() + self._input_left_spacing

        preview_margins = self._preview_frame.contentsMargins()
        self._preview_frame.setContentsMargins(
            left_offset,
            preview_margins.top(),
            preview_margins.right(),
            preview_margins.bottom(),
        )

    def _apply_info_label_color(self) -> None:
        palette = QGuiApplication.palette()
        base_color = palette.color(QPalette.ColorRole.WindowText)
        info_color = QColor(base_color)
        info_color.setAlpha(180)
        self._info_label.setStyleSheet(f"color: rgba({info_color.red()}, {info_color.green()}, {info_color.blue()}, {info_color.alpha()});")
