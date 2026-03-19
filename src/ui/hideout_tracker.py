"""Hideout tracker tab — workbench upgrade requirements from RaidTheory dataset."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor, QFont
from PyQt6.QtWidgets import (
    QCheckBox, QHeaderView, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.api.raidtheory import RaidTheoryClient
from src.core.config import Config
from src.core.worker import Worker

_HEADER_BG   = QColor("#1e2a1e")
_HEADER_FG   = QColor("#a5d6a7")
_LEVEL_ALT   = QColor("#1a1a1a")


class HideoutTab(QWidget):
    def __init__(self, config: Config, rt: RaidTheoryClient):
        super().__init__()
        self._config  = config
        self._rt      = rt
        self._stations: list[dict] = []
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

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["Station / Level", "Required Materials", "Done"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _start_fetch(self) -> None:
        self._worker = Worker(self._rt.get_hideout_stations)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._start_fetch()

    def _on_data_ready(self, result: object) -> None:
        if not isinstance(result, list):
            return
        self._stations = result
        self._populate_table()
        total_levels = sum(len(s["levels"]) for s in result)
        done = sum(
            1 for s in result for lv in s["levels"]
            if self._level_key(s["id"], lv["level"]) in self._config.completed_upgrades
        )
        self._status_label.setText(
            f"{done} / {total_levels} upgrade levels complete  •  {len(result)} stations"
        )

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error loading hideout data: {msg}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        self._table.setRowCount(0)
        completed = self._config.completed_upgrades
        bold = QFont()
        bold.setBold(True)

        for station in self._stations:
            # Station header row — spans all 3 columns
            header_row = self._table.rowCount()
            self._table.insertRow(header_row)
            header_item = QTableWidgetItem(station["name"].upper())
            header_item.setFont(bold)
            header_item.setForeground(QBrush(_HEADER_FG))
            header_item.setBackground(QBrush(_HEADER_BG))
            header_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # not selectable
            self._table.setItem(header_row, 0, header_item)
            for col in (1, 2):
                filler = QTableWidgetItem("")
                filler.setBackground(QBrush(_HEADER_BG))
                filler.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self._table.setItem(header_row, col, filler)
            self._table.setSpan(header_row, 0, 1, 3)

            # Level rows
            for i, lv in enumerate(station["levels"]):
                row = self._table.rowCount()
                self._table.insertRow(row)
                bg = _LEVEL_ALT if i % 2 else QColor("transparent")

                level_item = QTableWidgetItem(f"  Level {lv['level']}")
                level_item.setBackground(QBrush(bg))
                self._table.setItem(row, 0, level_item)

                mat_parts = [f"{m['name']} ×{m['qty']}" for m in lv["materials"]]
                mat_parts += lv["other"]
                if lv.get("description"):
                    mat_parts.insert(0, lv["description"])
                mat_text = ",   ".join(mat_parts) if mat_parts else "—"
                mat_item = QTableWidgetItem(mat_text)
                mat_item.setBackground(QBrush(bg))
                self._table.setItem(row, 1, mat_item)

                key = self._level_key(station["id"], lv["level"])
                cb = QCheckBox()
                cb.setChecked(key in completed)
                cb.setProperty("key", key)
                cb.toggled.connect(self._on_done_toggled)
                cb_widget = QWidget()
                cb_layout = QHBoxLayout(cb_widget)
                cb_layout.addWidget(cb)
                cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_layout.setContentsMargins(0, 0, 0, 0)
                cb_widget.setStyleSheet(f"background-color: {bg.name()};")
                self._table.setCellWidget(row, 2, cb_widget)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    @staticmethod
    def _level_key(station_id: str, level: int) -> str:
        return f"{station_id}_level_{level}"

    def _on_done_toggled(self, checked: bool) -> None:
        cb = self.sender()
        key = cb.property("key")
        completed = list(self._config.completed_upgrades)
        if checked and key not in completed:
            completed.append(key)
        elif not checked and key in completed:
            completed.remove(key)
        self._config.completed_upgrades = completed
        # Refresh progress label
        total_levels = sum(len(s["levels"]) for s in self._stations)
        done = len([k for k in completed if any(
            self._level_key(s["id"], lv["level"]) == k
            for s in self._stations for lv in s["levels"]
        )])
        self._status_label.setText(
            f"{done} / {total_levels} upgrade levels complete  •  {len(self._stations)} stations"
        )
