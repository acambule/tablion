from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


LocationKind = Literal["local", "remote"]


@dataclass(frozen=True)
class PaneLocation:
    kind: LocationKind
    path: str
    remote_id: str | None = None

    @property
    def is_local(self) -> bool:
        return self.kind == "local"

    @property
    def is_remote(self) -> bool:
        return self.kind == "remote"
