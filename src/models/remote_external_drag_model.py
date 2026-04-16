from __future__ import annotations

from debug_log import debug_log
from models.file_system_model import FileSystemModel


class RemoteExternalDragModel(FileSystemModel):
    def __init__(
        self,
        *,
        remote_clipboard_mime_type: str,
        clipboard_operation_mime_type: str,
        parent=None,
    ):
        super().__init__(parent)
        self._remote_clipboard_mime_type = remote_clipboard_mime_type
        self._clipboard_operation_mime_type = clipboard_operation_mime_type
        self._remote_payload = b""
        self._operation_payload = b"copy"

    def configure_remote_payload(self, payload: bytes, *, operation: bytes) -> None:
        self._remote_payload = payload or b""
        self._operation_payload = operation or b"copy"
        debug_log(
            "RemoteExternalDragModel payload configured: "
            f"payload_len={len(self._remote_payload)} operation={self._operation_payload!r}"
        )

    def mimeData(self, indexes):
        mime_data = super().mimeData(indexes)
        if self._remote_payload:
            mime_data.setData(self._remote_clipboard_mime_type, self._remote_payload)
            mime_data.setData(self._clipboard_operation_mime_type, self._operation_payload)
        return mime_data