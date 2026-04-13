from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics, QIcon, QPainter, QPixmap, QColor

from domain.filesystem import PaneLocation
from localization import app_tr


class DragVisualService:
    def build_remote_drag_pixmap(self, widget, locations: list[PaneLocation]) -> QPixmap | None:
        if widget is None or not locations:
            return None

        label = (
            Path(locations[0].path).name or locations[0].path
            if len(locations) == 1
            else app_tr("PaneController", "{count} Elemente").format(count=len(locations))
        )

        font = widget.font()
        metrics = QFontMetrics(font)
        text_width = min(260, max(80, metrics.horizontalAdvance(label)))
        width = text_width + 44
        height = 34

        pixmap = QPixmap(width, height)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QColor(48, 48, 48, 230))
        painter.setPen(QColor(255, 255, 255, 36))
        painter.drawRoundedRect(0, 0, width - 1, height - 1, 8, 8)

        icon = QIcon.fromTheme("folder-cloud" if len(locations) > 1 else "text-x-generic")
        icon_pixmap = icon.pixmap(16, 16)
        if not icon_pixmap.isNull():
            painter.drawPixmap(12, 9, icon_pixmap)

        painter.setPen(QColor(245, 245, 245))
        elided = metrics.elidedText(label, Qt.TextElideMode.ElideRight, text_width)
        painter.drawText(34, 22, elided)
        painter.end()
        return pixmap
