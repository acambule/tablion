from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QDir, Qt


@dataclass(frozen=True)
class DropContext:
    source_paths: list[str]
    target_dir: str


class DropService:
    def resolve_drop_context(
        self,
        mime_data,
        *,
        pos,
        source_widget=None,
        source_view=None,
        extract_paths_from_mime: Callable,
        extract_paths_from_drag_source: Callable,
        resolve_drop_target_directory: Callable,
    ) -> DropContext:
        source_paths = extract_paths_from_mime(mime_data)
        if not source_paths:
            source_paths = extract_paths_from_drag_source(source_widget)
        target_dir = resolve_drop_target_directory(pos, source_view=source_view)
        return DropContext(source_paths=source_paths, target_dir=target_dir)

    def extract_ark_drop_reference(self, mime_data, *, service_mime: str, path_mime: str, logger: Callable[[str], None] | None = None):
        if mime_data is None:
            return None
        if not mime_data.hasFormat(service_mime) or not mime_data.hasFormat(path_mime):
            return None

        service = bytes(mime_data.data(service_mime)).decode("utf-8", errors="ignore").strip()
        object_path = bytes(mime_data.data(path_mime)).decode("utf-8", errors="ignore").strip()
        if not service or not object_path:
            return None
        if logger is not None:
            logger(f"DND Ark reference: service={service!r} path={object_path!r}")
        return service, object_path

    def can_accept_tree_drop(self, *, source_paths: list[str], target_dir: str, ark_reference=None) -> bool:
        if not source_paths and ark_reference is None:
            return False
        return QDir(target_dir).exists()

    def resolve_drop_action(
        self,
        *,
        event,
        source_paths: list[str],
        target_dir: str,
        mime_data,
        source_widget,
        internal_drag_mime_type: str,
        internal_widgets: set,
    ):
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            return Qt.DropAction.LinkAction
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return Qt.DropAction.CopyAction
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return Qt.DropAction.MoveAction

        if source_paths and target_dir and self._is_internal_drop_source(
            mime_data=mime_data,
            source_widget=source_widget,
            internal_drag_mime_type=internal_drag_mime_type,
            internal_widgets=internal_widgets,
        ):
            same_fs = all(self._is_same_filesystem(source_path, target_dir) for source_path in source_paths)
            return Qt.DropAction.MoveAction if same_fs else Qt.DropAction.CopyAction

        return Qt.DropAction.CopyAction

    def handle_tree_drop(self, *, source_paths: list[str], target_dir: str, drop_action, ark_reference, copy_callback: Callable, move_callback: Callable, link_callback: Callable, ark_callback: Callable):
        if not source_paths and ark_reference is None:
            return False
        if not QDir(target_dir).exists():
            return False

        if ark_reference is not None:
            service, object_path = ark_reference
            return ark_callback(service, object_path, target_dir)
        if drop_action == Qt.DropAction.LinkAction:
            return link_callback(source_paths, target_dir)
        if drop_action == Qt.DropAction.MoveAction:
            return move_callback(source_paths, target_dir)
        return copy_callback(source_paths, target_dir)

    def _is_same_filesystem(self, source_path, target_dir):
        try:
            return Path(source_path).resolve().stat().st_dev == Path(target_dir).resolve().stat().st_dev
        except OSError:
            return False

    def _is_internal_drop_source(self, *, mime_data=None, source_widget=None, internal_drag_mime_type: str, internal_widgets: set):
        if mime_data is not None and mime_data.hasFormat(internal_drag_mime_type):
            return True
        if source_widget is None:
            return False
        return source_widget in internal_widgets
