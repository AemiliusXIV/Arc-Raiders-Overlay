"""Needed Items tab — aggregates required items across all quests, plus synced project data."""

from __future__ import annotations

import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QSpinBox,
    QGroupBox, QMessageBox,
)

from src.api.metaforge import MetaForgeAPI
from src.core.config import Config
from src.core.worker import Worker
from src.ocr.project_scanner import ProjectScanResult

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
        layout.setSpacing(8)

        # ── Quest Requirements group ──────────────────────────────────────
        quest_group = QGroupBox("Quest Requirements")
        quest_layout = QVBoxLayout(quest_group)
        quest_layout.setSpacing(6)

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
        quest_layout.addLayout(toolbar)

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
        quest_layout.addWidget(self._table)

        layout.addWidget(quest_group, stretch=1)

        # ── Project Requirements group ────────────────────────────────────
        proj_group = QGroupBox("Project Requirements")
        proj_layout = QVBoxLayout(proj_group)
        proj_layout.setSpacing(6)

        proj_toolbar = QHBoxLayout()

        self._proj_header = QLabel("")
        self._proj_header.setStyleSheet("font-size: 11px; color: #aaa;")
        proj_toolbar.addWidget(self._proj_header)

        self._auto_sync_label = QLabel("● Auto-syncing")
        self._auto_sync_label.setStyleSheet("color: #50c050; font-size: 11px;")
        self._auto_sync_label.setVisible(False)
        proj_toolbar.addWidget(self._auto_sync_label)

        proj_toolbar.addStretch()

        self._sync_btn = QPushButton("Sync Projects")
        self._sync_btn.setToolTip(
            "Open the guided scan dialog to read your in-game project hand-in screen"
        )
        self._sync_btn.clicked.connect(self._open_sync_dialog)
        proj_toolbar.addWidget(self._sync_btn)

        self._reset_btn = QPushButton("Reset")
        self._reset_btn.setToolTip("Clear all synced project data")
        self._reset_btn.clicked.connect(self._reset_projects)
        proj_toolbar.addWidget(self._reset_btn)

        proj_layout.addLayout(proj_toolbar)

        self._proj_table = QTableWidget(0, 4)
        self._proj_table.setHorizontalHeaderLabels(
            ["Item", "Progress", "Project / Phase", "Status"]
        )
        self._proj_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._proj_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._proj_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._proj_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._proj_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proj_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._proj_table.verticalHeader().setVisible(False)
        proj_layout.addWidget(self._proj_table)

        self._proj_empty_label = QLabel(
            'No project data synced yet.  Click "Sync Projects" to scan your in-game screen.'
        )
        self._proj_empty_label.setStyleSheet("color: #888; font-style: italic; padding: 4px;")
        self._proj_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        proj_layout.addWidget(self._proj_empty_label)

        layout.addWidget(proj_group, stretch=1)

        self._populate_projects_table()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def cached_quests(self) -> list[dict]:
        """Raw quest list from MetaForge — used by RT enrichment for quest cross-referencing."""
        return self._raw_quests

    def set_auto_sync_indicator(self, active: bool) -> None:
        """Show or hide the auto-sync status indicator."""
        self._auto_sync_label.setVisible(active)

    # ------------------------------------------------------------------
    # Fetch (quest data from API)
    # ------------------------------------------------------------------

    def _fetch(self) -> dict:
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

                item_obj = entry.get("item")
                if isinstance(item_obj, dict):
                    slug = item_obj.get("id") or item_obj.get("slug") or ""
                    name = item_obj.get("name") or ""
                else:
                    slug = str(entry.get("item_id") or entry.get("slug") or "")
                    name = str(entry.get("name") or "")

                if not slug:
                    continue

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
        client.invalidate(f"{_MF_BASE}/quests?all")
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
    # Quest items table
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

        collected = dict(self._config.collected_items)
        collected[slug] = value
        self._config.collected_items = collected

        info = self._totals.get(slug, {})
        still_need = max(0, info.get("total", 0) - value)
        for row in range(self._table.rowCount()):
            if self._table.cellWidget(row, 3) is spin:
                self._table.setItem(row, 4, self._still_need_cell(still_need))
                break

    # ------------------------------------------------------------------
    # Project sync
    # ------------------------------------------------------------------

    def _open_sync_dialog(self) -> None:
        from src.ocr.project_scanner import _MSS_OK, _TESS_OK
        if not (_MSS_OK and _TESS_OK):
            QMessageBox.information(
                self,
                "Project Sync — Setup Required",
                "The project screen reader requires Tesseract OCR to be installed.\n\n"
                "1. Download and install Tesseract from:\n"
                "   https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "2. During installation, check \"Add Tesseract to PATH\".\n\n"
                "3. Restart Arc Raiders Overlay.\n\n"
                "Python packages also required:\n"
                "   pip install mss pytesseract Pillow",
            )
            return

        from src.ui.project_sync_dialog import ProjectSyncDialog
        hotkey = self._config.hotkey_project_sync
        dlg = ProjectSyncDialog(hotkey=hotkey, parent=self)
        # page_scanned fires immediately after each successful scan (auto-save).
        dlg.page_scanned.connect(self._on_page_scanned)
        dlg.exec()

    def _on_page_scanned(self, page: ProjectScanResult) -> None:
        """Called immediately after each successful scan — saves without needing Apply."""
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        new_entry = {
            "project": page.project,
            "phase_fraction": page.phase_fraction,
            "scanned_at": now,
            "items": [
                {"name": it.name, "have": it.have, "need": it.need}
                for it in page.items
            ],
        }
        existing = list(self._config.synced_projects)
        replaced = False
        for i, old in enumerate(existing):
            if (old.get("project") == new_entry["project"]
                    and old.get("phase_fraction") == new_entry["phase_fraction"]):
                existing[i] = new_entry
                replaced = True
                break
        if not replaced:
            existing.append(new_entry)
        self._config.synced_projects = existing
        self._populate_projects_table()

    def _on_projects_synced(self, pages: list[ProjectScanResult]) -> None:
        """Called when the sync dialog is accepted with scanned pages."""
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        serialised = []
        for page in pages:
            serialised.append({
                "project": page.project,
                "phase_fraction": page.phase_fraction,
                "scanned_at": now,
                "items": [
                    {"name": it.name, "have": it.have, "need": it.need}
                    for it in page.items
                ],
            })

        # Merge with existing: replace pages for same project+phase, keep others.
        existing = list(self._config.synced_projects)
        for new_page in serialised:
            replaced = False
            for i, old in enumerate(existing):
                if (old.get("project") == new_page["project"]
                        and old.get("phase_fraction") == new_page["phase_fraction"]):
                    existing[i] = new_page
                    replaced = True
                    break
            if not replaced:
                existing.append(new_page)

        self._config.synced_projects = existing
        self._populate_projects_table()

    def update_from_auto_sync(self, page: ProjectScanResult) -> None:
        """Called by the auto-sync timer in main_window with a fresh scan result."""
        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        new_entry = {
            "project": page.project,
            "phase_fraction": page.phase_fraction,
            "scanned_at": now,
            "items": [
                {"name": it.name, "have": it.have, "need": it.need}
                for it in page.items
            ],
        }
        existing = list(self._config.synced_projects)
        replaced = False
        for i, old in enumerate(existing):
            if (old.get("project") == new_entry["project"]
                    and old.get("phase_fraction") == new_entry["phase_fraction"]):
                # Only update if data actually changed to avoid unnecessary writes.
                if old != new_entry:
                    existing[i] = new_entry
                    replaced = True
                break
        if not replaced:
            existing.append(new_entry)
            replaced = True

        if replaced:
            self._config.synced_projects = existing
            self._populate_projects_table()

    def _reset_projects(self) -> None:
        """Clear all synced project data after confirmation."""
        reply = QMessageBox.question(
            self,
            "Reset Project Data",
            "Clear all synced project data?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._config.synced_projects = []
        self._populate_projects_table()

    def _populate_projects_table(self) -> None:
        projects = self._config.synced_projects

        if not projects:
            self._proj_table.setRowCount(0)
            self._proj_table.setVisible(False)
            self._proj_empty_label.setVisible(True)
            self._proj_header.setText("Project Requirements (Synced)")
            return

        self._proj_empty_label.setVisible(False)
        self._proj_table.setVisible(True)

        # Flatten all items from all scanned pages into rows.
        rows: list[tuple[str, str, str, bool]] = []
        latest_ts = ""
        for page in projects:
            proj = page.get("project", "")
            phase = page.get("phase_fraction", "")
            scanned_at = page.get("scanned_at", "")
            if scanned_at > latest_ts:
                latest_ts = scanned_at
            phase_label = f"{proj} ({phase})" if phase else proj
            for item in page.get("items", []):
                name = item.get("name", "")
                have = int(item.get("have", 0))
                need = int(item.get("need", 0))
                progress = f"{have}/{need}"
                complete = have >= need
                rows.append((name, progress, phase_label, complete))

        # Sort: incomplete first, then by name.
        rows.sort(key=lambda r: (r[3], r[0].lower()))

        self._proj_table.setRowCount(len(rows))
        for row_idx, (name, progress, phase_label, complete) in enumerate(rows):
            name_item = self._cell(name)
            prog_item = self._cell(progress)
            phase_item = self._cell(phase_label)

            if complete:
                color = QColor(80, 200, 80)
                status_item = self._cell("Complete")
                status_item.setForeground(color)
            else:
                color = QColor(220, 80, 80)
                status_item = self._cell("Needed")
                status_item.setForeground(color)

            prog_item.setForeground(color)

            self._proj_table.setItem(row_idx, 0, name_item)
            self._proj_table.setItem(row_idx, 1, prog_item)
            self._proj_table.setItem(row_idx, 2, phase_item)
            self._proj_table.setItem(row_idx, 3, status_item)

        total = len(rows)
        done = sum(1 for r in rows if r[3])
        ts_str = f"  last synced {latest_ts}" if latest_ts else ""
        self._proj_header.setText(
            f"{done}/{total} complete  ·  {ts_str}" if ts_str else f"{done}/{total} complete"
        )

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
