"""Hideout/Workshop tracker tab.

Tries the /api/arc-raiders/workshop endpoint first.
Falls back to items that have a truthy 'workbench' field.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox,
)

from src.api.metaforge import MetaForgeAPI
from src.core.config import Config
from src.core.worker import Worker


class HideoutTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._upgrades: list[dict] = []
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
        self._table.setHorizontalHeaderLabels(["Upgrade / Item", "Materials / Details", "Tier", "Done"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> tuple[list, str]:
        # Try dedicated workshop endpoint first
        workshop = self._metaforge.get_workshop()
        if workshop:
            return workshop, "workshop"

        # Fall back: filter items with a workbench field
        items = self._metaforge.get_items()
        wb_items = [i for i in items if i.get("workbench")]
        return wb_items, "items"

    def _start_fetch(self) -> None:
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/workshop")
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/items")
        self._start_fetch()

    def _on_data_ready(self, result: object) -> None:
        if not isinstance(result, tuple):
            return
        upgrades, source = result
        self._upgrades = upgrades
        done_count = sum(
            1 for u in upgrades
            if self._upgrade_key(u) in self._config.completed_upgrades
        )
        if source == "workshop":
            self._status_label.setText(
                f"{done_count} / {len(upgrades)} upgrades complete (workshop API)"
            )
        else:
            self._status_label.setText(
                f"{len(upgrades)} workbench item(s) found — workshop API not yet available"
            )
        self._populate_table(source)

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self, source: str) -> None:
        self._table.setRowCount(len(self._upgrades))
        completed = self._config.completed_upgrades

        for row, entry in enumerate(self._upgrades):
            name = entry.get("name") or entry.get("title") or "Unknown"
            if source == "workshop":
                materials = self._format_materials(entry.get("materials") or entry.get("requirements") or [])
                tier = str(entry.get("tier") or entry.get("level") or "—")
            else:
                # Items fallback — show workbench field value as tier
                wb = entry.get("workbench")
                materials = entry.get("description") or "—"
                tier = str(wb) if wb and not isinstance(wb, bool) else "Workbench"

            self._table.setItem(row, 0, self._cell(name))
            self._table.setItem(row, 1, self._cell(str(materials)))
            self._table.setItem(row, 2, self._cell(tier))

            key = self._upgrade_key(entry)
            cb = QCheckBox()
            cb.setChecked(key in completed)
            cb.setProperty("key", key)
            cb.toggled.connect(self._on_done_toggled)
            self._table.setCellWidget(row, 3, cb)

    @staticmethod
    def _upgrade_key(entry: dict) -> str:
        return str(entry.get("id") or entry.get("slug") or entry.get("name") or id(entry))

    @staticmethod
    def _format_materials(materials) -> str:
        if not materials:
            return "—"
        if isinstance(materials, list):
            parts = []
            for m in materials:
                if isinstance(m, dict):
                    n = m.get("name") or "?"
                    q = m.get("quantity") or m.get("qty") or m.get("amount") or ""
                    parts.append(f"{n} x{q}" if q else n)
                else:
                    parts.append(str(m))
            return ", ".join(parts)
        return str(materials)

    def _on_done_toggled(self, checked: bool) -> None:
        cb = self.sender()
        key = cb.property("key")
        completed = list(self._config.completed_upgrades)
        if checked and key not in completed:
            completed.append(key)
        elif not checked and key in completed:
            completed.remove(key)
        self._config.completed_upgrades = completed
        # Update progress label
        done_count = len([u for u in self._upgrades if self._upgrade_key(u) in completed])
        total = len(self._upgrades)
        current = self._status_label.text()
        prefix = current.split("—")[0].strip() if "—" in current else ""
        self._status_label.setText(f"{done_count} / {total} upgrades complete")

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item
