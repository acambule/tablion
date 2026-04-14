from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from configparser import ConfigParser
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QMimeDatabase
from PySide6.QtGui import QIcon


@dataclass(frozen=True)
class DesktopApplication:
    desktop_id: str
    display_name: str
    exec_line: str
    mime_types: tuple[str, ...]
    icon_name: str | None = None
    desktop_file_path: str | None = None

    def icon(self) -> QIcon:
        if self.icon_name:
            icon = QIcon.fromTheme(self.icon_name)
            if not icon.isNull():
                return icon
        return QIcon.fromTheme("application-x-executable")


def _localized_name(values: dict[str, str]) -> str | None:
    locale_name = (os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").split(".")[0].strip()
    candidates = []
    if locale_name:
        candidates.append(locale_name)
        if "_" in locale_name:
            candidates.append(locale_name.split("_", 1)[0])
    candidates.extend(["", "en_US", "en", "de_DE", "de"])

    for candidate in candidates:
        key = f"Name[{candidate}]" if candidate else "Name"
        value = values.get(key)
        if value:
            return value
    return None


def _desktop_application_dirs() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
    dirs = [data_home / "applications"]

    data_dirs_env = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for value in data_dirs_env.split(":"):
        candidate = Path(value).expanduser()
        if str(candidate):
            dirs.append(candidate / "applications")

    dirs.extend(
        [
            Path.home() / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications"),
        ]
    )

    unique_dirs: list[Path] = []
    seen: set[Path] = set()
    for candidate in dirs:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_dirs.append(resolved)
    return unique_dirs


def _desktop_names() -> list[str]:
    raw = str(os.environ.get("XDG_CURRENT_DESKTOP") or "").strip()
    if not raw:
        return []
    names: list[str] = []
    for part in raw.replace(";", ":").split(":"):
        value = part.strip().lower()
        if value and value not in names:
            names.append(value)
    return names


def _mimeapps_search_paths() -> list[Path]:
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    data_home = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))

    config_dirs = [config_home]
    data_dirs = [data_home]

    data_dirs_env = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    for value in data_dirs_env.split(":"):
        candidate = Path(value).expanduser()
        if str(candidate):
            data_dirs.append(candidate)

    config_dirs_env = os.environ.get("XDG_CONFIG_DIRS") or "/etc/xdg"
    for value in config_dirs_env.split(":"):
        candidate = Path(value).expanduser()
        if str(candidate):
            config_dirs.append(candidate)

    desktop_names = _desktop_names()
    candidates: list[Path] = []

    for base in config_dirs:
        for desktop_name in desktop_names:
            candidates.append(base / f"{desktop_name}-mimeapps.list")
        candidates.append(base / "mimeapps.list")

    for base in data_dirs:
        app_dir = base / "applications"
        for desktop_name in desktop_names:
            candidates.append(app_dir / f"{desktop_name}-mimeapps.list")
        candidates.append(app_dir / "mimeapps.list")

    unique_paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_paths.append(resolved)
    return unique_paths


def _parse_desktop_id_list(value: str | None) -> list[str]:
    if not value:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for part in value.split(";"):
        desktop_id = part.strip()
        if not desktop_id or desktop_id in seen:
            continue
        seen.add(desktop_id)
        result.append(desktop_id)
    return result


@lru_cache(maxsize=1)
def _mimeapps_preferences() -> dict[str, dict[str, list[str]]]:
    defaults: dict[str, list[str]] = {}
    added: dict[str, list[str]] = {}
    removed: dict[str, list[str]] = {}

    for mimeapps_path in reversed(_mimeapps_search_paths()):
        if not mimeapps_path.exists():
            continue
        parser = ConfigParser(interpolation=None, strict=False)
        parser.optionxform = str
        try:
            parser.read(mimeapps_path, encoding="utf-8")
        except Exception:
            continue

        for section_name, target in (
            ("Default Applications", defaults),
            ("Added Associations", added),
            ("Removed Associations", removed),
        ):
            if not parser.has_section(section_name):
                continue
            for mime_type, raw_value in parser.items(section_name):
                desktop_ids = _parse_desktop_id_list(raw_value)
                if desktop_ids:
                    target[mime_type] = desktop_ids

    return {
        "defaults": defaults,
        "added": added,
        "removed": removed,
    }


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _parse_desktop_entry(desktop_path: Path, base_dir: Path) -> DesktopApplication | None:
    try:
        lines = desktop_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None

    in_entry = False
    values: dict[str, str] = {}
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            in_entry = line == "[Desktop Entry]"
            continue
        if not in_entry or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

    if values.get("Type") != "Application":
        return None
    if _parse_bool(values.get("Hidden")):
        return None
    if _parse_bool(values.get("Terminal")):
        return None

    exec_line = values.get("Exec")
    display_name = _localized_name(values)
    if not exec_line or not display_name:
        return None

    try_exec = values.get("TryExec")
    if try_exec:
        token = shlex.split(try_exec)[0] if try_exec.strip() else try_exec
        if token and shutil.which(token) is None and not Path(token).exists():
            return None

    mime_types = tuple(
        value.strip()
        for value in values.get("MimeType", "").split(";")
        if value.strip()
    )
    if not mime_types:
        return None

    try:
        desktop_id = desktop_path.relative_to(base_dir).as_posix()
    except ValueError:
        desktop_id = desktop_path.name

    return DesktopApplication(
        desktop_id=desktop_id,
        display_name=display_name,
        exec_line=exec_line,
        mime_types=mime_types,
        icon_name=values.get("Icon") or None,
        desktop_file_path=str(desktop_path),
    )


@lru_cache(maxsize=1)
def _desktop_applications() -> dict[str, DesktopApplication]:
    applications: dict[str, DesktopApplication] = {}
    for base_dir in _desktop_application_dirs():
        if not base_dir.exists():
            continue
        for desktop_path in sorted(base_dir.rglob("*.desktop")):
            parsed = _parse_desktop_entry(desktop_path, base_dir)
            if parsed is None:
                continue
            applications.setdefault(parsed.desktop_id, parsed)
    return applications


def _mime_types_for_path(path: str | Path) -> list[str]:
    target = Path(path).expanduser()
    if target.is_dir():
        return ["inode/directory"]
    mime_db = QMimeDatabase()
    mime_type = mime_db.mimeTypeForFile(str(target), QMimeDatabase.MatchMode.MatchDefault)
    collected: list[str] = []
    pending = [mime_type]
    seen: set[str] = set()

    while pending:
        current = pending.pop(0)
        current_name = current.name()
        if not current_name or current_name in seen:
            continue
        seen.add(current_name)
        collected.append(current_name)
        for parent_name in current.parentMimeTypes():
            parent_type = mime_db.mimeTypeForName(parent_name)
            if parent_type.isValid():
                pending.append(parent_type)

    return collected or ["application/octet-stream"]


def _default_desktop_id_for_mime(mime_type: str) -> str | None:
    if shutil.which("xdg-mime") is None:
        return None
    try:
        proc = subprocess.run(
            ["xdg-mime", "query", "default", mime_type],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None

    value = (proc.stdout or "").strip()
    return value or None


def set_default_application_for_mime(desktop_id: str, mime_type: str) -> bool:
    if shutil.which("xdg-mime") is None:
        return False
    try:
        proc = subprocess.run(
            ["xdg-mime", "default", desktop_id, mime_type],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return proc.returncode == 0


def applications_for_path(path: str | Path) -> list[DesktopApplication]:
    mime_types = _mime_types_for_path(path)
    all_applications = _desktop_applications()
    preferences = _mimeapps_preferences()

    matching_applications = [
        app for app in all_applications.values()
        if any(mime_type in app.mime_types for mime_type in mime_types)
    ]
    matching_ids = {app.desktop_id for app in matching_applications}

    removed_ids: set[str] = set()
    preferred_ids: list[str] = []
    seen_preferred: set[str] = set()
    default_desktop_id = None

    for mime_type in mime_types:
        for desktop_id in preferences["removed"].get(mime_type, []):
            removed_ids.add(desktop_id)

        preferred_for_mime = preferences["defaults"].get(mime_type, [])
        if preferred_for_mime and default_desktop_id is None:
            default_desktop_id = preferred_for_mime[0]
        for desktop_id in preferred_for_mime:
            if desktop_id not in seen_preferred:
                seen_preferred.add(desktop_id)
                preferred_ids.append(desktop_id)

        for desktop_id in preferences["added"].get(mime_type, []):
            if desktop_id not in seen_preferred:
                seen_preferred.add(desktop_id)
                preferred_ids.append(desktop_id)

    if default_desktop_id is None:
        for mime_type in mime_types:
            default_desktop_id = _default_desktop_id_for_mime(mime_type)
            if default_desktop_id:
                break
        if default_desktop_id and default_desktop_id not in seen_preferred:
            preferred_ids.insert(0, default_desktop_id)

    applications: dict[str, DesktopApplication] = {}
    for desktop_id in preferred_ids:
        application = all_applications.get(desktop_id)
        if application is None or desktop_id in removed_ids:
            continue
        applications.setdefault(desktop_id, application)

    for application in matching_applications:
        if application.desktop_id in removed_ids:
            continue
        applications.setdefault(application.desktop_id, application)

    all_applications = _desktop_applications()
    if default_desktop_id and default_desktop_id in all_applications:
        applications.setdefault(default_desktop_id, all_applications[default_desktop_id])
    sorted_applications = list(applications.values())
    sorted_applications.sort(
        key=lambda app: (
            0 if default_desktop_id and app.desktop_id == default_desktop_id else 1,
            preferred_ids.index(app.desktop_id) if app.desktop_id in preferred_ids else len(preferred_ids),
            app.display_name.casefold(),
        )
    )
    return sorted_applications


def default_application_for_path(path: str | Path) -> DesktopApplication | None:
    mime_types = _mime_types_for_path(path)
    applications = _desktop_applications()
    preferences = _mimeapps_preferences()
    for mime_type in mime_types:
        preferred = preferences["defaults"].get(mime_type, [])
        if preferred:
            desktop_id = preferred[0]
            if desktop_id in applications:
                return applications[desktop_id]
        desktop_id = _default_desktop_id_for_mime(mime_type)
        if desktop_id and desktop_id in applications:
            return applications[desktop_id]
    return None


def primary_mime_type_for_path(path: str | Path) -> str:
    return _mime_types_for_path(path)[0]


def _expand_exec_tokens(application: DesktopApplication, target: Path) -> tuple[str, list[str]] | None:
    try:
        tokens = shlex.split(application.exec_line)
    except ValueError:
        return None
    if not tokens:
        return None

    expanded: list[str] = []
    target_local = str(target)
    target_uri = target.as_uri()
    placeholder_used = False

    for token in tokens:
        if token == "%f":
            expanded.append(target_local)
            placeholder_used = True
            continue
        if token == "%u":
            expanded.append(target_uri)
            placeholder_used = True
            continue
        if token in {"%F", "%U"}:
            expanded.append(target_local if token == "%F" else target_uri)
            placeholder_used = True
            continue
        if token == "%i":
            continue
        if token == "%c":
            expanded.append(application.display_name)
            continue
        if token == "%k":
            if application.desktop_file_path:
                expanded.append(application.desktop_file_path)
            continue
        if "%" in token:
            cleaned = token.replace("%%", "%")
            for placeholder in ("%d", "%D", "%n", "%N", "%v", "%m"):
                cleaned = cleaned.replace(placeholder, "")
            if "%f" in cleaned or "%F" in cleaned:
                cleaned = cleaned.replace("%f", target_local).replace("%F", target_local)
                placeholder_used = True
            if "%u" in cleaned or "%U" in cleaned:
                cleaned = cleaned.replace("%u", target_uri).replace("%U", target_uri)
                placeholder_used = True
            if cleaned:
                expanded.append(cleaned)
            continue
        expanded.append(token)

    if not expanded:
        return None
    if not placeholder_used:
        expanded.append(target_local)

    program, *args = expanded
    return program, args


def launch_with_application(application: DesktopApplication, target: str | Path) -> bool:
    from PySide6.QtCore import QProcess

    target_path = Path(target).expanduser().resolve()
    expanded = _expand_exec_tokens(application, target_path)
    if expanded is None:
        return False
    program, args = expanded
    return QProcess.startDetached(program, args)
