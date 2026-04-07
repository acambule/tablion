from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass


DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
REFRESH_TOKEN_GRANT = "refresh_token"


@dataclass
class OneDriveAuthResult:
    access_token: str
    refresh_token: str
    expires_at: float
    account_label: str
    drive_id: str


class OneDriveAuthError(RuntimeError):
    pass


class OneDriveAuthService:
    DEVICE_CODE_SCOPE = "offline_access Files.ReadWrite User.Read"

    def authenticate(
        self,
        *,
        client_id: str,
        tenant_id: str = "common",
        open_browser: bool = True,
        device_prompt_callback=None,
    ) -> OneDriveAuthResult:
        tenant = str(tenant_id or "common").strip() or "common"
        client = str(client_id or "").strip()
        if not client:
            raise OneDriveAuthError("Client-ID fehlt.")

        device_payload = self._post_form(
            self._authority_url(tenant, "devicecode"),
            {
                "client_id": client,
                "scope": self.DEVICE_CODE_SCOPE,
            },
        )

        verification_uri = str(device_payload.get("verification_uri") or "").strip()
        verification_uri_complete = str(device_payload.get("verification_uri_complete") or "").strip()
        user_code = str(device_payload.get("user_code") or "").strip()
        device_code = str(device_payload.get("device_code") or "").strip()
        interval = int(device_payload.get("interval") or 5)
        message = str(device_payload.get("message") or "").strip()
        expires_in = int(device_payload.get("expires_in") or 900)

        if not verification_uri or not user_code or not device_code:
            raise OneDriveAuthError("Device-Code-Antwort von Microsoft ist unvollständig.")

        prompt_url = verification_uri_complete or verification_uri

        if open_browser:
            webbrowser.open(prompt_url)
        if callable(device_prompt_callback):
            device_prompt_callback(
                message=message,
                user_code=user_code,
                verification_uri=verification_uri,
                prompt_url=prompt_url,
            )

        deadline = time.time() + max(60, expires_in)
        token_payload = None
        while time.time() < deadline:
            time.sleep(max(1, interval))
            try:
                token_payload = self._post_form(
                    self._authority_url(tenant, "token"),
                    {
                        "grant_type": DEVICE_CODE_GRANT,
                        "client_id": client,
                        "device_code": device_code,
                    },
                )
                break
            except OneDriveAuthError as error:
                error_text = str(error)
                if "authorization_pending" in error_text:
                    continue
                if "slow_down" in error_text:
                    interval += 2
                    continue
                if "expired_token" in error_text:
                    raise OneDriveAuthError("Anmeldecode ist abgelaufen.")
                raise OneDriveAuthError(f"{message}\n\n{error_text}" if message else error_text)

        if token_payload is None:
            raise OneDriveAuthError("Zeitüberschreitung beim Warten auf die Microsoft-Anmeldung.")

        access_token = str(token_payload.get("access_token") or "").strip()
        refresh_token = str(token_payload.get("refresh_token") or "").strip()
        expires_in_token = int(token_payload.get("expires_in") or 3600)
        if not access_token or not refresh_token:
            raise OneDriveAuthError("Microsoft hat keine verwertbaren Tokens zurückgegeben.")

        profile = self._graph_get("https://graph.microsoft.com/v1.0/me", access_token)
        drive = self._graph_get("https://graph.microsoft.com/v1.0/me/drive", access_token)
        account_label = str(profile.get("userPrincipalName") or profile.get("mail") or profile.get("displayName") or "").strip()
        drive_id = str(drive.get("id") or "").strip()
        if not drive_id:
            raise OneDriveAuthError("OneDrive konnte nicht ermittelt werden.")

        return OneDriveAuthResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=time.time() + max(60, expires_in_token - 30),
            account_label=account_label,
            drive_id=drive_id,
        )

    def refresh_access_token(self, *, client_id: str, tenant_id: str, refresh_token: str) -> OneDriveAuthResult:
        client = str(client_id or "").strip()
        tenant = str(tenant_id or "common").strip() or "common"
        refresh = str(refresh_token or "").strip()
        if not client or not refresh:
            raise OneDriveAuthError("Refresh-Token oder Client-ID fehlt.")

        token_payload = self._post_form(
            self._authority_url(tenant, "token"),
            {
                "grant_type": REFRESH_TOKEN_GRANT,
                "client_id": client,
                "refresh_token": refresh,
                "scope": self.DEVICE_CODE_SCOPE,
            },
        )

        access_token = str(token_payload.get("access_token") or "").strip()
        next_refresh_token = str(token_payload.get("refresh_token") or refresh).strip()
        expires_in_token = int(token_payload.get("expires_in") or 3600)
        profile = self._graph_get("https://graph.microsoft.com/v1.0/me", access_token)
        drive = self._graph_get("https://graph.microsoft.com/v1.0/me/drive", access_token)
        return OneDriveAuthResult(
            access_token=access_token,
            refresh_token=next_refresh_token,
            expires_at=time.time() + max(60, expires_in_token - 30),
            account_label=str(profile.get("userPrincipalName") or profile.get("mail") or profile.get("displayName") or "").strip(),
            drive_id=str(drive.get("id") or "").strip(),
        )

    def _authority_url(self, tenant_id: str, suffix: str) -> str:
        return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/{suffix}"

    def _post_form(self, url: str, payload: dict) -> dict:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        request = urllib.request.Request(url, data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                raise OneDriveAuthError(body or str(error)) from error
            raise OneDriveAuthError(payload.get("error_description") or payload.get("error") or body or str(error)) from error
        except urllib.error.URLError as error:
            raise OneDriveAuthError(str(error)) from error

    def _graph_get(self, url: str, access_token: str) -> dict:
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
