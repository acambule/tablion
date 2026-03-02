"""Utilities to query and set the default file manager on Linux/XDG systems.

Provides safe fallbacks: `xdg-mime` -> `gio` -> direct edit of
`~/.config/mimeapps.list`.

Use from your app to check current default and to set `tablion.desktop`
as default for `inode/directory`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except Exception:
        return 1, "", ""


def get_default_file_manager() -> Optional[str]:
    """Return the desktop file name registered as default for `inode/directory`, or None.

    Tries `xdg-mime` first, then `gio mime`, then reads `~/.config/mimeapps.list`.
    """
    # xdg-mime
    if shutil.which("xdg-mime"):
        rc, out, _ = _run(["xdg-mime", "query", "default", "inode/directory"])
        if rc == 0:
            val = out.strip()
            if val:
                return val

    # gio
    if shutil.which("gio"):
        rc, out, _ = _run(["gio", "mime", "inode/directory"])
        if rc == 0 and out:
            for line in out.splitlines():
                if line.lower().startswith("default application") or line.lower().startswith("default application for"):
                    # formats differ, take last token
                    parts = line.split(":" ) if ":" in line else line.split()
                    token = parts[-1].strip()
                    if token:
                        return token

    # Fallback: parse ~/.config/mimeapps.list
    cfg = Path(os.path.expanduser("~/.config/mimeapps.list"))
    if cfg.exists():
        try:
            data = cfg.read_text(encoding="utf-8")
        except Exception:
            return None

        in_default = False
        for line in data.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("[Default Applications]"):
                in_default = True
                continue
            if line.startswith("["):
                in_default = False
                continue
            if in_default and line.startswith("inode/directory="):
                rhs = line.split("=", 1)[1].strip()
                # may be semicolon separated list
                if rhs:
                    return rhs.split(";")[0]

    return None


def set_default_file_manager(desktop_filename: str) -> bool:
    """Set `desktop_filename` as default for `inode/directory`.

    Returns True on (likely) success, False otherwise.
    Tries `xdg-mime` then `gio` then updates `~/.config/mimeapps.list`.
    """
    # xdg-mime
    if shutil.which("xdg-mime"):
        rc, _, _ = _run(["xdg-mime", "default", desktop_filename, "inode/directory"])
        if rc == 0:
            return True

    # gio
    if shutil.which("gio"):
        rc, _, _ = _run(["gio", "mime", "inode/directory", desktop_filename])
        if rc == 0:
            return True

    # Fallback: write ~/.config/mimeapps.list
    cfg_path = Path(os.path.expanduser("~/.config/mimeapps.list"))
    try:
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return False

    lines = []
    try:
        if cfg_path.exists():
            lines = cfg_path.read_text(encoding="utf-8").splitlines()
        else:
            lines = []
    except Exception:
        return False

    out_lines = []
    in_default = False
    set_done = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[Default Applications]"):
            in_default = True
            out_lines.append(line)
            continue
        if stripped.startswith("[") and in_default:
            # leaving section
            if not set_done:
                out_lines.append(f"inode/directory={desktop_filename};")
                set_done = True
            in_default = False
            out_lines.append(line)
            continue

        if in_default and stripped.startswith("inode/directory="):
            out_lines.append(f"inode/directory={desktop_filename};")
            set_done = True
            continue

        out_lines.append(line)

    if not set_done:
        # append section
        out_lines.append("")
        out_lines.append("[Default Applications]")
        out_lines.append(f"inode/directory={desktop_filename};")

    try:
        cfg_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    except Exception:
        return False

    return True


def ensure_user_desktop_file(desktop_filename: str, exec_path: Optional[str] = None) -> Path:
    """Ensure a minimal `desktop_filename` exists in `~/.local/share/applications`.

    If the file already exists, returns its Path. If not and `exec_path` is
    provided, writes a minimal desktop file and returns its Path.
    """
    apps_dir = Path(os.path.expanduser("~/.local/share/applications"))
    apps_dir.mkdir(parents=True, exist_ok=True)
    dest = apps_dir / desktop_filename
    if dest.exists():
        return dest

    if not exec_path:
        raise FileNotFoundError("desktop file missing and no exec_path provided")

    content = """[Desktop Entry]
Name=Tablion
Comment=Tablion File Manager
Exec=%s %%U
TryExec=%s
Icon=tablion
Terminal=false
Type=Application
Categories=Utility;FileManager;
MimeType=inode/directory;
""" % (exec_path, exec_path)

    dest.write_text(content, encoding="utf-8")
    return dest


def get_desktop_display_name(desktop_filename: Optional[str]) -> Optional[str]:
    """Return the human-visible Name from a desktop file, or None.

    Looks in user and system application dirs for `desktop_filename` and
    returns the `Name` or a localized `Name[...]` if present.
    """
    if not desktop_filename:
        return None

    search_dirs = [
        Path(os.path.expanduser("~/.local/share/applications")),
        Path("/usr/share/applications"),
        Path("/usr/local/share/applications"),
    ]

    for d in search_dirs:
        candidate = d / desktop_filename
        if candidate.exists():
            try:
                data = candidate.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            name = None
            localized_map: dict[str, str] = {}
            for line in data.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # localized forms: Name[de]=... or Name[de_DE]=...
                if line.startswith("Name[") and "]=" in line:
                    key = line[line.find("[") + 1 : line.find("]")]
                    val = line.split("=", 1)[1].strip()
                    localized_map[key] = val
                    continue
                if line.startswith("Name="):
                    name = line.split("=", 1)[1].strip()

            # Prefer non-localized Name= if present
            if name:
                return name

            # Otherwise try to select localized name according to environment
            if localized_map:
                # determine locale preference
                lang = os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or ""
                lang = (lang.split(".")[0] if lang else "").strip()
                # exact match
                if lang and lang in localized_map:
                    return localized_map[lang]
                # try language only (e.g., 'de' from 'de_DE')
                if lang and "_" in lang:
                    base = lang.split("_")[0]
                    if base in localized_map:
                        return localized_map[base]
                # try language-only keys
                for key in localized_map:
                    if key and key.split("_")[0] == lang.split("_")[0] if lang else False:
                        return localized_map[key]
                # fallback: return any localized value
                return next(iter(localized_map.values()))

            return None

    return None


def set_kde_meta_e_to_tablion(desktop_filename: str, exec_path: Optional[str] = None) -> bool:
    """Attempt to rebind KDE's Meta+E global shortcut to launch Tablion.

    This function is best-effort: it will backup `~/.config/kglobalshortcutsrc`,
    remove existing `Meta+E` bindings it finds, append a small `[tablion]`
    section with a `LaunchTablion` action bound to `Meta+E`, and try to reload
    kglobalaccel via `qdbus` so the change takes effect.

    Returns True if the file edits were written (and reload attempted), False
    on error. Because KDE variants vary, the operation may not succeed on all
    systems; it is recommended to fall back to instructing the user to set
    the shortcut in System Settings if needed.
    """
    cfg = Path(os.path.expanduser("~/.config/kglobalshortcutsrc"))
    if not cfg.exists():
        # nothing to do — KDE not configured or not present
        return False

    try:
        text = cfg.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False

    # Backup
    try:
        bak = cfg.with_suffix('.bak')
        cfg.write_text(text, encoding='utf-8')
        if not bak.exists():
            cfg.replace(bak)
    except Exception:
        # best-effort; continue but mark backup as failed
        pass

    lines = text.splitlines()
    new_lines = []
    changed = False

    for line in lines:
        if 'Meta+E' in line or 'meta+e' in line.lower():
            # remove the Meta+E token only (preserve other parts)
            # typical format: <something>=Meta+E,none,Action
            parts = line.split('=', 1)
            if len(parts) == 2:
                key, rhs = parts
                rhs_parts = rhs.split(',', 2)
                if rhs_parts:
                    # clear first token (the shortcut)
                    rhs_parts[0] = ''
                    new_rhs = ','.join(rhs_parts)
                    new_lines.append(f"{key}={new_rhs}")
                    changed = True
                    continue
        new_lines.append(line)

    # Append a small section to bind Meta+E to Tablion
    try:
        new_lines.append("")
        new_lines.append("[tablion]")
        # value format: "Meta+E,none,Invoke" — the third token is descriptive
        new_lines.append(f"LaunchTablion=Meta+E,none,Launch Tablion")
        changed = True
    except Exception:
        pass

    if not changed:
        return False

    try:
        cfg.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
    except Exception:
        return False

    # Try to reload kglobalaccel via qdbus if available
    if shutil.which('qdbus'):
        try:
            _run(['qdbus', 'org.kde.kglobalaccel', '/kglobalaccel', 'org.kde.KGlobalAccel.reloadConfiguration'])
        except Exception:
            pass

    return True


if __name__ == "__main__":
    # simple CLI for quick manual tests
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--get", action="store_true")
    p.add_argument("--set")
    p.add_argument("--ensure", nargs=2, metavar=("DESKTOP","EXEC"))
    args = p.parse_args()

    if args.get:
        print(get_default_file_manager())
    elif args.set:
        ok = set_default_file_manager(args.set)
        print("ok" if ok else "failed")
    elif args.ensure:
        desktop, execp = args.ensure
        pth = ensure_user_desktop_file(desktop, execp)
        print(pth)
