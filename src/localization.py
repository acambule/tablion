from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QMessageBox


def setup_localization(app, locale_name="de_DE"):
    locale = QLocale(locale_name)
    QLocale.setDefault(locale)

    translations_path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    translators = []

    for base_name in ("qtbase", "qt"):
        translator = QTranslator(app)
        if translator.load(locale, base_name, "_", translations_path):
            app.installTranslator(translator)
            translators.append(translator)

    app._qt_translators = translators
    return bool(translators)


def ask_yes_no(parent, title, text, default_no=True):
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setWindowTitle(title)
    dialog.setText(text)

    yes_button = dialog.addButton("Ja", QMessageBox.ButtonRole.YesRole)
    no_button = dialog.addButton("Nein", QMessageBox.ButtonRole.NoRole)

    if default_no:
        dialog.setDefaultButton(no_button)
        dialog.setEscapeButton(no_button)
    else:
        dialog.setDefaultButton(yes_button)
        dialog.setEscapeButton(no_button)

    dialog.exec()
    return dialog.clickedButton() == yes_button
