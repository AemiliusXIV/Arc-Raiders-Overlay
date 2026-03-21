"""Project Sync dialog — guided page-by-page project screen reader."""

from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, QPoint, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from src.ocr.project_scanner import ProjectScanner, ProjectScanError, ProjectScanResult


class _ScanWorkerSignals(QObject):
    """Signals emitted from the background scan thread, delivered to the main thread."""
    success = pyqtSignal(object)   # ProjectScanResult
    error   = pyqtSignal(str)


class ProjectSyncDialog(QDialog):
    """
    Guides the player through scanning each page of the project hand-in screen.

    Each successful scan is saved immediately via the page_scanned signal —
    no "Apply" step required. The user just scans each page and closes.
    """

    # Emitted immediately after each successful scan (auto-save, no Apply needed).
    page_scanned = pyqtSignal(object)   # ProjectScanResult

    # Kept for backward compatibility with main_window connections.
    projects_synced = pyqtSignal(list)  # list[ProjectScanResult]

    def __init__(self, hotkey: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Sync Project Pages")
        self.setMinimumWidth(540)
        self.setMinimumHeight(380)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        self._scanner = ProjectScanner()
        self._pages: list[ProjectScanResult] = []
        self._scan_lock = threading.Lock()
        self._hotkey = hotkey
        self._signals = _ScanWorkerSignals()
        self._signals.success.connect(self._on_scan_success)
        self._signals.error.connect(self._on_scan_error)
        self._saved_pos: QPoint | None = None  # position before off-screen move
        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Instructions
        instr = QLabel(
            "<b>How to sync your project requirements:</b><br>"
            "1. Switch to Arc Raiders and open your project screen.<br>"
            "2. Navigate to each page tab (1, 2, 3 …).<br>"
            f"3. Press <b>{self._hotkey.upper()}</b> on each page "
            "(or click <i>Scan Current Page</i> below) — "
            "<b>data saves automatically after each scan.</b><br>"
            "4. When all pages are done, click <b>Close</b>."
        )
        instr.setWordWrap(True)
        instr.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(instr)

        # Scanned pages list
        pages_label = QLabel("Pages saved:")
        pages_label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        layout.addWidget(pages_label)

        self._list = QListWidget()
        self._list.setMaximumHeight(160)
        self._list.setAlternatingRowColors(True)
        layout.addWidget(self._list)

        self._empty_hint = QLabel(
            "  No pages scanned yet — switch to the game and scan a page."
        )
        self._empty_hint.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(self._empty_hint)

        # Status label
        self._status = QLabel("Ready — click Scan Current Page or press the hotkey in-game.")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        # Buttons row
        btn_row = QHBoxLayout()

        self._scan_btn = QPushButton("Scan Current Page")
        self._scan_btn.setDefault(True)
        self._scan_btn.clicked.connect(self.trigger_scan)
        btn_row.addWidget(self._scan_btn)

        btn_row.addStretch()

        box = QDialogButtonBox()
        self._close_btn = box.addButton("Close", QDialogButtonBox.ButtonRole.AcceptRole)
        box.accepted.connect(self._on_close)
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

        # Move the dialog off-screen so it doesn't cover the game during
        # capture.  We can NOT use self.hide() because hiding a modal dialog
        # running under exec() causes Qt/Windows to terminate the modal event
        # loop, which kills the whole scan pipeline.
        self._move_offscreen()
        self._focus_game_window()

        def _run() -> None:
            import time
            time.sleep(0.6)  # let the OS redraw the game window beneath
            try:
                result = self._scanner.scan_page()
                self._signals.success.emit(result)
            except ProjectScanError as exc:
                self._signals.error.emit(str(exc))
            except Exception as exc:
                self._signals.error.emit(f"Unexpected error: {exc}")
            finally:
                self._scan_lock.release()

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Move off-screen / restore (avoids hide() which kills exec())
    # ------------------------------------------------------------------

    def _move_offscreen(self) -> None:
        """Save current position, then move the dialog way off-screen."""
        self._saved_pos = self.pos()
        self.move(-9999, -9999)

    def _move_back(self) -> None:
        """Restore the dialog to its saved position."""
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
                print(f"[ProjectScanner] Focused game window hwnd={hwnd}")
        except Exception as exc:
            print(f"[ProjectScanner] Could not focus game window: {exc}")

    # ------------------------------------------------------------------
    # Scan result slots (main thread)
    # ------------------------------------------------------------------

    def _on_scan_success(self, result: ProjectScanResult) -> None:
        self._move_back()
        self._scan_btn.setEnabled(True)

        # Store locally (for the list view).
        replaced = False
        for i, existing in enumerate(self._pages):
            if (existing.project == result.project
                    and existing.phase_fraction == result.phase_fraction):
                self._pages[i] = result
                replaced = True
                break
        if not replaced:
            self._pages.append(result)

        self._rebuild_list()

        # Auto-save immediately — no "Apply" step needed.
        self.page_scanned.emit(result)

        phase_str = f" ({result.phase_fraction})" if result.phase_fraction else ""
        project_str = result.project or "Unknown Project"
        n = len(result.items)
        self._set_status(
            f"Saved: {project_str}{phase_str} — {n} item(s) recorded.\n"
            "Navigate to the next page tab and scan again, or close when done.",
            error=False,
            success=True,
        )

    def _on_scan_error(self, message: str) -> None:
        self._move_back()
        self._scan_btn.setEnabled(True)
        self._set_status(message, error=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rebuild_list(self) -> None:
        self._list.clear()
        self._empty_hint.setVisible(len(self._pages) == 0)

        for page in self._pages:
            phase_str = f" ({page.phase_fraction})" if page.phase_fraction else ""
            project_str = page.project or "Unknown Project"
            n = len(page.items)
            item = QListWidgetItem(f"✓  {project_str}{phase_str}  —  {n} item(s) saved")
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

    def _on_close(self) -> None:
        # Emit projects_synced for any listeners that still use it.
        if self._pages:
            self.projects_synced.emit(self._pages)
        self.accept()
