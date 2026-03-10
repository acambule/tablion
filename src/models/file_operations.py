from __future__ import annotations

import bz2
import gzip
import importlib
import lzma
import shutil
import tarfile
import zipfile
from pathlib import Path

from localization import app_tr


class FileOperations:
    _ARCHIVE_SUFFIX_GROUPS = (
        (".tar.gz", ".tgz"),
        (".tar.bz2", ".tbz2"),
        (".tar.xz", ".txz"),
        (".tar",),
        (".zip",),
        (".gz",),
        (".bz2",),
        (".xz",),
    )
    _ARCHIVE_WRITE_FORMATS = {
        ".zip": "zip",
        ".tar": "tar",
        ".tar.gz": "gztar",
        ".tar.bz2": "bztar",
        ".tar.xz": "xztar",
    }

    def _to_path(self, value: str | Path) -> Path:
        return Path(value).expanduser().resolve()

    def _archive_suffix(self, value: str | Path) -> str | None:
        path = self._to_path(value)
        name = path.name.lower()
        for suffixes in self._ARCHIVE_SUFFIX_GROUPS:
            for suffix in suffixes:
                if name.endswith(suffix):
                    return suffix
        return None

    def is_supported_archive(self, value: str | Path) -> bool:
        return self._archive_suffix(value) is not None

    def supported_archive_write_suffixes(self) -> tuple[str, ...]:
        return tuple(self._ARCHIVE_WRITE_FORMATS.keys())

    def _resolve_destination(self, source: Path, destination: Path) -> Path:
        if destination.exists() and destination.is_dir():
            return destination / source.name
        return destination

    def copy(self, source: str | Path, destination: str | Path, overwrite: bool = False) -> Path:
        source_path = self._to_path(source)
        destination_path = self._to_path(destination)

        if not source_path.exists():
            raise FileNotFoundError(
                app_tr("FileOperations", "Quelle nicht gefunden: {path}").format(path=source_path)
            )

        target_path = self._resolve_destination(source_path, destination_path)

        if target_path.exists():
            if not overwrite:
                raise FileExistsError(
                    app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=target_path)
                )
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
            raise FileNotFoundError(
                app_tr("FileOperations", "Quelle nicht gefunden: {path}").format(path=source_path)
            )

        target_path = self._resolve_destination(source_path, destination_path)

        if target_path.exists():
            if not overwrite:
                raise FileExistsError(
                    app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=target_path)
                )
            self.delete(target_path, permanent=True)

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(target_path))
        return target_path

    def delete(self, target: str | Path, permanent: bool = False) -> None:
        target_path = self._to_path(target)

        if not target_path.exists():
            raise FileNotFoundError(
                app_tr("FileOperations", "Pfad nicht gefunden: {path}").format(path=target_path)
            )

        if not permanent:
            try:
                send2trash_module = importlib.import_module("send2trash")
            except ModuleNotFoundError as error:
                raise RuntimeError(
                    app_tr("FileOperations", "Papierkorb-Funktion ist nicht verfügbar (send2trash fehlt).")
                ) from error

            send2trash_module.send2trash(str(target_path))
            return

        if target_path.is_dir():
            shutil.rmtree(target_path)
        else:
            target_path.unlink()

    def rename(self, target: str | Path, new_name: str, overwrite: bool = False) -> Path:
        target_path = self._to_path(target)

        if not target_path.exists():
            raise FileNotFoundError(
                app_tr("FileOperations", "Pfad nicht gefunden: {path}").format(path=target_path)
            )

        if not new_name or new_name.strip() == "":
            raise ValueError(app_tr("FileOperations", "Neuer Name darf nicht leer sein"))

        if "/" in new_name or "\\" in new_name:
            raise ValueError(app_tr("FileOperations", "new_name darf keinen Pfad enthalten"))

        destination_path = target_path.with_name(new_name)

        if destination_path.exists():
            if not overwrite:
                raise FileExistsError(
                    app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=destination_path)
                )
            self.delete(destination_path, permanent=True)

        target_path.rename(destination_path)
        return destination_path

    def create_archive(self, sources: list[str | Path], archive: str | Path, overwrite: bool = False) -> Path:
        source_paths = [self._to_path(source) for source in sources]
        if not source_paths:
            raise ValueError(app_tr("FileOperations", "Keine Dateien zum Archivieren ausgewählt"))

        missing_paths = [path for path in source_paths if not path.exists()]
        if missing_paths:
            raise FileNotFoundError(
                app_tr("FileOperations", "Pfad nicht gefunden: {path}").format(path=missing_paths[0])
            )

        archive_path = self._to_path(archive)
        suffix = self._archive_suffix(archive_path)
        if suffix not in self._ARCHIVE_WRITE_FORMATS:
            raise ValueError(
                app_tr("FileOperations", "Archivformat zum Erstellen wird nicht unterstützt: {path}").format(
                    path=archive_path
                )
            )

        if archive_path.exists():
            if not overwrite:
                raise FileExistsError(
                    app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=archive_path)
                )
            self.delete(archive_path, permanent=True)

        archive_path.parent.mkdir(parents=True, exist_ok=True)

        if suffix == ".zip":
            self._create_zip_archive(source_paths, archive_path)
        else:
            self._create_tar_archive(source_paths, archive_path, self._ARCHIVE_WRITE_FORMATS[suffix])
        return archive_path

    def extract_archive(self, archive: str | Path, destination: str | Path) -> list[Path]:
        archive_path = self._to_path(archive)
        destination_path = self._to_path(destination)

        if not archive_path.exists():
            raise FileNotFoundError(
                app_tr("FileOperations", "Archiv nicht gefunden: {path}").format(path=archive_path)
            )
        if archive_path.is_dir():
            raise ValueError(
                app_tr("FileOperations", "Entpacken ist nur für Dateien möglich: {path}").format(path=archive_path)
            )

        suffix = self._archive_suffix(archive_path)
        if suffix is None:
            raise ValueError(
                app_tr("FileOperations", "Archivformat wird nicht unterstützt: {path}").format(path=archive_path)
            )

        destination_path.mkdir(parents=True, exist_ok=True)

        if suffix == ".zip":
            return self._extract_zip_archive(archive_path, destination_path)
        if suffix in {".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz", ".txz"}:
            return self._extract_tar_archive(archive_path, destination_path)
        return self._extract_single_file_archive(archive_path, destination_path, suffix)

    def _safe_target_path(self, destination: Path, member_name: str) -> Path:
        normalized_parts = [part for part in Path(member_name).parts if part not in {"", "."}]
        if not normalized_parts:
            return destination
        target_path = destination.joinpath(*normalized_parts).resolve()
        destination_root = destination.resolve()
        if target_path != destination_root and destination_root not in target_path.parents:
            raise ValueError(
                app_tr("FileOperations", "Archiv enthält einen ungültigen Pfad: {path}").format(path=member_name)
            )
        return target_path

    def _top_level_targets(self, destination: Path, member_names: list[str]) -> list[Path]:
        targets: list[Path] = []
        seen: set[Path] = set()
        for member_name in member_names:
            parts = [part for part in Path(member_name).parts if part not in {"", "."}]
            if not parts:
                continue
            top_level = destination / parts[0]
            if top_level in seen:
                continue
            seen.add(top_level)
            targets.append(top_level)
        return targets

    def _extract_zip_archive(self, archive_path: Path, destination_path: Path) -> list[Path]:
        with zipfile.ZipFile(archive_path) as archive:
            members = [info for info in archive.infolist() if info.filename and info.filename != "/"]
            if not members:
                return []

            member_names = [info.filename for info in members]
            for info in members:
                target_path = self._safe_target_path(destination_path, info.filename)
                if not info.is_dir() and target_path.exists():
                    raise FileExistsError(
                        app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=target_path)
                    )

            for info in members:
                target_path = self._safe_target_path(destination_path, info.filename)
                if info.is_dir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source_handle, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(source_handle, target_handle)

            return self._top_level_targets(destination_path, member_names)

    def _extract_tar_archive(self, archive_path: Path, destination_path: Path) -> list[Path]:
        with tarfile.open(archive_path, "r:*") as archive:
            members = [member for member in archive.getmembers() if member.name and member.name != "."]
            if not members:
                return []

            member_names = [member.name for member in members]
            for member in members:
                if member.issym() or member.islnk():
                    raise ValueError(
                        app_tr("FileOperations", "Archiv enthält unsichere Verknüpfungen: {path}").format(
                            path=member.name
                        )
                    )
                target_path = self._safe_target_path(destination_path, member.name)
                if member.isfile() and target_path.exists():
                    raise FileExistsError(
                        app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=target_path)
                    )

            for member in members:
                target_path = self._safe_target_path(destination_path, member.name)
                if member.isdir():
                    target_path.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with extracted, target_path.open("wb") as target_handle:
                    shutil.copyfileobj(extracted, target_handle)

            return self._top_level_targets(destination_path, member_names)

    def _extract_single_file_archive(self, archive_path: Path, destination_path: Path, suffix: str) -> list[Path]:
        if suffix == ".gz":
            opener = gzip.open
        elif suffix == ".bz2":
            opener = bz2.open
        elif suffix == ".xz":
            opener = lzma.open
        else:
            raise ValueError(
                app_tr("FileOperations", "Archivformat wird nicht unterstützt: {path}").format(path=archive_path)
            )

        target_path = destination_path / archive_path.name[: -len(suffix)]
        if not target_path.name:
            raise ValueError(
                app_tr("FileOperations", "Konnte Zieldatei nicht bestimmen: {path}").format(path=archive_path)
            )
        if target_path.exists():
            raise FileExistsError(
                app_tr("FileOperations", "Ziel existiert bereits: {path}").format(path=target_path)
            )

        target_path.parent.mkdir(parents=True, exist_ok=True)
        with opener(archive_path, "rb") as source_handle, target_path.open("wb") as target_handle:
            shutil.copyfileobj(source_handle, target_handle)
        return [target_path]

    def _create_zip_archive(self, source_paths: list[Path], archive_path: Path) -> None:
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source_path in source_paths:
                if source_path.is_dir():
                    archive.write(source_path, arcname=source_path.name)
                    for child in source_path.rglob("*"):
                        if child.resolve() == archive_path:
                            continue
                        archive.write(child, arcname=str(child.relative_to(source_path.parent)))
                    continue
                archive.write(source_path, arcname=source_path.name)

    def _create_tar_archive(self, source_paths: list[Path], archive_path: Path, mode_key: str) -> None:
        mode_map = {
            "tar": "w",
            "gztar": "w:gz",
            "bztar": "w:bz2",
            "xztar": "w:xz",
        }
        tar_mode = mode_map[mode_key]
        with tarfile.open(archive_path, tar_mode) as archive:
            for source_path in source_paths:
                archive.add(source_path, arcname=source_path.name, recursive=False)
                if not source_path.is_dir():
                    continue
                for child in source_path.rglob("*"):
                    if child.resolve() == archive_path:
                        continue
                    archive.add(child, arcname=str(child.relative_to(source_path.parent)), recursive=False)
