from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RemoteConnectionDefinition:
    id: str
    provider: str
    display_name: str
    tenant_id: str = "common"
    client_id: str = ""
    account_label: str = ""
    drive_id: str = ""
    access_token: str = ""
    refresh_token: str = ""
    access_token_expires_at: float = 0.0
    enabled: bool = True


class RemoteConnectionSettings:
    def __init__(self, storage_path: Path, legacy_storage_path: Path | None = None):
        self.storage_path = storage_path
        self.legacy_storage_path = legacy_storage_path
        self._connections: list[RemoteConnectionDefinition] = []
        self.load()

    @property
    def connections(self) -> list[RemoteConnectionDefinition]:
        return [RemoteConnectionDefinition(**asdict(item)) for item in self._connections]

    def load(self) -> None:
        payload = self._load_payload()
        if not isinstance(payload, dict):
            return
        raw_connections = payload.get("connections", [])
        if not isinstance(raw_connections, list):
            return
        loaded: list[RemoteConnectionDefinition] = []
        for item in raw_connections:
            normalized = self._normalize_connection(item)
            if normalized is not None:
                loaded.append(normalized)
        self._connections = loaded

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "connections": [asdict(item) for item in self._connections],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def replace_all(self, connections: list[RemoteConnectionDefinition | dict]) -> None:
        normalized: list[RemoteConnectionDefinition] = []
        for item in connections:
            candidate = self._normalize_connection(item)
            if candidate is not None:
                normalized.append(candidate)
        self._connections = normalized
        self.save()

    def get_by_id(self, connection_id: str) -> RemoteConnectionDefinition | None:
        key = str(connection_id or "").strip()
        for item in self._connections:
            if item.id == key:
                return RemoteConnectionDefinition(**asdict(item))
        return None

    def update_tokens(
        self,
        connection_id: str,
        *,
        access_token: str,
        refresh_token: str,
        expires_at: float,
        account_label: str | None = None,
        drive_id: str | None = None,
    ) -> bool:
        key = str(connection_id or "").strip()
        updated = False
        for index, item in enumerate(self._connections):
            if item.id != key:
                continue
            self._connections[index] = RemoteConnectionDefinition(
                id=item.id,
                provider=item.provider,
                display_name=item.display_name,
                tenant_id=item.tenant_id,
                client_id=item.client_id,
                account_label=str(account_label if account_label is not None else item.account_label),
                drive_id=str(drive_id if drive_id is not None else item.drive_id),
                access_token=str(access_token or "").strip(),
                refresh_token=str(refresh_token or "").strip(),
                access_token_expires_at=float(expires_at or 0.0),
                enabled=item.enabled,
            )
            updated = True
            break
        if updated:
            self.save()
        return updated

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
            return {"version": 1, "connections": []}
        connections = []
        for item in raw_remotes:
            if not isinstance(item, dict):
                continue
            client_id = str(item.get("client_id") or "").strip()
            refresh_token = str(item.get("refresh_token") or "").strip()
            if not client_id or not refresh_token:
                continue
            remote_id = str(item.get("id") or uuid.uuid4().hex).strip()
            connections.append(
                {
                    "id": f"conn-{remote_id}",
                    "provider": str(item.get("provider") or "onedrive").strip().lower(),
                    "display_name": str(item.get("display_name") or "").strip() or str(item.get("account_label") or "").strip() or "Remote",
                    "tenant_id": str(item.get("tenant_id") or "common").strip() or "common",
                    "client_id": client_id,
                    "account_label": str(item.get("account_label") or "").strip(),
                    "drive_id": str(item.get("drive_id") or "").strip(),
                    "access_token": str(item.get("access_token") or "").strip(),
                    "refresh_token": refresh_token,
                    "access_token_expires_at": item.get("access_token_expires_at") or 0.0,
                    "enabled": bool(item.get("enabled", True)),
                }
            )
        return {"version": 1, "connections": connections}

    def _normalize_connection(self, value) -> RemoteConnectionDefinition | None:
        if isinstance(value, RemoteConnectionDefinition):
            return RemoteConnectionDefinition(**asdict(value))
        if not isinstance(value, dict):
            return None

        provider = str(value.get("provider") or "onedrive").strip().lower()
        if provider not in {"onedrive", "dropbox", "gdrive"}:
            provider = "onedrive"

        display_name = str(value.get("display_name") or "").strip()
        client_id = str(value.get("client_id") or "").strip()
        refresh_token = str(value.get("refresh_token") or "").strip()
        if not display_name or not client_id or not refresh_token:
            return None

        connection_id = str(value.get("id") or f"conn-{uuid.uuid4().hex}").strip()
        try:
            expires_at = float(value.get("access_token_expires_at") or 0.0)
        except (TypeError, ValueError):
            expires_at = 0.0

        return RemoteConnectionDefinition(
            id=connection_id,
            provider=provider,
            display_name=display_name,
            tenant_id=str(value.get("tenant_id") or "common").strip() or "common",
            client_id=client_id,
            account_label=str(value.get("account_label") or "").strip(),
            drive_id=str(value.get("drive_id") or "").strip(),
            access_token=str(value.get("access_token") or "").strip(),
            refresh_token=refresh_token,
            access_token_expires_at=expires_at,
            enabled=bool(value.get("enabled", True)),
        )
