from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from PySide6.QtWidgets import QCheckBox, QMessageBox, QProgressDialog
from PySide6.QtCore import Qt

from domain.filesystem import PaneLocation
from localization import app_tr


@dataclass
class RemoteTransferResult:
    completed: list[object] = field(default_factory=list)
    skipped_count: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class ConflictResolution:
    decision: str
    apply_to_all: bool = False


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

        remembered_resolution: ConflictResolution | None = None
        total_steps = sum(self._count_local_transfer_steps(path) for path in sources)
        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=True),
            total_steps,
        )
        progress_value = 0
        try:
            for source_path in sources:
                dialog.setLabelText(self._progress_label(move, source_path.name, remote=True))
                dialog.setValue(progress_value)
                resolution, target_name = self._resolve_remote_conflict(
                    widget,
                    remote_drive_controller,
                    destination,
                    source_path.name,
                    remembered_resolution=remembered_resolution,
                )
                if resolution.apply_to_all:
                    remembered_resolution = resolution
                if resolution.decision == "skip":
                    result.skipped_count += 1
                    progress_value += self._count_local_transfer_steps(source_path)
                    continue
                try:
                    if resolution.decision == "none" and target_name == source_path.name:
                        uploaded = self._transfer_service.transfer_local_to_remote(
                            remote_drive_controller=remote_drive_controller,
                            file_operations=file_operations,
                            source_paths=[str(source_path)],
                            destination=destination,
                            move=move,
                        )
                    else:
                        uploaded = [
                            remote_drive_controller.upload_local_path(
                                source_path,
                                destination,
                                target_name=target_name,
                                overwrite=resolution.decision == "overwrite",
                            )
                        ]
                    if move and not (resolution.decision == "none" and target_name == source_path.name):
                        file_operations.delete(source_path, permanent=True)
                    result.completed.extend(uploaded)
                except Exception as error:
                    result.errors.append(str(error))
                progress_value += self._count_local_transfer_steps(source_path)
                dialog.setValue(progress_value)
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

        remembered_resolution: ConflictResolution | None = None
        total_steps = sum(self._count_remote_transfer_steps(remote_drive_controller, location) for location in remote_items)
        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=False),
            total_steps,
        )
        progress_value = 0
        try:
            for location in remote_items:
                source_name = PurePosixPath(str(location.path or "/")).name or location.path
                dialog.setLabelText(self._progress_label(move, source_name, remote=False))
                dialog.setValue(progress_value)
                resolution, target_name = self._resolve_local_conflict(
                    widget,
                    destination_directory,
                    source_name,
                    remembered_resolution=remembered_resolution,
                )
                if resolution.apply_to_all:
                    remembered_resolution = resolution
                if resolution.decision == "skip":
                    result.skipped_count += 1
                    progress_value += self._count_remote_transfer_steps(remote_drive_controller, location)
                    continue
                try:
                    target = remote_drive_controller.transfer_item_to_local(
                        location,
                        destination_directory,
                        move=move,
                        target_name=target_name,
                        overwrite=resolution.decision == "overwrite",
                    )
                    result.completed.append(target)
                except Exception as error:
                    result.errors.append(str(error))
                progress_value += self._count_remote_transfer_steps(remote_drive_controller, location)
                dialog.setValue(progress_value)
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

        remembered_resolution: ConflictResolution | None = None
        total_steps = sum(self._count_remote_transfer_steps(remote_drive_controller, location) for location in remote_items)
        dialog = self._create_progress_dialog(
            widget,
            self._progress_title(move, remote=True),
            total_steps,
        )
        progress_value = 0
        try:
            for location in remote_items:
                source_name = PurePosixPath(str(location.path or "/")).name or location.path
                dialog.setLabelText(self._progress_label(move, source_name, remote=True))
                dialog.setValue(progress_value)
                resolution, target_name = self._resolve_remote_conflict(
                    widget,
                    remote_drive_controller,
                    destination,
                    source_name,
                    source_location=location,
                    remembered_resolution=remembered_resolution,
                )
                if resolution.apply_to_all:
                    remembered_resolution = resolution
                if resolution.decision == "skip":
                    result.skipped_count += 1
                    progress_value += self._count_remote_transfer_steps(remote_drive_controller, location)
                    continue
                try:
                    changed = remote_drive_controller.transfer_item_to_remote(
                        location,
                        destination,
                        move=move,
                        target_name=target_name,
                        overwrite=resolution.decision == "overwrite",
                    )
                    result.completed.append(changed)
                except Exception as error:
                    result.errors.append(str(error))
                progress_value += self._count_remote_transfer_steps(remote_drive_controller, location)
                dialog.setValue(progress_value)
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
        remembered_resolution: ConflictResolution | None = None,
    ) -> tuple[str, str]:
        existing = self._find_remote_child(remote_drive_controller, destination, desired_name)
        if existing is None or (source_location is not None and existing.path == source_location.path and existing.remote_id == source_location.remote_id):
            return ConflictResolution("none"), desired_name

        decision = remembered_resolution or self._ask_conflict_resolution(widget, desired_name)
        if decision.decision == "rename":
            return decision, self._next_remote_name(remote_drive_controller, destination, desired_name)
        return decision, desired_name

    def _resolve_local_conflict(
        self,
        widget,
        destination_directory: str,
        desired_name: str,
        *,
        remembered_resolution: ConflictResolution | None = None,
    ) -> tuple[ConflictResolution, str]:
        target = Path(destination_directory).expanduser().resolve() / desired_name
        if not target.exists():
            return ConflictResolution("none"), desired_name

        decision = remembered_resolution or self._ask_conflict_resolution(widget, desired_name)
        if decision.decision == "rename":
            return decision, self._next_local_name(target.parent, desired_name)
        return decision, desired_name

    def _ask_conflict_resolution(self, widget, target_name: str) -> ConflictResolution:
        box = QMessageBox(widget)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(app_tr("PaneController", "Konflikt beim Übertragen"))
        box.setText(
            app_tr("PaneController", "Das Ziel '{name}' existiert bereits.").format(name=target_name)
        )
        remember_checkbox = QCheckBox(app_tr("PaneController", "Für alle Konflikte merken"), box)
        box.setCheckBox(remember_checkbox)
        overwrite_button = box.addButton(app_tr("PaneController", "Überschreiben"), QMessageBox.ButtonRole.AcceptRole)
        rename_button = box.addButton(app_tr("PaneController", "Beide behalten"), QMessageBox.ButtonRole.ActionRole)
        skip_button = box.addButton(app_tr("PaneController", "Überspringen"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(rename_button)
        box.exec()
        clicked = box.clickedButton()
        apply_to_all = remember_checkbox.isChecked()
        if clicked == overwrite_button:
            return ConflictResolution("overwrite", apply_to_all=apply_to_all)
        if clicked == rename_button:
            return ConflictResolution("rename", apply_to_all=apply_to_all)
        return ConflictResolution("skip", apply_to_all=apply_to_all)

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

    def _count_local_transfer_steps(self, source_path: Path) -> int:
        path = Path(source_path)
        if not path.exists():
            return 0
        if path.is_file():
            return 1
        return 1 + sum(1 for _ in path.rglob("*"))

    def _count_remote_transfer_steps(self, remote_drive_controller, location: PaneLocation) -> int:
        count = 1
        try:
            entries = remote_drive_controller.list_directory(location)
        except Exception:
            return count
        for entry in entries:
            count += self._count_remote_transfer_steps(remote_drive_controller, entry.location)
        return count

    def feedback_message(self, result: RemoteTransferResult, *, move: bool, direction: str) -> str:
        base_map = {
            ("copy", "local_to_remote"): app_tr("PaneController", "{count} Element(e) nach Remote kopiert"),
            ("move", "local_to_remote"): app_tr("PaneController", "{count} Element(e) nach Remote verschoben"),
            ("copy", "remote_to_local"): app_tr("PaneController", "{count} Remote-Element(e) lokal kopiert"),
            ("move", "remote_to_local"): app_tr("PaneController", "{count} Remote-Element(e) lokal verschoben"),
            ("copy", "remote_to_remote"): app_tr("PaneController", "{count} Remote-Element(e) kopiert"),
            ("move", "remote_to_remote"): app_tr("PaneController", "{count} Remote-Element(e) verschoben"),
        }
        key = ("move" if move else "copy", direction)
        if result.skipped_count:
            return app_tr("PaneController", "{count} Element(e) übertragen, {skipped} übersprungen").format(
                count=len(result.completed),
                skipped=result.skipped_count,
            )
        return base_map[key].format(count=len(result.completed))

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
