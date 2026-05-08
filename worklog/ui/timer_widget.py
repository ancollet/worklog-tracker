from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
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
from worklog.services.timer import TimerService, manual_log
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


def _readable_text_color(bg_hex: str) -> str:
    """Return '#000' or '#fff' depending on background luminance."""
    c = QColor(bg_hex)
    if not c.isValid():
        return "#000"
    # Rec. 709 luma
    luma = 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()
    return "#000" if luma > 160 else "#fff"


def _make_chip(text: str, bg_hex: Optional[str], tooltip: Optional[str] = None) -> QLabel:
    bg = bg_hex if bg_hex and QColor(bg_hex).isValid() else "#9CA3AF"
    fg = _readable_text_color(bg)
    label = QLabel(text)
    label.setStyleSheet(
        f"QLabel {{ background-color: {bg}; color: {fg}; "
        f"padding: 2px 8px; border-radius: 8px; font-size: 11px; }}"
    )
    if tooltip:
        label.setToolTip(tooltip)
    return label


def _make_flags_widget(log: LogEntry) -> Optional[QWidget]:
    """Return a widget with chips for each user-defined flag, or None if no flags."""
    if not log.flags:
        return None
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(2, 1, 2, 1)
    layout.setSpacing(4)
    for flag in log.flags:
        layout.addWidget(_make_chip(flag.name, flag.color))
    layout.addStretch(1)
    return w


def _make_project_chip_widget(log: LogEntry) -> QWidget:
    """Single chip showing 'Customer · Project' in project color."""
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(2, 1, 2, 1)
    layout.setSpacing(0)
    if log.customer_name and log.project_name:
        text = f"{log.customer_name} · {log.project_name}"
    else:
        text = log.project_name or log.customer_name or "?"
    tooltip = log.project_name or ""
    layout.addWidget(_make_chip(text, log.project_color, tooltip=tooltip))
    layout.addStretch(1)
    return w


class RecentTree(QTreeWidget):
    """Recent log entries grouped Month → Day → Entry, with Tags column (chips)."""

    edit_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(list)  # list[int]
    flags_apply_requested = pyqtSignal(list, int, bool)  # log_ids, flag_id, enabled
    manage_flags_requested = pyqtSignal()

    COLUMNS = ["Zeit", "Dauer", "Task", "Beschreibung", "Kunde", "Tags"]
    COL_TIME, COL_DURATION, COL_TASK, COL_DESC, COL_CUSTOMER, COL_TAGS = range(6)

    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self.setHeaderLabels(self.COLUMNS)
        self.setRootIsDecorated(True)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        header = self.header()
        header.setSectionResizeMode(self.COL_TIME, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_TASK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_DESC, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_CUSTOMER, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_TAGS, QHeaderView.ResizeMode.Interactive)
        self.setColumnWidth(self.COL_TAGS, 180)
        self.itemDoubleClicked.connect(self._on_double_click)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

    def populate(self, logs: list[LogEntry]) -> None:
        self.clear()

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
            month_row = [month_label, format_hm_short(month_total)] + [""] * (len(self.COLUMNS) - 2)
            month_item = QTreeWidgetItem(month_row)
            for col in range(len(self.COLUMNS)):
                month_item.setBackground(col, QColor("#E5E7EB"))
                month_item.setFont(col, bold)
            self.addTopLevelItem(month_item)
            month_item.setExpanded(True)

            for d, day_logs in days.items():
                day_label = f"{WEEKDAY_NAMES_DE[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
                day_total = sum((log.duration_seconds or 0) for log in day_logs)
                day_row = [day_label, format_hm_short(day_total)] + [""] * (len(self.COLUMNS) - 2)
                day_item = QTreeWidgetItem(day_row)
                italic = QFont()
                italic.setItalic(True)
                for col in range(len(self.COLUMNS)):
                    day_item.setBackground(col, QColor("#F3F4F6"))
                    day_item.setFont(col, italic)
                month_item.addChild(day_item)
                day_item.setExpanded(True)

                for log in day_logs:
                    leaf = self._build_leaf(log)
                    day_item.addChild(leaf)
                    self.setItemWidget(leaf, self.COL_CUSTOMER, _make_project_chip_widget(log))
                    flags_widget = _make_flags_widget(log)
                    if flags_widget is not None:
                        self.setItemWidget(leaf, self.COL_TAGS, flags_widget)

    def _build_leaf(self, log: LogEntry) -> QTreeWidgetItem:
        time_str = "—"
        if log.started_at and log.ended_at:
            time_str = f"{log.started_at.strftime('%H:%M')}–{log.ended_at.strftime('%H:%M')}"
        elif log.started_at:
            time_str = f"{log.started_at.strftime('%H:%M')}–…"

        duration = format_hm_short(log.duration_seconds) if log.duration_seconds else "läuft…"
        leaf = QTreeWidgetItem(
            [time_str, duration, log.task or "", log.description or "", "", ""]
        )
        leaf.setData(0, Qt.ItemDataRole.UserRole, int(log.id))
        leaf.setToolTip(self.COL_DESC, log.description or "")
        leaf.setTextAlignment(
            self.COL_DURATION, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        return leaf

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        log_id = item.data(0, Qt.ItemDataRole.UserRole)
        if log_id is not None:
            self.edit_requested.emit(int(log_id))

    def _selected_log_ids(self) -> list[int]:
        ids: list[int] = []
        for it in self.selectedItems():
            data = it.data(0, Qt.ItemDataRole.UserRole)
            if data is not None:
                ids.append(int(data))
        return ids

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        clicked_id = item.data(0, Qt.ItemDataRole.UserRole)
        if clicked_id is None:
            return
        clicked_id = int(clicked_id)

        selected_ids = self._selected_log_ids()
        # If user right-clicks an unselected leaf, operate on just that one
        # but don't disturb their selection.
        if clicked_id not in selected_ids:
            target_ids = [clicked_id]
        else:
            target_ids = selected_ids
        n = len(target_ids)

        menu = QMenu(self)
        header = QAction(f"{n} Eintrag" + ("e" if n != 1 else "") + " ausgewählt", menu)
        header.setEnabled(False)
        menu.addAction(header)
        menu.addSeparator()

        edit_act = QAction("✎  Bearbeiten…", menu)
        edit_act.setEnabled(n == 1)
        if n == 1:
            edit_act.triggered.connect(lambda: self.edit_requested.emit(target_ids[0]))
        menu.addAction(edit_act)

        flags_menu = menu.addMenu("⚑  Flags")
        flags = repo.list_flags(self.conn)
        if not flags:
            empty = QAction("(keine Flags – verwalten…)", flags_menu)
            empty.setEnabled(False)
            flags_menu.addAction(empty)
        else:
            counts = repo.count_logs_with_flag(self.conn, target_ids)
            for flag in flags:
                have = counts.get(flag.id, 0)
                if have == n:
                    state_label = flag.name
                    new_state = False
                    checked = True
                elif have == 0:
                    state_label = flag.name
                    new_state = True
                    checked = False
                else:
                    state_label = f"{flag.name}  (gemischt: {have}/{n})"
                    new_state = True
                    checked = False
                act = QAction(state_label, flags_menu)
                act.setCheckable(True)
                act.setChecked(checked)
                act.triggered.connect(
                    lambda _checked=False, fid=flag.id, ids=list(target_ids), s=new_state:
                        self.flags_apply_requested.emit(ids, fid, s)
                )
                flags_menu.addAction(act)
        flags_menu.addSeparator()
        manage = QAction("⚙  Flags verwalten…", flags_menu)
        manage.triggered.connect(self.manage_flags_requested.emit)
        flags_menu.addAction(manage)

        menu.addSeparator()
        del_act = QAction(
            "⌫  Löschen" if n == 1 else f"⌫  {n} Einträge löschen", menu
        )
        del_act.triggered.connect(
            lambda _checked=False, ids=list(target_ids): self.delete_requested.emit(ids)
        )
        menu.addAction(del_act)

        menu.exec(self.viewport().mapToGlobal(pos))


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

        self.quick_duration = QDoubleSpinBox()
        self.quick_duration.setSuffix(" h")
        self.quick_duration.setDecimals(2)
        self.quick_duration.setSingleStep(0.25)
        self.quick_duration.setMinimum(0.0)
        self.quick_duration.setMaximum(24.0)
        self.quick_duration.setValue(1.0)
        self.quick_duration.setToolTip("Dauer für Schnell-Buchung")

        self.quick_log_button = QPushButton("+ Buchen")
        self.quick_log_button.setToolTip(
            "Erstellt einen Log-Eintrag mit den aktuellen Feldern und der angegebenen Dauer "
            "(endet jetzt, Start = jetzt − Dauer)."
        )
        self.quick_log_button.setMinimumHeight(48)
        self.quick_log_button.clicked.connect(self.quick_log)

        self.add_log_button = QPushButton("+ Add Log…")
        self.add_log_button.setToolTip("Voller Log-Dialog mit Datum/Modi-Auswahl")
        self.add_log_button.clicked.connect(self.open_add_log)
        self.flags_button = QPushButton("⚑ Flags")
        self.flags_button.setToolTip("Benutzerdefinierte Flags verwalten")
        self.flags_button.clicked.connect(self.open_flags_dialog)
        self.clockwork_button = QPushButton("↗ Jira Clockwork")
        self.clockwork_button.setToolTip("Öffnet den Clockwork 'My Work'-Report im Browser")
        self.clockwork_button.clicked.connect(self.open_clockwork)
        self.settings_button = QPushButton("⚙ Einstellungen")
        self.settings_button.clicked.connect(self.open_settings)

        self.summary_label = QLabel("Heute: —     ·     Diese Woche: —")
        self.recent_tree = RecentTree(conn, self)
        self.recent_tree.edit_requested.connect(self._edit_log)
        self.recent_tree.delete_requested.connect(self._delete_logs)
        self.recent_tree.flags_apply_requested.connect(self._apply_flag)
        self.recent_tree.manage_flags_requested.connect(self.open_flags_dialog)

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
        timer_row.addSpacing(16)
        timer_row.addWidget(self.quick_duration)
        timer_row.addWidget(self.quick_log_button)
        timer_row.addStretch(1)
        outer.addLayout(timer_row)

        outer.addWidget(self.summary_label)

        recent_label = QLabel("Letzte Einträge   ·   Doppelklick zum Bearbeiten · Rechtsklick für Flags")
        recent_label.setStyleSheet("color: #6B7280;")
        outer.addWidget(recent_label)
        outer.addWidget(self.recent_tree, 1)

        bottom = QHBoxLayout()
        bottom.addWidget(self.add_log_button)
        bottom.addWidget(self.flags_button)
        bottom.addWidget(self.clockwork_button)
        bottom.addStretch(1)
        bottom.addWidget(self.settings_button)
        outer.addLayout(bottom)

        # signals
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.task_input.editingFinished.connect(self._refresh_desc_suggestions)

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

    def open_flags_dialog(self) -> None:
        from worklog.ui.flags_dialog import FlagsDialog
        dlg = FlagsDialog(self.conn, parent=self)
        if dlg.exec():
            self.changed.emit()

    def open_clockwork(self) -> None:
        QDesktopServices.openUrl(QUrl(CLOCKWORK_URL))

    def quick_log(self) -> None:
        """Create a manual log using current form fields + the duration spinbox."""
        pid = self.current_project_id()
        if pid is None:
            QMessageBox.information(self, "Kein Projekt", "Bitte erst ein Projekt anlegen.")
            return
        hours = self.quick_duration.value()
        if hours <= 0:
            QMessageBox.information(self, "Dauer", "Dauer muss > 0 sein.")
            return
        duration_seconds = int(round(hours * 3600))
        end = datetime.now().astimezone()
        start = end - timedelta(seconds=duration_seconds)
        manual_log(
            self.conn,
            project_id=pid,
            task=self.task_input.text().strip() or None,
            description=self.desc_input.text().strip() or None,
            started_at=start,
            duration_seconds=duration_seconds,
            round_minutes=None,
        )
        self.changed.emit()

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

    def _delete_logs(self, log_ids: list[int]) -> None:
        if not log_ids:
            return
        msg = (
            "Diesen Eintrag wirklich löschen?"
            if len(log_ids) == 1
            else f"{len(log_ids)} Einträge wirklich löschen?"
        )
        confirm = QMessageBox.question(self, "Löschen?", msg)
        if confirm != QMessageBox.StandardButton.Yes:
            return
        repo.delete_logs_bulk(self.conn, log_ids)
        self.changed.emit()

    def _apply_flag(self, log_ids: list, flag_id: int, enabled: bool) -> None:
        if not log_ids:
            return
        repo.set_log_flag_bulk(self.conn, [int(x) for x in log_ids], int(flag_id), bool(enabled))
        self.changed.emit()

    def _reload_projects(self) -> None:
        prev = self.current_project_id()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        for proj in repo.list_projects(self.conn):
            self.project_combo.addItem(proj.display_name, proj.id)
        self.project_combo.blockSignals(False)
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
