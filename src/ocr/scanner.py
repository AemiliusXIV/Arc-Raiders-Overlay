"""Item scanner — screen capture + OCR to auto-look up hovered items.

Optional feature. Requires:
    pip install mss pytesseract Pillow
    + Tesseract OCR binary installed and on PATH
      (https://github.com/UB-Mannheim/tesseract/wiki)
"""

from __future__ import annotations

import os
import re
import tempfile
from typing import Callable, Optional

try:
    import mss
    import mss.tools
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    from PIL import Image, ImageFilter, ImageEnhance, ImageOps
    import pytesseract
    # TEMP: Replace with bundled Tesseract path when building installer
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    _TESS_OK = True
except ImportError:
    _TESS_OK = False

try:
    import numpy as _np
    _NUMPY_OK = True
except ImportError:
    _NUMPY_OK = False

try:
    import ctypes
    class _POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    _CTYPES_OK = True
except Exception:
    _CTYPES_OK = False


# Capture region relative to cursor.
# The tooltip floats ABOVE the hovered item; on large screens with the cursor
# near the bottom edge the tooltip top can be 600-700 px above the cursor.
_REGION_W = 700
_REGION_H = 800
_REGION_LEFT_OFFSET = -350   # left edge relative to cursor x
_REGION_TOP_OFFSET  = -700   # top edge relative to cursor y (reach high)

# Minimum tooltip size in pixels to accept a detected bright region.
_MIN_TOOLTIP_W = 180
_MIN_TOOLTIP_H = 80


def _get_cursor_pos() -> tuple[int, int]:
    """Return the current mouse cursor position (Windows only; falls back to 0,0)."""
    if _CTYPES_OK:
        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    return 0, 0


# ---------------------------------------------------------------------------
# Tooltip detection
# ---------------------------------------------------------------------------

def _find_tooltip_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """
    Detect the ARC Raiders tooltip box by finding the largest bright region
    in the captured image.

    The tooltip renders on a cream/white background; the game's inventory
    screen dims everything behind it to near-black. We downsample 4× for
    speed, threshold per-pixel brightness, then scale the bounding box back.

    Returns (left, top, right, bottom) in original-image pixels, or None.
    """
    SCALE = 4
    small = img.resize(
        (max(1, img.width // SCALE), max(1, img.height // SCALE)),
        Image.BOX,
    ).convert("RGB")

    if _NUMPY_OK:
        arr = _np.array(small)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        # Cream/white: all channels high; tooltip bg is warm so blue is
        # slightly below red/green.
        bright = (
            (r.astype(_np.int16) > 200)
            & (g.astype(_np.int16) > 190)
            & (b.astype(_np.int16) > 175)
        )
        rows = _np.where(bright.any(axis=1))[0]
        cols = _np.where(bright.any(axis=0))[0]
        if not rows.size or not cols.size:
            return None
        rmin, rmax = int(rows[0]), int(rows[-1])
        cmin, cmax = int(cols[0]), int(cols[-1])
    else:
        # Pure-PIL path (no numpy): pixel-by-pixel on the downsampled image.
        px = small.load()
        w, h = small.size
        r_set: set[int] = set()
        c_set: set[int] = set()
        for y in range(h):
            for x in range(w):
                rv, gv, bv = px[x, y]
                if rv > 200 and gv > 190 and bv > 175:
                    r_set.add(y)
                    c_set.add(x)
        if not r_set or not c_set:
            return None
        rmin, rmax = min(r_set), max(r_set)
        cmin, cmax = min(c_set), max(c_set)

    # Reject regions that are too small to be a tooltip.
    if (rmax - rmin) * SCALE < _MIN_TOOLTIP_H or (cmax - cmin) * SCALE < _MIN_TOOLTIP_W:
        return None

    pad = SCALE * 3
    return (
        max(0, cmin * SCALE - pad),
        max(0, rmin * SCALE - pad),
        min(img.width,  cmax * SCALE + pad),
        min(img.height, rmax * SCALE + pad),
    )


# ---------------------------------------------------------------------------
# Font-size-based name extraction
# ---------------------------------------------------------------------------

_CAPS_WORD = re.compile(r'^[A-Z][A-Z0-9]{1,}$')


def _extract_by_font_size(img: Image.Image) -> list[str]:
    """
    Use Tesseract bounding-box data to isolate the item name.

    ARC Raiders renders item names in a significantly larger bold font than
    body text, section headers ("RECYCLES INTO"), or category badges
    ("REFINED MATERIAL"). We run image_to_data, collect ALL-CAPS words whose
    bounding-box height is at least 55% of the tallest character found, group
    them into lines, and return the lines as candidates (top-to-bottom order,
    which puts the item name first since it appears above description text).
    """
    try:
        data = pytesseract.image_to_data(
            img,
            config="--psm 6 --oem 3",
            output_type=pytesseract.Output.DICT,
        )
    except Exception as exc:
        print(f"[ItemScanner] image_to_data error: {exc}")
        return []

    words = []
    for i, raw in enumerate(data["text"]):
        text = re.sub(r"['\u2018\u2019`]", "C", (raw or "").strip())
        conf_raw = data["conf"][i]
        conf = int(conf_raw) if str(conf_raw).lstrip("-").isdigit() else 0
        h = data["height"][i]
        if not text or conf < 20 or h <= 0:
            continue
        words.append({"text": text, "h": h, "top": data["top"][i], "left": data["left"][i]})

    if not words:
        return []

    max_h = max(w["h"] for w in words)

    # Primary: ALL-CAPS words at ≥55% of the tallest character height.
    large = [w for w in words if w["h"] >= max_h * 0.55 and _CAPS_WORD.match(w["text"])]
    # Looser fallback: large words regardless of case.
    if not large:
        large = [w for w in words if w["h"] >= max_h * 0.55]
    if not large:
        return []

    large.sort(key=lambda w: (w["top"], w["left"]))

    # Group words that share the same text line (within half a char-height).
    half_h = max(1, max_h // 2)
    lines: list[list[dict]] = []
    cur: list[dict] = [large[0]]
    for w in large[1:]:
        if abs(w["top"] - cur[0]["top"]) <= half_h:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    lines.append(cur)

    candidates: list[str] = []
    seen: set[str] = set()
    for line in lines:
        line.sort(key=lambda w: w["left"])
        cand = " ".join(w["text"] for w in line)
        if cand and cand not in seen:
            seen.add(cand)
            candidates.append(cand)

    return candidates


# ---------------------------------------------------------------------------
# All-caps fallback (text-only, no size information)
# ---------------------------------------------------------------------------

def _extract_candidates(raw_text: str) -> list[str]:
    """
    Extract all ALL-CAPS word groups from raw Tesseract output.

    Used as a fallback when font-size extraction fails (e.g. tooltip not
    detected). The matcher tries each candidate in turn and returns the first
    that hits a real item — automatically skipping non-item descriptors like
    "TOPSIDE MATERIAL" or "RECYCLES INTO".

    Common OCR artifact: apostrophe rendered instead of 'C' in the game font.
    """
    seen: set[str] = set()
    candidates: list[str] = []
    for line in raw_text.splitlines():
        line = re.sub(r"['\u2018\u2019`]", "C", line)
        words = re.findall(r'\b[A-Z][A-Z0-9]{2,}\b', line)
        if not words:
            continue
        candidate = " ".join(words)
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


class ItemScanner:
    """Captures a region around the cursor and extracts an item name via OCR."""

    def __init__(
        self,
        on_result: Callable[[str], None],
        region: Optional[dict] = None,
    ):
        self._on_result = on_result
        self._fixed_region = region  # if set, bypasses cursor-relative logic

    @property
    def available(self) -> bool:
        return _MSS_OK and _TESS_OK

    def scan(self) -> None:
        """Capture region around cursor, run OCR, invoke callback with result."""
        if not _MSS_OK:
            print("[ItemScanner] mss not installed — OCR unavailable")
            return
        if not _TESS_OK:
            print("[ItemScanner] pytesseract/Pillow not installed — OCR unavailable")
            return

        try:
            # ── Build capture region ──────────────────────────────────────────
            if self._fixed_region:
                region = self._fixed_region
                print(f"[ItemScanner] Using fixed region: {region}")
            else:
                cx, cy = _get_cursor_pos()
                left = max(0, cx + _REGION_LEFT_OFFSET)
                top  = max(0, cy + _REGION_TOP_OFFSET)
                region = {"left": left, "top": top, "width": _REGION_W, "height": _REGION_H}
                print(f"[ItemScanner] Cursor at ({cx}, {cy}), capture region: {region}")

            # ── Screenshot ───────────────────────────────────────────────────
            with mss.mss() as sct:
                shot = sct.grab(region)
                img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

            debug_path = os.path.join(tempfile.gettempdir(), "arc_scanner_debug.png")
            img.save(debug_path)
            print(f"[ItemScanner] Raw capture saved to: {debug_path}")

            # ── Detect tooltip, crop to the item-name zone ───────────────────
            # The tooltip layout (top to bottom):
            #   1. Category badge row  (small coloured tags — REFINED MATERIAL, RARE)
            #   2. Item name           (large bold ALL-CAPS — this is what we want)
            #   3. Short description   (body text)
            #   4. Extra sections      (RECYCLES INTO, CAN BE FOUND IN, …)
            #
            # The item name always lives in the top ~45% of the tooltip, so
            # cropping there eliminates the noisy lower sections entirely.
            bbox = _find_tooltip_bbox(img)
            if bbox:
                print(f"[ItemScanner] Tooltip detected: {bbox}")
                tooltip = img.crop(bbox)
                name_zone = tooltip.crop(
                    (0, 0, tooltip.width, max(1, int(tooltip.height * 0.45)))
                )
            else:
                print("[ItemScanner] No tooltip detected — using full capture")
                tooltip = img
                name_zone = img

            # ── Pre-process the name zone ─────────────────────────────────────
            name_zone = name_zone.resize(
                (name_zone.width * 2, name_zone.height * 2), Image.LANCZOS
            )
            name_zone = name_zone.filter(ImageFilter.SHARPEN)
            name_zone = ImageEnhance.Contrast(name_zone).enhance(2.0)
            name_zone = name_zone.convert("L")

            proc_path = os.path.join(tempfile.gettempdir(), "arc_scanner_proc.png")
            name_zone.save(proc_path)
            print(f"[ItemScanner] Processed name zone saved to: {proc_path}")

            # ── Primary: font-size-based extraction ──────────────────────────
            # image_to_data gives us per-word bounding boxes; the item name
            # is in a significantly larger font than any other text in the zone.
            size_cands = _extract_by_font_size(name_zone)
            print(f"[ItemScanner] Font-size candidates: {size_cands}")

            # ── Fallback: raw OCR + all-caps filter ───────────────────────────
            # Run on normal and inverted; pick whichever yielded more text.
            raw_block = pytesseract.image_to_string(name_zone, config="--psm 6 --oem 3")
            raw_inv   = pytesseract.image_to_string(
                ImageOps.invert(name_zone), config="--psm 6 --oem 3"
            )
            raw_text = raw_block if len(raw_block.strip()) >= len(raw_inv.strip()) else raw_inv
            print(f"[ItemScanner] Raw OCR:\n{repr(raw_text)}")
            fallback_cands = _extract_candidates(raw_text)
            print(f"[ItemScanner] Fallback candidates: {fallback_cands}")

            # ── Merge, deduplicate, emit ──────────────────────────────────────
            # Font-size candidates come first (most likely to be the item name).
            seen: set[str] = set()
            all_cands: list[str] = []
            for c in size_cands + fallback_cands:
                if c not in seen:
                    seen.add(c)
                    all_cands.append(c)

            print(f"[ItemScanner] Final candidates: {all_cands}")

            if all_cands:
                self._on_result("\n".join(all_cands))
            else:
                print("[ItemScanner] No usable text found — check debug images")

        except Exception as exc:
            print(f"[ItemScanner] OCR error: {exc}")

    def update_region(self, region: dict) -> None:
        self._fixed_region = region
