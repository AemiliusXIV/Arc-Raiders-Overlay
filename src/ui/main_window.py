"""Main application window with tab container, tray icon, and always-on-top toggle."""

from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QSystemTrayIcon,
    QTabWidget,
    QMenu,
    QApplication,
)

from src.__version__ import __version__
from src.api.metaforge import MetaForgeAPI
from src.api.ardb import ARDBApi
from src.api.raidtheory import RaidTheoryClient
from src.core.config import Config
from src.core.hotkeys import HotkeyManager
from src.core.worker import Worker
from src.ui.event_timer import EventTimerTab
from src.ui.item_lookup import ItemLookupTab
from src.ui.map_viewer import MapViewerTab
from src.ui.quest_tracker import QuestTrackerTab
from src.ui.needed_items import NeededItemsTab
from src.ui.hideout_tracker import HideoutTab
from src.ui.blueprint_tracker import BlueprintTab
from src.ui.weekly_trials import WeeklyTrialsTab
from src.ui.minimap_overlay import MinimapOverlay
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
        rt: RaidTheoryClient,
        hotkeys: HotkeyManager,
    ):
        super().__init__()
        self._config = config
        self._metaforge = metaforge
        self._ardb = ardb
        self._rt = rt
        self._hotkeys = hotkeys
        self._active_workers: set[Worker] = set()  # keep refs until threads finish

        self.setWindowTitle(f"Arc Raiders Overlay  v{__version__}")
        self.resize(900, 600)
        self._apply_always_on_top(config.always_on_top)

        # Prevents concurrent OCR scans: OCR is slow (~2s) and the keyboard
        # library may fire callbacks from a background thread. If the lock is
        # already held the new hotkey press is silently dropped.
        self._scan_lock = threading.Lock()

        self._tabs = QTabWidget()
        self.setCentralWidget(self._tabs)

        self._event_tab = EventTimerTab(config, metaforge)
        self._item_tab = ItemLookupTab(config, metaforge, ardb)
        self._map_tab = MapViewerTab(config, metaforge)
        self._quest_tab = QuestTrackerTab(config, metaforge, ardb)
        self._needed_tab = NeededItemsTab(config, metaforge)
        self._hideout_tab = HideoutTab(config, rt)
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

        # Minimap overlay — created hidden; toggled by Alt+M hotkey
        self._minimap = MinimapOverlay(config)
        self._map_tab.url_changed.connect(self._minimap.load_url)

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

        if self._hotkeys.register(self._config.hotkey_minimap, self.toggle_minimap):
            print(f"[Hotkeys] Minimap toggle bound to: {self._config.hotkey_minimap}")
        else:
            print(f"[Hotkeys] Failed to bind minimap toggle to {self._config.hotkey_minimap}")

    def _rebind_hotkeys(
        self, new_scan: str, new_overlay: str, new_minimap: str
    ) -> tuple[bool, str]:
        """Unregister old hotkeys, apply new ones. Returns (success, error_msg)."""
        if not self._hotkeys.available:
            return False, "keyboard library not available"

        self._hotkeys.unregister(self._config.hotkey_scan)
        self._hotkeys.unregister(self._config.hotkey_overlay)
        self._hotkeys.unregister(self._config.hotkey_minimap)

        errors = []
        if new_scan:
            if self._hotkeys.register(new_scan, self._ocr_trigger):
                self._config.hotkey_scan = new_scan
            else:
                errors.append(f"Could not bind item scanner to '{new_scan}'")
                self._hotkeys.register(self._config.hotkey_scan, self._ocr_trigger)

        if new_overlay:
            if self._hotkeys.register(new_overlay, self.toggle_overlay):
                self._config.hotkey_overlay = new_overlay
            else:
                errors.append(f"Could not bind overlay toggle to '{new_overlay}'")
                self._hotkeys.register(self._config.hotkey_overlay, self.toggle_overlay)

        if new_minimap:
            if self._hotkeys.register(new_minimap, self.toggle_minimap):
                self._config.hotkey_minimap = new_minimap
            else:
                errors.append(f"Could not bind minimap toggle to '{new_minimap}'")
                self._hotkeys.register(self._config.hotkey_minimap, self.toggle_minimap)

        if errors:
            return False, "\n".join(errors)
        return True, ""

    def _ocr_trigger(self) -> None:
        """Called from the keyboard-library thread — must not touch Qt widgets.

        Acquires a non-blocking lock so that a second hotkey press while a scan
        is already running is silently ignored rather than starting a concurrent
        scan that could corrupt shared state.

        The scan itself is dispatched to a *fresh* daemon thread rather than
        running on the keyboard library's own thread.  mss and pytesseract are
        not guaranteed to be safe when re-entered on the same long-lived thread,
        which caused a crash on the second scan.
        """
        if not self._scan_lock.acquire(blocking=False):
            print("[Scanner] Scan already in progress — hotkey ignored")
            return

        scanner = ItemScanner(on_result=lambda name: self._scan_name_signal.emit(name))
        if not scanner.available:
            self._scan_lock.release()
            self._scan_name_signal.emit("\x00__UNAVAILABLE__")
            return

        def _run_scan() -> None:
            try:
                scanner.scan()
            except Exception as exc:
                print(f"[Scanner] Unexpected error in OCR trigger: {exc}")
                try:
                    self._scan_name_signal.emit("\x00__ERROR__")
                except Exception:
                    pass
            finally:
                self._scan_lock.release()

        threading.Thread(target=_run_scan, daemon=True).start()

    def _on_scan_name(self, name: str) -> None:
        """Runs on the main thread (delivered via queued signal from OCR thread)."""
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

        if name == "\x00__NO_RESULT__":
            self._scan_popup.show_item(None, "no item detected", None)
            return

        if name == "\x00__ERROR__":
            self._scan_popup.show_item(None, "scan error", None)
            return

        try:
            item = self._find_item_by_name(name)
        except Exception as exc:
            print(f"[Scanner] Error looking up item: {exc}")
            item = None

        # Fetch RT enrichment in a Worker; Worker._Signals lives in the main
        # thread so finished/error are always delivered to the main thread via
        # Qt's queued-connection mechanism — safe to update UI from the slots.
        try:
            quests = self._needed_tab.cached_quests
        except Exception:
            quests = []

        try:
            expedition_projects = self._metaforge.get_expedition_projects()
        except Exception:
            expedition_projects = []

        # Prefer the matched item's canonical name for RT lookup; the raw OCR
        # string is multi-line (all candidates) and won't match the name_map.
        enrich_name = (
            (item.get("name") if item else None)
            or name.strip().split("\n")[0]
        )
        print(f"[Scanner] Enriching as: {repr(enrich_name)}")

        def _do_enrich():
            try:
                return self._rt.enrich(enrich_name, quests, expedition_projects)
            except Exception as exc:
                print(f"[Scanner] RT enrichment failed: {exc}")
                return None

        worker = Worker(_do_enrich)

        def _on_enrichment(enrichment: object) -> None:
            try:
                self._scan_popup.show_item(
                    item, name,
                    enrichment if isinstance(enrichment, dict) else None,
                )
            except Exception as exc:
                print(f"[Scanner] Error showing result popup: {exc}")
                try:
                    self._scan_popup.show_item(None, name, None)
                except Exception:
                    pass
            finally:
                self._active_workers.discard(worker)

        def _on_enrich_error(msg: str) -> None:
            print(f"[Scanner] Enrichment worker error: {msg}")
            try:
                self._scan_popup.show_item(item, name, None)
            except Exception as exc:
                print(f"[Scanner] Error showing fallback popup: {exc}")
            finally:
                self._active_workers.discard(worker)

        worker.finished.connect(_on_enrichment)
        worker.error.connect(_on_enrich_error)
        self._active_workers.add(worker)
        worker.start()

    def _find_item_by_name(self, name: str) -> dict | None:
        """
        Case-insensitive name match against the cached items list.

        `name` may be a newline-separated list of OCR candidates (produced by
        the scanner when the tooltip contains multiple ALL-CAPS groups).

        Matching is done in three tiers, lowest-to-highest confidence:
          Tier 1 — Exact:    query == item name (case-insensitive)
          Tier 2 — Contains: query is a substring of the item name and covers
                             ≥40% of it (prevents "BLUEPRINT" matching
                             "Angled Grip II Blueprint")
          Tier 3 — Overlap:  ≥50% of query words (min 2) appear in item name

        Critically, ALL candidates are evaluated at each tier before moving to
        the next.  This guarantees an exact match on any candidate always wins
        over a fuzzy match on an earlier candidate — so if the OCR yields
        ["BLUEPRINT", "SNAP HOOK BLUEPRINT"], the exact match on the second
        candidate is returned rather than a loose contains hit on the first.
        """
        items = self._item_tab.cached_items
        if not items:
            print("[Match] Item cache is empty — Items tab may not have loaded yet")
            return None

        candidates = [c.strip() for c in name.strip().split("\n") if c.strip()]
        print(f"[Match] Candidates: {candidates}  ({len(items)} items in cache)")

        # Tier 1 — exact (all candidates)
        for cand in candidates:
            item = self._match_exact(cand, items)
            if item:
                print(f"[Match] Tier 1 exact: {repr(cand)} → {item.get('name')!r}")
                return item

        # Tier 2 — contains (all candidates)
        for cand in candidates:
            item = self._match_contains(cand, items)
            if item:
                print(f"[Match] Tier 2 contains: {repr(cand)} → {item.get('name')!r}")
                return item

        # Tier 3 — word overlap (all candidates)
        for cand in candidates:
            item = self._match_overlap(cand, items)
            if item:
                print(f"[Match] Tier 3 overlap: {repr(cand)} → {item.get('name')!r}")
                return item

        print("[Match] No match found for any candidate")
        return None

    def _match_exact(self, query_raw: str, items: list[dict]) -> dict | None:
        """Case-insensitive exact match."""
        query = query_raw.strip().lower()
        for item in items:
            if (item.get("name") or "").lower() == query:
                return item
        return None

    def _match_contains(self, query_raw: str, items: list[dict]) -> dict | None:
        """Substring match — query must cover ≥40% of the matched item name.

        Without the length ratio guard, a single shared word like "BLUEPRINT"
        would match "Angled Grip II Blueprint" (a long name that merely contains
        the word).  The 40% threshold requires the query to represent a
        substantial portion of the name, so short generic fragments are skipped.

        Among all qualifying items, the one with the highest query/name ratio
        is returned (most specific match first).
        """
        query = query_raw.strip().lower()
        if not query:
            return None
        best_item, best_ratio = None, 0.0
        for item in items:
            item_name = (item.get("name") or "").lower()
            if not item_name or query not in item_name:
                continue
            ratio = len(query) / len(item_name)
            if ratio < 0.4:
                continue
            if ratio > best_ratio:
                best_item, best_ratio = item, ratio
        return best_item

    def _match_overlap(self, query_raw: str, items: list[dict]) -> dict | None:
        """Word-set overlap match.

        Requires both an absolute minimum of 2 matching words AND that at
        least half the query words match.  This prevents a single shared word
        like "Blueprint" from producing a false-positive hit.

        Examples for a 3-word query ("SNAP HOOK BLUEPRINT"):
          "Angled Grip II Blueprint"  → 1 shared word  < min(2, ceil(3/2)=2) → rejected
          "Snap Hook Blueprint"       → 3 shared words ≥ 2                   → accepted
        """
        query = query_raw.strip().lower()
        query_words = set(query.split())
        if len(query_words) < 2:
            return None
        # Require ≥50% of query words to match, with a hard floor of 2.
        min_score = max(2, -(-len(query_words) // 2))  # ceil division
        best, best_score = None, 0
        for item in items:
            item_words = set((item.get("name") or "").lower().split())
            score = len(query_words & item_words)
            if score > best_score:
                best, best_score = item, score
        return best if best_score >= min_score else None

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        view_menu = self.menuBar().addMenu("View")

        self._aot_action = QAction("Always on Top", self, checkable=True)
        self._aot_action.setChecked(self._config.always_on_top)
        self._aot_action.toggled.connect(self._on_always_on_top_toggled)
        view_menu.addAction(self._aot_action)

        self._hide_on_blur_action = QAction("Hide When Unfocused", self, checkable=True)
        self._hide_on_blur_action.setChecked(self._config.hide_on_focus_loss)
        self._hide_on_blur_action.toggled.connect(self._on_hide_on_blur_toggled)
        view_menu.addAction(self._hide_on_blur_action)

        self._overlay_action = QAction("Show In-Game Overlay", self, checkable=True)
        self._overlay_action.setChecked(False)
        self._overlay_action.toggled.connect(self._on_overlay_toggled)
        view_menu.addAction(self._overlay_action)

        self._minimap_action = QAction("Show Minimap Overlay", self, checkable=True)
        self._minimap_action.setChecked(False)
        self._minimap_action.toggled.connect(self._on_minimap_toggled)
        view_menu.addAction(self._minimap_action)

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

    def _on_hide_on_blur_toggled(self, checked: bool) -> None:
        self._config.hide_on_focus_loss = checked

    def changeEvent(self, event: QEvent) -> None:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self._config.hide_on_focus_loss
        ):
            self.hide()
        super().changeEvent(event)

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
    # Minimap overlay toggle
    # ------------------------------------------------------------------

    def _on_minimap_toggled(self, checked: bool) -> None:
        self._minimap.setVisible(checked)

    def toggle_minimap(self) -> None:
        """Toggle minimap visibility (called from hotkey or menu)."""
        visible = not self._minimap.isVisible()
        self._minimap.setVisible(visible)
        self._minimap_action.setChecked(visible)

    # ------------------------------------------------------------------
    # Settings dialog
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            self._config.hotkey_scan,
            self._config.hotkey_overlay,
            self._config.hotkey_minimap,
            self._config.minimap_opacity,
            parent=self,
        )
        if dlg.exec() != SettingsDialog.DialogCode.Accepted:
            return

        ok, err = self._rebind_hotkeys(
            dlg.scan_hotkey, dlg.overlay_hotkey, dlg.minimap_hotkey
        )
        if not ok:
            QMessageBox.warning(self, "Hotkey Error", err)

        self._minimap.set_opacity(dlg.minimap_opacity)

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
