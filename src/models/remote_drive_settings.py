from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class RemoteDriveDefinition:
    id: str
    provider: str
    display_name: str
    account_label: str = ""
    root_path: str = "/"
    drive_scope: str = "personal"
    tenant_id: str = "common"
    client_id: str = ""
    drive_id: str = ""
    access_token: str = ""
    refresh_token: str = ""
    access_token_expires_at: float = 0.0
    enabled: bool = True


class RemoteDriveSettings:
    def __init__(self, storage_path: Path):
        self.storage_path = storage_path
        self._remotes: list[RemoteDriveDefinition] = []
        self.load()

    @property
    def remotes(self) -> list[RemoteDriveDefinition]:
        return [RemoteDriveDefinition(**asdict(item)) for item in self._remotes]

    def load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        if not isinstance(payload, dict):
            return

        raw_remotes = payload.get("remotes", [])
        if not isinstance(raw_remotes, list):
            return

        loaded: list[RemoteDriveDefinition] = []
        for item in raw_remotes:
            normalized = self._normalize_remote(item)
            if normalized is not None:
                loaded.append(normalized)
        self._remotes = loaded

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "remotes": [asdict(item) for item in self._remotes],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def replace_all(self, remotes: list[RemoteDriveDefinition | dict]) -> None:
        normalized: list[RemoteDriveDefinition] = []
        for item in remotes:
            candidate = self._normalize_remote(item)
            if candidate is not None:
                normalized.append(candidate)
        self._remotes = normalized
        self.save()

    def build_navigator_entries(self) -> list[dict]:
        entries: list[dict] = []
        for remote in self._remotes:
            if not remote.enabled:
                continue
            label_parts = [remote.display_name]
            if remote.account_label:
                label_parts.append(remote.account_label)
            label = " - ".join(part for part in label_parts if part)
            entries.append(
                {
                    "label": label,
                    "icon": self._provider_icon(remote.provider),
                    "source": "remote",
                    "remote_id": remote.id,
                    "provider": remote.provider,
                    "path": remote.root_path or "/",
                    "drive_scope": remote.drive_scope,
                    "account_label": remote.account_label,
                    "client_id": remote.client_id,
                    "tenant_id": remote.tenant_id,
                }
            )
        return entries

    def _normalize_remote(self, value) -> RemoteDriveDefinition | None:
        if isinstance(value, RemoteDriveDefinition):
            return RemoteDriveDefinition(**asdict(value))
        if not isinstance(value, dict):
            return None

        provider = str(value.get("provider") or "onedrive").strip().lower()
        if provider not in {"onedrive", "dropbox", "gdrive"}:
            provider = "onedrive"

        display_name = str(value.get("display_name") or "").strip()
        if not display_name:
            return None

        remote_id = str(value.get("id") or f"remote-{uuid.uuid4().hex}").strip()
        account_label = str(value.get("account_label") or "").strip()
        root_path = str(value.get("root_path") or "/").strip() or "/"
        if not root_path.startswith("/"):
            root_path = f"/{root_path}"
        drive_scope = str(value.get("drive_scope") or "personal").strip().lower()
        if drive_scope not in {"personal", "sharepoint", "team"}:
            drive_scope = "personal"
        tenant_id = str(value.get("tenant_id") or "common").strip() or "common"
        client_id = str(value.get("client_id") or "").strip()
        drive_id = str(value.get("drive_id") or "").strip()
        access_token = str(value.get("access_token") or "").strip()
        refresh_token = str(value.get("refresh_token") or "").strip()
        try:
            access_token_expires_at = float(value.get("access_token_expires_at") or 0.0)
        except (TypeError, ValueError):
            access_token_expires_at = 0.0

        if not client_id or not refresh_token:
            return None

        return RemoteDriveDefinition(
            id=remote_id,
            provider=provider,
            display_name=display_name,
            account_label=account_label,
            root_path=root_path,
            drive_scope=drive_scope,
            tenant_id=tenant_id,
            client_id=client_id,
            drive_id=drive_id,
            access_token=access_token,
            refresh_token=refresh_token,
            access_token_expires_at=access_token_expires_at,
            enabled=bool(value.get("enabled", True)),
        )

    def _provider_icon(self, provider: str) -> str:
        mapping = {
            "onedrive": "folder-cloud",
            "dropbox": "folder-cloud",
            "gdrive": "folder-cloud",
        }
        return mapping.get(provider, "folder-cloud")
