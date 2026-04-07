from __future__ import annotations

import json
import time
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

    def download_file(self, *, access_token: str, drive_id: str, item_path: str) -> bytes:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_path = self._normalize_path(item_path)
        if not drive_key or not token:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        if normalized_path == "/":
            raise OneDriveAuthError("Root kann nicht als Datei geladen werden.")

        quoted_path = urllib.parse.quote(normalized_path, safe="/")
        url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}:/content"
        return self._graph_get_bytes(url, token)

    def get_item(self, *, access_token: str, drive_id: str, item_path: str) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_path = self._normalize_path(item_path)
        if not drive_key or not token:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        if normalized_path == "/":
            endpoint = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root"
        else:
            quoted_path = urllib.parse.quote(normalized_path, safe="/")
            endpoint = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}"
        separator = "&" if "?" in endpoint else "?"
        url = f"{endpoint}{separator}$select={urllib.parse.quote(self._SELECT_FIELDS, safe=',')}"
        return self._graph_get_json(url, token)

    def rename_item(self, *, access_token: str, drive_id: str, item_path: str, new_name: str) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_path = self._normalize_path(item_path)
        target_name = str(new_name or "").strip()
        if not drive_key or not token or not target_name:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")
        if normalized_path == "/":
            raise OneDriveAuthError("Root kann nicht umbenannt werden.")

        quoted_path = urllib.parse.quote(normalized_path, safe="/")
        url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}"
        return self._graph_patch_json(url, token, {"name": target_name})

    def delete_item(self, *, access_token: str, drive_id: str, item_path: str) -> None:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_path = self._normalize_path(item_path)
        if not drive_key or not token:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")
        if normalized_path == "/":
            raise OneDriveAuthError("Root kann nicht gelöscht werden.")

        quoted_path = urllib.parse.quote(normalized_path, safe="/")
        url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}"
        self._graph_delete(url, token)

    def create_folder(self, *, access_token: str, drive_id: str, parent_path: str, folder_name: str) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_parent = self._normalize_path(parent_path)
        target_name = str(folder_name or "").strip()
        if not drive_key or not token or not target_name:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        if normalized_parent == "/":
            url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root/children"
        else:
            quoted_parent = urllib.parse.quote(normalized_parent, safe="/")
            url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_parent}:/children"

        payload = {
            "name": target_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "fail",
        }
        return self._graph_post_json(url, token, payload)

    def upload_file(self, *, access_token: str, drive_id: str, parent_path: str, file_name: str, content: bytes) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        normalized_parent = self._normalize_path(parent_path)
        target_name = str(file_name or "").strip()
        if not drive_key or not token or not target_name:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        item_path = self._normalize_path(f"{normalized_parent.rstrip('/')}/{target_name}")
        quoted_path = urllib.parse.quote(item_path, safe="/")
        url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/root:{quoted_path}:/content"
        return self._graph_put_bytes(url, token, content)

    def move_item(
        self,
        *,
        access_token: str,
        drive_id: str,
        item_id: str,
        destination_folder_id: str,
        new_name: str | None = None,
    ) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        source_item_id = str(item_id or "").strip()
        parent_id = str(destination_folder_id or "").strip()
        if not drive_key or not token or not source_item_id or not parent_id:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        url = f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/items/{urllib.parse.quote(source_item_id)}"
        payload: dict = {"parentReference": {"id": parent_id}}
        if str(new_name or "").strip():
            payload["name"] = str(new_name).strip()
        return self._graph_patch_json(url, token, payload)

    def copy_item(
        self,
        *,
        access_token: str,
        drive_id: str,
        item_id: str,
        destination_folder_id: str,
        destination_drive_id: str | None = None,
        new_name: str | None = None,
    ) -> dict:
        drive_key = str(drive_id or "").strip()
        token = str(access_token or "").strip()
        source_item_id = str(item_id or "").strip()
        parent_id = str(destination_folder_id or "").strip()
        target_drive_id = str(destination_drive_id or drive_id or "").strip()
        if not drive_key or not token or not source_item_id or not parent_id or not target_drive_id:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")

        url = (
            f"https://graph.microsoft.com/v1.0/drives/{urllib.parse.quote(drive_key)}/items/"
            f"{urllib.parse.quote(source_item_id)}/copy?@microsoft.graph.conflictBehavior=rename"
        )
        payload: dict = {
            "parentReference": {
                "driveId": target_drive_id,
                "id": parent_id,
            }
        }
        if str(new_name or "").strip():
            payload["name"] = str(new_name).strip()

        response = self._graph_post_with_response(url, token, payload)
        monitor_url = response["headers"].get("Location") or response["headers"].get("location")
        if not monitor_url:
            raise OneDriveAuthError("Kopiervorgang wurde akzeptiert, aber keine Monitor-URL wurde zurückgegeben.")
        return self._monitor_copy_operation(monitor_url, token)

    def list_joined_teams(self, *, access_token: str) -> list[dict]:
        token = str(access_token or "").strip()
        if not token:
            raise OneDriveAuthError("OneDrive-Zugriff ist nicht vollständig konfiguriert.")
        payload = self._graph_get_json(
            "https://graph.microsoft.com/v1.0/me/joinedTeams?$select=id,displayName,description",
            token,
        )
        value = payload.get("value", [])
        return value if isinstance(value, list) else []

    def list_group_drives(self, *, access_token: str, group_id: str) -> list[dict]:
        token = str(access_token or "").strip()
        group_key = str(group_id or "").strip()
        if not token or not group_key:
            raise OneDriveAuthError("Team-Zugriff ist nicht vollständig konfiguriert.")
        payload = self._graph_get_json(
            f"https://graph.microsoft.com/v1.0/groups/{urllib.parse.quote(group_key)}/drives?$select=id,name,webUrl",
            token,
        )
        value = payload.get("value", [])
        return value if isinstance(value, list) else []

    def _normalize_path(self, raw_path: str) -> str:
        text = str(raw_path or "").strip() or "/"
        if not text.startswith("/"):
            text = f"/{text}"
        while "//" in text:
            text = text.replace("//", "/")
        return text or "/"

    def _monitor_copy_operation(self, url: str, access_token: str) -> dict:
        last_payload: dict = {}
        for _ in range(120):
            payload = self._graph_get_json(url, access_token=None)
            if isinstance(payload, dict):
                last_payload = payload
            status = str(last_payload.get("status") or "").strip().lower()
            if status == "completed":
                return last_payload
            if status == "failed":
                error = last_payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message") or error.get("code") or "").strip()
                    if message:
                        raise OneDriveAuthError(message)
                raise OneDriveAuthError("Der Kopiervorgang ist fehlgeschlagen.")
            time.sleep(0.5)
        raise OneDriveAuthError("Der Kopiervorgang hat das Zeitlimit überschritten.")

    def _graph_get_json(self, url: str, access_token: str | None = None) -> dict:
        request = urllib.request.Request(url, method="GET")
        token = str(access_token or "").strip()
        if token:
            request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_get_bytes(self, url: str, access_token: str) -> bytes:
        request = urllib.request.Request(url, method="GET")
        request.add_header("Authorization", f"Bearer {access_token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_patch_json(self, url: str, access_token: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="PATCH",
        )
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="ignore")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_post_json(self, url: str, access_token: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="ignore")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_post_with_response(self, url: str, access_token: str, payload: dict) -> dict:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8", errors="ignore")
                parsed_body = json.loads(body) if body else {}
                return {
                    "status": response.status,
                    "headers": dict(response.headers.items()),
                    "body": parsed_body,
                }
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_put_bytes(self, url: str, access_token: str, content: bytes) -> dict:
        request = urllib.request.Request(url, data=content, method="PUT")
        request.add_header("Authorization", f"Bearer {access_token}")
        request.add_header("Accept", "application/json")
        request.add_header("Content-Type", "application/octet-stream")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8", errors="ignore")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_delete(self, url: str, access_token: str) -> None:
        request = urllib.request.Request(url, method="DELETE")
        request.add_header("Authorization", f"Bearer {access_token}")
        try:
            with urllib.request.urlopen(request, timeout=20):
                return
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            raise OneDriveAuthError(body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error
