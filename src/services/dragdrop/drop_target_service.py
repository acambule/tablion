from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, Qt

from services.dragdrop.drag_payload import DragDropContext, DragPayload


class DropTargetService:
    def __init__(self, drop_service):
        self._drop_service = drop_service

    def resolve_context(
        self,
        mime_data,
        *,
        pos,
        source_widget=None,
        source_view=None,
        mime_codec,
        extract_paths_from_drag_source,
        resolve_drop_target_directory,
        ark_reference,
        logger=None,
    ) -> DragDropContext:
        payload = mime_codec.decode_payload(mime_data, logger=logger, ark_reference=ark_reference)
        if not payload.has_local_paths:
            fallback_paths = extract_paths_from_drag_source(source_widget)
            if fallback_paths:
                payload = DragPayload(
                    local_paths=fallback_paths,
                    remote_locations=payload.remote_locations,
                    operation=payload.operation,
                    ark_reference=payload.ark_reference,
                )
        target_dir = resolve_drop_target_directory(pos, source_view=source_view)
        return DragDropContext(payload=payload, target_dir=target_dir)

    def can_accept_drop(self, context: DragDropContext, *, current_location) -> bool:
        payload = context.payload
        if payload.is_empty:
            return False
        if current_location is not None and current_location.is_remote:
            if payload.has_ark_reference:
                return False
            if payload.has_remote_locations:
                return bool(context.target_dir)
            return any(Path(path).exists() for path in payload.local_paths)

        if payload.has_remote_locations:
            return QDir(str(context.target_dir or "")).exists()

        return self._drop_service.can_accept_tree_drop(
            source_paths=payload.local_paths,
            target_dir=context.target_dir,
            ark_reference=payload.ark_reference,
        )

    def resolve_drop_action(
        self,
        *,
        event,
        context: DragDropContext,
        current_location,
        mime_data,
        source_widget,
        internal_drag_mime_type: str,
        internal_widgets: set,
    ):
        payload = context.payload
        if current_location is not None and current_location.is_remote:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                return Qt.DropAction.MoveAction
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                return Qt.DropAction.CopyAction
            if payload.has_remote_locations and all(
                location.remote_id == current_location.remote_id for location in payload.remote_locations
            ):
                return Qt.DropAction.MoveAction
            return Qt.DropAction.CopyAction

        return self._drop_service.resolve_drop_action(
            event=event,
            source_paths=payload.local_paths,
            target_dir=context.target_dir,
            mime_data=mime_data,
            source_widget=source_widget,
            internal_drag_mime_type=internal_drag_mime_type,
            internal_widgets=internal_widgets,
        )
