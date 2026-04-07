from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

from remotes.providers.onedrive_auth import OneDriveAuthError


class OneDriveClient:
    _SELECT_FIELDS = "id,name,size,file,folder,webUrl,lastModifiedDateTime,parentReference"

    def list_children(self, *, access_token: str, drive_id: str, item_path: str) -> list[dict]:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_path = self._normalize_path(item_path)
        if not drive_key or not token:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        if normalized_path == "/":
            endpoint = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root/children"
        else:
            quoted_path = urllib.parse.quote(normalized_path, safe="/")
            endpoint = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}:/children"

        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}$select={urllib.parse.quote(self._SELECT_FIELDS, safe=',')}"
        payload = self._graph_get_json(url, token)
        value = payload.get("value", [])
        return value if isinstance(value, list) else []

    def _normalize_path(self, raw_path: str) -> str:
        text = str(raw_path or "").strip() or "/"
        if not text.startswith("/"):
            text = f"/{text}"
        while "//" in text:
            text = text.replace("//", "/")
        return text or "/"

    def _graph_get_json(self, url: str, access_token: str) -> dict:
        request = urllib.request.Request(url, method="GET")
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error
