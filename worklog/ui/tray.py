from __future__ import annotations

import sqlite3
from datetime import datetime

from PyQt6.QtCore import QPoint, QRectF, QTimer
from PyQt6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from worklog import repository as repo
from worklog.paths import icon_path
from worklog.services.rounding import format_hms
from worklog.services.timer import TimerService
from worklog.ui.quick_add import QuickAddPopup


def _build_icon(running: bool) -> QIcon:
    """Themed icon lookup (sets SNI IconName so COSMIC/Plasma StatusArea
    can find it via hicolor); fall back to the packaged SVG, or a
    programmatic pixmap if everything else fails."""
    name = "worklog-active" if running else "worklog"
    themed = QIcon.fromTheme(name)
    if not themed.isNull():
        return themed
    # Fallback chain: load packaged SVG, then overlay status badge.
    try:
        return QIcon(str(icon_path()))
    except Exception:
        pass
    pix = QPixmap(64, 64)
    pix.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor("#4338CA"))
    painter.setPen(QColor("#1F2937"))
    painter.drawEllipse(6, 6, 52, 52)
    dot_color = QColor("#10B981") if running else QColor("#9CA3AF")
    painter.setBrush(dot_color)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawEllipse(40, 40, 22, 22)
    painter.end()
    return QIcon(pix)


class TrayController:
    def __init__(self, conn: sqlite3.Connection, timer: TimerService, window) -> None:
        self.conn = conn
        self.timer = timer
        self.window = window

        self.tray = QSystemTrayIcon(_build_icon(timer.is_running()))
        self.tray.setToolTip("Worklog")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

        self._tick = QTimer()
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._update_tooltip)
        self._tick.start()

        self._popup: QuickAddPopup | None = None

        self._rebuild_menu()
        self.tray.show()

        # rebuild menu when data changes
        self.window.data_changed.connect(self._rebuild_menu)

    # ------------------ public ------------------

    def open_quick_add(self, *, mode: str = QuickAddPopup.MODE_START, anchor=None) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._popup.activateWindow()
            return
        anchor = anchor or QCursor.pos()
        self._popup = QuickAddPopup(self.conn, self.timer, parent=None, mode=mode, anchor_global=anchor)
        self._popup.finished.connect(self._on_popup_closed)
        self._popup.show()
        self._popup.raise_()
        self._popup.activateWindow()

    def show_main_window(self) -> None:
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    # ------------------ events ------------------

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            mode = QuickAddPopup.MODE_EDIT if self.timer.is_running() else QuickAddPopup.MODE_START
            self.open_quick_add(mode=mode, anchor=self._tray_anchor())
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self._toggle_timer()

    def _on_popup_closed(self, _result: int) -> None:
        self._popup = None
        self._refresh_state()
        # propagate change to other widgets
        self.window.timer_tab.refresh()
        self.window.logs_tab.refresh()
        self.window.analytics_tab.refresh()
        self._rebuild_menu()

    def _tray_anchor(self) -> QPoint:
        geo = self.tray.geometry()
        if geo.isValid() and geo.width() > 0:
            return geo.center()
        return QCursor.pos()

    # ------------------ menu ------------------

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        running = self.timer.is_running()
        self._refresh_state()
        if running:
            cur = self.timer.current()
            header_text = "▣  Worklog"
            if cur and cur.task:
                header_text = f"▣  {cur.task}"
            header = QAction(header_text, self.menu)
            header.setEnabled(False)
            self.menu.addAction(header)
            self.menu.addSeparator()
            stop_act = QAction("⏸  Stop", self.menu)
            stop_act.triggered.connect(self._toggle_timer)
            self.menu.addAction(stop_act)
            edit_act = QAction("✎  Aktuellen Eintrag bearbeiten…", self.menu)
            edit_act.triggered.connect(lambda: self.open_quick_add(mode=QuickAddPopup.MODE_EDIT))
            self.menu.addAction(edit_act)
            switch_act = QAction("↻  Task wechseln…", self.menu)
            switch_act.triggered.connect(lambda: self.open_quick_add(mode=QuickAddPopup.MODE_SWITCH))
            self.menu.addAction(switch_act)
        else:
            header = QAction("⏱  Bereit", self.menu)
            header.setEnabled(False)
            self.menu.addAction(header)
            self.menu.addSeparator()
            quick_act = QAction("▶  Quick Start…", self.menu)
            quick_act.triggered.connect(lambda: self.open_quick_add())
            self.menu.addAction(quick_act)
            last = repo.last_log(self.conn)
            if last and last.task:
                last_act = QAction(f"↻  Last: {last.task}", self.menu)
                last_act.triggered.connect(lambda: self._restart(last.project_id, last.task, last.description))
                self.menu.addAction(last_act)
            recent_menu = self.menu.addMenu("↻  Recent Tasks")
            for task, project_id, label in repo.recent_unique_tasks(self.conn):
                act = QAction(f"{task}  ({label})", recent_menu)
                act.triggered.connect(
                    lambda _checked=False, pid=project_id, t=task: self._restart(pid, t, None)
                )
                recent_menu.addAction(act)
            if recent_menu.isEmpty():
                empty_act = QAction("(keine)", recent_menu)
                empty_act.setEnabled(False)
                recent_menu.addAction(empty_act)
        self.menu.addSeparator()
        show_act = QAction("▣  Fenster anzeigen", self.menu)
        show_act.triggered.connect(self.show_main_window)
        self.menu.addAction(show_act)
        settings_act = QAction("⚙  Einstellungen", self.menu)
        settings_act.triggered.connect(self._open_settings)
        self.menu.addAction(settings_act)
        self.menu.addSeparator()
        quit_act = QAction("⏻  Beenden", self.menu)
        quit_act.triggered.connect(self.window.request_quit)
        self.menu.addAction(quit_act)

    def _restart(self, project_id: int, task: str | None, description: str | None) -> None:
        self.timer.start(project_id=project_id, task=task, description=description)
        self._refresh_state()
        self.window.timer_tab.refresh()
        self.window.logs_tab.refresh()
        self.window.analytics_tab.refresh()
        self._rebuild_menu()

    def _toggle_timer(self) -> None:
        if self.timer.is_running():
            self.timer.stop()
        else:
            self.open_quick_add(anchor=self._tray_anchor())
            return
        self._refresh_state()
        self.window.timer_tab.refresh()
        self.window.logs_tab.refresh()
        self.window.analytics_tab.refresh()
        self._rebuild_menu()

    def _open_settings(self) -> None:
        from worklog.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.conn, parent=self.window)
        if dlg.exec():
            self.window.timer_tab.refresh()

    # ------------------ state / tooltip ------------------

    def _refresh_state(self) -> None:
        self.tray.setIcon(_build_icon(self.timer.is_running()))

    def _update_tooltip(self) -> None:
        cur = self.timer.current()
        if cur is None:
            self.tray.setToolTip("Worklog · bereit")
            return
        elapsed = (datetime.now().astimezone() - cur.started_at).total_seconds()
        parts = []
        if cur.task:
            parts.append(cur.task)
        if cur.description:
            parts.append(cur.description)
        parts.append(format_hms(int(max(0, elapsed))))
        self.tray.setToolTip(" · ".join(parts))
