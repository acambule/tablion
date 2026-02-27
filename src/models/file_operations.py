from __future__ import annotations

import importlib
import shutil
from pathlib import Path


class FileOperations:
    def _to_path(self, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    def _resolve_destination(self, source: Path, destination: Path) -> Path:
        if destination.exists() and destination.is_dir():
            return destination / source.name
        return destination

    def copy(self, source: str | Path, destination: str | Path, overwrite: bool = False) -> Path:
        source_path = self._to_path(source)
        destination_path = self._to_path(destination)

        if not source_path.exists():
            raise FileNotFoundError(f"Quelle nicht gefunden: {source_path}")

        target_path = self._resolve_destination(source_path, destination_path)

        if target_path.exists():
            if not overwrite:
                raise FileExistsError(f"Ziel existiert bereits: {target_path}")
            self.delete(target_path, permanent=True)

        target_path.parent.mkdir(parents=True, exist_ok=True)

        if source_path.is_dir():
            shutil.copytree(source_path, target_path)
        else:
            shutil.copy2(source_path, target_path)

        return target_path

    def move(self, source: str | Path, destination: str | Path, overwrite: bool = False) -> Path:
        source_path = self._to_path(source)
        destination_path = self._to_path(destination)

        if not source_path.exists():
            raise FileNotFoundError(f"Quelle nicht gefunden: {source_path}")

        target_path = self._resolve_destination(source_path, destination_path)

        if target_path.exists():
            if not overwrite:
                raise FileExistsError(f"Ziel existiert bereits: {target_path}")
            self.delete(target_path, permanent=True)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(target_path))
        return target_path

    def delete(self, target: str | Path, permanent: bool = False) -> None:
        target_path = self._to_path(target)

        if not target_path.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {target_path}")

        if not permanent:
            try:
                send2trash_module = importlib.import_module("send2trash")
            except ModuleNotFoundError as error:
                raise RuntimeError("Papierkorb-Funktion ist nicht verfügbar (send2trash fehlt).") from error

            send2trash_module.send2trash(str(target_path))
            return

        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    def rename(self, target: str | Path, new_name: str, overwrite: bool = False) -> Path:
        target_path = self._to_path(target)

        if not target_path.exists():
            raise FileNotFoundError(f"Pfad nicht gefunden: {target_path}")

        if not new_name or new_name.strip() == "":
            raise ValueError("Neuer Name darf nicht leer sein")

        if "/" in new_name or "\\" in new_name:
            raise ValueError("new_name darf keinen Pfad enthalten")

        destination_path = target_path.with_name(new_name)

        if destination_path.exists():
            if not overwrite:
                raise FileExistsError(f"Ziel existiert bereits: {destination_path}")
            self.delete(destination_path, permanent=True)

        target_path.rename(destination_path)
        return destination_path
