from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QDir, QUrl
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget


class SingleApplication(QApplication):
    APP_ID = "tablion-file-manager"

    def __init__(self, argv):
        super().__init__(argv)
        self._activation_window: QWidget | None = None
        self._activation_handler = None
        self._is_running = False

        self._server = QLocalServer(self)
        if self._connect_to_running_instance():
            self._is_running = True
            return

        QLocalServer.removeServer(self.APP_ID)

        if not self._server.listen(self.APP_ID):
            self._is_running = True
            self._notify_running_instance(self._collect_activation_paths())
            return

        self._server.newConnection.connect(self._handle_new_connection)

    def is_running(self) -> bool:
        return self._is_running

    def set_activation_window(self, window: QWidget | None) -> None:
        self._activation_window = window

    def set_activation_handler(self, handler) -> None:
        self._activation_handler = handler

    def _collect_activation_paths(self) -> list[str]:
        paths: list[str] = []
        for arg in list(self.arguments())[1:]:
            value = str(arg or "").strip()
            if not value or value.startswith("-"):
                continue

            url = QUrl(value)
            if url.isValid() and url.isLocalFile():
                candidate = QDir.cleanPath(url.toLocalFile())
            else:
                candidate = QDir.cleanPath(str(Path(value).expanduser()))

            if candidate and candidate not in paths:
                paths.append(candidate)
        return paths

    def _notify_running_instance(self, paths: list[str] | None = None) -> None:
        payload = {
            "command": "activate",
            "paths": list(paths or []),
        }
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self.APP_ID, QLocalSocket.WriteOnly)
            if socket.waitForConnected(250):
                socket.write(encoded)
                socket.flush()
                socket.waitForBytesWritten(250)
                socket.disconnectFromServer()
        finally:
            socket.close()

    def _connect_to_running_instance(self) -> bool:
        paths = self._collect_activation_paths()
        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self.APP_ID, QLocalSocket.WriteOnly)
            if socket.waitForConnected(250):
                payload = {
                    "command": "activate",
                    "paths": paths,
                }
                socket.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
                socket.flush()
                socket.waitForBytesWritten(250)
                socket.disconnectFromServer()
                return True
        finally:
            socket.close()
        return False

    def _handle_new_connection(self) -> None:
        activation_paths: list[str] = []
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            try:
                socket.waitForReadyRead(250)
                raw = bytes(socket.readAll()).decode("utf-8", errors="ignore").strip()
                if raw:
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        payload = {"command": "activate", "paths": []}
                    if isinstance(payload, dict):
                        raw_paths = payload.get("paths")
                        if isinstance(raw_paths, list):
                            for item in raw_paths:
                                path = QDir.cleanPath(str(item or ""))
                                if path and path not in activation_paths:
                                    activation_paths.append(path)
                socket.disconnectFromServer()
            except Exception:
                pass
            finally:
                socket.close()
        self._activate_window(activation_paths)

    def _activate_window(self, paths: list[str] | None = None) -> None:
        window = self._activation_window
        if window is None:
            return
        try:
            if window.isMinimized():
                window.showNormal()
            window.raise_()
            window.activateWindow()
        except Exception:
            pass
        handler = self._activation_handler
        if handler is not None:
            try:
                handler(list(paths or []))
            except Exception:
                pass
