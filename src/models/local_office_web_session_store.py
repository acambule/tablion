from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class LocalOfficeWebSession:
    id: str
    local_path: str
    connection_id: str
    remote_path: str
    web_url: str
    created_at: float
    last_opened_at: float
    local_mtime_at_opened: float
    remote_modified_at: float
    last_prompted_remote_modified_at: float


class LocalOfficeWebSessionStore:
    def __init__(self, storage_path: Path):
        self.storage_path = Path(storage_path)
        self._sessions: list[LocalOfficeWebSession] = []
        self.load()

    @property
    def sessions(self) -> list[LocalOfficeWebSession]:
        return [LocalOfficeWebSession(**asdict(item)) for item in self._sessions]

    def find_session(self, *, local_path: str, connection_id: str) -> LocalOfficeWebSession | None:
        normalized_local_path = str(local_path or "").strip()
        normalized_connection_id = str(connection_id or "").strip()
        if not normalized_local_path or not normalized_connection_id:
            return None
        for item in self._sessions:
            if item.local_path == normalized_local_path and item.connection_id == normalized_connection_id:
                return LocalOfficeWebSession(**asdict(item))
        return None

    def load(self) -> None:
        if not self.storage_path.exists():
            return
        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return
        raw_sessions = payload.get("sessions", [])
        if not isinstance(raw_sessions, list):
            return
        loaded: list[LocalOfficeWebSession] = []
        for item in raw_sessions:
            normalized = self._normalize_session(item)
            if normalized is not None:
                loaded.append(normalized)
        self._sessions = loaded

    def save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "sessions": [asdict(item) for item in self._sessions],
        }
        self.storage_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add_session(
        self,
        *,
        local_path: str,
        connection_id: str,
        remote_path: str,
        web_url: str,
        local_mtime_at_opened: float = 0.0,
        remote_modified_at: float = 0.0,
    ) -> LocalOfficeWebSession:
        now = time.time()
        normalized_local_path = str(local_path or "").strip()
        normalized_connection_id = str(connection_id or "").strip()
        normalized_remote_path = str(remote_path or "").strip()
        self._sessions = [
            item
            for item in self._sessions
            if not (
                item.local_path == normalized_local_path
                and item.connection_id == normalized_connection_id
            )
            and not (
                item.connection_id == normalized_connection_id
                and item.remote_path == normalized_remote_path
            )
        ]
        session = LocalOfficeWebSession(
            id=f"office-web-{uuid.uuid4().hex}",
            local_path=normalized_local_path,
            connection_id=normalized_connection_id,
            remote_path=normalized_remote_path,
            web_url=str(web_url or "").strip(),
            created_at=now,
            last_opened_at=now,
            local_mtime_at_opened=float(local_mtime_at_opened or 0.0),
            remote_modified_at=float(remote_modified_at or 0.0),
            last_prompted_remote_modified_at=0.0,
        )
        self._sessions.append(session)
        self.save()
        return LocalOfficeWebSession(**asdict(session))

    def update_session(self, session_id: str, **changes) -> LocalOfficeWebSession | None:
        key = str(session_id or "").strip()
        if not key:
            return None
        updated = False
        for index, item in enumerate(self._sessions):
            if item.id != key:
                continue
            payload = asdict(item)
            payload.update(changes)
            normalized = self._normalize_session(payload)
            if normalized is None:
                return None
            self._sessions[index] = normalized
            updated = True
            break
        if not updated:
            return None
        self.save()
        for item in self._sessions:
            if item.id == key:
                return LocalOfficeWebSession(**asdict(item))
        return None

    def remove_session(self, session_id: str) -> bool:
        key = str(session_id or "").strip()
        if not key:
            return False
        original_len = len(self._sessions)
        self._sessions = [item for item in self._sessions if item.id != key]
        changed = len(self._sessions) != original_len
        if changed:
            self.save()
        return changed

    def stale_sessions(self, *, older_than_seconds: float) -> list[LocalOfficeWebSession]:
        cutoff = time.time() - max(0.0, float(older_than_seconds or 0.0))
        return [
            LocalOfficeWebSession(**asdict(item))
            for item in self._sessions
            if float(item.last_opened_at or item.created_at or 0.0) <= cutoff
        ]

    def _normalize_session(self, value) -> LocalOfficeWebSession | None:
        if isinstance(value, LocalOfficeWebSession):
            return LocalOfficeWebSession(**asdict(value))
        if not isinstance(value, dict):
            return None
        local_path = str(value.get("local_path") or "").strip()
        connection_id = str(value.get("connection_id") or "").strip()
        remote_path = str(value.get("remote_path") or "").strip()
        web_url = str(value.get("web_url") or "").strip()
        if not local_path or not connection_id or not remote_path or not web_url:
            return None
        try:
            created_at = float(value.get("created_at") or 0.0)
        except (TypeError, ValueError):
            created_at = 0.0
        try:
            last_opened_at = float(value.get("last_opened_at") or created_at or 0.0)
        except (TypeError, ValueError):
            last_opened_at = created_at
        try:
            local_mtime_at_opened = float(value.get("local_mtime_at_opened") or 0.0)
        except (TypeError, ValueError):
            local_mtime_at_opened = 0.0
        try:
            remote_modified_at = float(value.get("remote_modified_at") or 0.0)
        except (TypeError, ValueError):
            remote_modified_at = 0.0
        try:
            last_prompted_remote_modified_at = float(value.get("last_prompted_remote_modified_at") or 0.0)
        except (TypeError, ValueError):
            last_prompted_remote_modified_at = 0.0
        return LocalOfficeWebSession(
            id=str(value.get("id") or f"office-web-{uuid.uuid4().hex}").strip(),
            local_path=local_path,
            connection_id=connection_id,
            remote_path=remote_path,
            web_url=web_url,
            created_at=created_at or time.time(),
            last_opened_at=last_opened_at or created_at or time.time(),
            local_mtime_at_opened=local_mtime_at_opened,
            remote_modified_at=remote_modified_at,
            last_prompted_remote_modified_at=last_prompted_remote_modified_at,
        )
