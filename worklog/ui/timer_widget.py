from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import date, datetime
from typing import Optional

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.rounding import format_hm_short, format_hms
from worklog.services.timer import TimerService
from worklog.ui.completers import (
    make_description_completer,
    make_task_completer,
    refresh_description_completer,
    refresh_task_completer,
)

CLOCKWORK_URL = (
    "https://igusdev.atlassian.net/plugins/servlet/ac/clockwork-free-cloud/clockwork-mywork"
    "?project.key=DIS&project.id=11541#!reportName=My%20Work"
    "&scope%5BstartingAt%5D=LAST_7_DAYS_START&scope%5BendingAt%5D=LAST_7_DAYS_END"
    "&selectedBreakdowns%5B%5D=issues&period=PERIOD_DAY&additionalColumn="
    "&activeColumnFormat=time"
)

MONTH_NAMES_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]
WEEKDAY_NAMES_DE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start.replace(hour=23, minute=59, second=59)


def _week_bounds(now: datetime) -> tuple[datetime, datetime]:
    start_naive = datetime.fromordinal(now.toordinal() - now.weekday())
    monday = start_naive.replace(tzinfo=now.tzinfo)
    sunday_end = datetime.fromordinal(monday.toordinal() + 7).replace(tzinfo=now.tzinfo)
    return monday, sunday_end


def _soft_tint(hex_color: Optional[str]) -> Optional[QColor]:
    """Mix the project color heavily with white for a readable row tint."""
    if not hex_color:
        return None
    c = QColor(hex_color)
    if not c.isValid():
        return None
    r = int(c.red() * 0.22 + 255 * 0.78)
    g = int(c.green() * 0.22 + 255 * 0.78)
    b = int(c.blue() * 0.22 + 255 * 0.78)
    return QColor(r, g, b)


class RecentTree(QTreeWidget):
    """Recent log entries grouped Month → Day → Entry, color-tinted by project."""

    edit_requested = pyqtSignal(int)

    COLUMNS = ["Zeit", "Dauer", "Projekt / Kunde", "Task", "Beschreibung"]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(self.COLUMNS)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(False)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.itemDoubleClicked.connect(self._on_double_click)

    def populate(self, logs: list[LogEntry]) -> None:
        self.clear()

        # Group: month → day → logs (insertion order = newest first since logs come DESC)
        months: "OrderedDict[tuple[int, int], OrderedDict[date, list[LogEntry]]]" = OrderedDict()
        for log in logs:
            if not log.started_at:
                continue
            ym = (log.started_at.year, log.started_at.month)
            d = log.started_at.date()
            months.setdefault(ym, OrderedDict()).setdefault(d, []).append(log)

        bold = QFont()
        bold.setBold(True)

        for (year, month), days in months.items():
            month_label = f"{MONTH_NAMES_DE[month - 1]} {year}"
            month_total = sum(
                (log.duration_seconds or 0) for day_logs in days.values() for log in day_logs
            )
            month_item = QTreeWidgetItem([month_label, format_hm_short(month_total), "", "", ""])
            month_item.setFirstColumnSpanned(False)
            for col in range(len(self.COLUMNS)):
                month_item.setBackground(col, QColor("#E5E7EB"))
                month_item.setFont(col, bold)
            self.addTopLevelItem(month_item)
            month_item.setExpanded(True)

            for d, day_logs in days.items():
                day_label = f"{WEEKDAY_NAMES_DE[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
                day_total = sum((log.duration_seconds or 0) for log in day_logs)
                day_item = QTreeWidgetItem([day_label, format_hm_short(day_total), "", "", ""])
                for col in range(len(self.COLUMNS)):
                    day_item.setBackground(col, QColor("#F3F4F6"))
                    f = QFont()
                    f.setItalic(True)
                    day_item.setFont(col, f)
                month_item.addChild(day_item)
                day_item.setExpanded(True)

                for log in day_logs:
                    leaf = self._build_leaf(log)
                    day_item.addChild(leaf)

    def _build_leaf(self, log: LogEntry) -> QTreeWidgetItem:
        time_str = "—"
        if log.started_at and log.ended_at:
            time_str = f"{log.started_at.strftime('%H:%M')}–{log.ended_at.strftime('%H:%M')}"
        elif log.started_at:
            time_str = f"{log.started_at.strftime('%H:%M')}–…"

        duration = (
            format_hm_short(log.duration_seconds) if log.duration_seconds else "läuft…"
        )

        project_str = ""
        if log.customer_name and log.project_name:
            project_str = f"{log.customer_name} · {log.project_name}"
        elif log.project_name:
            project_str = log.project_name

        leaf = QTreeWidgetItem(
            [time_str, duration, project_str, log.task or "", log.description or ""]
        )
        leaf.setData(0, Qt.ItemDataRole.UserRole, int(log.id))
        leaf.setToolTip(4, log.description or "")

        tint = _soft_tint(log.project_color)
        if tint is not None:
            for col in range(len(self.COLUMNS)):
                leaf.setBackground(col, tint)

        leaf.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return leaf

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        log_id = item.data(0, Qt.ItemDataRole.UserRole)
        if log_id is None:
            return
        self.edit_requested.emit(int(log_id))


class TimerWidget(QWidget):
    changed = pyqtSignal()

    def __init__(self, conn: sqlite3.Connection, timer: TimerService, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.timer = timer

        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(280)
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("z.B. ACME-123")
        self.desc_input = QLineEdit()
        self.desc_input.setPlaceholderText("Kurzbeschreibung")

        self.task_completer = make_task_completer(self, conn)
        self.desc_completer = make_description_completer(self, conn)
        self.task_input.setCompleter(self.task_completer)
        self.desc_input.setCompleter(self.desc_completer)

        self.display = QLabel("00:00:00")
        f = QFont()
        f.setPointSize(36)
        f.setBold(True)
        f.setFamily("monospace")
        self.display.setFont(f)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.start_button = QPushButton("▶ Start")
        self.start_button.setMinimumHeight(48)
        self.start_button.clicked.connect(self.toggle_start_stop)

        self.add_log_button = QPushButton("+ Add Log")
        self.add_log_button.clicked.connect(self.open_add_log)
        self.clockwork_button = QPushButton("↗ Jira Clockwork")
        self.clockwork_button.setToolTip("Öffnet den Clockwork 'My Work'-Report im Browser")
        self.clockwork_button.clicked.connect(self.open_clockwork)
        self.settings_button = QPushButton("⚙ Einstellungen")
        self.settings_button.clicked.connect(self.open_settings)

        self.summary_label = QLabel("Heute: —     ·     Diese Woche: —")
        self.recent_tree = RecentTree(self)
        self.recent_tree.edit_requested.connect(self._edit_log)

        # Layout
        outer = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Projekt:"))
        row.addWidget(self.project_combo, 1)
        outer.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Task:"))
        row2.addWidget(self.task_input, 1)
        outer.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Beschr.:"))
        row3.addWidget(self.desc_input, 1)
        outer.addLayout(row3)

        timer_row = QHBoxLayout()
        timer_row.addStretch(1)
        timer_row.addWidget(self.display, 2)
        timer_row.addWidget(self.start_button)
        timer_row.addStretch(1)
        outer.addLayout(timer_row)

        outer.addWidget(self.summary_label)

        recent_label = QLabel("Letzte Einträge   ·   Doppelklick zum Bearbeiten")
        recent_label.setStyleSheet("color: #6B7280;")
        outer.addWidget(recent_label)
        outer.addWidget(self.recent_tree, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self.add_log_button)
        bottom.addWidget(self.clockwork_button)
        bottom.addStretch(1)
        bottom.addWidget(self.settings_button)
        outer.addLayout(bottom)

        # signals
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.task_input.editingFinished.connect(self._refresh_desc_suggestions)

        # 1Hz tick for live display
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)
        self._tick.start()

        self.refresh()

    # ------------------ public ------------------

    def refresh(self) -> None:
        self._reload_projects()
        self._reload_recent()
        self._reload_summary()
        self._sync_running_state()
        refresh_task_completer(self.task_completer, self.current_project_id())

    def open_add_log(self) -> None:
        from worklog.ui.log_dialog import LogDialog
        dlg = LogDialog(self.conn, parent=self)
        if dlg.exec():
            self.changed.emit()

    def open_settings(self) -> None:
        from worklog.ui.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.conn, parent=self)
        if dlg.exec():
            self.changed.emit()

    def open_clockwork(self) -> None:
        QDesktopServices.openUrl(QUrl(CLOCKWORK_URL))

    def toggle_start_stop(self) -> None:
        if self.timer.is_running():
            self.timer.stop()
            self.changed.emit()
        else:
            pid = self.current_project_id()
            if pid is None:
                QMessageBox.information(self, "Kein Projekt", "Bitte erst ein Projekt anlegen.")
                return
            self.timer.start(
                project_id=pid,
                task=self.task_input.text().strip() or None,
                description=self.desc_input.text().strip() or None,
            )
            self.changed.emit()

    def current_project_id(self) -> Optional[int]:
        data = self.project_combo.currentData()
        return int(data) if data is not None else None

    # ------------------ internals ------------------

    def _edit_log(self, log_id: int) -> None:
        from worklog.ui.log_dialog import LogDialog
        dlg = LogDialog(self.conn, parent=self, log_id=log_id)
        if dlg.exec():
            self.changed.emit()

    def _reload_projects(self) -> None:
        prev = self.current_project_id()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for proj in repo.list_projects(self.conn):
            self.project_combo.addItem(proj.display_name, proj.id)
        self.project_combo.blockSignals(False)
        # restore selection
        state = repo.get_app_state(self.conn)
        target = prev if prev is not None else state.last_project_id
        if target is not None:
            idx = self.project_combo.findData(target)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)

    def _reload_recent(self) -> None:
        logs = repo.list_logs(self.conn, limit=80)
        self.recent_tree.populate(logs)

    def _reload_summary(self) -> None:
        now = datetime.now().astimezone()
        d_start, d_end = _day_bounds(now)
        w_start, w_end = _week_bounds(now)
        today = repo.sum_duration(
            self.conn,
            from_iso=d_start.isoformat(timespec="seconds"),
            to_iso=d_end.isoformat(timespec="seconds"),
        )
        week = repo.sum_duration(
            self.conn,
            from_iso=w_start.isoformat(timespec="seconds"),
            to_iso=w_end.isoformat(timespec="seconds"),
        )
        self.summary_label.setText(
            f"Heute: {format_hm_short(today)}     ·     Diese Woche: {format_hm_short(week)}"
        )

    def _sync_running_state(self) -> None:
        cur = self.timer.current()
        if cur is None:
            self.start_button.setText("▶ Start")
            self.display.setText("00:00:00")
            return
        self.start_button.setText("⏸ Stop")
        if cur.project_id is not None:
            idx = self.project_combo.findData(cur.project_id)
            if idx >= 0:
                self.project_combo.blockSignals(True)
                self.project_combo.setCurrentIndex(idx)
                self.project_combo.blockSignals(False)
        if cur.task and self.task_input.text() != cur.task:
            self.task_input.setText(cur.task)
        if cur.description and self.desc_input.text() != cur.description:
            self.desc_input.setText(cur.description)

    def _on_tick(self) -> None:
        cur = self.timer.current()
        if cur is None:
            return
        elapsed = (datetime.now().astimezone() - cur.started_at).total_seconds()
        self.display.setText(format_hms(int(max(0, elapsed))))

    def _on_project_changed(self) -> None:
        refresh_task_completer(self.task_completer, self.current_project_id())
        self._refresh_desc_suggestions()

    def _refresh_desc_suggestions(self) -> None:
        refresh_description_completer(
            self.desc_completer,
            self.current_project_id(),
            self.task_input.text().strip() or None,
        )
