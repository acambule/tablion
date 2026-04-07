from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TabState:
    title: str
    path: str
    pinned: bool = False
    view_mode: str = "details"
    icon_zoom_percent: int = 100
    history: list[str] = field(default_factory=list)
    scroll_value: int = 0
    selected_paths: list[str] = field(default_factory=list)
