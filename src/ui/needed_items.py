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

_MF_BASE = "https://metaforge.app/api/arc-raiders"


class NeededItemsTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._totals: dict[str, dict] = {}  # slug → {name, total, quests}
        self._raw_quests: list[dict] = []   # full quest list for RT enrichment
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
    # Public API
    # ------------------------------------------------------------------

    @property
    def cached_quests(self) -> list[dict]:
        """Raw quest list from MetaForge — used by RT enrichment for quest cross-referencing."""
        return self._raw_quests

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> dict:
        # Build a slug→name map from the full MetaForge items list for fallback resolution.
        try:
            all_items = self._metaforge.get_items()
            item_name_map: dict[str, str] = {
                it["id"]: it["name"]
                for it in all_items
                if it.get("id") and it.get("name")
            }
        except Exception:
            item_name_map = {}

        quests = self._metaforge.get_quests()
        totals: dict[str, dict] = {}

        for quest in quests:
            quest_name = quest.get("name") or quest.get("title") or "Unknown Quest"
            required = quest.get("required_items") or []
            if not isinstance(required, list):
                continue
            for entry in required:
                if not isinstance(entry, dict):
                    continue

                # MetaForge format:
                #   {"id": <UUID>, "item": {"id": "battery", "name": "Battery", …},
                #    "item_id": "battery", "quantity": N}
                # The top-level "id" is the requirement UUID — never use it as the item key.
                item_obj = entry.get("item")
                if isinstance(item_obj, dict):
                    slug = item_obj.get("id") or item_obj.get("slug") or ""
                    name = item_obj.get("name") or ""
                else:
                    # Flat format fallback (shouldn't occur with current API but kept for safety)
                    slug = str(entry.get("item_id") or entry.get("slug") or "")
                    name = str(entry.get("name") or "")

                if not slug:
                    continue

                # Resolve name: MetaForge items DB → prettify slug
                if not name or name == slug:
                    name = item_name_map.get(slug, "")
                if not name:
                    name = slug.replace("-", " ").replace("_", " ").title()

                qty = int(entry.get("quantity") or entry.get("qty") or entry.get("amount") or 1)

                if slug not in totals:
                    totals[slug] = {"name": name, "total": 0, "quests": []}
                totals[slug]["total"] += qty
                if quest_name not in totals[slug]["quests"]:
                    totals[slug]["quests"].append(quest_name)

        return {"totals": totals, "raw_quests": quests}

    def _start_fetch(self) -> None:
        # Disconnect any previous worker to avoid stale callbacks.
        if self._worker is not None:
            try:
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
            except Exception:
                pass
            self._worker = None

        self._status_label.setText("Loading…")
        worker = Worker(self._fetch)
        worker.finished.connect(self._on_data_ready)
        worker.error.connect(self._on_error)
        worker.start()
        self._worker = worker

    def _force_refresh(self) -> None:
        """Clear the quests cache and reload from the API."""
        client = self._metaforge._client
        # Invalidate the paginated sentinel key used by get_quests()
        client.invalidate(f"{_MF_BASE}/quests?all")
        # Invalidate individual page URLs in case they were cached separately
        for page in range(1, 10):
            client.invalidate(f"{_MF_BASE}/quests?page={page}&limit=50")
        self._start_fetch()

    def _on_data_ready(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        self._raw_quests = result.get("raw_quests") or []
        self._totals     = result.get("totals")     or {}
        self._status_label.setText(
            f"{len(self._totals)} item(s) needed across all quests"
        )
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
        for slug, info in sorted(self._totals.items(), key=lambda x: x[1]["name"].lower()):
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
            # Block signals so setValue() doesn't trigger _on_have_changed while building the table
            spin.blockSignals(True)
            spin.setValue(have)
            spin.blockSignals(False)
            spin.setProperty("slug", slug)
            spin.valueChanged.connect(self._on_have_changed)
            self._table.setCellWidget(row_idx, 3, spin)

            self._table.setItem(row_idx, 4, self._still_need_cell(still_need))

    def _apply_filter(self) -> None:
        self._populate_table()

    def _on_have_changed(self, value: int) -> None:
        spin = self.sender()
        if spin is None:
            return
        slug = spin.property("slug")
        if not slug:
            return

        # Persist the updated count
        collected = dict(self._config.collected_items)
        collected[slug] = value
        self._config.collected_items = collected

        # Update only the "Still Need" cell for this row — do NOT rebuild the
        # whole table, which would create new spinboxes, each firing valueChanged
        # and causing an infinite rebuild loop.
        info = self._totals.get(slug, {})
        still_need = max(0, info.get("total", 0) - value)
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, 3) is spin:
                self._table.setItem(row, 4, self._still_need_cell(still_need))
                break

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item

    @staticmethod
    def _still_need_cell(still_need: int) -> QTableWidgetItem:
        item = QTableWidgetItem(str(still_need))
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        color = QColor(80, 200, 80) if still_need == 0 else QColor(220, 80, 80)
        item.setForeground(color)
        return item
