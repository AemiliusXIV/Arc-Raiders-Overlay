"""Item scanner result popup — shown after an OCR scan.

Displays a rich item card (name, rarity, type, sell value, stats, workbench)
as a frameless always-on-top window. Styled to match the dark game aesthetic.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

# ---------------------------------------------------------------------------
# Rarity colours (matching MetaForge palette)
# ---------------------------------------------------------------------------

RARITY_COLORS: dict[str, str] = {
    "common":    "#9e9e9e",
    "uncommon":  "#4caf50",
    "rare":      "#2196f3",
    "epic":      "#9c27b0",
    "legendary": "#ff9800",
}

# stat_block keys worth displaying with friendly labels (only if non-zero)
STAT_LABELS: dict[str, str] = {
    "damage":                  "Damage",
    "health":                  "Health",
    "shield":                  "Shield",
    "healing":                 "Healing",
    "stamina":                 "Stamina",
    "weight":                  "Weight",
    "useTime":                 "Use Time (s)",
    "duration":                "Duration (s)",
    "stackSize":               "Stack Size",
    "fireRate":                "Fire Rate",
    "magazineSize":            "Magazine Size",
    "range":                   "Range",
    "healingPerSecond":        "Healing/s",
    "staminaPerSecond":        "Stamina Regen/s",
    "damageMitigation":        "Damage Mitigation (%)",
    "damagePerSecond":         "Damage/s",
    "illuminationRadius":      "Light Radius",
    "backpackSlots":           "Backpack Slots",
    "augmentSlots":            "Augment Slots",
    "quickUseSlots":           "Quick-Use Slots",
    "safePocketSlots":         "Safe Pocket Slots",
    "damageMult":              "Damage Mult",
    "arcStun":                 "ARC Stun",
    "raiderStun":              "Raider Stun",
}


def _rarity_color(rarity: str) -> str:
    return RARITY_COLORS.get((rarity or "").lower(), "#9e9e9e")


def _fmt_number(value) -> str:
    try:
        n = float(value)
        if n == int(n):
            return f"{int(n):,}"
        return f"{n:,.1f}"
    except (TypeError, ValueError):
        return str(value)


# ---------------------------------------------------------------------------
# Dark-background label helpers
# ---------------------------------------------------------------------------

def _section_label(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setStyleSheet("color: #888; font-size: 10px; font-weight: bold; margin-top: 6px;")
    return lbl


def _value_row(label: str, value: str, value_color: str = "#e0e0e0") -> QWidget:
    row = QWidget()
    row.setStyleSheet("background: transparent;")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 1, 0, 1)
    layout.setSpacing(4)

    lbl = QLabel(label)
    lbl.setStyleSheet("color: #888; font-size: 12px;")
    val = QLabel(value)
    val.setStyleSheet(f"color: {value_color}; font-size: 12px; font-weight: bold;")
    val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    layout.addWidget(lbl)
    layout.addStretch()
    layout.addWidget(val)
    return row


# ---------------------------------------------------------------------------
# Main popup widget
# ---------------------------------------------------------------------------

class ScannerResultWindow(QWidget):
    """Rich item detail card shown after OCR scan."""

    _WIDTH = 380
    _AUTO_CLOSE_MS = 15_000  # auto-close after 15 seconds of inactivity

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedWidth(self._WIDTH)
        self.setStyleSheet("""
            QWidget { background: transparent; color: #e0e0e0; }
            QScrollArea { border: none; background: transparent; }
            QScrollBar:vertical { width: 6px; background: #1a1a1a; }
            QScrollBar::handle:vertical { background: #444; border-radius: 3px; }
        """)

        self._card = QWidget()
        self._card.setObjectName("card")
        self._card.setStyleSheet("""
            QWidget#card {
                background-color: rgba(18, 18, 22, 230);
                border: 1px solid #333;
                border-radius: 10px;
            }
        """)

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(14, 12, 14, 14)
        self._card_layout.setSpacing(4)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._card)

        # Auto-close timer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_item(self, item: dict | None, queried_name: str) -> None:
        """Populate and display the result card."""
        self._clear()

        if item is None:
            self._build_not_found(queried_name)
        else:
            self._build_item(item)

        self.adjustSize()
        self._position()
        self.show()
        self._timer.start(self._AUTO_CLOSE_MS)

    # ------------------------------------------------------------------
    # Layout builders
    # ------------------------------------------------------------------

    def _clear(self) -> None:
        while self._card_layout.count():
            child = self._card_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _build_not_found(self, name: str) -> None:
        hdr = self._header_row("Item not found", None)
        self._card_layout.addWidget(hdr)
        lbl = QLabel(f'"{name}" did not match any item in the database.\nTry scanning again.')
        lbl.setStyleSheet("color: #888; font-size: 12px;")
        lbl.setWordWrap(True)
        self._card_layout.addWidget(lbl)

    def _build_item(self, item: dict) -> None:
        name = item.get("name") or "Unknown"
        rarity = item.get("rarity") or ""
        item_type = item.get("item_type") or ""
        subcategory = item.get("subcategory") or ""
        description = item.get("description") or ""
        value = item.get("value")
        workbench = item.get("workbench") or ""
        stat_block = item.get("stat_block") or {}
        icon_url = item.get("icon") or ""

        # Header row (name + rarity badge + close button)
        self._card_layout.addWidget(self._header_row(name, rarity))

        # Type / subcategory line
        type_parts = [p for p in (item_type, subcategory) if p]
        if type_parts:
            type_lbl = QLabel(" · ".join(type_parts))
            type_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
            self._card_layout.addWidget(type_lbl)

        # Description
        if description:
            desc = QLabel(description)
            desc.setWordWrap(True)
            desc.setStyleSheet("color: #777; font-size: 11px; font-style: italic; margin-top: 4px;")
            self._card_layout.addWidget(desc)

        # --- Values section ---
        self._card_layout.addWidget(_section_label("Value"))

        if value is not None:
            self._card_layout.addWidget(
                _value_row("Sell Value", f"{int(value):,}", "#f0c040")
            )

        # Weight + stack size from stat_block
        weight = stat_block.get("weight")
        stack = stat_block.get("stackSize")
        if weight:
            self._card_layout.addWidget(_value_row("Weight", _fmt_number(weight)))
        if stack and int(stack) > 1:
            self._card_layout.addWidget(_value_row("Stack Size", str(int(stack))))

        # --- Notable stats ---
        stat_rows = []
        for key, label in STAT_LABELS.items():
            if key in ("weight", "stackSize"):
                continue  # already shown above
            v = stat_block.get(key)
            if v and float(v) != 0:
                stat_rows.append((label, _fmt_number(v)))

        if stat_rows:
            self._card_layout.addWidget(_section_label("Stats"))
            for label, val in stat_rows[:8]:  # cap at 8 to keep popup manageable
                self._card_layout.addWidget(_value_row(label, val))

        # --- Workbench ---
        if workbench:
            self._card_layout.addWidget(_section_label("Crafting"))
            wb_lbl = QLabel(f"Workbench: {workbench}")
            wb_lbl.setStyleSheet("color: #c0c0c0; font-size: 12px;")
            self._card_layout.addWidget(wb_lbl)

        # --- Sources / Locations ---
        sources = item.get("sources")
        if sources and isinstance(sources, list) and sources:
            self._card_layout.addWidget(_section_label("Sources"))
            for src in sources[:5]:
                src_lbl = QLabel(f"• {src}" if isinstance(src, str) else f"• {src}")
                src_lbl.setStyleSheet("color: #c0c0c0; font-size: 11px;")
                self._card_layout.addWidget(src_lbl)

        # Separator + close hint
        hint = QLabel("Click × or wait 15s to close")
        hint.setStyleSheet("color: #444; font-size: 10px; margin-top: 6px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight)
        self._card_layout.addWidget(hint)

    def _header_row(self, name: str, rarity: str | None) -> QWidget:
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(6)

        if rarity:
            color = _rarity_color(rarity)
            badge = QLabel(rarity.upper())
            badge.setStyleSheet(
                f"color: {color}; font-size: 10px; font-weight: bold; "
                f"border: 1px solid {color}; border-radius: 3px; padding: 1px 5px;"
            )
            layout.addWidget(badge)

        name_lbl = QLabel(name)
        font = QFont("Segoe UI", 13, QFont.Weight.Bold)
        name_lbl.setFont(font)
        name_lbl.setStyleSheet("color: #ffffff;")
        name_lbl.setWordWrap(True)
        layout.addWidget(name_lbl, 1)

        close_btn = QPushButton("×")
        close_btn.setFixedSize(22, 22)
        close_btn.setStyleSheet(
            "QPushButton { color: #888; background: transparent; border: none; font-size: 16px; }"
            "QPushButton:hover { color: #fff; }"
        )
        close_btn.clicked.connect(self.hide)
        layout.addWidget(close_btn)

        return row

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _position(self) -> None:
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if not screen:
            return
        rect = screen.availableGeometry()
        # Top-right, below where the in-game overlay sits (offset by 200px)
        x = rect.right() - self._WIDTH - 10
        y = rect.top() + 200
        self.move(x, y)

    # ------------------------------------------------------------------
    # Mouse events (keep popup alive while hovering)
    # ------------------------------------------------------------------

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._timer.start(self._AUTO_CLOSE_MS)
