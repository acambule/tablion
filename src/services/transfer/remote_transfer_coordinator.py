from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

from domain.filesystem import PaneLocation
from localization import app_tr


@dataclass
class RemoteTransferResult:
    completed: list[object] = field(default_factory=list)
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


class RemoteTransferCoordinator:
    def __init__(self, transfer_service):
        self._transfer_service = transfer_service

    def transfer_local_to_remote(
        self,
        *,
        widget,
        remote_drive_controller,
        file_operations,
        source_paths: list[str],
        destination: PaneLocation,
        move: bool = False,
    ) -> RemoteTransferResult:
        result = RemoteTransferResult()
        sources = [Path(path).expanduser() for path in source_paths if Path(path).expanduser().exists()]
        if not sources:
            return result

        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=True),
            len(sources),
        )
        try:
            for index, source_path in enumerate(sources, start=1):
                dialog.setLabelText(self._progress_label(move, source_path.name, remote=True))
                dialog.setValue(index - 1)
                resolution, target_name = self._resolve_remote_conflict(
                    widget,
                    remote_drive_controller,
                    destination,
                    source_path.name,
                )
                if resolution == "skip":
                    result.skipped_count += 1
                    continue
                try:
                    uploaded = self._transfer_service.transfer_local_to_remote(
                        remote_drive_controller=remote_drive_controller,
                        file_operations=file_operations,
                        source_paths=[str(source_path)],
                        destination=destination,
                        move=move,
                    ) if resolution == "rename" and target_name == source_path.name else [
                        remote_drive_controller.upload_local_path(
                            source_path,
                            destination,
                            target_name=target_name,
                            overwrite=resolution == "overwrite",
                        )
                    ]
                    if move:
                        file_operations.delete(source_path, permanent=True)
                    result.completed.extend(uploaded)
                except Exception as error:
                    result.errors.append(str(error))
                dialog.setValue(index)
        finally:
            dialog.close()
            dialog.deleteLater()
        return result

    def transfer_remote_to_local(
        self,
        *,
        widget,
        remote_drive_controller,
        locations: list[PaneLocation],
        destination_directory: str,
        move: bool = False,
    ) -> RemoteTransferResult:
        result = RemoteTransferResult()
        remote_items = [location for location in locations if location.is_remote]
        if not remote_items:
            return result

        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=False),
            len(remote_items),
        )
        try:
            for index, location in enumerate(remote_items, start=1):
                source_name = PurePosixPath(str(location.path or "/")).name or location.path
                dialog.setLabelText(self._progress_label(move, source_name, remote=False))
                dialog.setValue(index - 1)
                resolution, target_name = self._resolve_local_conflict(widget, destination_directory, source_name)
                if resolution == "skip":
                    result.skipped_count += 1
                    continue
                try:
                    target = remote_drive_controller.transfer_item_to_local(
                        location,
                        destination_directory,
                        move=move,
                        target_name=target_name,
                        overwrite=resolution == "overwrite",
                    )
                    result.completed.append(target)
                except Exception as error:
                    result.errors.append(str(error))
                dialog.setValue(index)
        finally:
            dialog.close()
            dialog.deleteLater()
        return result

    def transfer_remote_to_remote(
        self,
        *,
        widget,
        remote_drive_controller,
        locations: list[PaneLocation],
        destination: PaneLocation,
        move: bool = False,
    ) -> RemoteTransferResult:
        result = RemoteTransferResult()
        remote_items = [location for location in locations if location.is_remote]
        if not remote_items:
            return result

        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=True),
            len(remote_items),
        )
        try:
            for index, location in enumerate(remote_items, start=1):
                source_name = PurePosixPath(str(location.path or "/")).name or location.path
                dialog.setLabelText(self._progress_label(move, source_name, remote=True))
                dialog.setValue(index - 1)
                resolution, target_name = self._resolve_remote_conflict(
                    widget,
                    remote_drive_controller,
                    destination,
                    source_name,
                    source_location=location,
                )
                if resolution == "skip":
                    result.skipped_count += 1
                    continue
                try:
                    changed = remote_drive_controller.transfer_item_to_remote(
                        location,
                        destination,
                        move=move,
                        target_name=target_name,
                        overwrite=resolution == "overwrite",
                    )
                    result.completed.append(changed)
                except Exception as error:
                    result.errors.append(str(error))
                dialog.setValue(index)
        finally:
            dialog.close()
            dialog.deleteLater()
        return result

    def _create_progress_dialog(self, widget, title: str, total: int) -> QProgressDialog:
        dialog = QProgressDialog(widget)
        dialog.setWindowTitle(title)
        dialog.setLabelText("")
        dialog.setRange(0, total)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setCancelButton(None)
        dialog.setValue(0)
        dialog.show()
        return dialog

    def _resolve_remote_conflict(
        self,
        widget,
        remote_drive_controller,
        destination: PaneLocation,
        desired_name: str,
        *,
        source_location: PaneLocation | None = None,
    ) -> tuple[str, str]:
        existing = self._find_remote_child(remote_drive_controller, destination, desired_name)
        if existing is None or (source_location is not None and existing.path == source_location.path and existing.remote_id == source_location.remote_id):
            return "none", desired_name

        decision = self._ask_conflict_resolution(widget, desired_name)
        if decision == "rename":
            return "rename", self._next_remote_name(remote_drive_controller, destination, desired_name)
        return decision, desired_name

    def _resolve_local_conflict(self, widget, destination_directory: str, desired_name: str) -> tuple[str, str]:
        target = Path(destination_directory).expanduser().resolve() / desired_name
        if not target.exists():
            return "none", desired_name

        decision = self._ask_conflict_resolution(widget, desired_name)
        if decision == "rename":
            return "rename", self._next_local_name(target.parent, desired_name)
        return decision, desired_name

    def _ask_conflict_resolution(self, widget, target_name: str) -> str:
        box = QMessageBox(widget)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(app_tr("PaneController", "Konflikt beim Übertragen"))
        box.setText(
            app_tr("PaneController", "Das Ziel '{name}' existiert bereits.").format(name=target_name)
        )
        overwrite_button = box.addButton(app_tr("PaneController", "Überschreiben"), QMessageBox.ButtonRole.AcceptRole)
        rename_button = box.addButton(app_tr("PaneController", "Beide behalten"), QMessageBox.ButtonRole.ActionRole)
        skip_button = box.addButton(app_tr("PaneController", "Überspringen"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(rename_button)
        box.exec()
        clicked = box.clickedButton()
        if clicked == overwrite_button:
            return "overwrite"
        if clicked == rename_button:
            return "rename"
        return "skip"

    def _find_remote_child(self, remote_drive_controller, destination: PaneLocation, desired_name: str) -> PaneLocation | None:
        target = str(desired_name or "").strip()
        if not target:
            return None
        try:
            for entry in remote_drive_controller.list_directory(destination):
                if entry.name.casefold() == target.casefold():
                    return entry.location
        except Exception:
            return None
        return None

    def _next_remote_name(self, remote_drive_controller, destination: PaneLocation, desired_name: str) -> str:
        existing_names = set()
        try:
            existing_names = {entry.name.casefold() for entry in remote_drive_controller.list_directory(destination)}
        except Exception:
            existing_names = set()
        return self._next_available_name(existing_names, desired_name)

    def _next_local_name(self, destination_directory: Path, desired_name: str) -> str:
        existing_names = {path.name.casefold() for path in destination_directory.iterdir()} if destination_directory.exists() else set()
        return self._next_available_name(existing_names, desired_name)

    def _next_available_name(self, existing_names: set[str], desired_name: str) -> str:
        clean_name = str(desired_name or "").strip() or "Element"
        if clean_name.casefold() not in existing_names:
            return clean_name
        stem = Path(clean_name).stem or clean_name
        suffix = Path(clean_name).suffix
        counter = 2
        while True:
            candidate = f"{stem} {counter}{suffix}"
            if candidate.casefold() not in existing_names:
                return candidate
            counter += 1

    def _progress_title(self, move: bool, *, remote: bool) -> str:
        if move:
            return app_tr("PaneController", "Elemente verschieben")
        if remote:
            return app_tr("PaneController", "Elemente übertragen")
        return app_tr("PaneController", "Elemente kopieren")

    def _progress_label(self, move: bool, name: str, *, remote: bool) -> str:
        if move:
            return app_tr("PaneController", "Verschiebe: {name}").format(name=name)
        if remote:
            return app_tr("PaneController", "Übertrage: {name}").format(name=name)
        return app_tr("PaneController", "Kopiere: {name}").format(name=name)
