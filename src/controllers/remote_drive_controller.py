from __future__ import annotations

import time
from datetime import datetime
from pathlib import PurePosixPath

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
