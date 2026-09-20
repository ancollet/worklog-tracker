"""Application entry point: QApplication, single-instance lock, IPC, tray glue."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

from PyQt6.QtCore import QObject, QSocketNotifier, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

from worklog import db as db_module
from worklog import repository as repo
from worklog.paths import icon_path, lock_path, socket_path
from worklog.services.timer import TimerService
from worklog.ui.main_window import MainWindow
from worklog.ui.theme import DEFAULT_UI_THEME, SETTINGS_UI_THEME, apply_theme
from worklog.ui.tray import TrayController


class IpcServer(QObject):
    """Listen on a Unix socket; emit signal when another instance pings us."""
    quick_add_requested = pyqtSignal()
    show_window_requested = pyqtSignal()

    def __init__(self, sock: socket.socket) -> None:
        super().__init__()
        self.sock = sock
        self.notifier = QSocketNotifier(sock.fileno(), QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self._on_ready)

    def _on_ready(self) -> None:
        try:
            client, _ = self.sock.accept()
        except BlockingIOError:
            return
        with client:
            data = client.recv(64).decode("utf-8", "replace").strip()
        if data == "quick":
            self.quick_add_requested.emit()
        else:
            self.show_window_requested.emit()


def _try_acquire_lock(lock: Path, sock_path: Path, command: str) -> socket.socket | None:
    """Bind a Unix socket; if already bound, ping the existing instance and return None."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.setblocking(False)
    try:
        if sock_path.exists():
            # Test whether the existing socket has a live owner
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
                    probe.settimeout(0.3)
                    probe.connect(str(sock_path))
                    probe.sendall(command.encode("utf-8"))
                # Existing instance handled the request
                sock.close()
                return None
            except (ConnectionRefusedError, FileNotFoundError, OSError):
                sock_path.unlink(missing_ok=True)
        sock.bind(str(sock_path))
        sock.listen(1)
        lock.write_text(str(os.getpid()))
        return sock
    except OSError as exc:
        sock.close()
        print(f"worklog: could not bind IPC socket: {exc}", file=sys.stderr)
        return None


def main() -> int:
    command = "quick" if "--quick" in sys.argv[1:] else "show"

    sock = _try_acquire_lock(lock_path(), socket_path(), command)
    if sock is None:
        return 0  # forwarded to running instance

    app = QApplication(sys.argv)
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

    # Theming is opt-in; the default is the plain native Qt look. WORKLOG_THEME
    # env var wins, else the persisted 'ui_theme' setting, else the default.
    theme = os.environ.get("WORKLOG_THEME") or repo.get_setting(
        conn, SETTINGS_UI_THEME, DEFAULT_UI_THEME
    )
    apply_theme(app, theme)

    timer_service = TimerService(conn)

    window = MainWindow(conn, timer_service)
    tray = TrayController(conn, timer_service, window)
    ipc = IpcServer(sock)
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
        try:
            sock.close()
        except OSError:
            pass
        socket_path().unlink(missing_ok=True)
        lock_path().unlink(missing_ok=True)
        conn.close()


def _system_tray_available() -> bool:
    from PyQt6.QtWidgets import QSystemTrayIcon
    return QSystemTrayIcon.isSystemTrayAvailable()


if __name__ == "__main__":
    raise SystemExit(main())
