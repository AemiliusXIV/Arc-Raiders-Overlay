"""Quest tracker tab — browse quests, filter, track progress, and sync active status."""

from __future__ import annotations

import difflib
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont
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
        self._quest_sync_dlg = None  # reference held while dialog is open

        self._build_ui()
        QTimer.singleShot(0, self._start_fetch)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Sync toolbar
        sync_row = QHBoxLayout()
        self._sync_status_label = QLabel("")
        self._sync_status_label.setStyleSheet("color: #888; font-style: italic;")
        sync_row.addWidget(self._sync_status_label)
        sync_row.addStretch()

        self._sync_btn = QPushButton("Sync Quests")
        self._sync_btn.setToolTip(
            "Scan the quest widget in the Arc Raiders play menu to detect active quests"
        )
        self._sync_btn.clicked.connect(self.open_sync_dialog)
        sync_row.addWidget(self._sync_btn)

        self._reset_sync_btn = QPushButton("Reset")
        self._reset_sync_btn.setToolTip("Clear synced quest status")
        self._reset_sync_btn.clicked.connect(self._reset_sync)
        sync_row.addWidget(self._reset_sync_btn)

        layout.addLayout(sync_row)

        # Update sync label from persisted data
        self._update_sync_label()

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

        self._active_only = QCheckBox("Active only")
        self._active_only.setToolTip("Show only quests detected as active in your last sync")
        self._active_only.toggled.connect(self._apply_filter)
        filter_row.addWidget(self._active_only)

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
    # Sync dialog
    # ------------------------------------------------------------------

    def open_sync_dialog(self) -> None:
        """Open the guided quest sync dialog (called from button or main window hotkey)."""
        from src.ui.quest_sync_dialog import QuestSyncDialog
        hotkey = self._config.hotkey_quest_sync
        self._quest_sync_dlg = QuestSyncDialog(hotkey=hotkey, parent=self)
        self._quest_sync_dlg.quests_scanned.connect(self._on_quests_scanned)
        self._quest_sync_dlg.exec()
        self._quest_sync_dlg = None

    def _on_quests_scanned(self, raw_lines: list[str]) -> None:
        """
        Cross-reference raw OCR lines against the MetaForge quest database
        to determine which quests are currently active.

        Uses difflib fuzzy matching so minor OCR errors (missing characters,
        case differences) still find the right quest.  If MetaForge quest
        objects contain prerequisite fields (requires / prerequisites), those
        quests are also marked as auto-completed.
        """
        if not self._all_quests:
            # Quest data not loaded yet — save raw lines and retry after load.
            self._config.synced_quests = raw_lines
            self._config.synced_quest_ids = []
            self._config.synced_quests_at = datetime.now().isoformat()
            self._update_sync_label()
            self._apply_filter()
            return

        # Build lookup: display name → quest dict
        all_names = [
            (quest.get("name") or quest.get("title") or "")
            for quest in self._all_quests
        ]

        active_names: list[str] = []
        active_ids: list[str] = []

        for line in raw_lines:
            matches = difflib.get_close_matches(line, all_names, n=1, cutoff=0.60)
            if matches:
                matched_name = matches[0]
                active_names.append(matched_name)
                # Find the matching quest to get its ID
                for quest in self._all_quests:
                    qname = quest.get("name") or quest.get("title") or ""
                    if qname == matched_name:
                        qid = str(
                            quest.get("id") or quest.get("slug") or qname
                        )
                        if qid not in active_ids:
                            active_ids.append(qid)
                        break
            else:
                print(f"[QuestSync] No match for OCR line: {line!r}")

        print(f"[QuestSync] Matched {len(active_names)} active quests: {active_names}")

        # Check for prerequisite fields — mark those as auto-completed.
        # MetaForge may add these fields in the future; we handle them if present.
        auto_completed_ids: set[str] = set()
        for quest in self._all_quests:
            qid = str(quest.get("id") or quest.get("slug") or
                      quest.get("name") or "")
            if qid not in active_ids:
                continue
            prereqs = (quest.get("requires") or quest.get("prerequisites")
                       or quest.get("requiredQuests") or [])
            for prereq in prereqs:
                if isinstance(prereq, dict):
                    pid = str(prereq.get("id") or prereq.get("slug") or "")
                else:
                    pid = str(prereq)
                if pid:
                    auto_completed_ids.add(pid)

        if auto_completed_ids:
            print(f"[QuestSync] Auto-completed prerequisites: {auto_completed_ids}")

        self._config.synced_quests = active_names
        self._config.synced_quest_ids = active_ids
        self._config.synced_quests_at = datetime.now().isoformat()

        # Store auto-completed IDs alongside active IDs for the status column.
        all_done_ids = active_ids + list(auto_completed_ids)
        self._config.set("synced_auto_completed_ids", all_done_ids)

        self._update_sync_label()
        self._apply_filter()

        # Update the dialog list to show only matched names (not raw OCR noise).
        if self._quest_sync_dlg is not None:
            self._quest_sync_dlg.update_results(active_names)

    def _reset_sync(self) -> None:
        """Clear all synced quest status."""
        self._config.synced_quests = []
        self._config.synced_quest_ids = []
        self._config.synced_quests_at = ""
        self._config.set("synced_auto_completed_ids", [])
        self._update_sync_label()
        self._apply_filter()

    def _update_sync_label(self) -> None:
        at = self._config.synced_quests_at
        names = self._config.synced_quests
        if at and names:
            try:
                dt = datetime.fromisoformat(at)
                ts = dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                ts = at
            n = len(names)
            self._sync_status_label.setText(
                f"{n} active quest(s) · last synced {ts}"
            )
        elif at:
            self._sync_status_label.setText("Synced — no quests matched")
        else:
            self._sync_status_label.setText("Not synced")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        query = self._search.text().strip().lower()
        trader_filter = self._trader_combo.currentText()
        tracked_only = self._tracked_only.isChecked()
        active_only = self._active_only.isChecked()
        tracked_ids = set(self._config.tracked_quests)
        active_ids = set(self._config.synced_quest_ids)
        active_names = set(self._config.synced_quests)

        filtered = []
        for quest in self._all_quests:
            name = (quest.get("name") or quest.get("title") or "")
            quest_id = str(quest.get("id") or quest.get("slug") or quest.get("name") or "")
            trader = self._trader_name(quest)

            if query and query not in name.lower():
                continue
            if trader_filter != "All" and trader != trader_filter:
                continue
            if tracked_only and quest_id not in tracked_ids:
                continue
            if active_only and quest_id not in active_ids and name not in active_names:
                continue
            filtered.append(quest)

        self._populate_table(filtered)

    # ------------------------------------------------------------------
    # Table rendering
    # ------------------------------------------------------------------

    def _quest_sync_status(self, quest_id: str, quest_name: str) -> str:
        """Return the sync status string for a given quest."""
        active_ids = set(self._config.synced_quest_ids)
        active_names = set(self._config.synced_quests)
        auto_done = set(self._config.get("synced_auto_completed_ids", []))

        if quest_id in active_ids or quest_name in active_names:
            return "active"
        if quest_id in auto_done:
            return "completed"
        return ""

    def _populate_table(self, quests: list[dict]) -> None:
        self._table.setRowCount(len(quests))
        tracked_ids = set(self._config.tracked_quests)

        for row, quest in enumerate(quests):
            quest_id = str(quest.get("id") or quest.get("slug") or quest.get("name") or "")
            name = quest.get("name") or quest.get("title") or "Unknown"
            trader = self._trader_name(quest)
            required = self._required_str(quest)

            sync_status = self._quest_sync_status(quest_id, name)

            # Status cell text
            if sync_status == "active":
                status_text = "Active"
            elif sync_status == "completed":
                status_text = "Completed"
            else:
                status_text = "—"

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

            for col, text in enumerate([name, trader, status_text, required], start=1):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

                # Status column styling
                if col == 3:
                    if sync_status == "active":
                        item.setForeground(QColor("#50c878"))   # green
                        font = item.font()
                        font.setBold(True)
                        item.setFont(font)
                    elif sync_status == "completed":
                        item.setForeground(QColor("#888888"))   # gray
                        font = item.font()
                        font.setItalic(True)
                        item.setFont(font)

                self._table.setItem(row, col, item)

            # Row background tint for active quests
            if sync_status == "active":
                bg = QColor(0, 80, 0, 40)
                for col in range(1, 5):
                    it = self._table.item(row, col)
                    if it:
                        it.setBackground(bg)

    @staticmethod
    def _required_str(quest: dict) -> str:
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

        objectives = quest.get("objectives") or []
        if objectives:
            return " / ".join(str(o) for o in objectives[:2])
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
