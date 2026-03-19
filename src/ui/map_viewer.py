"""Interactive map viewer tab.

Embeds a QWebEngineView (PyQt6's built-in browser) pointing at a third-party
interactive map site. Falls back to a plain clickable link if PyQtWebEngine is
not installed.

Supported map sources:
  - ArcMaps.com (default)
  - MetaForge  (metaforge.app/arc-raiders/map)
  - ArcRaidersMaps.app

Deep-link URL patterns are defined in _MAP_DEEP_LINKS. Where a specific map
URL is not yet known the base URL for the source is used instead.

Polish applied via _map_polish.setup_web_view():
  - Custom user-agent (desktop Chrome) so sites serve full layouts.
  - CSS injection that hides nav bars, footers, cookie banners, ads, and
    scrollbars so the map fills the widget without website chrome.
  - Re-applied on loadFinished to cover SPA client-side navigation.
  - Thin accent progress bar gives visual feedback while the page loads.
"""

from __future__ import annotations

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE = True
except ImportError:
    _WEBENGINE = False

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QProgressBar,
)

from src.api.metaforge import VALID_MAPS
from src.core.config import Config
from src.ui._map_polish import CSS_JS, setup_web_view


# (display label, internal key) pairs — key is what's stored in config and
# used for URL lookups; label is what the player sees in the dropdown.
MAP_SOURCE_LABELS: list[tuple[str, str]] = [
    ("ArcMaps.com (recommended)", "ArcMaps.com"),
    ("MetaForge",                 "MetaForge"),
    ("ArcRaidersMaps.app",        "ArcRaidersMaps.app"),
]
MAP_SOURCES = [key for _, key in MAP_SOURCE_LABELS]  # kept for external callers

_BASE_URLS: dict[str, str] = {
    "ArcMaps.com":        "https://arcmaps.com/map",
    "MetaForge":          "https://metaforge.app/arc-raiders/map",
    "ArcRaidersMaps.app": "https://arcraidersmaps.app",
}

# Deep-link URL patterns per source per map.
# Keys must match entries in VALID_MAPS exactly.
# Where a map key is absent the base URL for that source is used as fallback.
_MAP_DEEP_LINKS: dict[str, dict[str, str]] = {
    "ArcMaps.com": {
        "Dam":         "https://arcmaps.com/map/dam-battlegrounds",
        "Spaceport":   "https://arcmaps.com/map/spaceport",
        "Buried City": "https://arcmaps.com/map/buried-city",
        "Blue Gate":   "https://arcmaps.com/map/blue-gate",
        "Stella Montis": "https://arcmaps.com/map/stella-montis",
    },
    "MetaForge": {},
    "ArcRaidersMaps.app": {},
}

# ── Progress bar styling ───────────────────────────────────────────────────
_PROGRESS_CSS = (
    "QProgressBar {"
    "  border: none;"
    "  background: #1a1a1a;"
    "  margin: 0;"
    "}"
    "QProgressBar::chunk {"
    "  background: qlineargradient("
    "    x1:0, y1:0, x2:1, y2:0,"
    "    stop:0 #3a7bd5, stop:1 #6aadff"
    "  );"
    "  border-radius: 0;"
    "}"
)


def _url_for(source: str, map_name: str) -> str:
    """Return the best URL for the given source + map combination."""
    deep = _MAP_DEEP_LINKS.get(source, {}).get(map_name)
    return deep if deep else _BASE_URLS.get(source, _BASE_URLS["ArcMaps.com"])


class MapViewerTab(QWidget):
    """Map tab: embedded interactive map via QWebEngineView (or fallback link)."""

    # Emitted whenever the current map URL changes (so minimap can follow).
    url_changed = pyqtSignal(str)

    def __init__(self, config: Config, metaforge=None):
        super().__init__()
        self._config = config
        self._current_url = _url_for(config.map_source, config.default_map)
        self._web_view: QWebEngineView | None = None
        self._progress: QProgressBar | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        layout.addLayout(self._build_toolbar())

        if _WEBENGINE:
            # Thin accent bar — visible only while a page is loading.
            self._progress = QProgressBar()
            self._progress.setFixedHeight(3)
            self._progress.setRange(0, 100)
            self._progress.setTextVisible(False)
            self._progress.setStyleSheet(_PROGRESS_CSS)
            self._progress.hide()
            layout.addWidget(self._progress)
            layout.setSpacing(0)          # bar flush against the web view

            self._web_view = QWebEngineView()
            setup_web_view(self._web_view)
            self._web_view.loadStarted.connect(self._on_load_started)
            self._web_view.loadProgress.connect(self._on_load_progress)
            self._web_view.loadFinished.connect(self._on_load_finished)
            layout.addWidget(self._web_view)
            # Load immediately so Chromium starts during app init rather than
            # on first tab click — eliminates the cold-start freeze/flicker.
            self._web_view.setUrl(QUrl(self._current_url))
        else:
            layout.addWidget(self._build_fallback())
            layout.addStretch()

    def _build_toolbar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(6)

        # Source selector — display labels are user-facing; userData keys are
        # used for URL lookups and config storage so they never change.
        bar.addWidget(QLabel("Source:"))
        self._source_combo = QComboBox()
        for label, key in MAP_SOURCE_LABELS:
            self._source_combo.addItem(label, key)
        saved = self._config.map_source
        for i in range(self._source_combo.count()):
            if self._source_combo.itemData(i) == saved:
                self._source_combo.setCurrentIndex(i)
                break
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        bar.addWidget(self._source_combo)

        bar.addSpacing(12)

        # Map selector
        bar.addWidget(QLabel("Map:"))
        self._map_combo = QComboBox()
        self._map_combo.addItems(VALID_MAPS)
        default = self._config.default_map
        if default in VALID_MAPS:
            self._map_combo.setCurrentText(default)
        self._map_combo.currentTextChanged.connect(self._on_map_changed)
        bar.addWidget(self._map_combo)

        bar.addStretch()

        # Refresh button
        self._refresh_btn = QPushButton("\u27f3 Refresh")
        self._refresh_btn.setFixedWidth(80)
        self._refresh_btn.clicked.connect(self._on_refresh)
        bar.addWidget(self._refresh_btn)

        # Open in browser button
        open_btn = QPushButton("Open in Browser")
        open_btn.clicked.connect(self._on_open_browser)
        bar.addWidget(open_btn)

        return bar

    def _build_fallback(self) -> QLabel:
        """Shown when PyQtWebEngine is not installed."""
        url = self._current_url
        lbl = QLabel(
            "Map viewer requires <b>PyQtWebEngine</b> to be installed.<br><br>"
            f'<a href="{url}">Open {self._source_combo.currentData()} in your browser</a><br><br>'
            "<small>Install with: <code>pip install PyQt6-WebEngine</code></small>"
        )
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setOpenExternalLinks(True)
        lbl.setStyleSheet("color: #ccc; font-size: 13px; padding: 40px;")
        self._fallback_label = lbl
        return lbl

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
        # Re-apply CSS via runJavaScript as a belt-and-suspenders pass that
        # also covers SPA client-side navigation where DocumentReady only
        # fires once.
        if self._web_view:
            self._web_view.page().runJavaScript(CSS_JS)

    # ------------------------------------------------------------------
    # Toolbar callbacks
    # ------------------------------------------------------------------

    def _on_source_changed(self) -> None:
        source = self._source_combo.currentData()
        self._config.map_source = source
        self._navigate(_url_for(source, self._map_combo.currentText()))

    def _on_map_changed(self, map_name: str) -> None:
        self._config.default_map = map_name
        self._navigate(_url_for(self._source_combo.currentText(), map_name))

    def _on_refresh(self) -> None:
        if _WEBENGINE and self._web_view:
            self._web_view.reload()

    def _on_open_browser(self) -> None:
        QDesktopServices.openUrl(QUrl(self._current_url))

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, url: str) -> None:
        self._current_url = url
        if _WEBENGINE and self._web_view:
            self._web_view.setUrl(QUrl(url))
        elif not _WEBENGINE and hasattr(self, "_fallback_label"):
            source = self._source_combo.currentData()
            self._fallback_label.setText(
                "Map viewer requires <b>PyQtWebEngine</b> to be installed.<br><br>"
                f'<a href="{url}">Open {source} in your browser</a><br><br>'
                "<small>Install with: <code>pip install PyQt6-WebEngine</code></small>"
            )
        self.url_changed.emit(url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def current_url(self) -> str:
        return self._current_url
