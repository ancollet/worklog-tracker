from __future__ import annotations

import sqlite3

from PyQt6.QtCore import QPoint, QRectF
from PyQt6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.paths import icon_path
from worklog.services.timer import AlreadyRunningError, TimerService
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


def _entry_label(log: LogEntry, max_len: int = 70) -> str:
    """Menütext eines laufenden Eintrags: Projekt, Task, Beschreibung (soweit vorhanden)."""
    project = " · ".join(p for p in (log.customer_name, log.project_name) if p)
    parts = [p for p in (project, log.task, log.description) if p]
    text = " · ".join(parts) or f"Eintrag {log.id}"
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text.replace("&", "&&")  # "&" wäre sonst ein Mnemonic


def _running_count_text(count: int) -> str:
    if count == 0:
        return "bereit"
    return "1 laufender Eintrag" if count == 1 else f"{count} laufende Einträge"


class TrayController:
    def __init__(self, conn: sqlite3.Connection, timer: TimerService, window) -> None:
        self.conn = conn
        self.timer = timer
        self.window = window

        self.tray = QSystemTrayIcon(_build_icon(bool(timer.running_entries())))
        self.tray.setToolTip("Worklog")
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._on_activated)

        self._popup: QuickAddPopup | None = None

        self._rebuild_menu()
        self.tray.show()

        # rebuild menu when data changes
        self.window.data_changed.connect(self._rebuild_menu)

    # ------------------ public ------------------

    def open_quick_add(self, *, anchor=None) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._popup.activateWindow()
            return
        anchor = anchor or QCursor.pos()
        self._popup = QuickAddPopup(self.conn, self.timer, parent=None, anchor_global=anchor)
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
        # Klick öffnet immer Quick-Start, egal ob etwas läuft; nichts wird umgeschaltet.
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.MiddleClick,
        ):
            self.open_quick_add(anchor=self._tray_anchor())

    def _on_popup_closed(self, _result: int) -> None:
        self._popup = None
        self._after_change()

    def _tray_anchor(self) -> QPoint:
        geo = self.tray.geometry()
        if geo.isValid() and geo.width() > 0:
            return geo.center()
        return QCursor.pos()

    # ------------------ menu ------------------

    def _rebuild_menu(self) -> None:
        self.menu.clear()
        running = self.timer.running_entries()
        self._refresh_state(len(running))
        if running:
            header = QAction(f"▣  {_running_count_text(len(running))}", self.menu)
        else:
            header = QAction("⏱  Bereit", self.menu)
        header.setEnabled(False)
        self.menu.addAction(header)
        for log in running:
            stop_act = QAction(f"⏸  {_entry_label(log)}", self.menu)
            stop_act.setToolTip("Diesen Eintrag stoppen")
            stop_act.triggered.connect(
                lambda _checked=False, log_id=log.id: self._stop_entry(log_id)
            )
            self.menu.addAction(stop_act)
        if running:
            stop_all_act = QAction("⏹  Alle stoppen", self.menu)
            stop_all_act.triggered.connect(self._stop_all)
            self.menu.addAction(stop_all_act)
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
        """Startet einen zusätzlichen Eintrag; stoppt nichts (ADR-0001)."""
        try:
            self.timer.start_entry(project_id=project_id, task=task, description=description)
        except AlreadyRunningError:
            self.tray.showMessage("Worklog", "Dieser Eintrag läuft bereits.")
            return
        self._after_change()

    def _stop_entry(self, log_id: int) -> None:
        self.timer.stop_entry(log_id)
        self._after_change()

    def _stop_all(self) -> None:
        self.timer.stop_all()
        self._after_change()

    def _after_change(self) -> None:
        """Timer-Tab, Logs-Tab, Analytics und Tray nach Start/Stopp synchron halten."""
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

    def _refresh_state(self, running_count: int | None = None) -> None:
        if running_count is None:
            running_count = len(self.timer.running_entries())
        self.tray.setIcon(_build_icon(running_count > 0))
        self.tray.setToolTip(f"Worklog · {_running_count_text(running_count)}")
