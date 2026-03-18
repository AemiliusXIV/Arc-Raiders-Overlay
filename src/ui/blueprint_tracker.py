"""Blueprint tracker tab — track which blueprints have been found."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QLineEdit,
)

from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.core.config import Config
from src.core.worker import Worker


def _is_blueprint(item: dict) -> bool:
    for field in ("name", "category", "type", "itemType", "item_type", "tags"):
        if "blueprint" in str(item.get(field) or "").lower():
            return True
    return False


def _category(item: dict) -> str:
    """Return the best available category string for display."""
    for field in ("category", "type", "itemType", "item_type", "rarity", "workbench"):
        val = item.get(field)
        if val and str(val).strip():
            return str(val)
    return "—"


class BlueprintTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI, ardb: ARDBApi):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._ardb = ardb
        self._blueprints: list[dict] = []
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
        self._hide_found_cb = QCheckBox("Hide found")
        self._hide_found_cb.setChecked(False)
        self._hide_found_cb.toggled.connect(self._apply_filter)
        toolbar.addWidget(self._hide_found_cb)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter blueprints…")
        self._search.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search)
        layout.addLayout(search_row)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Blueprint", "Category", "Sell Value", "Found"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> list:
        # Merge MetaForge + ARDB, deduplicate by name, then filter
        try:
            mf_items = self._metaforge.get_items()
        except Exception:
            mf_items = []
        try:
            ardb_items = self._ardb.get_items()
        except Exception:
            ardb_items = []

        seen: set[str] = set()
        merged: list[dict] = []
        for item in (mf_items or []) + (ardb_items or []):
            key = str(item.get("name") or "").strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(item)

        return [i for i in merged if _is_blueprint(i)]

    def _start_fetch(self) -> None:
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/items")
        self._start_fetch()

    def _on_data_ready(self, blueprints: object) -> None:
        if not isinstance(blueprints, list):
            return
        self._blueprints = blueprints
        found = self._config.found_blueprints
        found_count = sum(1 for b in blueprints if self._bp_key(b) in found)
        if blueprints:
            self._status_label.setText(f"{found_count} / {len(blueprints)} blueprints found")
        else:
            self._status_label.setText(
                "No blueprint items found in the item database — "
                "they may not be released yet or use a different category name."
            )
        self._apply_filter()

    def _on_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        query = self._search.text().lower()
        hide_found = self._hide_found_cb.isChecked()
        found = self._config.found_blueprints

        rows = []
        for bp in self._blueprints:
            key = self._bp_key(bp)
            is_found = key in found
            if hide_found and is_found:
                continue
            name = bp.get("name") or ""
            if query and query not in name.lower():
                continue
            rows.append((key, bp, is_found))

        self._table.setRowCount(len(rows))
        for row_idx, (key, bp, is_found) in enumerate(rows):
            name = bp.get("name") or "Unknown"
            category = _category(bp)
            value = str(bp.get("value") or bp.get("sell_value") or "—")

            self._table.setItem(row_idx, 0, self._cell(name))
            self._table.setItem(row_idx, 1, self._cell(category))
            self._table.setItem(row_idx, 2, self._cell(value))

            cb = QCheckBox()
            cb.setChecked(is_found)
            cb.setProperty("key", key)
            cb.toggled.connect(self._on_found_toggled)
            self._table.setCellWidget(row_idx, 3, cb)

    def _on_found_toggled(self, checked: bool) -> None:
        cb = self.sender()
        key = cb.property("key")
        found = list(self._config.found_blueprints)
        if checked and key not in found:
            found.append(key)
        elif not checked and key in found:
            found.remove(key)
        self._config.found_blueprints = found
        found_count = sum(1 for b in self._blueprints if self._bp_key(b) in found)
        self._status_label.setText(f"{found_count} / {len(self._blueprints)} blueprints found")

    @staticmethod
    def _bp_key(item: dict) -> str:
        return str(item.get("slug") or item.get("id") or item.get("name") or id(item))

    @staticmethod
    def _cell(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        return item
