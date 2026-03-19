"""Minimap overlay window — always-on-top, resizable, semi-transparent web view.

Shows the same interactive map source as the main Map tab in a compact
floating window that can be kept visible while in-game.

Features:
- Frameless, always-on-top tool window.
- Thin header bar: drag handle, opacity slider, close button.
- QSizeGrip at bottom-right corner for resizing.
- Window opacity controlled via setWindowOpacity().
- Position and size persist across sessions via config.
- Falls back to a clickable label if PyQtWebEngine is not installed.

Polish (via _map_polish):
- Custom user-agent so map sites serve full desktop layouts.
- CSS injection strips nav bars, footers, cookie banners, ads, scrollbars.
- Thin accent progress bar in the header row shows page-load progress.
"""

from __future__ import annotations

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE = True
except ImportError:
    _WEBENGINE = False

from PyQt6.QtCore import Qt, QUrl, QPoint, QTimer
from PyQt6.QtGui import QColor, QPainter, QPen, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QSlider, QSizeGrip, QApplication, QProgressBar,
)

from src.core.config import Config
from src.ui._map_polish import CSS_JS, setup_web_view

_HEADER_H = 30          # slightly taller to accommodate the progress bar row
_MIN_SIZE = (200, 150)
_DEFAULT_SIZE = (420, 380)

# Thin accent bar — same gradient as the main map tab for visual consistency.
_PROGRESS_CSS = (
    "QProgressBar {"
    "  border: none;"
    "  background: #111;"
    "  margin: 0;"
    "}"
    "QProgressBar::chunk {"
    "  background: qlineargradient("
    "    x1:0, y1:0, x2:1, y2:0,"
    "    stop:0 #3a7bd5, stop:1 #6aadff"
    "  );"
    "}"
)


class _Header(QWidget):
    """Drag handle + opacity slider + close button."""

    def __init__(self, parent: "MinimapOverlay"):
        super().__init__(parent)
        self._overlay = parent
        self.setFixedHeight(_HEADER_H)
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 4, 0)
        layout.setSpacing(6)

        title = QLabel("Minimap")
        title.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(title)
        layout.addStretch()

        opacity_lbl = QLabel("Opacity:")
        opacity_lbl.setStyleSheet("color: #888; font-size: 10px;")
        layout.addWidget(opacity_lbl)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(20, 100)
        self._slider.setFixedWidth(80)
        self._slider.setValue(int(parent._config.minimap_opacity * 100))
        self._slider.setToolTip("Minimap opacity")
        self._slider.valueChanged.connect(self._on_opacity_changed)
        layout.addWidget(self._slider)

        close_btn = QPushButton("\u00d7")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton { color: #aaa; background: transparent; border: none; font-size: 14px; }"
            "QPushButton:hover { color: #fff; }"
        )
        close_btn.clicked.connect(parent.hide)
        layout.addWidget(close_btn)

        self._drag_offset: QPoint | None = None

    def _on_opacity_changed(self, value: int) -> None:
        opacity = value / 100.0
        self._overlay.setWindowOpacity(opacity)
        self._overlay._config.minimap_opacity = opacity

    def set_opacity_slider(self, opacity: float) -> None:
        self._slider.setValue(int(opacity * 100))

    # Drag the whole overlay window by clicking the header
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self._overlay.frameGeometry().topLeft()
            )

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._overlay.move(
                event.globalPosition().toPoint() - self._drag_offset
            )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = None
            pos = self._overlay.pos()
            self._overlay._config.minimap_position = [pos.x(), pos.y()]

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(20, 20, 20, 230))
        painter.setPen(QPen(QColor(60, 60, 60), 1))
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.end()


class MinimapOverlay(QWidget):
    """Always-on-top resizable minimap overlay window."""

    def __init__(self, config: Config):
        super().__init__(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._config = config
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumSize(*_MIN_SIZE)

        self._web_view: QWebEngineView | None = None
        self._progress: QProgressBar | None = None
        self._build_ui()
        self._restore_geometry()
        self.setWindowOpacity(config.minimap_opacity)

        # Debounce resize saves — only write to config 500ms after last resize
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._save_size)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._header = _Header(self)
        layout.addWidget(self._header)

        # 2px accent bar — sits directly below the header, hidden when idle.
        self._progress = QProgressBar()
        self._progress.setFixedHeight(2)
        self._progress.setRange(0, 100)
        self._progress.setTextVisible(False)
        self._progress.setStyleSheet(_PROGRESS_CSS)
        self._progress.hide()
        layout.addWidget(self._progress)

        if _WEBENGINE:
            self._web_view = QWebEngineView()
            setup_web_view(self._web_view)
            self._web_view.loadStarted.connect(self._on_load_started)
            self._web_view.loadProgress.connect(self._on_load_progress)
            self._web_view.loadFinished.connect(self._on_load_finished)
            layout.addWidget(self._web_view)
        else:
            self._fallback_label = QLabel(
                "Map viewer requires <b>PyQtWebEngine</b>.<br>"
                '<a href="">Open in browser</a>'
            )
            self._fallback_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._fallback_label.setWordWrap(True)
            self._fallback_label.setOpenExternalLinks(True)
            self._fallback_label.setStyleSheet(
                "color: #888; font-size: 12px; padding: 20px;"
            )
            layout.addWidget(self._fallback_label)

        # Size grip at bottom-right
        grip = QSizeGrip(self)
        grip.setFixedSize(16, 16)
        grip.move(self.width() - 16, self.height() - 16)
        grip.raise_()

    # ------------------------------------------------------------------
    # Load-progress callbacks
    # ------------------------------------------------------------------

    def _on_load_started(self) -> None:
        if self._progress:
            self._progress.setValue(0)
            self._progress.show()

    def _on_load_progress(self, value: int) -> None:
        if self._progress:
            self._progress.setValue(value)

    def _on_load_finished(self, ok: bool) -> None:  # noqa: ARG002
        if self._progress:
            self._progress.hide()
        # Belt-and-suspenders re-application for SPA navigation.
        if self._web_view:
            self._web_view.page().runJavaScript(CSS_JS)

    # ------------------------------------------------------------------
    # Geometry persistence
    # ------------------------------------------------------------------

    def _restore_geometry(self) -> None:
        pos = self._config.minimap_position
        size = self._config.minimap_size

        w, h = _DEFAULT_SIZE
        if size and len(size) == 2:
            w, h = size[0], size[1]
        self.resize(w, h)

        if pos and len(pos) == 2:
            self.move(pos[0], pos[1])
        else:
            screen = QApplication.primaryScreen()
            if screen:
                rect = screen.availableGeometry()
                self.move(
                    rect.right() - w - 20,
                    rect.top() + rect.height() // 2 - h // 2,
                )

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        # Re-position any child SizeGrip
        for child in self.findChildren(QSizeGrip):
            child.move(self.width() - child.width(), self.height() - child.height())
        self._resize_timer.start(500)

    def _save_size(self) -> None:
        self._config.minimap_size = [self.width(), self.height()]

    # ------------------------------------------------------------------
    # Public slot — called when map source changes in the main tab
    # ------------------------------------------------------------------

    def load_url(self, url: str) -> None:
        if _WEBENGINE and self._web_view:
            self._web_view.setUrl(QUrl(url))
        elif not _WEBENGINE and hasattr(self, "_fallback_label"):
            self._fallback_label.setText(
                "Map viewer requires <b>PyQtWebEngine</b>.<br>"
                f'<a href="{url}">Open in browser</a>'
            )

    # ------------------------------------------------------------------
    # Opacity update (called from settings dialog)
    # ------------------------------------------------------------------

    def set_opacity(self, opacity: float) -> None:
        self._config.minimap_opacity = opacity
        self.setWindowOpacity(opacity)
        self._header.set_opacity_slider(opacity)

    # ------------------------------------------------------------------
    # Background painting (dark rounded border)
    # ------------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(10, 10, 10, 200))
        painter.setPen(QPen(QColor(70, 70, 70, 220), 1))
        painter.drawRoundedRect(self.rect(), 6, 6)
        painter.end()
