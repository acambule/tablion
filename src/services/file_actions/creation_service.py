from __future__ import annotations

from pathlib import Path

from localization import app_tr


class CreationService:
    def create_folder(self, destination: str, base_name: str | None = None) -> Path | None:
        target_dir = Path(destination)
        if not target_dir.exists():
            return None

        folder_name = (base_name or app_tr("PaneController", "Neuer Ordner")).strip()
        candidate = target_dir / folder_name
        suffix = 2
        while candidate.exists():
            candidate = target_dir / f"{folder_name} {suffix}"
            suffix += 1

        try:
            candidate.mkdir(parents=False, exist_ok=False)
        except OSError:
            return None
        return candidate

    def create_file(self, destination: str, base_name: str | None = None) -> Path | None:
        target_dir = Path(destination)
        if not target_dir.exists():
            return None

        raw_name = (base_name or app_tr("PaneController", "Neue Datei.txt")).strip()
        base_stem = Path(raw_name).stem or app_tr("PaneController", "Neue Datei")
        suffix = Path(raw_name).suffix or ".txt"
        candidate = target_dir / f"{base_stem}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = target_dir / f"{base_stem} {counter}{suffix}"
            counter += 1

        try:
            candidate.touch(exist_ok=False)
        except OSError:
            return None
        return candidate
