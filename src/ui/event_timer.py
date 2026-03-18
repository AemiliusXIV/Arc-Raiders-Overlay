"""Event timer tab — live countdowns with audio/visual alerts."""

from __future__ import annotations

import time
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QSlider,
    QLineEdit, QGroupBox,
)

from src.api.metaforge import MetaForgeAPI
from src.core.config import Config
from src.core.worker import Worker

ASSETS_DIR = Path(__file__).parent.parent.parent / "assets" / "sounds"
ALERT_SOUND = ASSETS_DIR / "alert.wav"

COLOR_IMMINENT = QColor(200, 50, 50)
COLOR_SOON = QColor(200, 140, 0)
COLOR_ACTIVE = QColor(50, 150, 50)
COLOR_DEFAULT = QColor(0, 0, 0, 0)


def _format_seconds(secs: float) -> str:
    if secs <= 0:
        return "Active"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class EventTimerTab(QWidget):
    events_loaded = pyqtSignal(list)

    def __init__(self, config: Config, metaforge: MetaForgeAPI):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._events: list[dict] = []
        self._alerted: set[tuple] = set()
        self._worker: Worker | None = None

        self._init_audio()
        self._build_ui()

        # Defer first fetch until event loop is running
        QTimer.singleShot(0, self._start_fetch)

        # 1-second tick for countdown updates
        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(1000)

        # Re-fetch every 5 minutes
        self._fetch_timer = QTimer(self)
        self._fetch_timer.timeout.connect(self._start_fetch)
        self._fetch_timer.start(5 * 60 * 1000)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    def _init_audio(self) -> None:
        self._pygame_ok = False
        try:
            import pygame
            pygame.mixer.init()
            self._pygame = pygame
            self._pygame_ok = True
        except Exception:
            pass

    def _play_alert(self) -> None:
        if not self._pygame_ok or not ALERT_SOUND.exists():
            return
        try:
            self._pygame.mixer.music.load(str(ALERT_SOUND))
            self._pygame.mixer.music.set_volume(self._config.volume)
            self._pygame.mixer.music.play()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self._status_label = QLabel("Loading events…")
        toolbar.addWidget(self._status_label)
        toolbar.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._force_refresh)
        toolbar.addWidget(refresh_btn)
        layout.addLayout(toolbar)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Event", "Map", "Starts In", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        settings_box = QGroupBox("Alert Settings")
        settings_layout = QHBoxLayout(settings_box)
        settings_layout.addWidget(QLabel("Alert at (seconds before):"))
        self._alert_edit = QLineEdit(
            ", ".join(str(s) for s in self._config.alert_seconds_before)
        )
        self._alert_edit.setFixedWidth(140)
        self._alert_edit.editingFinished.connect(self._save_alert_thresholds)
        settings_layout.addWidget(self._alert_edit)
        settings_layout.addSpacing(20)
        settings_layout.addWidget(QLabel("Volume:"))
        self._vol_slider = QSlider(Qt.Orientation.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(int(self._config.volume * 100))
        self._vol_slider.setFixedWidth(100)
        self._vol_slider.valueChanged.connect(self._on_volume_changed)
        settings_layout.addWidget(self._vol_slider)
        settings_layout.addStretch()
        layout.addWidget(settings_box)

    # ------------------------------------------------------------------
    # Fetch
    # ------------------------------------------------------------------

    def _fetch(self) -> list:
        events = self._metaforge.get_events()
        if not isinstance(events, list):
            return []
        now_ms = time.time() * 1000
        # Past: drop anything that ended more than 10 minutes ago
        cutoff_past_ms = now_ms - 10 * 60 * 1000
        # Future: drop anything that hasn't started within the next 4 hours
        cutoff_future_ms = now_ms + 4 * 60 * 60 * 1000

        result = []
        for e in events:
            end_ms = e.get("endTime") or e.get("end_time")
            start_ms = e.get("startTime") or e.get("start_time")
            try:
                end = float(end_ms) if end_ms else None
                start = float(start_ms) if start_ms else None
            except (TypeError, ValueError):
                continue

            # Must have at least a start time to be useful
            if not start:
                continue
            # Drop if it starts more than 4 hours from now
            if start > cutoff_future_ms:
                continue
            # Drop if it ended more than 10 minutes ago
            if end is not None and end < cutoff_past_ms:
                continue
            # No end time: drop if it started more than 1 hour ago
            if end is None and start < now_ms - 60 * 60 * 1000:
                continue

            result.append(e)
        return result

    def _start_fetch(self) -> None:
        self._worker = Worker(self._fetch)
        self._worker.finished.connect(self._on_data_ready)
        self._worker.error.connect(self._on_fetch_error)
        self._worker.start()

    def _force_refresh(self) -> None:
        self._metaforge._client.invalidate("https://metaforge.app/api/arc-raiders/events")
        self._start_fetch()

    def _on_data_ready(self, events: object) -> None:
        self._events = events if isinstance(events, list) else []
        self._alerted.clear()
        self._status_label.setText(f"{len(self._events)} event(s) loaded")
        self._populate_table()
        self.events_loaded.emit(self._events)

    def _on_fetch_error(self, msg: str) -> None:
        self._status_label.setText(f"Error: {msg}")

    # ------------------------------------------------------------------
    # Table
    # ------------------------------------------------------------------

    def _populate_table(self) -> None:
        self._table.setRowCount(len(self._events))
        for row, event in enumerate(self._events):
            self._set_row(row, event)

    def _set_row(self, row: int, event: dict) -> None:
        name = event.get("name") or event.get("title") or "Unknown"
        map_name = event.get("map") or event.get("location") or "—"
        start_ts = event.get("startTime") or event.get("start_time")
        end_ts = event.get("endTime") or event.get("end_time")
        seconds_left = self._seconds_until_ms(start_ts)
        status = self._derive_status(start_ts, end_ts)

        for col, text in enumerate([name, map_name, _format_seconds(seconds_left), status]):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            self._table.setItem(row, col, item)

        self._color_row(row, seconds_left, status)

    def _color_row(self, row: int, seconds_left: float, status: str) -> None:
        if status == "Active":
            color = COLOR_ACTIVE
        elif seconds_left <= 60:
            color = COLOR_IMMINENT
        elif seconds_left <= 300:
            color = COLOR_SOON
        else:
            color = COLOR_DEFAULT

        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            if item:
                if color != COLOR_DEFAULT:
                    item.setBackground(color)
                else:
                    item.setData(Qt.ItemDataRole.BackgroundRole, None)

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        for row, event in enumerate(self._events):
            start_ts = event.get("startTime") or event.get("start_time")
            end_ts = event.get("endTime") or event.get("end_time")
            seconds_left = self._seconds_until_ms(start_ts)
            status = self._derive_status(start_ts, end_ts)

            item = self._table.item(row, 2)
            if item:
                item.setText(_format_seconds(seconds_left))
            self._color_row(row, seconds_left, status)
            self._check_alert(event, seconds_left)

    def _check_alert(self, event: dict, seconds_left: float) -> None:
        event_id = event.get("name") or id(event)
        for threshold in self._config.alert_seconds_before:
            key = (event_id, threshold)
            if key in self._alerted:
                continue
            if threshold - 5 <= seconds_left <= threshold + 5:
                self._alerted.add(key)
                self._play_alert()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _save_alert_thresholds(self) -> None:
        text = self._alert_edit.text()
        try:
            thresholds = sorted(
                {int(s.strip()) for s in text.split(",") if s.strip().isdigit()},
                reverse=True,
            )
            self._config.alert_seconds_before = thresholds
        except ValueError:
            pass

    def _on_volume_changed(self, value: int) -> None:
        self._config.volume = value / 100.0

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _seconds_until_ms(timestamp_ms) -> float:
        if timestamp_ms is None:
            return float("inf")
        try:
            return float(timestamp_ms) / 1000.0 - time.time()
        except (TypeError, ValueError):
            return float("inf")

    @staticmethod
    def _derive_status(start_ms, end_ms) -> str:
        now = time.time()
        try:
            if start_ms and float(start_ms) / 1000.0 <= now:
                if end_ms and float(end_ms) / 1000.0 > now:
                    return "Active"
                return "Ended"
        except (TypeError, ValueError):
            pass
        return "Upcoming"
