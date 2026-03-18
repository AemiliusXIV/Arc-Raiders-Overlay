"""Weekly Trials tracker tab.

Fetches /api/arc-raiders/trials from MetaForge.
Shows a graceful placeholder if the endpoint is not yet available.
Completion state is keyed by trial ID + ISO week number so checkboxes
auto-reset each week.
"""

from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
)

from src.api.metaforge import MetaForgeAPI
from src.core.config import Config
from src.core.worker import Worker


def _week_key(trial_id: str) -> str:
    """Build a persistence key that resets every Monday."""
    week = datetime.date.today().isocalendar()  # (year, week, weekday)
    return f"{trial_id}::{week.year}W{week.week:02d}"


class WeeklyTrialsTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._trials: list[dict] = []
        self._worker: Worker | None = None

        self._build_ui()
        QTimer.singleShot(0, self._start_fetch)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._status_label = QLabel("Loading…")
        toolbar.addWidget(self._status_label)
        toolbar.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Trial", "Objective", "Reward", "Complete"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        self._placeholder = QLabel(
            "Weekly Trials data is not yet available from the MetaForge API.\n"
            "Check back after a future update."
        )
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #888; font-size: 13px;")
        self._placeholder.hide()
        layout.addWidget(self._placeholder)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> list:
        return self._metaforge.get_trials()

    def _start_fetch(self) -> None:
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/trials")
        self._start_fetch()

    def _on_data_ready(self, trials: object) -> None:
        if not isinstance(trials, list):
            trials = []
        self._trials = trials

        if not trials:
            self._table.hide()
            self._placeholder.show()
            self._status_label.setText("No trials data available")
            return

        self._placeholder.hide()
        self._table.show()
        completed = self._config.completed_trials
        done_count = sum(1 for t in trials if completed.get(_week_key(self._trial_id(t))))
        self._status_label.setText(f"{done_count} / {len(trials)} trials complete this week")
        self._populate_table()

    def _on_error(self, msg: str) -> None:
        self._table.hide()
        self._placeholder.show()
        self._status_label.setText("Not available")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        completed = self._config.completed_trials
        self._table.setRowCount(len(self._trials))

        for row, trial in enumerate(self._trials):
            name = trial.get("name") or trial.get("title") or "Unknown"
            objective = trial.get("objective") or trial.get("description") or "—"
            reward = str(trial.get("reward") or trial.get("rewards") or "—")
            tid = self._trial_id(trial)
            key = _week_key(tid)

            self._table.setItem(row, 0, self._cell(name))
            self._table.setItem(row, 1, self._cell(objective))
            self._table.setItem(row, 2, self._cell(reward))

            cb = QCheckBox()
            cb.setChecked(bool(completed.get(key)))
            cb.setProperty("key", key)
            cb.toggled.connect(self._on_complete_toggled)
            self._table.setCellWidget(row, 3, cb)

    def _on_complete_toggled(self, checked: bool) -> None:
        cb = self.sender()
        key = cb.property("key")
        completed = dict(self._config.completed_trials)
        completed[key] = checked
        self._config.completed_trials = completed
        done_count = sum(
            1 for t in self._trials
            if completed.get(_week_key(self._trial_id(t)))
        )
        self._status_label.setText(f"{done_count} / {len(self._trials)} trials complete this week")

    @staticmethod
    def _trial_id(trial: dict) -> str:
        return str(trial.get("id") or trial.get("slug") or trial.get("name") or id(trial))

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item
