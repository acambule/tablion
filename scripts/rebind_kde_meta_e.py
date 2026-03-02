#!/usr/bin/env python3
"""Search for Meta+E / Dolphin shortcut bindings in KDE config and rebind to Tablion.

Usage: run without args to preview changes, or with --apply to make edits.

This script is best-effort and makes backups before writing. It only edits
user config files under ~/.config and will not touch system files.
"""
from __future__ import annotations

import argparse
import shutil
import re
from pathlib import Path
from typing import List


TARGET_SHORTCUT = "Meta+E"
TABLION_GROUP = "[tablion]"
TABLION_ACTION = "LaunchTablion=Meta+E,none,Launch Tablion"


def find_config_files() -> List[Path]:
    home = Path.home()
    candidates = [
        home / ".config" / "kglobalshortcutsrc",
        home / ".config" / "khotkeysrc",
        home / ".config" / "kwinrc",
        home / ".config" / "plasma-org.kde.plasma.desktop-appletsrc",
    ]
    return [p for p in candidates if p.exists()]


def preview_changes(files: List[Path]) -> bool:
    found = False
    pattern = re.compile(re.escape(TARGET_SHORTCUT), flags=re.IGNORECASE)
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        if pattern.search(text) or "Dolphin" in text:
            found = True
            print(f"--- {f} ---")
            for i, line in enumerate(text.splitlines(), start=1):
                if pattern.search(line) or "Dolphin" in line:
                    print(f"{i}: {line}")
    return found


def apply_changes(files: List[Path]) -> bool:
    # Only modify kglobalshortcutsrc directly (if present)
    kglobal = next((f for f in files if f.name == "kglobalshortcutsrc"), None)
    changed = False
    if kglobal:
        text = kglobal.read_text(encoding="utf-8", errors="ignore")
        original = text
        # backup
        bak = kglobal.with_suffix('.bak')
        shutil.copy2(str(kglobal), str(bak))

        lines = text.splitlines()
        out_lines = []
        pattern = re.compile(r"^(?P<key>[^=]+=)(?P<sc>[^,]*)(?P<rest>,.*)?$")
        for line in lines:
            m = pattern.match(line)
            if m and (TARGET_SHORTCUT in m.group("sc") or "Dolphin" in line):
                # remove the shortcut token
                new_line = f"{m.group('key')},{m.group('rest')[1:] if m.group('rest') else ''}" if m.group('rest') else f"{m.group('key')}"
                # normalize (avoid leading commas)
                new_line = new_line.rstrip(',')
                out_lines.append(new_line)
                changed = True
            else:
                out_lines.append(line)

        # append tablion group if not present
        if TABLION_GROUP not in "\n".join(out_lines):
            out_lines.append("")
            out_lines.append(TABLION_GROUP)
            out_lines.append(TABLION_ACTION)
            changed = True

        if changed:
            kglobal.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
            # try to reload kglobalaccel
            try:
                import subprocess

                if shutil.which("qdbus"):
                    subprocess.run([
                        "qdbus",
                        "org.kde.kglobalaccel",
                        "/kglobalaccel",
                        "org.kde.KGlobalAccel.reloadConfiguration",
                    ])
            except Exception:
                pass

    else:
        print("kglobalshortcutsrc not found; no automatic edits performed.")

    return changed


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true", help="Apply changes (writes files)")
    args = p.parse_args()

    files = find_config_files()
    if not files:
        print("No KDE config files found in ~/.config; nothing to do.")
        return

    print("Found config files:")
    for f in files:
        print(" -", f)

    print("\nPreviewing occurrences of Meta+E / Dolphin:")
    found = preview_changes(files)
    if not found:
        print("No occurrences found. If Meta+E still triggers Dolphin, the binding may be stored elsewhere or provided by Plasma.")
        return

    if not args.apply:
        print("\nRun with --apply to perform safe edits (backups will be created).")
        return

    ok = apply_changes(files)
    if ok:
        print("Changes applied. A .bak file was created for modified files.")
    else:
        print("No changes made.")


if __name__ == "__main__":
    main()
