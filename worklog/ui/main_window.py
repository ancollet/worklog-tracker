from __future__ import annotations

import sqlite3

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PyQt6.QtWidgets import QMainWindow, QTabWidget

from worklog.services.timer import TimerService
from worklog.ui.analytics_view import AnalyticsView
from worklog.ui.customers_view import CustomersView
from worklog.ui.logs_view import LogsView
from worklog.ui.timer_widget import TimerWidget


class MainWindow(QMainWindow):
    quit_requested = pyqtSignal()
    data_changed = pyqtSignal()  # any tab changed data → others may want refresh

    def __init__(self, conn: sqlite3.Connection, timer: TimerService) -> None:
        super().__init__()
        self.conn = conn
        self.timer = timer
        self._allow_quit = False  # close button hides instead, tray-quit sets True

        self.setWindowTitle("Worklog")
        self.resize(900, 620)

        self.tabs = QTabWidget(self)
        self.timer_tab = TimerWidget(conn, timer, self)
        self.logs_tab = LogsView(conn, self)
        self.customers_tab = CustomersView(conn, self)
        self.analytics_tab = AnalyticsView(conn, self)

        self.tabs.addTab(self.timer_tab, "Timer")
        self.tabs.addTab(self.logs_tab, "Logs")
        self.tabs.addTab(self.customers_tab, "Kunden")
        self.tabs.addTab(self.analytics_tab, "Analytics")
        self.setCentralWidget(self.tabs)

        # cross-tab refresh wiring
        self.timer_tab.changed.connect(self._refresh_others)
        self.logs_tab.changed.connect(self._refresh_others)
        self.customers_tab.changed.connect(self._refresh_others)

        # shortcuts
        QShortcut(QKeySequence("Ctrl+S"), self, activated=self.timer_tab.start_from_form)
        QShortcut(QKeySequence("Ctrl+N"), self, activated=lambda: self.tabs.setCurrentIndex(0))
        QShortcut(QKeySequence("Ctrl+L"), self, activated=self.timer_tab.open_add_log)

    def _refresh_others(self) -> None:
        self.timer_tab.refresh()
        self.logs_tab.refresh()
        self.customers_tab.refresh()
        self.analytics_tab.refresh()
        self.data_changed.emit()

    def request_quit(self) -> None:
        self._allow_quit = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt)
        if self._allow_quit:
            self.quit_requested.emit()
            event.accept()
        else:
            event.ignore()
            self.hide()
