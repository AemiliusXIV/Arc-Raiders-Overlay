"""In-game overlay window — frameless, always-on-top, semi-transparent event display.

Behaviour:
- Always-on-top, no title bar, no taskbar entry (Qt.Tool flag).
- Semi-transparent dark background painted via paintEvent.
- Click-through by default (Windows WS_EX_TRANSPARENT); becomes interactive
  when the cursor moves inside the window boundary so the player can drag it.
- Toggle visibility with Alt+Z (registered externally in main.py).
- Saves/restores position to config.overlay_position.
"""

from __future__ import annotations

import sys
import time

from PyQt6.QtCore import Qt, QTimer, QPoint
from PyQt6.QtGui import QColor, QPainter, QFont, QPen
from PyQt6.QtWidgets import QWidget, QApplication

from src.core.config import Config

_ON_WINDOWS = sys.platform == "win32"
_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_LAYERED = 0x00080000
_GWL_EXSTYLE = -20


def _format_seconds(secs: float) -> str:
    if secs <= 0:
        return "ACTIVE"
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


class OverlayWindow(QWidget):
    """Transparent always-on-top event overlay."""

    _ROW_H = 22
    _PAD = 10
    _WIDTH = 370
    _MAX_ROWS = 8

    def __init__(self, config: Config):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._config = config
        self._events: list[dict] = []
        self._drag_offset: QPoint | None = None
        self._is_click_through = False  # track current state to avoid redundant syscalls

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._restore_position()

        # 1-second tick for countdown updates
        self._tick = QTimer(self)
        self._tick.timeout.connect(self.update)  # triggers paintEvent
        self._tick.start(1000)

        # 100ms hover check to toggle click-through
        self._hover_check = QTimer(self)
        self._hover_check.timeout.connect(self._check_hover)
        self._hover_check.start(100)

        # Start click-through until cursor enters
        self._set_click_through(True)

    # ------------------------------------------------------------------
    # Public slot — called by EventTimerTab.events_loaded signal
    # ------------------------------------------------------------------

    def update_events(self, events: list) -> None:
        """Receive fresh event list and redraw."""
        now_ms = time.time() * 1000
        # Sort: active first, then upcoming by startTime
        def _sort_key(e):
            start = e.get("startTime") or e.get("start_time") or 0
            end = e.get("endTime") or e.get("end_time") or 0
            is_active = float(start) / 1000 <= time.time() and float(end) / 1000 > time.time()
            return (0 if is_active else 1, float(start))

        self._events = sorted(events, key=_sort_key)[: self._MAX_ROWS]
        self._resize_to_content()
        self.update()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def _resize_to_content(self) -> None:
        rows = len(self._events)
        h = self._PAD * 2 + self._ROW_H + rows * self._ROW_H  # title + rows
        self.setFixedSize(self._WIDTH, h)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background
        painter.setBrush(QColor(10, 10, 10, 185))
        painter.setPen(QPen(QColor(80, 80, 80, 200), 1))
        painter.drawRoundedRect(self.rect(), 8, 8)

        now = time.time()

        # Title row
        title_font = QFont("Segoe UI", 9, QFont.Weight.Bold)
        painter.setFont(title_font)
        painter.setPen(QColor(200, 200, 200))
        painter.drawText(
            self._PAD, self._PAD, self._WIDTH - self._PAD * 2, self._ROW_H,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "ARC Raiders — Events",
        )

        row_font = QFont("Segoe UI", 8)
        painter.setFont(row_font)

        for i, event in enumerate(self._events):
            y = self._PAD + self._ROW_H + i * self._ROW_H
            name = event.get("name") or event.get("title") or "Unknown"
            map_name = event.get("map") or event.get("location") or ""
            start_ts = event.get("startTime") or event.get("start_time")
            end_ts = event.get("endTime") or event.get("end_time")

            try:
                start_s = float(start_ts) / 1000.0 if start_ts else None
                end_s = float(end_ts) / 1000.0 if end_ts else None
            except (TypeError, ValueError):
                start_s = end_s = None

            is_active = start_s and start_s <= now and (end_s is None or end_s > now)
            secs_left = (start_s - now) if start_s else 0

            if is_active:
                color = QColor(80, 200, 80)
                time_text = "ACTIVE"
            elif secs_left <= 60:
                color = QColor(220, 60, 60)
                time_text = _format_seconds(secs_left)
            elif secs_left <= 300:
                color = QColor(220, 160, 40)
                time_text = _format_seconds(secs_left)
            else:
                color = QColor(180, 180, 180)
                time_text = _format_seconds(secs_left)

            painter.setPen(color)
            label = f"[{map_name}] {name}" if map_name else name
            painter.drawText(
                self._PAD, y, self._WIDTH - 110, self._ROW_H,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                label,
            )
            painter.drawText(
                self._WIDTH - 100, y, 90, self._ROW_H,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                time_text,
            )

        painter.end()

    # ------------------------------------------------------------------
    # Dragging
    # ------------------------------------------------------------------

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            pos = self.pos()
            self._config.overlay_position = [pos.x(), pos.y()]

    # ------------------------------------------------------------------
    # Click-through
    # ------------------------------------------------------------------

    def _check_hover(self) -> None:
        """Enable interaction when cursor is inside, click-through when outside."""
        if not _ON_WINDOWS:
            return
        from PyQt6.QtGui import QCursor
        cursor_inside = self.geometry().contains(QCursor.pos())
        if cursor_inside and self._is_click_through:
            self._set_click_through(False)
        elif not cursor_inside and not self._is_click_through:
            self._set_click_through(True)

    def _set_click_through(self, enabled: bool) -> None:
        if not _ON_WINDOWS or self._is_click_through == enabled:
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if enabled:
                style |= _WS_EX_TRANSPARENT | _WS_EX_LAYERED
            else:
                style &= ~_WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, _GWL_EXSTYLE, style)
            self._is_click_through = enabled
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Position
    # ------------------------------------------------------------------

    def _restore_position(self) -> None:
        pos = self._config.overlay_position
        if pos and len(pos) == 2:
            self.move(pos[0], pos[1])
        else:
            # Default: top-right corner
            screen = QApplication.primaryScreen()
            if screen:
                rect = screen.availableGeometry()
                self.move(rect.right() - self._WIDTH - 10, rect.top() + 20)
        self._resize_to_content()
