from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path, PurePosixPath

from PySide6.QtCore import QStandardPaths

from domain.filesystem import PaneLocation
from models.remote_connection_settings import RemoteConnectionSettings
from models.remote_mount_settings import RemoteMountDefinition, RemoteMountSettings
from models.remote_file_tree_model import RemoteFileItem
from remotes.providers.onedrive_auth import OneDriveAuthError, OneDriveAuthService
from remotes.providers.onedrive_client import OneDriveClient


class RemoteDriveController:
    def __init__(self, connection_settings: RemoteConnectionSettings, mount_settings: RemoteMountSettings):
        self._connection_settings = connection_settings
        self._mount_settings = mount_settings
        self._auth_service = OneDriveAuthService()
        self._onedrive_client = OneDriveClient()

    def list_directory(self, location: PaneLocation) -> list[RemoteFileItem]:
        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        graph_path = self._join_mount_path(mount.root_path, location.path)
        raw_items = self._onedrive_client.list_children(
            access_token=connection.access_token,
            drive_id=drive_id,
            item_path=graph_path,
        )

        entries: list[RemoteFileItem] = []
        for raw_item in raw_items:
            name = str(raw_item.get("name") or "").strip()
            if not name:
                continue
            is_dir = isinstance(raw_item.get("folder"), dict)
            child_path = self._join_visible_path(location.path, name)
            modified = self._parse_datetime(raw_item.get("lastModifiedDateTime"))
            entries.append(
                RemoteFileItem(
                    name=name,
                    location=PaneLocation(kind="remote", path=child_path, remote_id=location.remote_id),
                    is_dir=is_dir,
                    size=None if is_dir else self._safe_int(raw_item.get("size")),
                    modified_at=modified,
                    web_url=str(raw_item.get("webUrl") or "").strip(),
                )
            )
        return entries

    def display_name_for_location(self, location: PaneLocation) -> str:
        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            return location.path or "/"
        if location.path in {"", "/"}:
            return mount.display_name
        return PurePosixPath(location.path).name or mount.display_name

    def get_parent_location(self, location: PaneLocation) -> PaneLocation | None:
        if not location.is_remote:
            return None
        current = PurePosixPath(location.path or "/")
        if str(current) in {".", "/"}:
            return None
        parent = str(current.parent)
        if parent in {"", "."}:
            parent = "/"
        return PaneLocation(kind="remote", path=parent, remote_id=location.remote_id)

    def list_subdirectory_targets(self, location: PaneLocation) -> list[tuple[str, PaneLocation]]:
        entries = self.list_directory(location)
        return [(entry.name, entry.location) for entry in entries if entry.is_dir]

    def rename_item(self, location: PaneLocation, new_name: str) -> PaneLocation:
        if not location.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Element übergeben.")
        target_name = str(new_name or "").strip()
        if not target_name:
            raise OneDriveAuthError("Der neue Name darf nicht leer sein.")

        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        graph_path = self._join_mount_path(mount.root_path, location.path)
        self._onedrive_client.rename_item(
            access_token=connection.access_token,
            drive_id=drive_id,
            item_path=graph_path,
            new_name=target_name,
        )

        current = PurePosixPath(location.path or "/")
        parent = current.parent if str(current.parent) not in {"", "."} else PurePosixPath("/")
        renamed_path = (parent / target_name).as_posix()
        if not renamed_path.startswith("/"):
            renamed_path = f"/{renamed_path}"
        return PaneLocation(kind="remote", path=renamed_path, remote_id=location.remote_id)

    def delete_items(self, locations: list[PaneLocation]) -> list[PaneLocation]:
        deleted: list[PaneLocation] = []
        for location in locations:
            if not location.is_remote:
                continue
            mount = self._mount_by_id(location.remote_id)
            if mount is None:
                raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
            connection = self._ensure_connection_for_mount(mount)
            drive_id = mount.drive_id or connection.drive_id
            if not drive_id:
                raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

            graph_path = self._join_mount_path(mount.root_path, location.path)
            self._onedrive_client.delete_item(
                access_token=connection.access_token,
                drive_id=drive_id,
                item_path=graph_path,
            )
            deleted.append(location)
        return deleted

    def create_folder(self, location: PaneLocation, base_name: str | None = None) -> PaneLocation:
        if not location.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Ziel übergeben.")
        folder_name = str(base_name or "Neuer Ordner").strip() or "Neuer Ordner"

        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        unique_name = self._next_available_name(location, folder_name)
        graph_path = self._join_mount_path(mount.root_path, location.path)
        self._onedrive_client.create_folder(
            access_token=connection.access_token,
            drive_id=drive_id,
            parent_path=graph_path,
            folder_name=unique_name,
        )
        child_path = self._join_visible_path(location.path, unique_name)
        return PaneLocation(kind="remote", path=child_path, remote_id=location.remote_id)

    def create_file(self, location: PaneLocation, base_name: str | None = None) -> PaneLocation:
        if not location.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Ziel übergeben.")
        file_name = str(base_name or "Neue Datei.txt").strip() or "Neue Datei.txt"

        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        unique_name = self._next_available_name(location, file_name)
        graph_parent = self._join_mount_path(mount.root_path, location.path)
        self._onedrive_client.upload_file(
            access_token=connection.access_token,
            drive_id=drive_id,
            parent_path=graph_parent,
            file_name=unique_name,
            content=b"",
        )
        child_path = self._join_visible_path(location.path, unique_name)
        return PaneLocation(kind="remote", path=child_path, remote_id=location.remote_id)

    def copy_items(self, locations: list[PaneLocation], destination: PaneLocation) -> list[PaneLocation]:
        if not destination.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Ziel übergeben.")
        destination_mount = self._mount_by_id(destination.remote_id)
        if destination_mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        destination_connection = self._ensure_connection_for_mount(destination_mount)
        destination_drive_id = destination_mount.drive_id or destination_connection.drive_id
        if not destination_drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        destination_item = self._onedrive_client.get_item(
            access_token=destination_connection.access_token,
            drive_id=destination_drive_id,
            item_path=self._join_mount_path(destination_mount.root_path, destination.path),
        )
        destination_folder_id = str(destination_item.get("id") or "").strip()
        if not destination_folder_id:
            raise OneDriveAuthError("Das Remote-Ziel konnte nicht bestimmt werden.")

        copied: list[PaneLocation] = []
        for location in locations:
            if not location.is_remote or location.remote_id != destination.remote_id:
                raise OneDriveAuthError("Kopieren zwischen unterschiedlichen Remote-Einträgen ist noch nicht verfügbar.")
            source_mount = self._mount_by_id(location.remote_id)
            if source_mount is None:
                raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
            source_connection = self._ensure_connection_for_mount(source_mount)
            source_drive_id = source_mount.drive_id or source_connection.drive_id
            if not source_drive_id:
                raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")
            source_item = self._onedrive_client.get_item(
                access_token=source_connection.access_token,
                drive_id=source_drive_id,
                item_path=self._join_mount_path(source_mount.root_path, location.path),
            )
            source_item_id = str(source_item.get("id") or "").strip()
            if not source_item_id:
                raise OneDriveAuthError("Das zu kopierende Remote-Element konnte nicht bestimmt werden.")
            self._onedrive_client.copy_item(
                access_token=source_connection.access_token,
                drive_id=source_drive_id,
                item_id=source_item_id,
                destination_folder_id=destination_folder_id,
                destination_drive_id=destination_drive_id,
            )
            copied.append(location)
        return copied

    def move_items(self, locations: list[PaneLocation], destination: PaneLocation) -> list[PaneLocation]:
        if not destination.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Ziel übergeben.")
        destination_mount = self._mount_by_id(destination.remote_id)
        if destination_mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        destination_connection = self._ensure_connection_for_mount(destination_mount)
        destination_drive_id = destination_mount.drive_id or destination_connection.drive_id
        if not destination_drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        destination_item = self._onedrive_client.get_item(
            access_token=destination_connection.access_token,
            drive_id=destination_drive_id,
            item_path=self._join_mount_path(destination_mount.root_path, destination.path),
        )
        destination_folder_id = str(destination_item.get("id") or "").strip()
        if not destination_folder_id:
            raise OneDriveAuthError("Das Remote-Ziel konnte nicht bestimmt werden.")

        moved: list[PaneLocation] = []
        for location in locations:
            if not location.is_remote or location.remote_id != destination.remote_id:
                raise OneDriveAuthError("Verschieben zwischen unterschiedlichen Remote-Einträgen ist noch nicht verfügbar.")
            source_mount = self._mount_by_id(location.remote_id)
            if source_mount is None:
                raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
            source_connection = self._ensure_connection_for_mount(source_mount)
            source_drive_id = source_mount.drive_id or source_connection.drive_id
            if not source_drive_id:
                raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")
            source_item = self._onedrive_client.get_item(
                access_token=source_connection.access_token,
                drive_id=source_drive_id,
                item_path=self._join_mount_path(source_mount.root_path, location.path),
            )
            source_item_id = str(source_item.get("id") or "").strip()
            if not source_item_id:
                raise OneDriveAuthError("Das zu verschiebende Remote-Element konnte nicht bestimmt werden.")
            self._onedrive_client.move_item(
                access_token=source_connection.access_token,
                drive_id=source_drive_id,
                item_id=source_item_id,
                destination_folder_id=destination_folder_id,
            )
            moved.append(location)
        return moved

    def upload_local_paths(self, source_paths: list[str], destination: PaneLocation) -> list[PaneLocation]:
        if not destination.is_remote:
            raise OneDriveAuthError("Es wurde kein Remote-Ziel übergeben.")
        uploaded: list[PaneLocation] = []
        for raw_source in source_paths:
            source_path = Path(raw_source)
            if not source_path.exists():
                continue
            uploaded.append(self._upload_local_path(source_path, destination))
        return uploaded

    def download_file_to_cache(self, location: PaneLocation) -> Path:
        if not location.is_remote:
            raise OneDriveAuthError("Es wurde keine Remote-Datei übergeben.")

        mount = self._mount_by_id(location.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        remote_path = str(location.path or "").strip()
        if not remote_path or remote_path == "/":
            raise OneDriveAuthError("Root kann nicht als Datei geöffnet werden.")

        graph_path = self._join_mount_path(mount.root_path, remote_path)
        file_bytes = self._onedrive_client.download_file(
            access_token=connection.access_token,
            drive_id=drive_id,
            item_path=graph_path,
        )

        cache_root = self._cache_root() / str(location.remote_id or "remote")
        relative_path = PurePosixPath(remote_path.lstrip("/"))
        target_path = cache_root.joinpath(*relative_path.parts)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(file_bytes)
        return target_path

    def _mount_by_id(self, remote_id: str | None) -> RemoteMountDefinition | None:
        key = str(remote_id or "").strip()
        if not key:
            return None
        for mount in self._mount_settings.mounts:
            if mount.id == key:
                return mount
        return None

    def _ensure_connection_for_mount(self, mount: RemoteMountDefinition):
        connection = self._connection_settings.get_by_id(mount.connection_id)
        if connection is None or not connection.enabled:
            raise OneDriveAuthError("Die zugehörige Verbindung ist nicht verfügbar.")

        if connection.provider != "onedrive":
            raise OneDriveAuthError("Aktuell wird nur OneDrive als Remote-Provider unterstützt.")

        if connection.access_token and connection.access_token_expires_at > time.time() + 30:
            return connection

        refreshed = self._auth_service.refresh_access_token(
            client_id=connection.client_id,
            tenant_id=connection.tenant_id,
            refresh_token=connection.refresh_token,
        )
        self._connection_settings.update_tokens(
            connection.id,
            access_token=refreshed.access_token,
            refresh_token=refreshed.refresh_token,
            expires_at=refreshed.expires_at,
            account_label=refreshed.account_label,
            drive_id=refreshed.drive_id,
        )
        updated = self._connection_settings.get_by_id(connection.id)
        if updated is None:
            raise OneDriveAuthError("Verbindung konnte nach Token-Aktualisierung nicht geladen werden.")
        return updated

    def _join_mount_path(self, mount_root: str, visible_path: str) -> str:
        base = PurePosixPath(str(mount_root or "/").strip() or "/")
        child = PurePosixPath(str(visible_path or "/").strip() or "/")
        parts = [part for part in base.parts if part != "/"] + [part for part in child.parts if part != "/"]
        return "/" + "/".join(parts) if parts else "/"

    def _join_visible_path(self, current_path: str, child_name: str) -> str:
        base = PurePosixPath(str(current_path or "/").strip() or "/")
        if str(base) in {".", ""}:
            base = PurePosixPath("/")
        child = (base / child_name).as_posix()
        return child if child.startswith("/") else f"/{child}"

    def _upload_local_path(self, source_path: Path, destination: PaneLocation) -> PaneLocation:
        mount = self._mount_by_id(destination.remote_id)
        if mount is None:
            raise OneDriveAuthError("Remote-Eintrag wurde nicht gefunden.")
        connection = self._ensure_connection_for_mount(mount)
        drive_id = mount.drive_id or connection.drive_id
        if not drive_id:
            raise OneDriveAuthError("Für den Remote-Eintrag ist keine Drive-ID hinterlegt.")

        target_name = self._next_available_name(destination, source_path.name)
        graph_parent = self._join_mount_path(mount.root_path, destination.path)

        if source_path.is_dir():
            self._onedrive_client.create_folder(
                access_token=connection.access_token,
                drive_id=drive_id,
                parent_path=graph_parent,
                folder_name=target_name,
            )
            new_destination = PaneLocation(
                kind="remote",
                path=self._join_visible_path(destination.path, target_name),
                remote_id=destination.remote_id,
            )
            for child in sorted(source_path.iterdir(), key=lambda item: item.name.lower()):
                self._upload_local_path(child, new_destination)
            return new_destination

        self._onedrive_client.upload_file(
            access_token=connection.access_token,
            drive_id=drive_id,
            parent_path=graph_parent,
            file_name=target_name,
            content=source_path.read_bytes(),
        )
        return PaneLocation(
            kind="remote",
            path=self._join_visible_path(destination.path, target_name),
            remote_id=destination.remote_id,
        )

    def _next_available_name(self, destination: PaneLocation, desired_name: str) -> str:
        clean_name = str(desired_name or "").strip() or "Element"
        try:
            existing_names = {
                entry.name.casefold()
                for entry in self.list_directory(destination)
            }
        except Exception:
            existing_names = set()

        if clean_name.casefold() not in existing_names:
            return clean_name

        stem = Path(clean_name).stem or clean_name
        suffix = Path(clean_name).suffix
        counter = 2
        while True:
            candidate = f"{stem} {counter}{suffix}"
            if candidate.casefold() not in existing_names:
                return candidate
            counter += 1

    def _parse_datetime(self, value) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _safe_int(self, value) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _cache_root(self) -> Path:
        cache_root = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
        base = Path(cache_root) if cache_root else (Path.home() / ".cache")
        return base / "tablion" / "remote-files"
