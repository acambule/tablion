from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QDir

from localization import app_tr


@dataclass
class RestoreExecutionResult:
    restored_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class TrashRestoreService:
    def restore_paths(self, selected_paths: list[str], *, file_operations) -> RestoreExecutionResult:
        result = RestoreExecutionResult()

        for trashed in selected_paths:
            trashed_path = Path(QDir.cleanPath(str(trashed)))
            if not trashed_path.exists():
                continue

            original_path = self._read_trash_original_path(trashed_path)
            if original_path is None:
                result.errors.append(
                    app_tr("PaneController", "Wiederherstellen fehlgeschlagen: Metadaten fehlen für '{name}'.").format(
                        name=trashed_path.name
                    )
                )
                continue

            restore_target = self._build_restore_target(original_path)
            try:
                file_operations.move(trashed_path, restore_target, overwrite=False)
                info_path = self._trash_info_path_for(trashed_path)
                if info_path is not None and info_path.exists():
                    try:
                        info_path.unlink()
                    except OSError:
                        pass
                result.restored_paths.append(str(restore_target))
            except (FileExistsError, FileNotFoundError, OSError, ValueError) as error:
                result.errors.append(
                    app_tr("PaneController", "Wiederherstellen fehlgeschlagen für '{name}': {error}").format(
                        name=trashed_path.name,
                        error=error,
                    )
                )

        return result

    def _trash_info_path_for(self, trashed_path):
        trashed = Path(QDir.cleanPath(str(trashed_path))).expanduser()
        parent_dir = trashed.parent
        if parent_dir.name != "files":
            return None

        info_dir = parent_dir.parent / "info"
        return info_dir / f"{trashed.name}.trashinfo"

    def _read_trash_original_path(self, trashed_path):
        info_path = self._trash_info_path_for(trashed_path)
        if info_path is None or not info_path.exists():
            return None

        try:
            with info_path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("Path="):
                        raw_value = line.split("=", 1)[1].strip()
                        return Path(unquote(raw_value)).expanduser()
        except OSError:
            return None

        return None

    def _build_restore_target(self, original_path):
        target = Path(original_path)
        if not target.exists():
            return target

        if target.is_file():
            stem = target.stem
            suffix = target.suffix
            restored_suffix = app_tr("PaneController", "Wiederhergestellt")
            candidate = target.with_name(f"{stem} - {restored_suffix}{suffix}")
            counter = 2
            while candidate.exists():
                candidate = target.with_name(f"{stem} - {restored_suffix} {counter}{suffix}")
                counter += 1
            return candidate

        restored_suffix = app_tr("PaneController", "Wiederhergestellt")
        candidate = target.with_name(f"{target.name} - {restored_suffix}")
        counter = 2
        while candidate.exists():
            candidate = target.with_name(f"{target.name} - {restored_suffix} {counter}")
            counter += 1
        return candidate
