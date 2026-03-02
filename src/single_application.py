from __future__ import annotations

from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QWidget


class SingleApplication(QApplication):
    APP_ID = "tablion-file-manager"

    def __init__(self, argv):
        super().__init__(argv)
        self._activation_window: QWidget | None = None
        self._is_running = False

        self._server = QLocalServer(self)
        if self._connect_to_running_instance():
            self._is_running = True
            return

        QLocalServer.removeServer(self.APP_ID)

        if not self._server.listen(self.APP_ID):
            self._is_running = True
            self._notify_running_instance()
            return

        self._server.newConnection.connect(self._handle_new_connection)

    def is_running(self) -> bool:
        return self._is_running

    def set_activation_window(self, window: QWidget | None) -> None:
        self._activation_window = window

    def _notify_running_instance(self) -> None:
        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self.APP_ID, QLocalSocket.WriteOnly)
            if socket.waitForConnected(250):
                socket.write(b"activate")
                socket.flush()
                socket.waitForBytesWritten(250)
                socket.disconnectFromServer()
        finally:
            socket.close()

    def _connect_to_running_instance(self) -> bool:
        socket = QLocalSocket(self)
        try:
            socket.connectToServer(self.APP_ID, QLocalSocket.WriteOnly)
            if socket.waitForConnected(250):
                socket.write(b"activate")
                socket.flush()
                socket.waitForBytesWritten(250)
                socket.disconnectFromServer()
                return True
        finally:
            socket.close()
        return False

    def _handle_new_connection(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            try:
                socket.waitForReadyRead(250)
                socket.disconnectFromServer()
            except Exception:
                pass
            finally:
                socket.close()
        self._activate_window()

    def _activate_window(self) -> None:
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