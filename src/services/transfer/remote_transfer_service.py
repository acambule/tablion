from __future__ import annotations

from pathlib import Path

from domain.filesystem import PaneLocation


class RemoteTransferService:
    def transfer_local_to_remote(
        self,
        *,
        remote_drive_controller,
        file_operations,
        source_paths: list[str],
        destination: PaneLocation,
        move: bool = False,
    ):
        uploaded = remote_drive_controller.upload_local_paths(source_paths, destination)
        if move:
            for source_path in source_paths:
                path = Path(source_path).expanduser()
                if not path.exists():
                    continue
                file_operations.delete(path, permanent=True)
        return uploaded

    def transfer_remote_to_local(
        self,
        *,
        remote_drive_controller,
        locations: list[PaneLocation],
        destination_directory: str | Path,
        move: bool = False,
    ):
        return remote_drive_controller.transfer_items_to_local(
            locations,
            destination_directory,
            move=move,
        )

    def transfer_remote_to_remote(
        self,
        *,
        remote_drive_controller,
        locations: list[PaneLocation],
        destination: PaneLocation,
        move: bool = False,
    ):
        return remote_drive_controller.transfer_items_to_remote(
            locations,
            destination,
            move=move,
        )
