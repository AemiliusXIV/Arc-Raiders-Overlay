"""Needed Items tab — aggregates required items across all quests."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox,
)

from src.api.metaforge import MetaForgeAPI
from src.core.config import Config
from src.core.worker import Worker


class NeededItemsTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._totals: dict[str, dict] = {}  # slug → {name, total, quests}
        self._raw_quests: list[dict] = []   # full quest list for cross-referencing
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
        self._show_done_cb = QCheckBox("Show completed")
        self._show_done_cb.setChecked(False)
        self._show_done_cb.toggled.connect(self._apply_filter)
        toolbar.addWidget(self._show_done_cb)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Item", "Total Needed", "Needed For", "Have", "Still Need"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    @property
    def cached_quests(self) -> list[dict]:
        """Raw quest list from MetaForge — used by RT enrichment for quest cross-referencing."""
        return self._raw_quests

    def _fetch(self) -> dict:
        quests = self._metaforge.get_quests()
        totals: dict[str, dict] = {}
        for quest in quests:
            quest_name = quest.get("name") or quest.get("title") or "Unknown Quest"
            required = quest.get("required_items") or []
            if not isinstance(required, list):
                continue
            for item in required:
                if not isinstance(item, dict):
                    continue
                slug = str(item.get("slug") or item.get("name") or item.get("id") or "")
                if not slug:
                    continue
                name = item.get("name") or slug
                qty = int(item.get("quantity") or item.get("qty") or item.get("amount") or 1)
                if slug not in totals:
                    totals[slug] = {"name": name, "total": 0, "quests": []}
                totals[slug]["total"] += qty
                if quest_name not in totals[slug]["quests"]:
                    totals[slug]["quests"].append(quest_name)
        return {"totals": totals, "raw_quests": quests}

    def _start_fetch(self) -> None:
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/quests")
        self._start_fetch()

    def _on_data_ready(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        self._raw_quests = result.get("raw_quests") or []
        self._totals = result.get("totals") or {}
        self._status_label.setText(f"{len(self._totals)} item(s) needed across all quests")
        self._populate_table()

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        collected = self._config.collected_items
        show_done = self._show_done_cb.isChecked()

        rows = []
        for slug, info in sorted(self._totals.items(), key=lambda x: x[1]["name"]):
            have = int(collected.get(slug, 0))
            still_need = max(0, info["total"] - have)
            if not show_done and still_need == 0:
                continue
            rows.append((slug, info, have, still_need))

        self._table.setRowCount(len(rows))
        for row_idx, (slug, info, have, still_need) in enumerate(rows):
            self._table.setItem(row_idx, 0, self._cell(info["name"]))
            self._table.setItem(row_idx, 1, self._cell(str(info["total"])))
            self._table.setItem(row_idx, 2, self._cell(", ".join(info["quests"])))

            spin = QSpinBox()
            spin.setRange(0, 9999)
            spin.setValue(have)
            spin.setProperty("slug", slug)
            spin.valueChanged.connect(self._on_have_changed)
            self._table.setCellWidget(row_idx, 3, spin)

            still_item = self._cell(str(still_need))
            color = QColor(80, 200, 80) if still_need == 0 else QColor(220, 80, 80)
            still_item.setForeground(color)
            self._table.setItem(row_idx, 4, still_item)

    def _apply_filter(self) -> None:
        self._populate_table()

    def _on_have_changed(self, value: int) -> None:
        spin = self.sender()
        slug = spin.property("slug")
        collected = dict(self._config.collected_items)
        collected[slug] = value
        self._config.collected_items = collected
        # Refresh still-need column for this row
        self._populate_table()

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item
