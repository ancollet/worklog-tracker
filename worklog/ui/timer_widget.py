from __future__ import annotations

import sqlite3
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QTimer, QUrl, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDesktopServices, QFont
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QTreeWidgetItemIterator,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.models import LogEntry
from worklog.services.entry_menu import target_log_ids
from worklog.services.move import (
    drop_changes_anything,
    drop_target_day,
    move_entries_to_date,
)
from worklog.services.rounding import format_hm_short, format_hms
from worklog.services.timer import AlreadyRunningError, TimerService, manual_log
from worklog.ui.completers import (
    make_description_completer,
    make_task_completer,
    refresh_description_completer,
    refresh_task_completer,
)
from worklog.ui.entry_context_menu import build_entry_context_menu, keep_selection_on_right_click
from worklog.ui.move_dialog import MOVE_REJECTIONS, show_move_rejected
from worklog.ui.snippet_button import with_snippet_button

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
    """Recent log entries grouped Month → Day → Entry, with Tags column (chips).

    Drag & Drop: Eintragszeilen can be dragged onto a Tageszeile or an
    Eintragszeile (target = that row's day). Qt never re-parents items; a drop
    calls the Verschieben operation and the tree is rebuilt from the database.
    """

    edit_requested = pyqtSignal(int)
    changed = pyqtSignal()  # a context-menu action or a drop changed data

    ROLE_LOG_ID = Qt.ItemDataRole.UserRole  # Eintragszeile only
    ROLE_DAY = Qt.ItemDataRole.UserRole + 1  # ISO date; Tageszeile and Eintragszeile
    ROLE_MONTH = Qt.ItemDataRole.UserRole + 2  # "YYYY-MM"; Monatszeile only

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
        keep_selection_on_right_click(self)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDragDropOverwriteMode(True)  # drop *on* a row, never between rows
        self.setDropIndicatorShown(True)

    def populate(self, logs: list[LogEntry]) -> None:
        collapsed = self._collapsed_keys()
        scroll = self.verticalScrollBar().value()
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
            month_key = f"{year:04d}-{month:02d}"
            month_item.setData(0, self.ROLE_MONTH, month_key)
            month_item.setFlags(
                month_item.flags() & ~(Qt.ItemFlag.ItemIsDragEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            )
            for col in range(len(self.COLUMNS)):
                month_item.setBackground(col, QColor("#E5E7EB"))
                month_item.setFont(col, bold)
            self.addTopLevelItem(month_item)
            month_item.setExpanded(month_key not in collapsed)

            for d, day_logs in days.items():
                day_label = f"{WEEKDAY_NAMES_DE[d.weekday()]}, {d.strftime('%d.%m.%Y')}"
                day_total = sum((log.duration_seconds or 0) for log in day_logs)
                day_row = [day_label, format_hm_short(day_total)] + [""] * (len(self.COLUMNS) - 2)
                day_item = QTreeWidgetItem(day_row)
                day_item.setData(0, self.ROLE_DAY, d.isoformat())
                day_item.setFlags(day_item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
                italic = QFont()
                italic.setItalic(True)
                for col in range(len(self.COLUMNS)):
                    day_item.setBackground(col, QColor("#F3F4F6"))
                    day_item.setFont(col, italic)
                month_item.addChild(day_item)
                day_item.setExpanded(d.isoformat() not in collapsed)

                for log in day_logs:
                    leaf = self._build_leaf(log)
                    day_item.addChild(leaf)
                    self.setItemWidget(leaf, self.COL_CUSTOMER, _make_project_chip_widget(log))
                    flags_widget = _make_flags_widget(log)
                    if flags_widget is not None:
                        self.setItemWidget(leaf, self.COL_TAGS, flags_widget)

        self.executeDelayedItemsLayout()  # scroll range is known only after the layout
        self.verticalScrollBar().setValue(scroll)

    def _collapsed_keys(self) -> set[str]:
        """Months ("YYYY-MM") and days (ISO date) the user has folded."""
        keys: set[str] = set()
        for i in range(self.topLevelItemCount()):
            month_item = self.topLevelItem(i)
            if not month_item.isExpanded():
                keys.add(month_item.data(0, self.ROLE_MONTH))
            for j in range(month_item.childCount()):
                day_item = month_item.child(j)
                if not day_item.isExpanded():
                    keys.add(day_item.data(0, self.ROLE_DAY))
        return keys

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
        leaf.setData(0, self.ROLE_DAY, log.started_at.date().isoformat())
        if log.ended_at is None:  # a laufender Eintrag stays on its day
            leaf.setFlags(leaf.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
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
        """Selected entries in visual (top-to-bottom) order."""
        ids: list[int] = []
        it = QTreeWidgetItemIterator(self)
        while it.value() is not None:
            item = it.value()
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data is not None and item.isSelected():
                ids.append(int(data))
            it += 1
        return ids

    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        clicked_id = item.data(0, Qt.ItemDataRole.UserRole)
        if clicked_id is None:
            return

        target_ids = target_log_ids(int(clicked_id), self._selected_log_ids())
        logs = [log for log in (repo.get_log(self.conn, i) for i in target_ids) if log is not None]
        if not logs:
            return
        menu = build_entry_context_menu(
            self, self.conn, logs,
            on_edit=self.edit_requested.emit,
            on_changed=self.changed.emit,
            move_anchor_id=int(clicked_id),
        )
        menu.exec(self.viewport().mapToGlobal(pos))
        menu.deleteLater()

    # ------------------ Drag & Drop ------------------

    def _dragged_items(self) -> list[QTreeWidgetItem]:
        """The selected Eintragszeilen; a selected laufender Eintrag counts too,
        so that the Verschieben operation can refuse the whole drop."""
        return [
            item for item in self.selectedItems()
            if item.data(0, self.ROLE_LOG_ID) is not None
        ]

    def _drop_day(self, event) -> Optional[date]:
        """The day this drag would be dropped on, or None when it is no drop target."""
        if event.source() is not self:
            return None
        item = self.itemAt(event.position().toPoint())
        row_day = item.data(0, self.ROLE_DAY) if item is not None else None
        return drop_target_day(
            date.fromisoformat(row_day) if row_day else None,
            [date.fromisoformat(i.data(0, self.ROLE_DAY)) for i in self._dragged_items()],
        )

    def dragEnterEvent(self, event) -> None:
        if event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        super().dragMoveEvent(event)  # auto-scroll and drop indicator
        if self._drop_day(event) is None:
            event.ignore()  # Monatszeile / empty area: "forbidden" cursor
        else:
            event.setDropAction(Qt.DropAction.MoveAction)
            event.accept()

    def dropEvent(self, event) -> None:
        # Never call super(): Qt must not re-parent or remove any item.
        target = self._drop_day(event)
        if target is None:
            event.ignore()
            return
        log_ids = self._selected_log_ids()
        days = [date.fromisoformat(i.data(0, self.ROLE_DAY)) for i in self._dragged_items()]
        # IgnoreAction keeps Qt from removing the dragged rows after a "move".
        event.setDropAction(Qt.DropAction.IgnoreAction)
        event.accept()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()
        if drop_changes_anything(target, days):
            # After the drag has ended: the tree is rebuilt and a message may pop up.
            QTimer.singleShot(0, lambda: self._move_dropped(log_ids, target))

    def _move_dropped(self, log_ids: list[int], target: date) -> None:
        try:
            move_entries_to_date(self.conn, log_ids, target)
        except MOVE_REJECTIONS as exc:
            show_move_rejected(self, exc)
            return
        self.changed.emit()


class RunningList(QTreeWidget):
    """Liste "Läuft gerade": eine Zeile pro laufendem Eintrag mit eigener Uhr und Stop-Button."""

    edit_requested = pyqtSignal(int)
    stop_requested = pyqtSignal(int)

    COLUMNS = ["Projekt", "Task", "Beschreibung", "Läuft", ""]
    COL_PROJECT, COL_TASK, COL_DESC, COL_CLOCK, COL_STOP = range(5)
    MAX_VISIBLE_ROWS = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._started_at: dict[int, datetime] = {}
        self.setHeaderLabels(self.COLUMNS)
        self.setRootIsDecorated(False)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        header = self.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(self.COL_PROJECT, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_TASK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_DESC, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_CLOCK, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_STOP, QHeaderView.ResizeMode.ResizeToContents)
        self.itemDoubleClicked.connect(self._on_double_click)

    def populate(self, logs: list[LogEntry]) -> None:
        self.clear()
        self._started_at = {}
        clock_font = QFont()
        clock_font.setFamily("monospace")
        clock_font.setBold(True)
        for log in logs:
            item = QTreeWidgetItem(["", log.task or "", log.description or "", "", ""])
            item.setData(0, Qt.ItemDataRole.UserRole, int(log.id))
            item.setToolTip(self.COL_DESC, log.description or "")
            item.setFont(self.COL_CLOCK, clock_font)
            item.setTextAlignment(
                self.COL_CLOCK, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.addTopLevelItem(item)
            self.setItemWidget(item, self.COL_PROJECT, _make_project_chip_widget(log))
            stop_button = QPushButton("⏸ Stop")
            stop_button.clicked.connect(
                lambda _checked=False, log_id=int(log.id): self.stop_requested.emit(log_id)
            )
            self.setItemWidget(item, self.COL_STOP, stop_button)
            self._started_at[int(log.id)] = log.started_at
        self.tick()
        self._fit_height()

    def log_ids(self) -> list[int]:
        return [
            int(self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole))
            for i in range(self.topLevelItemCount())
        ]

    def tick(self) -> None:
        """Update every row's clock from its own start."""
        now = datetime.now().astimezone()
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            started = self._started_at.get(int(item.data(0, Qt.ItemDataRole.UserRole)))
            if started is None:
                continue
            elapsed = (now - started).total_seconds()
            item.setText(self.COL_CLOCK, format_hms(int(max(0, elapsed))))

    def _fit_height(self) -> None:
        rows = self.topLevelItemCount()
        if rows == 0:
            return
        row_height = max(self.sizeHintForRow(0), 28)
        visible = min(rows, self.MAX_VISIBLE_ROWS)
        self.setFixedHeight(self.header().sizeHint().height() + visible * row_height + 2 * self.frameWidth())

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        log_id = item.data(0, Qt.ItemDataRole.UserRole)
        if log_id is not None:
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

        self.running_label = QLabel("Läuft gerade   ·   Doppelklick zum Bearbeiten")
        self.running_label.setStyleSheet("color: #6B7280;")
        self.running_list = RunningList(self)
        self.running_list.edit_requested.connect(self._edit_log)
        self.running_list.stop_requested.connect(self._stop_entry)

        self.start_button = QPushButton("▶ Start")
        self.start_button.setToolTip("Startet einen neuen Eintrag; laufende Einträge laufen weiter (Ctrl+S).")
        self.start_button.setMinimumHeight(48)
        self.start_button.clicked.connect(self.start_from_form)

        self.start_hint = QLabel("")
        self.start_hint.setStyleSheet("color: #B45309;")
        self.start_hint.setVisible(False)

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
        self.recent_tree.changed.connect(self.changed.emit)

        # Layout
        outer = QVBoxLayout(self)

        outer.addWidget(self.running_label)
        outer.addWidget(self.running_list)

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
        row3.addWidget(with_snippet_button(conn, self.desc_input), 1)
        outer.addLayout(row3)

        timer_row = QHBoxLayout()
        timer_row.addWidget(self.start_button)
        timer_row.addWidget(self.start_hint, 1)
        timer_row.addSpacing(16)
        timer_row.addWidget(self.quick_duration)
        timer_row.addWidget(self.quick_log_button)
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
        self._reload_running()
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

    def start_from_form(self) -> None:
        """Start a new laufender Eintrag from the form; never stops anything."""
        pid = self.current_project_id()
        if pid is None:
            QMessageBox.information(self, "Kein Projekt", "Bitte erst ein Projekt anlegen.")
            return
        try:
            self.timer.start_entry(
                project_id=pid,
                task=self.task_input.text().strip() or None,
                description=self.desc_input.text().strip() or None,
            )
        except AlreadyRunningError:
            self._show_start_hint("Dieser Eintrag läuft bereits.")
            return
        self._show_start_hint("")
        # Projekt bleibt; Task und Beschreibung gehören zum gestarteten Eintrag.
        self.task_input.clear()
        self.desc_input.clear()
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

    def _reload_running(self) -> None:
        running = self.timer.running_entries()
        self.running_list.populate(running)
        self.running_label.setVisible(bool(running))
        self.running_list.setVisible(bool(running))

    def _stop_entry(self, log_id: int) -> None:
        self.timer.stop_entry(log_id)
        self.changed.emit()

    def _show_start_hint(self, text: str) -> None:
        self.start_hint.setText(text)
        self.start_hint.setVisible(bool(text))
        if text:
            QTimer.singleShot(4000, lambda: self._show_start_hint("") if self.start_hint.text() == text else None)

    def _on_tick(self) -> None:
        self.running_list.tick()

    def _on_project_changed(self) -> None:
        refresh_task_completer(self.task_completer, self.current_project_id())
        self._refresh_desc_suggestions()

    def _refresh_desc_suggestions(self) -> None:
        refresh_description_completer(
            self.desc_completer,
            self.current_project_id(),
            self.task_input.text().strip() or None,
        )
