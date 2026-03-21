"""Quest Sync dialog — guided one-shot quest widget screen reader."""

from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from src.ocr.quest_scanner import QuestScanner, QuestScanError, QuestScanResult


class _ScanWorkerSignals(QObject):
    """Signals emitted from the background scan thread, delivered to the main thread."""
    success = pyqtSignal(object)   # QuestScanResult
    error   = pyqtSignal(str)


class QuestSyncDialog(QDialog):
    """
    Guides the player through scanning the quest widget in the play menu.

    The player opens the Speranza play menu (where the quest widget is
    visible), then presses the hotkey or clicks Scan.  The raw OCR lines
    are emitted via quests_scanned so the quest tracker tab can cross-
    reference them against the MetaForge database.
    """

    # Emitted immediately after a successful scan with the raw OCR lines.
    quests_scanned = pyqtSignal(list)   # list[str]

    def __init__(self, hotkey: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sync Quest Status")
        self.setMinimumWidth(480)
        self.setMinimumHeight(340)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._scanner = QuestScanner()
        self._scan_lock = threading.Lock()
        self._hotkey = hotkey
        self._signals = _ScanWorkerSignals()
        self._signals.success.connect(self._on_scan_success)
        self._signals.error.connect(self._on_scan_error)
        self._saved_pos: QPoint | None = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Instructions
        instr = QLabel(
            "<b>How to sync your active quests:</b><br>"
            "1. Switch to Arc Raiders and go to the <b>Speranza</b> hub.<br>"
            "2. Click <b>PLAY</b> — the quest widget must be visible on the left.<br>"
            f"3. Press <b>{self._hotkey.upper()}</b> (or click <i>Scan</i> below).<br>"
            "4. Quest status updates automatically — click <b>Close</b> when done."
        )
        instr.setWordWrap(True)
        instr.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(instr)

        # Detected quests list
        found_label = QLabel("Quests detected:")
        found_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        layout.addWidget(found_label)

        self._list = QListWidget()
        self._list.setMaximumHeight(140)
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        self._empty_hint = QLabel(
            "  No quests detected yet — switch to the game and click Scan."
        )
        self._empty_hint.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._empty_hint)

        # Status label
        self._status = QLabel(
            "Ready — open the play menu in Arc Raiders, then click Scan."
        )
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Buttons row
        btn_row = QHBoxLayout()

        self._scan_btn = QPushButton("Scan")
        self._scan_btn.setDefault(True)
        self._scan_btn.clicked.connect(self.trigger_scan)
        btn_row.addWidget(self._scan_btn)

        btn_row.addStretch()

        box = QDialogButtonBox()
        self._close_btn = box.addButton("Close", QDialogButtonBox.ButtonRole.AcceptRole)
        box.accepted.connect(self.accept)
        btn_row.addWidget(box)

        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def trigger_scan(self) -> None:
        """Start an OCR scan of the current screen (thread-safe, non-blocking)."""
        if not self._scan_lock.acquire(blocking=False):
            return  # scan already in progress

        if not self._scanner.available:
            self._scan_lock.release()
            self._set_status(
                "OCR is not available. Tesseract must be installed.\n"
                "See Settings → Item Scanner for setup instructions.",
                error=True,
            )
            return

        self._set_status("Scanning — reading game screen…", error=False)
        self._scan_btn.setEnabled(False)

        # Move off-screen instead of hiding — hiding a modal dialog under exec()
        # terminates the Qt event loop and kills the scan pipeline.
        self._move_offscreen()
        self._focus_game_window()

        def _run() -> None:
            import time
            time.sleep(0.6)  # let the OS redraw the game window beneath
            try:
                result = self._scanner.scan_page()
                self._signals.success.emit(result)
            except QuestScanError as exc:
                self._signals.error.emit(str(exc))
            except Exception as exc:
                self._signals.error.emit(f"Unexpected error: {exc}")
            finally:
                self._scan_lock.release()

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Move off-screen / restore
    # ------------------------------------------------------------------

    def _move_offscreen(self) -> None:
        self._saved_pos = self.pos()
        self.move(-9999, -9999)

    def _move_back(self) -> None:
        if self._saved_pos is not None:
            self.move(self._saved_pos)
            self._saved_pos = None
        self.raise_()
        self.activateWindow()

    @staticmethod
    def _focus_game_window() -> None:
        """Best-effort: bring the Arc Raiders game window to the foreground."""
        try:
            import ctypes
            user32 = ctypes.windll.user32
            found: list[int] = []

            def _cb(hwnd: int, _: int) -> bool:
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    buf = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buf, length + 1)
                    if (("Arc Raiders" in buf.value or "ArcRaiders" in buf.value)
                            and "Overlay" not in buf.value):
                        found.append(hwnd)
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            user32.EnumWindows(WNDENUMPROC(_cb), 0)
            if found:
                hwnd = found[0]
                user32.ShowWindow(hwnd, 9)        # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
                print(f"[QuestScanner] Focused game window hwnd={hwnd}")
        except Exception as exc:
            print(f"[QuestScanner] Could not focus game window: {exc}")

    # ------------------------------------------------------------------
    # Scan result slots (main thread)
    # ------------------------------------------------------------------

    def _on_scan_success(self, result: QuestScanResult) -> None:
        self._move_back()
        self._scan_btn.setEnabled(True)

        # Show placeholder while the tracker fuzzy-matches the lines.
        self._rebuild_list([])
        self._empty_hint.setText("  Matching against quest database…")
        self._empty_hint.setVisible(True)
        self._set_status("Scan complete — matching quests…", error=False)

        # Emit for cross-referencing in the quest tracker tab.
        # The tracker will call update_results() with the matched names.
        self.quests_scanned.emit(result.raw_lines)

    def update_results(self, matched_names: list[str]) -> None:
        """Called by the quest tracker after fuzzy-matching to display matched quests."""
        self._empty_hint.setText(
            "  No quests detected yet — switch to the game and click Scan."
        )
        self._rebuild_list(matched_names)
        n = len(matched_names)
        if n:
            self._set_status(
                f"Matched {n} active quest(s). Quest status updated in the Quests tab.\n"
                "Click Close when done, or scan again if the widget changed pages.",
                error=False,
                success=True,
            )
        else:
            self._set_status(
                "No quests matched. Make sure the quest widget is fully visible\n"
                "and the play menu is open in Speranza, then try again.",
                error=True,
            )

    def _on_scan_error(self, message: str) -> None:
        self._move_back()
        self._scan_btn.setEnabled(True)
        self._set_status(message, error=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rebuild_list(self, lines: list[str]) -> None:
        self._list.clear()
        self._empty_hint.setVisible(len(lines) == 0)
        for line in lines:
            item = QListWidgetItem(f"✓  {line}")
            item.setForeground(Qt.GlobalColor.green)
            self._list.addItem(item)

    def _set_status(self, text: str, *, error: bool, success: bool = False) -> None:
        self._status.setText(text)
        if error:
            color = "#e05050"
        elif success:
            color = "#50c878"
        else:
            color = "#aaaaaa"
        self._status.setStyleSheet(f"color: {color};")
