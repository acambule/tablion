from __future__ import annotations

from dataclasses import dataclass, field

from domain.filesystem import PaneLocation


@dataclass
class TabState:
    title: str
    location: PaneLocation
    pinned: bool = False
    view_mode: str = "details"
    icon_zoom_percent: int = 100
    history: list[PaneLocation] = field(default_factory=list)
    scroll_value: int = 0
    selected_paths: list[str] = field(default_factory=list)

    @property
    def path(self) -> str:
        return self.location.path

    @path.setter
    def path(self, value: str) -> None:
        self.location = PaneLocation(kind="local", path=str(value or ""))
