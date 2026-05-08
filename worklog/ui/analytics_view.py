from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCharts import QBarCategoryAxis, QBarSet, QChart, QChartView, QStackedBarSeries, QValueAxis
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from worklog import repository as repo
from worklog.services.analytics import AggRow, Bucket, GroupBy, aggregate
from worklog.services.rounding import format_hm_short, format_hours_decimal


PRESETS = [
    ("Heute", "today"),
    ("Diese Woche", "week"),
    ("Dieser Monat", "month"),
    ("Letzte 30 Tage", "last30"),
    ("Custom", "custom"),
]

PALETTE = [
    "#3B82F6", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6",
    "#06B6D4", "#EC4899", "#84CC16", "#F97316", "#6366F1",
]


def _preset_range(key: str) -> tuple[datetime, datetime]:
    now = datetime.now().astimezone()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if key == "today":
        return today, today + timedelta(days=1)
    if key == "week":
        from datetime import datetime as _dt
        monday = _dt.fromordinal(today.toordinal() - today.weekday()).replace(tzinfo=now.tzinfo)
        return monday, monday + timedelta(days=7)
    if key == "month":
        first = today.replace(day=1)
        if first.month == 12:
            next_month = first.replace(year=first.year + 1, month=1)
        else:
            next_month = first.replace(month=first.month + 1)
        return first, next_month
    if key == "last30":
        return today - timedelta(days=30), today + timedelta(days=1)
    return today, today + timedelta(days=1)


class AnalyticsView(QWidget):
    def __init__(self, conn: sqlite3.Connection, parent=None) -> None:
        super().__init__(parent)
        self.conn = conn
        self._rows: list[AggRow] = []

        self.preset_combo = QComboBox()
        for label, key in PRESETS:
            self.preset_combo.addItem(label, key)
        self.preset_combo.setCurrentIndex(1)
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)

        self.from_edit = QDateEdit()
        self.from_edit.setCalendarPopup(True)
        self.from_edit.setDisplayFormat("yyyy-MM-dd")
        self.to_edit = QDateEdit()
        self.to_edit.setCalendarPopup(True)
        self.to_edit.setDisplayFormat("yyyy-MM-dd")
        self.from_edit.dateChanged.connect(self.refresh)
        self.to_edit.dateChanged.connect(self.refresh)

        self.bucket_combo = QComboBox()
        for b in Bucket:
            self.bucket_combo.addItem({"day": "Tag", "week": "Woche", "month": "Monat"}[b.value], b)
        self.bucket_combo.currentIndexChanged.connect(self.refresh)

        self.group_combo = QComboBox()
        for g, label in [(GroupBy.PROJECT, "Projekt"), (GroupBy.CUSTOMER, "Kunde"), (GroupBy.NONE, "—")]:
            self.group_combo.addItem(label, g)
        self.group_combo.currentIndexChanged.connect(self.refresh)

        self.customer_combo = QComboBox()
        self.customer_combo.addItem("Alle Kunden", None)
        for c in repo.list_customers(conn):
            self.customer_combo.addItem(c.name, c.id)
        self.customer_combo.currentIndexChanged.connect(self.refresh)

        self.export_btn = QPushButton("↓ Export CSV")
        self.export_btn.clicked.connect(self._export_csv)

        # Table + chart
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Bucket", "Gruppe", "Stunden"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.total_label = QLabel("Σ —")

        self.chart_view = QChartView()
        self.chart_view.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Layout
        outer = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Zeitraum:"))
        filter_row.addWidget(self.preset_combo)
        filter_row.addWidget(QLabel("von"))
        filter_row.addWidget(self.from_edit)
        filter_row.addWidget(QLabel("bis"))
        filter_row.addWidget(self.to_edit)
        outer.addLayout(filter_row)

        group_row = QHBoxLayout()
        group_row.addWidget(QLabel("Gruppe:"))
        group_row.addWidget(self.bucket_combo)
        group_row.addWidget(QLabel("Sub:"))
        group_row.addWidget(self.group_combo)
        group_row.addWidget(QLabel("Filter:"))
        group_row.addWidget(self.customer_combo)
        group_row.addStretch(1)
        group_row.addWidget(self.export_btn)
        outer.addLayout(group_row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.addWidget(self.table, 1)
        left_l.addWidget(self.total_label)
        splitter.addWidget(left)
        splitter.addWidget(self.chart_view)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self._apply_preset()
        self.refresh()

    # ------------------ public ------------------

    def refresh(self) -> None:
        from_dt = self.from_edit.dateTime().toPyDateTime().astimezone().replace(hour=0, minute=0, second=0)
        to_dt_inclusive = self.to_edit.dateTime().toPyDateTime().astimezone().replace(hour=0, minute=0, second=0)
        to_dt = to_dt_inclusive + timedelta(days=1)
        bucket: Bucket = self.bucket_combo.currentData()
        group: GroupBy = self.group_combo.currentData()
        customer_id: Optional[int] = self.customer_combo.currentData()

        self._rows = aggregate(
            self.conn,
            from_iso=from_dt.isoformat(timespec="seconds"),
            to_iso=to_dt.isoformat(timespec="seconds"),
            bucket=bucket,
            group_by=group,
            customer_id=customer_id,
        )
        self._render_table()
        self._render_chart()

    # ------------------ rendering ------------------

    def _render_table(self) -> None:
        self.table.setRowCount(0)
        total = 0
        for row in self._rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(row.bucket))
            self.table.setItem(r, 1, QTableWidgetItem(row.group_label))
            hours = QTableWidgetItem(format_hours_decimal(row.seconds))
            hours.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.table.setItem(r, 2, hours)
            total += row.seconds
        self.total_label.setText(f"Σ {format_hours_decimal(total)} h  ({format_hm_short(total)})")

    def _render_chart(self) -> None:
        chart = QChart()
        chart.setTitle("Stunden")
        chart.setAnimationOptions(QChart.AnimationOption.SeriesAnimations)

        if not self._rows:
            self.chart_view.setChart(chart)
            return

        buckets: list[str] = []
        for r in self._rows:
            if r.bucket not in buckets:
                buckets.append(r.bucket)
        groups: list[str] = []
        for r in self._rows:
            if r.group_label not in groups:
                groups.append(r.group_label)

        series = QStackedBarSeries()
        max_total = 0.0
        for i, group in enumerate(groups):
            bar = QBarSet(group)
            for b in buckets:
                seconds = next((r.seconds for r in self._rows if r.bucket == b and r.group_label == group), 0)
                bar.append(seconds / 3600)
            bar.setColor(QColor(PALETTE[i % len(PALETTE)]))
            series.append(bar)
        # compute max stack height
        for b in buckets:
            tot = sum(r.seconds for r in self._rows if r.bucket == b) / 3600
            max_total = max(max_total, tot)

        chart.addSeries(series)

        axis_x = QBarCategoryAxis()
        axis_x.append(buckets)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        series.attachAxis(axis_x)

        axis_y = QValueAxis()
        axis_y.setRange(0, max(1.0, max_total * 1.1))
        axis_y.setTitleText("Stunden")
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_y)

        chart.legend().setVisible(True)
        chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)
        self.chart_view.setChart(chart)

    # ------------------ filters ------------------

    def _apply_preset(self) -> None:
        key = self.preset_combo.currentData()
        if key == "custom":
            return
        start, end = _preset_range(key)
        self.from_edit.blockSignals(True)
        self.to_edit.blockSignals(True)
        self.from_edit.setDate(start.date())
        self.to_edit.setDate((end - timedelta(days=1)).date())
        self.from_edit.blockSignals(False)
        self.to_edit.blockSignals(False)
        self.refresh()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "CSV exportieren", "worklog.csv", "CSV (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["bucket", "group", "hours"])
            for row in self._rows:
                w.writerow([row.bucket, row.group_label, format_hours_decimal(row.seconds)])
