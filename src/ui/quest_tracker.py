"""Quest tracker tab — browse quests, filter, and manually track progress."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QLineEdit,
    QComboBox, QCheckBox,
)

from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.core.config import Config
from src.core.worker import Worker


class QuestTrackerTab(QWidget):
    def __init__(self, config: Config, metaforge: MetaForgeAPI, ardb: ARDBApi):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._ardb = ardb
        self._all_quests: list[dict] = []
        self._worker: Worker | None = None

        self._build_ui()
        QTimer.singleShot(0, self._start_fetch)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Search:"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Quest name…")
        self._search.textChanged.connect(self._apply_filter)
        filter_row.addWidget(self._search)

        filter_row.addWidget(QLabel("Trader:"))
        self._trader_combo = QComboBox()
        self._trader_combo.addItem("All")
        self._trader_combo.currentTextChanged.connect(self._apply_filter)
        filter_row.addWidget(self._trader_combo)

        self._tracked_only = QCheckBox("Tracked only")
        self._tracked_only.toggled.connect(self._apply_filter)
        filter_row.addWidget(self._tracked_only)

        self._status_label = QLabel("Loading…")
        filter_row.addWidget(self._status_label)
        filter_row.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        filter_row.addWidget(refresh_btn)
        layout.addLayout(filter_row)

        # Table — columns: Track | Quest | Trader | Status | Required Items
        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Track", "Quest", "Trader", "Status", "Required Items"]
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> list:
        try:
            quests = self._metaforge.get_quests()
            if isinstance(quests, list):
                return quests
        except Exception:
            pass
        quests = self._ardb.get_quests()
        return quests if isinstance(quests, list) else []

    def _start_fetch(self) -> None:
        self._status_label.setText("Loading…")
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate(
            "https://metaforge.app/api/arc-raiders/quests"
        )
        self._start_fetch()

    def _on_data_ready(self, quests: object) -> None:
        self._all_quests = quests if isinstance(quests, list) else []
        self._status_label.setText(f"{len(self._all_quests)} quests")
        self._refresh_trader_filter()
        self._apply_filter()

    def _on_fetch_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    @staticmethod
    def _trader_name(quest: dict) -> str:
        # API field is "trader_name" (plain string)
        val = quest.get("trader_name") or quest.get("trader") or quest.get("vendor")
        if isinstance(val, dict):
            return val.get("name") or val.get("title") or str(val)
        return str(val) if val else "Unknown"

    def _refresh_trader_filter(self) -> None:
        traders = sorted({self._trader_name(q) for q in self._all_quests})
        self._trader_combo.blockSignals(True)
        current = self._trader_combo.currentText()
        self._trader_combo.clear()
        self._trader_combo.addItem("All")
        self._trader_combo.addItems(traders)
        idx = self._trader_combo.findText(current)
        self._trader_combo.setCurrentIndex(max(0, idx))
        self._trader_combo.blockSignals(False)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        query = self._search.text().strip().lower()
        trader_filter = self._trader_combo.currentText()
        tracked_only = self._tracked_only.isChecked()
        tracked_ids = set(self._config.tracked_quests)

        filtered = []
        for quest in self._all_quests:
            name = (quest.get("name") or quest.get("title") or "").lower()
            trader = self._trader_name(quest)
            quest_id = str(quest.get("id") or quest.get("slug") or quest.get("name") or "")

            if query and query not in name:
                continue
            if trader_filter != "All" and trader != trader_filter:
                continue
            if tracked_only and quest_id not in tracked_ids:
                continue
            filtered.append(quest)

        self._populate_table(filtered)

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _populate_table(self, quests: list[dict]) -> None:
        self._table.setRowCount(len(quests))
        tracked_ids = set(self._config.tracked_quests)

        for row, quest in enumerate(quests):
            quest_id = str(quest.get("id") or quest.get("slug") or quest.get("name") or "")
            name = quest.get("name") or quest.get("title") or "Unknown"
            trader = self._trader_name(quest)
            status = quest.get("status") or "—"
            required = self._required_str(quest)

            # Track checkbox
            chk = QCheckBox()
            chk.setChecked(quest_id in tracked_ids)
            chk.toggled.connect(lambda checked, qid=quest_id: self._on_track_toggled(qid, checked))
            chk_widget = QWidget()
            chk_layout = QHBoxLayout(chk_widget)
            chk_layout.addWidget(chk)
            chk_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chk_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(row, 0, chk_widget)

            for col, text in enumerate([name, trader, status, required], start=1):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                self._table.setItem(row, col, item)

    @staticmethod
    def _required_str(quest: dict) -> str:
        # required_items shape: [{"item": {"name": "..."}, "quantity": "5"}, ...]
        required = quest.get("required_items") or quest.get("requiredItems") or []
        if required:
            parts = []
            for obj in required:
                if isinstance(obj, dict):
                    item_obj = obj.get("item") or {}
                    item_name = (
                        item_obj.get("name") if isinstance(item_obj, dict)
                        else obj.get("name") or "?"
                    )
                    qty = obj.get("quantity") or obj.get("count") or obj.get("amount")
                    parts.append(f"{item_name} x{qty}" if qty else str(item_name))
                else:
                    parts.append(str(obj))
            return ", ".join(parts) if parts else "—"

        # Fall back to objectives (plain list of strings) if no required_items
        objectives = quest.get("objectives") or []
        if objectives:
            return " / ".join(str(o) for o in objectives[:2])  # cap at 2 to fit column
        return "—"

    # ------------------------------------------------------------------
    # Tracking persistence
    # ------------------------------------------------------------------

    def _on_track_toggled(self, quest_id: str, checked: bool) -> None:
        tracked = list(self._config.tracked_quests)
        if checked and quest_id not in tracked:
            tracked.append(quest_id)
        elif not checked and quest_id in tracked:
            tracked.remove(quest_id)
        self._config.tracked_quests = tracked
