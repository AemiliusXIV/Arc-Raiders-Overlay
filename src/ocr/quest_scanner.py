"""Quest screen scanner — OCR reader for the quest widget in the play menu.

Captures the Speranza play-menu screen and extracts the names of the player's
currently active quests from the small quest widget (white text on dark panel,
top-left of the screen).

Requires the same dependencies as the other scanners:
    pip install mss pytesseract Pillow
    + Tesseract OCR binary installed
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Project root — two levels up from src/ocr/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

# Set DEBUG_OCR=1 to save debug images during development.
_DEBUG_OCR = os.environ.get("DEBUG_OCR", "0") == "1"

try:
    import mss
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    import pytesseract
    # TEMP: Replace with bundled Tesseract path when building installer
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    _TESS_OK = True
except ImportError:
    _TESS_OK = False


# Minimum line length to consider a line a plausible quest name.
_MIN_NAME_LEN = 3
# Maximum line length — filters out full-sentence noise.
_MAX_NAME_LEN = 80


class QuestScanError(Exception):
    """Raised when the quest scanner cannot produce a usable result."""


@dataclass
class QuestScanResult:
    """Raw OCR output from one scan of the quest widget."""

    # All cleaned text lines extracted from the screen — the UI layer
    # fuzzy-matches these against the MetaForge quest database.
    raw_lines: list[str] = field(default_factory=list)


def _find_game_monitor(sct) -> dict:
    """
    Return the mss monitor dict for the monitor that contains Arc Raiders.

    Falls back to the primary monitor (monitors[1]) if the game window cannot
    be found or the platform does not support the win32 calls.
    """
    try:
        import ctypes
        import ctypes.wintypes
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
            rect = ctypes.wintypes.RECT()
            user32.GetWindowRect(found[0], ctypes.byref(rect))
            game_cx = (rect.left + rect.right) // 2
            game_cy = (rect.top + rect.bottom) // 2
            for mon in sct.monitors[1:]:
                if (mon["left"] <= game_cx < mon["left"] + mon["width"]
                        and mon["top"] <= game_cy < mon["top"] + mon["height"]):
                    print(f"[QuestScanner] Game on monitor: {mon}")
                    return mon
    except Exception as exc:
        print(f"[QuestScanner] Monitor detection failed: {exc}")

    return sct.monitors[1]


def _preprocess(img: Image.Image) -> Image.Image:
    """Prepare the captured image for Tesseract.

    The quest widget uses white text on a dark semi-transparent panel.
    We invert so Tesseract sees dark text on a light background, which
    it handles much better.
    """
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.convert("L")
    img = ImageOps.invert(img)
    return img


def _clean_lines(raw_text: str) -> list[str]:
    """Split OCR output into plausible quest-name lines."""
    lines = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Skip lines that are too short (UI noise) or too long (body text)
        if len(line) < _MIN_NAME_LEN or len(line) > _MAX_NAME_LEN:
            continue
        # Skip lines that look like UI chrome: all digits, pure punctuation, etc.
        if all(not ch.isalpha() for ch in line):
            continue
        lines.append(line)
    return lines


class QuestScanner:
    """Reads active quest names from the in-game quest widget via OCR."""

    @property
    def available(self) -> bool:
        return _MSS_OK and _TESS_OK

    def scan_page(self) -> QuestScanResult:
        """
        Capture the game monitor and extract quest names from the quest widget.

        The quest widget (visible on the Speranza play menu) shows up to 4
        active quest names in white text on a dark panel in the top-left area.

        Returns a QuestScanResult with raw_lines populated.
        The caller (quest_tracker UI) is responsible for fuzzy-matching these
        lines against the MetaForge quest database, since the full quest list
        is already loaded there.

        Raises QuestScanError with a human-readable message on failure.
        """
        if not _MSS_OK:
            raise QuestScanError(
                "Screen capture library (mss) is not installed.\n"
                "Run: pip install mss"
            )
        if not _TESS_OK:
            raise QuestScanError(
                "OCR library (pytesseract / Pillow) is not installed.\n"
                "Run: pip install pytesseract Pillow\n"
                "Also install Tesseract from:\n"
                "  https://github.com/UB-Mannheim/tesseract/wiki"
            )

        # ── Capture ────────────────────────────────────────────────────────
        try:
            with mss.mss() as sct:
                monitor = _find_game_monitor(sct)
                shot = sct.grab(monitor)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        except Exception as exc:
            raise QuestScanError(f"Screen capture failed: {exc}") from exc

        if _DEBUG_OCR:
            try:
                img.save(os.path.join(_PROJECT_ROOT, "debug_quest_raw.png"))
                print(f"[QuestScanner] debug_quest_raw.png saved ({img.width}x{img.height})")
            except Exception as e:
                print(f"[QuestScanner] Could not save debug_quest_raw.png: {e}")

        # ── Pre-process ─────────────────────────────────────────────────────
        proc = _preprocess(img)

        if _DEBUG_OCR:
            try:
                proc.save(os.path.join(_PROJECT_ROOT, "debug_quest_proc.png"))
                print("[QuestScanner] debug_quest_proc.png saved")
            except Exception as e:
                print(f"[QuestScanner] Could not save debug_quest_proc.png: {e}")

        # ── Tesseract OCR ──────────────────────────────────────────────────
        # --psm 4: assume a single column of text (matches the widget layout)
        try:
            raw_text = pytesseract.image_to_string(
                proc,
                config="--psm 4 --oem 3",
            )
        except Exception as exc:
            raise QuestScanError(f"OCR failed: {exc}") from exc

        lines = _clean_lines(raw_text)
        print(f"[QuestScanner] {len(lines)} lines extracted: {lines[:10]}")

        if not lines:
            raise QuestScanError(
                "No text detected on screen.\n"
                "Make sure Arc Raiders is open on the Speranza play menu with "
                "the quest widget visible, then try again."
            )

        return QuestScanResult(raw_lines=lines)
