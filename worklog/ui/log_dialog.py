from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QDateTime, Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services.rounding import format_hm_short, round_up_seconds
from worklog.services.timer import manual_log
from worklog.ui.completers import (
    make_description_completer,
    make_task_completer,
    refresh_description_completer,
    refresh_task_completer,
)

ROUNDING_CHOICES = [
    ("Default", None),
    ("Aus", 0),
    ("5 min", 5),
    ("10 min", 10),
    ("15 min", 15),
    ("30 min", 30),
    ("60 min", 60),
]


class LogDialog(QDialog):
    """Add or edit a manual log entry. Two modes: start/end vs date+duration."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        parent=None,
        log_id: Optional[int] = None,
    ) -> None:
        super().__init__(parent)
        self.conn = conn
        self.log_id = log_id
        # Original time-of-day of the edited entry; reused by the "Datum + Dauer"
        # mode on save so editing the duration doesn't move the entry to now.
        self._loaded_start_time = None
        # True while editing a laufender Eintrag: saving must not stop it.
        self._running = False
        self.setWindowTitle("Log bearbeiten" if log_id else "Add Log")
        self.setMinimumWidth(440)

        # Mode selector
        self.mode_se = QRadioButton("Start/End-Zeit")
        self.mode_dur = QRadioButton("Datum + Dauer")
        self.mode_dur.setChecked(True)
        mode_group = QButtonGroup(self)
        mode_group.addButton(self.mode_se)
        mode_group.addButton(self.mode_dur)

        # Mode pages
        self.start_edit = QDateTimeEdit(QDateTime.currentDateTime().addSecs(-3600))
        self.start_edit.setCalendarPopup(True)
        self.start_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.end_edit = QDateTimeEdit(QDateTime.currentDateTime())
        self.end_edit.setCalendarPopup(True)
        self.end_edit.setDisplayFormat("yyyy-MM-dd HH:mm")

        self.date_edit = QDateEdit(QDateTime.currentDateTime().date())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setSuffix(" h")
        self.duration_spin.setDecimals(2)
        self.duration_spin.setSingleStep(0.25)
        self.duration_spin.setMaximum(24.0)
        self.duration_spin.setValue(1.0)
        self.duration_label = QLabel("1h 0min")
        self.duration_spin.valueChanged.connect(self._update_duration_preview)

        page_se = QWidget()
        se_form = QFormLayout(page_se)
        se_form.addRow("Start:", self.start_edit)
        se_form.addRow("Ende:", self.end_edit)

        page_dur = QWidget()
        dur_form = QFormLayout(page_dur)
        dur_form.addRow("Datum:", self.date_edit)
        dur_row = QHBoxLayout()
        dur_row.addWidget(self.duration_spin)
        dur_row.addWidget(self.duration_label)
        dur_form.addRow("Dauer:", dur_row)

        self.stack = QStackedWidget()
        self.stack.addWidget(page_se)
        self.stack.addWidget(page_dur)
        self.stack.setCurrentIndex(1)
        self.mode_se.toggled.connect(lambda v: v and self.stack.setCurrentIndex(0))
        self.mode_dur.toggled.connect(lambda v: v and self.stack.setCurrentIndex(1))

        # Common fields
        self.project_combo = QComboBox()
        for proj in repo.list_projects(conn):
            self.project_combo.addItem(proj.display_name, proj.id)
        state = repo.get_app_state(conn)
        if state.last_project_id is not None:
            idx = self.project_combo.findData(state.last_project_id)
            if idx >= 0:
                self.project_combo.setCurrentIndex(idx)

        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("z.B. ACME-123")
        self.desc_input = QPlainTextEdit()
        self.desc_input.setPlaceholderText("Beschreibung")
        self.desc_input.setFixedHeight(72)

        self.task_completer = make_task_completer(self, conn)
        self.desc_completer = make_description_completer(self, conn)
        self.task_input.setCompleter(self.task_completer)

        self.round_combo = QComboBox()
        for label, val in ROUNDING_CHOICES:
            self.round_combo.addItem(label, val)
        self.round_preview = QLabel("")
        self.round_combo.currentIndexChanged.connect(self._update_duration_preview)

        # Layout
        outer = QVBoxLayout(self)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Modus:"))
        mode_row.addWidget(self.mode_se)
        mode_row.addWidget(self.mode_dur)
        mode_row.addStretch(1)
        outer.addLayout(mode_row)
        outer.addWidget(self.stack)
        self.running_hint = QLabel("Läuft gerade · Ende und Dauer entstehen erst beim Stoppen.")
        self.running_hint.setStyleSheet("color: #6B7280;")
        self.running_hint.setVisible(False)
        outer.addWidget(self.running_hint)

        common = QFormLayout()
        common.addRow("Projekt:", self.project_combo)
        common.addRow("Task:", self.task_input)
        common.addRow("Beschr.:", self.desc_input)
        round_row = QHBoxLayout()
        round_row.addWidget(self.round_combo)
        round_row.addWidget(self.round_preview, 1)
        common.addRow("Rundung:", round_row)
        outer.addLayout(common)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Speichern")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        self.task_input.editingFinished.connect(self._refresh_desc_suggestions)

        if log_id is not None:
            self._load(log_id)

        self._on_project_changed()
        self._update_duration_preview()

    # ------------------ helpers ------------------

    def _current_project_id(self) -> Optional[int]:
        data = self.project_combo.currentData()
        return int(data) if data is not None else None

    def _effective_round_minutes(self) -> Optional[int]:
        override = self.round_combo.currentData()
        if override is not None:
            return override
        pid = self._current_project_id()
        proj = repo.get_project(self.conn, pid) if pid else None
        state = repo.get_app_state(self.conn)
        if proj and proj.round_minutes is not None:
            return proj.round_minutes
        return state.default_round_minutes

    def _on_project_changed(self) -> None:
        refresh_task_completer(self.task_completer, self._current_project_id())
        self._refresh_desc_suggestions()

    def _refresh_desc_suggestions(self) -> None:
        refresh_description_completer(
            self.desc_completer,
            self._current_project_id(),
            self.task_input.text().strip() or None,
        )

    def _update_duration_preview(self) -> None:
        seconds = int(self.duration_spin.value() * 3600)
        self.duration_label.setText(format_hm_short(seconds))
        rounded = round_up_seconds(seconds, self._effective_round_minutes())
        self.round_preview.setText(f"→ {format_hm_short(rounded)}")

    # ------------------ load / save ------------------

    def _load(self, log_id: int) -> None:
        log = repo.get_log(self.conn, log_id)
        if log is None:
            return
        self.project_combo.setCurrentIndex(self.project_combo.findData(log.project_id))
        self.task_input.setText(log.task or "")
        self.desc_input.setPlainText(log.description or "")
        # Populate *both* mode pages from the entry so the original day/time is
        # preserved no matter which mode the user saves in (switching to
        # "Datum + Dauer" must not silently re-book the entry on today).
        if log.started_at:
            naive_start = log.started_at.replace(tzinfo=None)
            self._loaded_start_time = naive_start.time()
            self.start_edit.setDateTime(QDateTime(naive_start))
            self.date_edit.setDate(QDateTime(naive_start).date())
            self.duration_spin.setValue((log.duration_seconds or 0) / 3600)
        if log.ended_at:
            self.end_edit.setDateTime(QDateTime(log.ended_at.replace(tzinfo=None)))
            self.mode_se.setChecked(True)
        else:
            # Laufender Eintrag: nur der Start ist editierbar, kein Ende, keine Dauer.
            self._running = True
            self.mode_se.setChecked(True)
            self.mode_se.setEnabled(False)
            self.mode_dur.setEnabled(False)
            self.end_edit.setEnabled(False)
            self.round_combo.setEnabled(False)
            self.round_preview.setVisible(False)
            self.running_hint.setVisible(True)
        idx = self.round_combo.findData(log.rounded_to_minutes)
        self.round_combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _save(self) -> None:
        pid = self._current_project_id()
        if pid is None:
            QMessageBox.warning(self, "Fehler", "Bitte ein Projekt wählen.")
            return
        task = self.task_input.text().strip() or None
        description = self.desc_input.toPlainText().strip() or None
        round_minutes = self._effective_round_minutes()

        if self._running:
            log = repo.get_log(self.conn, self.log_id)
            # if it was stopped meanwhile (e.g. via tray), the normal path applies
            if log is not None and log.ended_at is None:
                if self._save_running(log, pid, task, description):
                    self.accept()
                return

        if self.mode_se.isChecked():
            start_dt = self.start_edit.dateTime().toPyDateTime().astimezone()
            end_dt = self.end_edit.dateTime().toPyDateTime().astimezone()
            if end_dt <= start_dt:
                QMessageBox.warning(self, "Fehler", "Ende muss nach dem Start liegen.")
                return
            raw = int((end_dt - start_dt).total_seconds())
            rounded = round_up_seconds(raw, round_minutes)
            ended_at = start_dt + timedelta(seconds=rounded)
            self._persist(
                project_id=pid, task=task, description=description,
                started_at=start_dt, ended_at=ended_at,
                duration_seconds=rounded, rounded_to_minutes=round_minutes,
            )
        else:
            date = self.date_edit.date().toPyDate()
            now = datetime.now().astimezone()
            tod = self._loaded_start_time or now.time().replace(minute=0, second=0, microsecond=0)
            start_dt = datetime(
                date.year, date.month, date.day, tod.hour, tod.minute, tzinfo=now.tzinfo
            )
            seconds = int(self.duration_spin.value() * 3600)
            if seconds <= 0:
                QMessageBox.warning(self, "Fehler", "Dauer muss > 0 sein.")
                return
            rounded = round_up_seconds(seconds, round_minutes)
            ended_at = start_dt + timedelta(seconds=rounded)
            self._persist(
                project_id=pid, task=task, description=description,
                started_at=start_dt, ended_at=ended_at,
                duration_seconds=rounded, rounded_to_minutes=round_minutes,
            )

        self.accept()

    def _save_running(
        self, log, project_id: int, task: Optional[str], description: Optional[str]
    ) -> bool:
        """Save a laufender Eintrag without giving it an end or a duration."""
        start_dt = self.start_edit.dateTime().toPyDateTime().astimezone()
        # the editor has minute precision; keep the stored start unless it was changed
        if start_dt == log.started_at.replace(second=0, microsecond=0):
            start_dt = log.started_at
        if start_dt > datetime.now().astimezone():
            QMessageBox.warning(self, "Fehler", "Start darf nicht in der Zukunft liegen.")
            return False
        repo.update_log(
            self.conn, self.log_id,
            project_id=project_id, task=task, description=description,
            started_at=start_dt.isoformat(timespec="seconds"),
            ended_at=None, duration_seconds=None, rounded_to_minutes=None,
        )
        return True

    def _persist(
        self,
        *,
        project_id: int,
        task: Optional[str],
        description: Optional[str],
        started_at: datetime,
        ended_at: datetime,
        duration_seconds: int,
        rounded_to_minutes: Optional[int],
    ) -> None:
        if self.log_id is None:
            repo.create_log(
                self.conn,
                project_id=project_id, task=task, description=description,
                started_at=started_at.isoformat(timespec="seconds"),
                ended_at=ended_at.isoformat(timespec="seconds"),
                duration_seconds=duration_seconds,
                rounded_to_minutes=rounded_to_minutes,
                is_manual=True,
            )
        else:
            repo.update_log(
                self.conn, self.log_id,
                project_id=project_id, task=task, description=description,
                started_at=started_at.isoformat(timespec="seconds"),
                ended_at=ended_at.isoformat(timespec="seconds"),
                duration_seconds=duration_seconds,
                rounded_to_minutes=rounded_to_minutes,
            )
