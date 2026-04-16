from __future__ import annotations

import json

from PySide6.QtCore import QDir, QMimeData, QUrl

from domain.filesystem import PaneLocation
from services.dragdrop.drag_payload import DragPayload


class DragMimeCodec:
    def __init__(
        self,
        transfer_service,
        *,
        clipboard_mime_type: str,
        clipboard_operation_mime_type: str,
        remote_clipboard_mime_type: str,
        internal_drag_mime_type: str,
        ark_dnd_service_mime: str,
        ark_dnd_path_mime: str,
    ):
        self._transfer_service = transfer_service
        self._clipboard_mime_type = clipboard_mime_type
        self._clipboard_operation_mime_type = clipboard_operation_mime_type
        self._remote_clipboard_mime_type = remote_clipboard_mime_type
        self._internal_drag_mime_type = internal_drag_mime_type
        self._ark_dnd_service_mime = ark_dnd_service_mime
        self._ark_dnd_path_mime = ark_dnd_path_mime

    def build_remote_mime_data(
        self,
        locations: list[PaneLocation],
        *,
        operation: str,
        external_local_paths: list[str] | None = None,
        base_mime_data: QMimeData | None = None,
    ) -> QMimeData:
        mime_data = base_mime_data if base_mime_data is not None else QMimeData()
        payload = [
            {
                "kind": location.kind,
                "path": location.path,
                "remote_id": location.remote_id,
            }
            for location in locations
            if location.is_remote and location.remote_id
        ]
        mime_data.setData(self._remote_clipboard_mime_type, json.dumps(payload).encode("utf-8"))
        if base_mime_data is None:
            mime_data.setData(self._clipboard_operation_mime_type, operation.encode("utf-8"))
        urls = [QUrl.fromLocalFile(path) for path in (external_local_paths or []) if path]
        if urls and base_mime_data is None:
            mime_data.setUrls(urls)
            uri_values = [bytes(url.toEncoded()).decode("utf-8") for url in urls]
            uri_payload = ("\n".join(uri_values) + "\n").encode("utf-8")
            mime_data.setData("text/uri-list", uri_payload)
            mime_data.setData("application/x-kde4-urilist", uri_payload)
            mime_data.setData("application/x-kde-urilist", uri_payload)
            mime_data.setData(
                "x-special/gnome-copied-files",
                ("copy\n" + "\n".join(uri_values) + "\n").encode("utf-8"),
            )
            if len(urls) == 1:
                moz_url = f"{uri_values[0]}\n{urls[0].fileName()}\n".encode("utf-16le")
                mime_data.setData("text/x-moz-url", moz_url)
                mime_data.setData("text/x-moz-url-data", uri_values[0].encode("utf-16le"))
                mime_data.setData("text/x-moz-url-desc", urls[0].fileName().encode("utf-16le"))
        return mime_data

    def extract_local_paths(self, mime_data, *, logger=None) -> list[str]:
        if mime_data is not None and mime_data.hasFormat(self._remote_clipboard_mime_type):
            return []
        return self._transfer_service.extract_paths_from_mime(
            mime_data,
            internal_drag_mime_type=self._internal_drag_mime_type,
            clipboard_mime_type=self._clipboard_mime_type,
            ark_dnd_service_mime=self._ark_dnd_service_mime,
            ark_dnd_path_mime=self._ark_dnd_path_mime,
            logger=logger,
        )

    def extract_operation(self, mime_data) -> str:
        return self._transfer_service.extract_operation_from_mime(
            mime_data,
            operation_mime_type=self._clipboard_operation_mime_type,
        )

    def extract_remote_locations(self, mime_data) -> list[PaneLocation]:
        if mime_data is None or not mime_data.hasFormat(self._remote_clipboard_mime_type):
            return []
        raw_payload = bytes(mime_data.data(self._remote_clipboard_mime_type)).decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(raw_payload)
        except json.JSONDecodeError:
            return []
        if not isinstance(parsed, list):
            return []

        locations: list[PaneLocation] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            path = QDir.cleanPath(str(item.get("path") or ""))
            remote_id = str(item.get("remote_id") or "").strip()
            kind = str(item.get("kind") or "remote").strip() or "remote"
            if kind != "remote" or not path or not remote_id or path == "/":
                continue
            locations.append(PaneLocation(kind="remote", path=path, remote_id=remote_id))
        return locations

    def decode_payload(self, mime_data, *, logger=None, ark_reference=None) -> DragPayload:
        return DragPayload(
            local_paths=self.extract_local_paths(mime_data, logger=logger),
            remote_locations=self.extract_remote_locations(mime_data),
            operation=self.extract_operation(mime_data),
            ark_reference=ark_reference,
        )
