"""Main application window with tab container, tray icon, and always-on-top toggle."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QSystemTrayIcon,
    QTabWidget,
    QMenu,
    QApplication,
)

from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.core.config import Config
from src.core.hotkeys import HotkeyManager
from src.ui.event_timer import EventTimerTab
from src.ui.item_lookup import ItemLookupTab
from src.ui.map_viewer import MapViewerTab
from src.ui.quest_tracker import QuestTrackerTab
from src.ui.needed_items import NeededItemsTab
from src.ui.hideout_tracker import HideoutTab
from src.ui.blueprint_tracker import BlueprintTab
from src.ui.weekly_trials import WeeklyTrialsTab
from src.ui.overlay import OverlayWindow
from src.ui.scanner_result import ScannerResultWindow
from src.ui.settings_dialog import SettingsDialog
from src.ocr.scanner import ItemScanner


class MainWindow(QMainWindow):
    # Emitted from keyboard-library thread; processed safely on the Qt main thread
    _scan_name_signal = pyqtSignal(str)

    def __init__(
        self,
        config: Config,
        metaforge: MetaForgeAPI,
        ardb: ARDBApi,
        hotkeys: HotkeyManager,
    ):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._ardb = ardb
        self._hotkeys = hotkeys

        self.setWindowTitle("Arc Raiders Overlay")
        self.resize(900, 600)
        self._apply_always_on_top(config.always_on_top)

        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._event_tab = EventTimerTab(config, metaforge)
        self._item_tab = ItemLookupTab(config, metaforge, ardb)
        self._map_tab = MapViewerTab(config, metaforge)
        self._quest_tab = QuestTrackerTab(config, metaforge, ardb)
        self._needed_tab = NeededItemsTab(config, metaforge)
        self._hideout_tab = HideoutTab(config, metaforge)
        self._blueprint_tab = BlueprintTab(config, metaforge, ardb)
        self._trials_tab = WeeklyTrialsTab(config, metaforge)

        self._tabs.addTab(self._event_tab, "Events")
        self._tabs.addTab(self._item_tab, "Items")
        self._tabs.addTab(self._map_tab, "Map")
        self._tabs.addTab(self._quest_tab, "Quests")
        self._tabs.addTab(self._needed_tab, "Needed Items")
        self._tabs.addTab(self._hideout_tab, "Hideout")
        self._tabs.addTab(self._blueprint_tab, "Blueprints")
        self._tabs.addTab(self._trials_tab, "Weekly Trials")

        # In-game overlay — created hidden; toggled by Alt+Z hotkey
        self._overlay = OverlayWindow(config)
        self._event_tab.events_loaded.connect(self._overlay.update_events)

        # Scanner result popup — shown after OCR scan
        self._scan_popup = ScannerResultWindow()
        self._scan_name_signal.connect(self._on_scan_name)

        self._build_menu()
        self._build_tray()
        self._register_hotkeys()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def overlay(self) -> OverlayWindow:
        return self._overlay

    @property
    def event_tab(self) -> EventTimerTab:
        return self._event_tab

    # ------------------------------------------------------------------
    # Hotkey registration
    # ------------------------------------------------------------------

    def _register_hotkeys(self) -> None:
        if not self._hotkeys.available:
            print("[Hotkeys] keyboard library not available — hotkeys disabled")
            return

        if self._hotkeys.register(self._config.hotkey_scan, self._ocr_trigger):
            print(f"[Hotkeys] Item scanner bound to: {self._config.hotkey_scan}")
        else:
            print(f"[Hotkeys] Failed to bind item scanner to {self._config.hotkey_scan}")

        if self._hotkeys.register(self._config.hotkey_overlay, self.toggle_overlay):
            print(f"[Hotkeys] Overlay toggle bound to: {self._config.hotkey_overlay}")
        else:
            print(f"[Hotkeys] Failed to bind overlay toggle to {self._config.hotkey_overlay}")

    def _rebind_hotkeys(self, new_scan: str, new_overlay: str) -> tuple[bool, str]:
        """Unregister old hotkeys, apply new ones. Returns (success, error_msg)."""
        if not self._hotkeys.available:
            return False, "keyboard library not available"

        self._hotkeys.unregister(self._config.hotkey_scan)
        self._hotkeys.unregister(self._config.hotkey_overlay)

        errors = []
        if new_scan:
            if self._hotkeys.register(new_scan, self._ocr_trigger):
                self._config.hotkey_scan = new_scan
            else:
                errors.append(f"Could not bind item scanner to '{new_scan}'")
                # Restore old binding
                self._hotkeys.register(self._config.hotkey_scan, self._ocr_trigger)

        if new_overlay:
            if self._hotkeys.register(new_overlay, self.toggle_overlay):
                self._config.hotkey_overlay = new_overlay
            else:
                errors.append(f"Could not bind overlay toggle to '{new_overlay}'")
                self._hotkeys.register(self._config.hotkey_overlay, self.toggle_overlay)

        if errors:
            return False, "\n".join(errors)
        return True, ""

    def _ocr_trigger(self) -> None:
        """Called from keyboard-library thread — must not touch Qt widgets directly."""
        scanner = ItemScanner(on_result=lambda name: self._scan_name_signal.emit(name))
        if scanner.available:
            scanner.scan()
        else:
            # Signal the main thread to show the setup dialog
            self._scan_name_signal.emit("\x00__UNAVAILABLE__")

    def _on_scan_name(self, name: str) -> None:
        """Runs on main thread. Find the item and show the result popup."""
        if name == "\x00__UNAVAILABLE__":
            QMessageBox.information(
                self,
                "Item Scanner — Setup Required",
                "The item scanner requires Tesseract OCR to be installed.\n\n"
                "1. Download and install Tesseract from:\n"
                "   https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "2. During installation, check \"Add Tesseract to PATH\".\n\n"
                "3. Restart Arc Raiders Overlay.\n\n"
                "Python packages also required:\n"
                "   pip install mss pytesseract Pillow",
            )
            return

        # Find best matching item in the cached items list
        item = self._find_item_by_name(name)
        self._scan_popup.show_item(item, name)

    def _find_item_by_name(self, name: str) -> dict | None:
        """Case-insensitive name match against the cached items list."""
        items = self._item_tab.cached_items
        if not items:
            return None
        query = name.strip().lower()
        # Exact match first
        for item in items:
            if (item.get("name") or "").lower() == query:
                return item
        # Contains match
        for item in items:
            if query in (item.get("name") or "").lower():
                return item
        # Partial word overlap
        query_words = set(query.split())
        best, best_score = None, 0
        for item in items:
            item_words = set((item.get("name") or "").lower().split())
            score = len(query_words & item_words)
            if score > best_score:
                best, best_score = item, score
        return best if best_score > 0 else None

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("View")

        self._aot_action = QAction("Always on Top", self, checkable=True)
        self._aot_action.setChecked(self._config.always_on_top)
        self._aot_action.toggled.connect(self._on_always_on_top_toggled)
        view_menu.addAction(self._aot_action)

        self._overlay_action = QAction("Show In-Game Overlay", self, checkable=True)
        self._overlay_action.setChecked(False)
        self._overlay_action.toggled.connect(self._on_overlay_toggled)
        view_menu.addAction(self._overlay_action)

        minimize_action = QAction("Minimize to Tray", self)
        minimize_action.triggered.connect(self.hide)
        view_menu.addAction(minimize_action)

        settings_menu = self.menuBar().addMenu("Settings")
        hotkeys_action = QAction("Configure Hotkeys…", self)
        hotkeys_action.triggered.connect(self._open_settings)
        settings_menu.addAction(hotkeys_action)

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(self)
        self._tray.setIcon(self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        ))
        self._tray.setToolTip("Arc Raiders Overlay")

        tray_menu = QMenu()
        show_action = QAction("Show", self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)

        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)

        self._tray.setContextMenu(tray_menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    # ------------------------------------------------------------------
    # Always-on-top
    # ------------------------------------------------------------------

    def _apply_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        self._config.always_on_top = checked
        self._apply_always_on_top(checked)

    # ------------------------------------------------------------------
    # Overlay toggle
    # ------------------------------------------------------------------

    def _on_overlay_toggled(self, checked: bool) -> None:
        self._overlay.setVisible(checked)

    def toggle_overlay(self) -> None:
        """Toggle overlay visibility (called from hotkey or menu)."""
        visible = not self._overlay.isVisible()
        self._overlay.setVisible(visible)
        self._overlay_action.setChecked(visible)

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            self._config.hotkey_scan,
            self._config.hotkey_overlay,
            parent=self,
        )
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return

        ok, err = self._rebind_hotkeys(dlg.scan_hotkey, dlg.overlay_hotkey)
        if not ok:
            QMessageBox.warning(self, "Hotkey Error", err)

    # ------------------------------------------------------------------
    # Public helpers used by hotkey / OCR
    # ------------------------------------------------------------------

    def search_item(self, name: str) -> None:
        """Switch to Items tab and populate search bar (called from OCR hotkey)."""
        self._tabs.setCurrentWidget(self._item_tab)
        self._item_tab.set_search(name)

    def closeEvent(self, event) -> None:
        # Minimize to tray instead of closing
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "Arc Raiders Overlay",
            "Running in background. Double-click tray icon to restore.",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )
