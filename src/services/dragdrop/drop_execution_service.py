from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt


class DropExecutionService:
    def __init__(self, drop_service):
        self._drop_service = drop_service

    def execute_paste(
        self,
        *,
        payload,
        current_location,
        target_directory,
        paste_local_to_remote,
        paste_remote_to_local,
        paste_remote_to_remote,
        start_local_file_operation,
        copy_paths_to_directory,
        on_local_cut_to_remote_unavailable,
    ) -> bool:
        if payload.is_empty:
            return False

        if current_location is not None and current_location.is_remote:
            if payload.has_remote_locations:
                return paste_remote_to_remote(
                    payload.remote_locations,
                    target_directory,
                    move=payload.operation == "cut",
                    clear_clipboard_on_success=True,
                )
            if payload.operation == "cut":
                on_local_cut_to_remote_unavailable()
                return False
            return paste_local_to_remote(payload.local_paths, target_directory)

        if payload.has_remote_locations:
            return paste_remote_to_local(
                payload.remote_locations,
                target_directory,
                move=payload.operation == "cut",
                clear_clipboard_on_success=payload.operation == "cut",
            )

        if payload.operation == "cut":
            return start_local_file_operation(
                payload.local_paths,
                target_directory,
                "move",
                clear_clipboard_on_success=True,
            )
        return copy_paths_to_directory(payload.local_paths, target_directory)

    def execute_drop(
        self,
        *,
        context,
        current_location,
        drop_action,
        paste_local_to_remote,
        paste_remote_to_local,
        paste_remote_to_remote,
        copy_paths_to_directory,
        move_paths_to_directory,
        link_paths_to_directory,
        ark_callback,
    ) -> bool:
        payload = context.payload
        if current_location is not None and current_location.is_remote:
            if payload.has_ark_reference:
                return False
            if payload.has_remote_locations:
                return paste_remote_to_remote(
                    payload.remote_locations,
                    context.target_dir,
                    move=drop_action == Qt.DropAction.MoveAction,
                )
            local_source_paths = [path for path in payload.local_paths if Path(path).exists()]
            if not local_source_paths:
                return False
            return paste_local_to_remote(local_source_paths, context.target_dir)

        if payload.has_remote_locations:
            return paste_remote_to_local(
                payload.remote_locations,
                context.target_dir,
                move=drop_action == Qt.DropAction.MoveAction,
            )

        return self._drop_service.handle_tree_drop(
            source_paths=payload.local_paths,
            target_dir=context.target_dir,
            drop_action=drop_action,
            ark_reference=payload.ark_reference,
            copy_callback=copy_paths_to_directory,
            move_callback=move_paths_to_directory,
            link_callback=link_paths_to_directory,
            ark_callback=ark_callback,
        )
