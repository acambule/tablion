from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QDrag

from debug_log import debug_log


class DragSessionService:
    def __init__(self, mime_codec, visual_service, remote_drag_guard, build_external_remote_mime_data=None):
        self._mime_codec = mime_codec
        self._visual_service = visual_service
        self._remote_drag_guard = remote_drag_guard
        self._build_external_remote_mime_data = build_external_remote_mime_data

    def arm_remote_drag(self, *, source_view, start_pos: QPoint, locations) -> None:
        self._remote_drag_guard.arm(source_view=source_view, start_pos=start_pos, locations=locations)

    def should_start_remote_drag(self, *, source_view, current_pos: QPoint, drag_distance: int) -> bool:
        return self._remote_drag_guard.should_start_drag(
            source_view=source_view,
            current_pos=current_pos,
            drag_distance=drag_distance,
        )

    def release_was_guarded(self) -> bool:
        return self._remote_drag_guard.release_was_guarded()

    def clear_remote_drag(self) -> None:
        self._remote_drag_guard.clear()

    def remote_drag_locations(self):
        return self._remote_drag_guard.snapshot_locations()

    def start_remote_drag(self, *, widget, source_view, locations) -> None:
        drag_locations = list(locations or self._remote_drag_guard.snapshot_locations())
        debug_log(
            "Remote drag start requested: "
            f"count={len(drag_locations)} paths={[location.path for location in drag_locations[:5]]}"
        )
        if not drag_locations:
            debug_log("Remote drag start aborted: no selected remote locations")
            return

        if self._build_external_remote_mime_data is not None:
            mime_data = self._build_external_remote_mime_data(drag_locations, operation="copy")
        else:
            mime_data = self._mime_codec.build_remote_mime_data(drag_locations, operation="copy")
        debug_log(f"Remote drag mime formats={mime_data.formats()}")
        drag_source = source_view.viewport() if hasattr(source_view, "viewport") else source_view
        debug_log(f"Remote drag source widget={type(drag_source).__name__}")
        drag = QDrag(drag_source)
        drag.setMimeData(mime_data)
        preview = self._visual_service.build_remote_drag_pixmap(widget, drag_locations)
        if preview is not None:
            drag.setPixmap(preview)
            drag.setHotSpot(QPoint(18, 18))
        debug_log("Remote drag object created and mime data attached")
        drag.exec(Qt.DropAction.CopyAction)
        debug_log("Remote drag exec returned")
