"""Settings dialog — configure hotkeys and other options in-app."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QLineEdit, QVBoxLayout, QWidget,
)


class HotkeyEdit(QLineEdit):
    """QLineEdit that captures a key combination on press and converts it to
    the string format used by the keyboard library (e.g. "alt+x", "ctrl+shift+i").

    Click the field and press any key combo to record it.
    The field is read-only via keyboard — the combo is set on press.
    """

    _MOD_KEYS = {
        Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Shift,
        Qt.Key.Key_Meta, Qt.Key.Key_AltGr,
    }

    def __init__(self, current: str, parent: QWidget | None = None):
        super().__init__(current, parent)
        self.setPlaceholderText("Click and press a key combo…")
        self.setReadOnly(True)
        self.setToolTip(
            "Click this field, then press the key combination you want.\n"
            "Example: press Alt+X to set 'alt+x'."
        )

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = event.key()
        if key in self._MOD_KEYS:
            return  # wait for a non-modifier key

        mods = event.modifiers()
        parts: list[str] = []
        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("shift")

        key_str = QKeySequence(key).toString().lower()
        if not key_str:
            return

        # QKeySequence gives "+" for the plus key — keep it; otherwise strip
        parts.append(key_str)
        combo = "+".join(parts)
        self.setText(combo)


class SettingsDialog(QDialog):
    def __init__(self, scan_hotkey: str, overlay_hotkey: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(400)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        layout = QVBoxLayout(self)

        # Hotkeys group
        hk_group = QGroupBox("Hotkeys")
        form = QFormLayout(hk_group)

        self._scan_edit = HotkeyEdit(scan_hotkey)
        self._overlay_edit = HotkeyEdit(overlay_hotkey)

        form.addRow("Item Scanner:", self._scan_edit)
        form.addRow("Toggle Overlay:", self._overlay_edit)

        hint = QLabel(
            "Click a field and press your desired key combination to record it.\n"
            "Changes take effect immediately without restarting."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        form.addRow(hint)

        layout.addWidget(hk_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def scan_hotkey(self) -> str:
        return self._scan_edit.text().strip()

    @property
    def overlay_hotkey(self) -> str:
        return self._overlay_edit.text().strip()
