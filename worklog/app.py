"""Application entry point: QApplication, single-instance lock, IPC, tray glue."""
from __future__ import annotations

import os
import sys

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from worklog import db as db_module
from worklog import repository as repo
from worklog.paths import icon_path
from worklog.services.timer import TimerService
from worklog.ui.main_window import MainWindow
from worklog.ui.theme import DEFAULT_UI_THEME, SETTINGS_UI_ACCENT, SETTINGS_UI_THEME, apply_theme
from worklog.ui.tray import TrayController

IPC_NAME = "worklog"


class IpcServer(QObject):
    """Listen on a Qt local socket (named pipe on Windows, Unix socket elsewhere);
    emit signal when another instance pings us."""
    quick_add_requested = pyqtSignal()
    show_window_requested = pyqtSignal()

    def __init__(self, server: QLocalServer) -> None:
        super().__init__()
        self.server = server
        self.server.newConnection.connect(self._on_connection)

    def _on_connection(self) -> None:
        conn = self.server.nextPendingConnection()
        if conn is None:
            return
        conn.waitForReadyRead(200)
        data = bytes(conn.readAll()).decode("utf-8", "replace").strip()
        conn.disconnectFromServer()
        if data == "quick":
            self.quick_add_requested.emit()
        else:
            self.show_window_requested.emit()


def _try_acquire_server(command: str) -> QLocalServer | None:
    """Become the IPC server; if another instance already owns it, forward the command instead."""
    probe = QLocalSocket()
    probe.connectToServer(IPC_NAME)
    if probe.waitForConnected(200):
        probe.write(command.encode("utf-8"))
        probe.waitForBytesWritten(200)
        probe.disconnectFromServer()
        return None
    QLocalServer.removeServer(IPC_NAME)  # clean up a stale socket left by a crashed instance
    server = QLocalServer()
    if not server.listen(IPC_NAME):
        print(f"worklog: could not bind IPC server: {server.errorString()}", file=sys.stderr)
        return None
    return server


def main() -> int:
    command = "quick" if "--quick" in sys.argv[1:] else "show"

    app = QApplication(sys.argv)

    server = _try_acquire_server(command)
    if server is None:
        return 0  # forwarded to running instance

    # IDs must all align for Wayland docks (COSMIC/GNOME) to associate
    # the running window with worklog.desktop:
    #   - applicationName     → Wayland app_id fallback (must be lowercase)
    #   - desktopFileName     → explicit match against ~/.../applications/worklog.desktop
    #   - displayName         → human-visible label
    app.setApplicationName("worklog")
    app.setDesktopFileName("worklog")
    app.setApplicationDisplayName("Worklog")
    app.setQuitOnLastWindowClosed(False)
    try:
        icon = QIcon(str(icon_path()))
    except (FileNotFoundError, ModuleNotFoundError):
        icon = QIcon.fromTheme("appointment-new")
    if not icon.isNull():
        app.setWindowIcon(icon)

    if not _system_tray_available():
        QMessageBox.warning(
            None,
            "Worklog",
            "Kein System-Tray verfügbar. Worklog läuft, aber im Hintergrund nur als Fenster.",
        )

    conn = db_module.connect()

    # WORKLOG_THEME (system/light/dark)
    # env var wins, else the persisted 'ui_theme' setting, else the default.
    theme = os.environ.get("WORKLOG_THEME") or repo.get_setting(
        conn, SETTINGS_UI_THEME, DEFAULT_UI_THEME
    )
    apply_theme(app, theme, repo.get_setting(conn, SETTINGS_UI_ACCENT))

    timer_service = TimerService(conn)

    window = MainWindow(conn, timer_service)
    tray = TrayController(conn, timer_service, window)
    ipc = IpcServer(server)
    ipc.quick_add_requested.connect(tray.open_quick_add)
    ipc.show_window_requested.connect(tray.show_main_window)

    if command == "quick":
        tray.open_quick_add()
    else:
        window.show()

    window.quit_requested.connect(app.quit)

    try:
        return app.exec()
    finally:
        server.close()
        conn.close()


def _system_tray_available() -> bool:
    from PyQt6.QtWidgets import QSystemTrayIcon
    return QSystemTrayIcon.isSystemTrayAvailable()


if __name__ == "__main__":
    raise SystemExit(main())
