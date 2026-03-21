"""Overlay toast notification — shown briefly when the in-game overlay is toggled.

Animates: fade-in (350 ms) → hold (1300 ms) → fade-out (350 ms), then hides
itself automatically.  Re-entrant: calling show_toast() while an animation is
already running restarts from the beginning so rapid keypresses don't get stuck.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget


class OverlayToast(QWidget):
    """Small floating notification with fade-in / hold / fade-out animation."""

    _FADE_MS = 350    # ms for each fade animation
    _HOLD_MS = 1_300  # ms to hold at full opacity between fades

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowOpacity(0.0)

        self._label = QLabel()
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet("""
            QLabel {
                color: #ffffff;
                background: rgba(18, 18, 22, 220);
                border: 1px solid #555;
                border-radius: 8px;
                padding: 10px 24px;
            }
        """)
        font = QFont("Segoe UI", 12, QFont.Weight.Bold)
        self._label.setFont(font)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._label)

        # Fade in
        self._fade_in = QPropertyAnimation(self, b"windowOpacity")
        self._fade_in.setDuration(self._FADE_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._fade_in.finished.connect(self._hold_timer_start)

        # Hold timer
        self._hold_timer = QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(self._HOLD_MS)
        self._hold_timer.timeout.connect(self._start_fade_out)

        # Fade out
        self._fade_out = QPropertyAnimation(self, b"windowOpacity")
        self._fade_out.setDuration(self._FADE_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fade_out.finished.connect(self.hide)

        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_toast(self, message: str) -> None:
        """Display *message* with a fade-in → hold → fade-out sequence.

        Safe to call while a previous toast is still animating — the in-progress
        animation is stopped and the sequence restarts from the beginning.
        """
        self._fade_in.stop()
        self._fade_out.stop()
        self._hold_timer.stop()

        self._label.setText(message)
        self.adjustSize()
        self._reposition()

        self.setWindowOpacity(0.0)
        self.show()
        self._fade_in.start()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _hold_timer_start(self) -> None:
        self._hold_timer.start()

    def _start_fade_out(self) -> None:
        self._fade_out.start()

    def _reposition(self) -> None:
        """Centre horizontally, place ~15 % from top of primary screen."""
        screen = QApplication.primaryScreen()
        if not screen:
            return
        rect = screen.availableGeometry()
        x = rect.center().x() - self.width() // 2
        y = rect.top() + int(rect.height() * 0.15)
        self.move(x, y)
