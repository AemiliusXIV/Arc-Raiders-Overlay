"""Settings dialog — configure hotkeys and other options in-app."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QKeySequence
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QSlider, QVBoxLayout, QWidget,
)

from src.__version__ import __version__


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
    def __init__(
        self,
        scan_hotkey: str,
        overlay_hotkey: str,
        minimap_hotkey: str,
        minimap_opacity: float,
        project_sync_hotkey: str = "alt+p",
        project_auto_sync: bool = False,
        show_overlay_toast: bool = True,
        quest_sync_hotkey: str = "alt+q",
        quest_auto_sync: bool = False,
        parent: QWidget | None = None,
    ):
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
        self._minimap_edit = HotkeyEdit(minimap_hotkey)

        form.addRow("Item Scanner:", self._scan_edit)
        form.addRow("Toggle Overlay:", self._overlay_edit)
        form.addRow("Toggle Minimap:", self._minimap_edit)

        hint = QLabel(
            "Click a field and press your desired key combination to record it.\n"
            "Changes take effect immediately without restarting."
        )
        hint.setStyleSheet("color: #888; font-size: 11px;")
        hint.setWordWrap(True)
        form.addRow(hint)

        layout.addWidget(hk_group)

        # Minimap group
        mm_group = QGroupBox("Minimap")
        mm_form = QFormLayout(mm_group)

        opacity_row = QHBoxLayout()
        self._opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self._opacity_slider.setRange(20, 100)
        self._opacity_slider.setValue(int(minimap_opacity * 100))
        self._opacity_slider.setToolTip("Minimap overlay opacity")
        self._opacity_label = QLabel(f"{int(minimap_opacity * 100)}%")
        self._opacity_label.setFixedWidth(36)
        self._opacity_slider.valueChanged.connect(
            lambda v: self._opacity_label.setText(f"{v}%")
        )
        opacity_row.addWidget(self._opacity_slider)
        opacity_row.addWidget(self._opacity_label)

        mm_form.addRow("Opacity:", opacity_row)

        layout.addWidget(mm_group)

        # Project Sync group
        ps_group = QGroupBox("Project Sync")
        ps_form = QFormLayout(ps_group)

        self._project_sync_edit = HotkeyEdit(project_sync_hotkey)
        ps_form.addRow("Scan Hotkey:", self._project_sync_edit)

        self._auto_sync_cb = QCheckBox("Auto-sync when project screen is detected")
        self._auto_sync_cb.setChecked(project_auto_sync)
        self._auto_sync_cb.setToolTip(
            "When enabled, the overlay polls the screen every few seconds.\n"
            "If a project hand-in screen is detected it is read automatically."
        )
        ps_form.addRow(self._auto_sync_cb)

        layout.addWidget(ps_group)

        # Quest Sync group
        qs_group = QGroupBox("Quest Sync")
        qs_form = QFormLayout(qs_group)

        self._quest_sync_edit = HotkeyEdit(quest_sync_hotkey)
        qs_form.addRow("Scan Hotkey:", self._quest_sync_edit)

        self._quest_auto_sync_cb = QCheckBox(
            "Silently sync quest status when hotkey is pressed (no dialog)"
        )
        self._quest_auto_sync_cb.setChecked(quest_auto_sync)
        self._quest_auto_sync_cb.setToolTip(
            "When enabled, pressing the hotkey scans immediately without opening\n"
            "the guided dialog. Make sure the play menu is visible before pressing."
        )
        qs_form.addRow(self._quest_auto_sync_cb)

        layout.addWidget(qs_group)

        # Notifications group
        notif_group = QGroupBox("Notifications")
        notif_form = QFormLayout(notif_group)

        self._overlay_toast_cb = QCheckBox("Show notification when overlay is toggled on/off")
        self._overlay_toast_cb.setChecked(show_overlay_toast)
        self._overlay_toast_cb.setToolTip(
            "Displays a brief 'Overlay Enabled' / 'Overlay Disabled' message\n"
            "on screen when you press the overlay toggle hotkey.\n"
            "Disable if you find it distracting."
        )
        notif_form.addRow(self._overlay_toast_cb)

        layout.addWidget(notif_group)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        version_lbl = QLabel(f"Arc Raiders Overlay  v{__version__}")
        version_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version_lbl.setStyleSheet("color: #555; font-size: 10px; padding-top: 4px;")
        layout.addWidget(version_lbl)

    @property
    def scan_hotkey(self) -> str:
        return self._scan_edit.text().strip()

    @property
    def overlay_hotkey(self) -> str:
        return self._overlay_edit.text().strip()

    @property
    def minimap_hotkey(self) -> str:
        return self._minimap_edit.text().strip()

    @property
    def minimap_opacity(self) -> float:
        return self._opacity_slider.value() / 100.0

    @property
    def project_sync_hotkey(self) -> str:
        return self._project_sync_edit.text().strip()

    @property
    def project_auto_sync(self) -> bool:
        return self._auto_sync_cb.isChecked()

    @property
    def show_overlay_toast(self) -> bool:
        return self._overlay_toast_cb.isChecked()

    @property
    def quest_sync_hotkey(self) -> str:
        return self._quest_sync_edit.text().strip()

    @property
    def quest_auto_sync(self) -> bool:
        return self._quest_auto_sync_cb.isChecked()
