import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator, Qt
from PySide6.QtWidgets import QMessageBox, QWidget


_active_language_code = "de"


def _resolve_locale_code(language_preference: str | None) -> str:
    pref = str(language_preference or "system").strip().lower()
    if pref in {"de", "de_de"}:
        return "de_DE"
    if pref in {"en", "en_us", "en_gb"}:
        return "en_US"

    system_name = QLocale.system().name().lower()
    if system_name.startswith("en"):
        return "en_US"
    return "de_DE"


def current_language_code() -> str:
    return _active_language_code


def app_tr(context: str, source_text: str) -> str:
    return QCoreApplication.translate(context, source_text)


def setup_localization(app, locale_name="system"):
    global _active_language_code
    resolved = _resolve_locale_code(locale_name)
    locale = QLocale(resolved)
    QLocale.setDefault(locale)
    _active_language_code = "en" if resolved.lower().startswith("en") else "de"

    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translators = []

    for base_name in ("qtbase", "qt"):
        translator = QTranslator(app)
        if translator.load(locale, base_name, "_", translations_path):
            app.installTranslator(translator)
            translators.append(translator)

    app_translation = QTranslator(app)
    project_root = Path(__file__).resolve().parent.parent
    app_translation_paths = [
        project_root / "resources" / "translations",
        Path(sys.prefix) / "resources" / "translations",
        Path(__file__).resolve().parent / "translations",
    ]
    for app_translations_path in app_translation_paths:
        if app_translation.load(locale, "tablion", "_", str(app_translations_path)):
            app.installTranslator(app_translation)
            translators.append(app_translation)
            break

    app._qt_translators = translators
    return bool(translators)


def apply_localization(app, locale_name="system"):
    existing = getattr(app, "_qt_translators", [])
    for translator in existing:
        try:
            app.removeTranslator(translator)
        except Exception:
            continue
    app._qt_translators = []
    return setup_localization(app, locale_name)


def ask_yes_no(parent, title, text, default_no=True):
    dialog = QMessageBox()
    dialog.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
    if isinstance(parent, QWidget):
        dialog.setParent(parent, dialog.windowFlags())
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
    else:
        dialog.setWindowModality(Qt.WindowModality.ApplicationModal)

    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setWindowTitle(title)
    dialog.setText(text)

    dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    yes_button = dialog.button(QMessageBox.StandardButton.Yes)
    no_button = dialog.button(QMessageBox.StandardButton.No)
    if yes_button is not None:
        yes_button.setText("Yes" if _active_language_code == "en" else "Ja")
    if no_button is not None:
        no_button.setText("No" if _active_language_code == "en" else "Nein")

    if default_no:
        dialog.setDefaultButton(no_button)
        dialog.setEscapeButton(no_button)
    else:
        dialog.setDefaultButton(yes_button)
        dialog.setEscapeButton(no_button)

    result = dialog.exec()
    return result == QMessageBox.StandardButton.Yes
