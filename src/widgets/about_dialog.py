from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QApplication, QWidget
from PySide6.QtCore import Qt

from localization import app_tr
from utils.xdg_defaults import get_default_file_manager, get_desktop_display_name, ensure_user_desktop_file, set_default_file_manager
from version_info import formatted_version


class AboutDialog(QDialog):
    def __init__(self, parent, navigator_data_path: Path, session_data_path: Path):
        super().__init__(parent)
        loader = QUiLoader()
        ui_path = Path(__file__).resolve().parent.parent / 'ui' / 'about.ui'
        # load the UI with this dialog as parent so widget hierarchy and
        # geometry behave correctly (important for centering)
        self.ui = loader.load(str(ui_path), self)
        if self.ui is None:
            raise RuntimeError(f"Konnte UI nicht laden: {ui_path}")

        # embed loaded UI into this dialog
        self.setWindowTitle(app_tr("AboutDialog", "Über / Info"))
        # Try stricter customization: use CustomizeWindowHint and explicitly
        # disable minimize/maximize. This tends to be honored on X11/KDE.
        try:
            flags = Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowCloseButtonHint
            self.setWindowFlags(flags)
            # explicitly clear min/max hints
            try:
                self.setWindowFlag(Qt.WindowMinimizeButtonHint, False)
            except Exception:
                pass
            try:
                self.setWindowFlag(Qt.WindowMaximizeButtonHint, False)
            except Exception:
                pass
            self.setWindowModality(Qt.WindowModality.WindowModal)
        except Exception:
            pass
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(self.ui)

        # find widgets inside the loaded UI
        self.introLabel = self.ui.findChild(QLabel, 'introLabel')
        self.pathsLabel = self.ui.findChild(QLabel, 'pathsLabel')
        self.defaultLabel = self.ui.findChild(QLabel, 'defaultLabel')
        self.setDefaultButton = self.ui.findChild(QPushButton, 'setDefaultButton')
        self.closeButton = self.ui.findChild(QPushButton, 'closeButton')

        try:
            if self.setDefaultButton:
                self.setDefaultButton.setText(app_tr("AboutDialog", "Tablion als Standard"))
            if self.closeButton:
                self.closeButton.setText(app_tr("AboutDialog", "Schließen"))
        except Exception:
            pass

        # update intro text with version
        try:
            intro_html = (
                f"<b>Tablion {formatted_version()}</b><br/><br/>"
                f"{app_tr('AboutDialog', 'Dateimanager mit Tabgruppen, Multi-View und smarter Dateiorganisation.')}"
            )
            if self.introLabel:
                self.introLabel.setText(intro_html)
        except Exception:
            pass

        # populate paths
        try:
            self.pathsLabel.setText(
                f"{app_tr('AboutDialog', 'Navigator-Daten:')}<br>{navigator_data_path}<br><br>"
                f"{app_tr('AboutDialog', 'Sitzungsdaten:')}<br>{session_data_path}"
            )
        except Exception:
            pass

        # show current default file manager
        try:
            current = get_default_file_manager()
            disp = get_desktop_display_name(current) if current else None
            fallback_name = disp or (current or app_tr("AboutDialog", "unbekannt"))
            self.defaultLabel.setText(
                app_tr("AboutDialog", "Standard-Dateimanager: {name}").format(name=fallback_name)
            )
        except Exception:
            try:
                self.defaultLabel.setText(
                    app_tr("AboutDialog", "Standard-Dateimanager: {name}").format(
                        name=app_tr("AboutDialog", "unbekannt")
                    )
                )
            except Exception:
                pass

        # setup set-default button
        desired_desktop = 'tablion.desktop'
        try:
            if current and str(current).strip() == desired_desktop:
                self.setDefaultButton.setVisible(False)
        except Exception:
            pass

        def on_set_default():
            exec_path = shutil.which('tablion') or Path(sys.argv[0]).resolve().as_posix()
            try:
                ensure_user_desktop_file(desired_desktop, exec_path)
            except Exception:
                pass
            ok = False
            try:
                ok = set_default_file_manager(desired_desktop)
            except Exception:
                ok = False
            if ok:
                try:
                    dn = get_desktop_display_name(desired_desktop) or desired_desktop
                    self.defaultLabel.setText(
                        app_tr("AboutDialog", "Standard-Dateimanager: {name}").format(name=dn)
                    )
                except Exception:
                    try:
                        self.defaultLabel.setText(
                            app_tr("AboutDialog", "Standard-Dateimanager: {name}").format(name=desired_desktop)
                        )
                    except Exception:
                        pass
                try:
                    self.setDefaultButton.setVisible(False)
                except Exception:
                    pass

        try:
            self.setDefaultButton.clicked.connect(on_set_default)
        except Exception:
            pass

        try:
            self.closeButton.clicked.connect(self.close)
        except Exception:
            pass

        # small layout tweaks
        try:
            self.setContentsMargins(12, 12, 12, 12)
        except Exception:
            pass

    def exec_centered(self):
        # size & center over parent then exec
        try:
            sh = self.sizeHint()
            w = sh.width() or 400
            h = sh.height() or 200
            self.resize(w, h)
            # enforce fixed size to prevent window managers offering a maximize
            # action (many WMs disable maximize when the window has a fixed size)
            try:
                self.setFixedSize(w, h)
            except Exception:
                pass
            # determine the visible widget to center over
            ref = None
            parent = self.parent()
            try:
                if parent is not None:
                    # if parent wraps a UI in `.ui`, prefer that visible widget
                    ui_widget = getattr(parent, 'ui', None)
                    if isinstance(ui_widget, QWidget) and ui_widget.isVisible():
                        ref = ui_widget
                    elif isinstance(parent, QWidget) and parent.isVisible():
                        ref = parent
            except Exception:
                ref = None

            if ref is None:
                ref = QApplication.activeWindow()

            if isinstance(ref, QWidget):
                try:
                    ref_center = ref.mapToGlobal(ref.rect().center())
                    x = ref_center.x() - (w // 2)
                    y = ref_center.y() - (h // 2)
                    self.move(max(0, x), max(0, y))
                except Exception:
                    pass
            else:
                # fallback to primary screen center
                try:
                    screen = QApplication.primaryScreen()
                    if screen:
                        center = screen.availableGeometry().center()
                        x = center.x() - (w // 2)
                        y = center.y() - (h // 2)
                        self.move(max(0, x), max(0, y))
                except Exception:
                    pass
        except Exception:
            pass
        return self.exec()
