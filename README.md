# Tablion

<!-- Logo placeholder -->
![Tablion Logo](assets/tablion-logo.png)

**Tablion** is a Linux file manager designed for power users who need tab groups, multi‑pane views and advanced file organization features. It blends the simplicity of a traditional file browser with capabilities commonly found in developer IDEs and productivity tools.

<!-- Badges: build, license, PyPI, etc. -->
[![Build Status](https://img.shields.io/badge/build-passing-brightgreen)](#)
[![License](https://img.shields.io/badge/license-EUPL%201.2-blue)](#)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](#)

## Features

<!-- Screenshots -->
![Screenshot 1](assets/screenshots/screen1.png)
![Screenshot 2](assets/screenshots/screen2.png)

- **Tab groups**: Organize tabs into named groups, move tabs between groups, and collapse groups to reduce clutter.
- **Multi‑view**: Split a group pane into single/2‑split/4‑split layouts with synchronized navigation and focus tracking.
- **Flexible grouping behavior**: Create new groups with a default tab or clone existing tabs; configurable in settings.
- **Drag‑and‑drop support**: Internal and external DND works across Flatpak sandboxes using staging.
- **Advanced context menus**: Right‑click on tabs or tree view to perform operations such as grouping, renaming, copying, and more.
- **Rubber‑band selection** in both tree and icon view modes.
- **Breadcrumb path bar** with click‑able arrows, autocompletion, and overflow menus.
- **Session export/import & factory reset** for privacy and portability.
- **Customizable settings** including language, editor path, UI options, and group creation mode.

## Installation

Build from source or install via packaged distributions (if available).

```bash
# clone the repository
git clone https://github.com/acambule/tablion.git
cd tablion
# install dependencies (PySide6, etc.)
pip install -r requirements.txt
# run
python -m src.main
```

> _Note_: Tablion currently targets Python 3.11+ and uses PySide6 for its UI. On Flatpak, external drag‑and‑drop is supported via a staging folder under `~/Downloads/.tablion-dnd`.

## Usage

- Launch the application and use the toolbar/menu to create groups, open settings, or switch views.
- Double‑click the empty group tab bar area or use the context menu to add groups.
- Right‑click tabs or tree items for context actions.
- Access settings via the burger menu to change language, behavior, or export/import sessions.

## Development

The codebase is arranged as follows (see `documentation/files.md` for a detailed list):

- `src/main.py` – application entry point and main window logic.
- `src/controllers` – controllers for groups and panes.
- `src/widgets` – custom widgets (path bar, dialogs, group workspace).
- `src/models` – file system model, navigator data, editor settings, utilities.
- `src/ui` – Qt Designer `.ui` files for layouts.
- `src/translations` – translation files for i18n.

Run tests or start a development instance with:

```bash
python -m pytest
python -m src.main
```

## Contributing

Contributions are welcome! Please open issues for bugs or feature requests, and submit pull requests against the `main` branch.

## License

This project is licensed under the [EUPL‑1.2](LICENSE) or later. See the `LICENSE` file for details.
