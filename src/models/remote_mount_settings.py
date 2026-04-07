from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RemoteMountDefinition:
    id: str
    connection_id: str
    provider: str
    display_name: str
    icon_name: str = ""
    scope: str = "personal"
    drive_id: str = ""
    site_id: str = ""
    root_item_id: str = ""
    root_path: str = "/"
    enabled: bool = True


class RemoteMountSettings:
    def __init__(self, storage_path: Path, legacy_storage_path: Path | None = None):
        self.storage_path = storage_path
        self.legacy_storage_path = legacy_storage_path
        self._mounts: list[RemoteMountDefinition] = []
        self.load()

    @property
    def mounts(self) -> list[RemoteMountDefinition]:
        return [RemoteMountDefinition(**asdict(item)) for item in self._mounts]

    def load(self) -> None:
        payload = self._load_payload()
        if not isinstance(payload, dict):
            return
        raw_mounts = payload.get("mounts", [])
        if not isinstance(raw_mounts, list):
            return
        loaded: list[RemoteMountDefinition] = []
        for item in raw_mounts:
            normalized = self._normalize_mount(item)
            if normalized is not None:
                loaded.append(normalized)
        self._mounts = loaded

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "mounts": [asdict(item) for item in self._mounts],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def replace_all(self, mounts: list[RemoteMountDefinition | dict]) -> None:
        normalized: list[RemoteMountDefinition] = []
        for item in mounts:
            candidate = self._normalize_mount(item)
            if candidate is not None:
                normalized.append(candidate)
        self._mounts = normalized
        self.save()

    def build_navigator_entries(self, connection_settings) -> list[dict]:
        entries: list[dict] = []
        if connection_settings is None:
            return entries
        for mount in self._mounts:
            if not mount.enabled:
                continue
            connection = connection_settings.get_by_id(mount.connection_id)
            if connection is None or not connection.enabled:
                continue
            label_parts = [mount.display_name]
            if connection.account_label:
                label_parts.append(connection.account_label)
            entries.append(
                {
                    "label": mount.display_name,
                    "icon": mount.icon_name or self._provider_icon(mount.provider),
                    "tooltip": " - ".join(part for part in label_parts if part),
                    "source": "remote",
                    "remote_id": mount.id,
                    "provider": mount.provider,
                    "path": mount.root_path or "/",
                    "scope": mount.scope,
                    "connection_id": mount.connection_id,
                    "drive_id": mount.drive_id or connection.drive_id,
                    "account_label": connection.account_label,
                }
            )
        return entries

    def _load_payload(self):
        if self.storage_path.exists():
            try:
                return json.loads(self.storage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
        if self.legacy_storage_path and self.legacy_storage_path.exists():
            try:
                legacy_payload = json.loads(self.legacy_storage_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return self._migrate_legacy_payload(legacy_payload)
        return {}

    def _migrate_legacy_payload(self, payload: dict) -> dict:
        raw_remotes = payload.get("remotes", [])
        if not isinstance(raw_remotes, list):
            return {"version": 1, "mounts": []}
        mounts = []
        for item in raw_remotes:
            if not isinstance(item, dict):
                continue
            client_id = str(item.get("client_id") or "").strip()
            refresh_token = str(item.get("refresh_token") or "").strip()
            if not client_id or not refresh_token:
                continue
            remote_id = str(item.get("id") or uuid.uuid4().hex).strip()
            mounts.append(
                {
                    "id": f"mount-{remote_id}",
                    "connection_id": f"conn-{remote_id}",
                    "provider": str(item.get("provider") or "onedrive").strip().lower(),
                    "display_name": str(item.get("display_name") or "").strip() or "Remote",
                    "icon_name": str(item.get("icon") or "").strip(),
                    "scope": str(item.get("drive_scope") or "personal").strip().lower() or "personal",
                    "drive_id": str(item.get("drive_id") or "").strip(),
                    "root_path": str(item.get("root_path") or "/").strip() or "/",
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return {"version": 1, "mounts": mounts}

    def _normalize_mount(self, value) -> RemoteMountDefinition | None:
        if isinstance(value, RemoteMountDefinition):
            return RemoteMountDefinition(**asdict(value))
        if not isinstance(value, dict):
            return None

        connection_id = str(value.get("connection_id") or "").strip()
        display_name = str(value.get("display_name") or "").strip()
        if not connection_id or not display_name:
            return None

        provider = str(value.get("provider") or "onedrive").strip().lower()
        if provider not in {"onedrive", "dropbox", "gdrive"}:
            provider = "onedrive"

        scope = str(value.get("scope") or "personal").strip().lower()
        if scope not in {"personal", "sharepoint", "team"}:
            scope = "personal"

        root_path = str(value.get("root_path") or "/").strip() or "/"
        if not root_path.startswith("/"):
            root_path = f"/{root_path}"

        mount_id = str(value.get("id") or f"mount-{uuid.uuid4().hex}").strip()
        return RemoteMountDefinition(
            id=mount_id,
            connection_id=connection_id,
            provider=provider,
            display_name=display_name,
            icon_name=str(value.get("icon_name") or "").strip(),
            scope=scope,
            drive_id=str(value.get("drive_id") or "").strip(),
            site_id=str(value.get("site_id") or "").strip(),
            root_item_id=str(value.get("root_item_id") or "").strip(),
            root_path=root_path,
            enabled=bool(value.get("enabled", True)),
        )

    def _provider_icon(self, provider: str) -> str:
        mapping = {
            "onedrive": "folder-cloud",
            "dropbox": "folder-cloud",
            "gdrive": "folder-cloud",
        }
        return mapping.get(provider, "folder-cloud")
