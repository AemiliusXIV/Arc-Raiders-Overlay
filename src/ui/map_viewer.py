"""Map POI viewer tab.

The MetaForge /api/game-map-data endpoint currently returns HTTP 500 for all
maps. No alternative endpoint exists. This tab shows a holding message and will
be re-enabled once the API is functional.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QComboBox, QHBoxLayout,
)

from src.api.metaforge import VALID_MAPS
from src.core.config import Config


class MapViewerTab(QWidget):
    def __init__(self, config: Config, metaforge=None):
        super().__init__()
        self._config = config
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Map:"))
        self._map_combo = QComboBox()
        self._map_combo.addItems(VALID_MAPS)
        default = self._config.default_map
        if default in VALID_MAPS:
            self._map_combo.setCurrentText(default)
        self._map_combo.currentTextChanged.connect(self._on_map_changed)
        toolbar.addWidget(self._map_combo)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        msg = QLabel(
            "Map POI data is currently unavailable.\n\n"
            "The MetaForge map endpoint (/api/game-map-data) is returning a server error "
            "for all maps. This is a known issue on their side.\n\n"
            "Check metaforge.app directly for map information in the meantime."
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        msg.setStyleSheet("color: gray; font-size: 13px; padding: 40px;")
        layout.addWidget(msg)
        layout.addStretch()

    def _on_map_changed(self, map_name: str) -> None:
        self._config.default_map = map_name
