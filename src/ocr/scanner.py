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
from collections import deque
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


# Minimum tooltip size in pixels to accept a detected bright region.
_MIN_TOOLTIP_W = 180
_MIN_TOOLTIP_H = 80

# Downscale factor for full-screen tooltip detection.
# At 16×, a 1920×1080 screen becomes ~120×68 — fast to scan.
# Text inside the tooltip (~20–40 px tall) shrinks to ≤2 px and disappears,
# leaving the solid cream background as one coherent blob.
_DETECT_SCALE = 16

# Minimum fill ratio: bright pixels in component ÷ bounding-box area.
# Rejects scattered bright noise whose bbox is large but internally sparse.
_MIN_FILL_RATIO = 0.35


def _get_cursor_pos() -> tuple[int, int]:
    """Return the current mouse cursor position (Windows only; falls back to 0,0)."""
    if _CTYPES_OK:
        pt = _POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
        return pt.x, pt.y
    return 0, 0


# ---------------------------------------------------------------------------
# Tooltip detection — BFS connected components
# ---------------------------------------------------------------------------

def _find_tooltip_bbox(img: Image.Image) -> tuple[int, int, int, int] | None:
    """
    Detect the ARC Raiders tooltip box by finding the largest connected blob
    of cream/white pixels in the captured image.

    The tooltip renders on a cream/white background; the game's inventory
    screen dims everything behind it to near-black. We downsample 16× for
    speed, threshold per-pixel brightness, then use BFS (8-connectivity) to
    find connected components. The largest component whose bounding box meets
    the minimum size and fill-ratio constraints is returned.

    Using connected components (instead of overall bright-pixel bounding box)
    prevents scattered UI elements — item icons, stash panel backgrounds,
    text highlights — from inflating the detected region.

    Returns (left, top, right, bottom) in original-image pixels, or None.
    """
    S = _DETECT_SCALE
    sw = max(1, img.width  // S)
    sh = max(1, img.height // S)
    small = img.resize((sw, sh), Image.BOX).convert("RGB")

    # Build a 2-D boolean bright mask.
    if _NUMPY_OK:
        arr = _np.array(small)
        r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
        bright_np = (
            (r.astype(_np.int16) > 200)
            & (g.astype(_np.int16) > 190)
            & (b.astype(_np.int16) > 175)
        )
        # Convert to a list-of-lists for the shared BFS below.
        bright = bright_np.tolist()
    else:
        px = small.load()
        bright = [
            [
                (px[x, y][0] > 200 and px[x, y][1] > 190 and px[x, y][2] > 175)
                for x in range(sw)
            ]
            for y in range(sh)
        ]

    # BFS to find connected components (8-connectivity).
    visited = [[False] * sw for _ in range(sh)]
    best_bounds = None
    best_size   = 0

    NEIGHBORS = [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]

    for sy in range(sh):
        for sx in range(sw):
            if visited[sy][sx] or not bright[sy][sx]:
                continue
            # BFS from (sy, sx).
            queue  = deque([(sy, sx)])
            rmin, rmax, cmin, cmax = sy, sy, sx, sx
            size   = 0
            while queue:
                y, x = queue.popleft()
                if visited[y][x]:
                    continue
                visited[y][x] = True
                size += 1
                if y < rmin: rmin = y
                if y > rmax: rmax = y
                if x < cmin: cmin = x
                if x > cmax: cmax = x
                for dy, dx in NEIGHBORS:
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < sh and 0 <= nx < sw and not visited[ny][nx] and bright[ny][nx]:
                        queue.append((ny, nx))

            if size <= best_size:
                continue

            # Fill-ratio check: reject sparse noise.
            bbox_area = max(1, (rmax - rmin + 1) * (cmax - cmin + 1))
            if size / bbox_area < _MIN_FILL_RATIO:
                continue

            # Size check (in original-image pixels).
            if (rmax - rmin) * S < _MIN_TOOLTIP_H or (cmax - cmin) * S < _MIN_TOOLTIP_W:
                continue

            best_size   = size
            best_bounds = (rmin, rmax, cmin, cmax)

    if best_bounds is None:
        return None

    rmin, rmax, cmin, cmax = best_bounds
    pad = S * 3
    return (
        max(0, cmin * S - pad),
        max(0, rmin * S - pad),
        min(img.width,  cmax * S + pad),
        min(img.height, rmax * S + pad),
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
    """Captures the full screen and extracts an item name via OCR."""

    def __init__(
        self,
        on_result: Callable[[str], None],
        region: Optional[dict] = None,
    ):
        self._on_result = on_result
        self._fixed_region = region  # if set, bypasses full-screen capture

    @property
    def available(self) -> bool:
        return _MSS_OK and _TESS_OK

    def scan(self) -> None:
        """Capture the screen, run OCR, invoke callback with result."""
        if not _MSS_OK:
            print("[ItemScanner] mss not installed — OCR unavailable")
            return
        if not _TESS_OK:
            print("[ItemScanner] pytesseract/Pillow not installed — OCR unavailable")
            return

        try:
            # ── Screenshot ───────────────────────────────────────────────────
            with mss.mss() as sct:
                if self._fixed_region:
                    region = self._fixed_region
                    print(f"[ItemScanner] Using fixed region: {region}")
                    shot = sct.grab(region)
                else:
                    monitor = sct.monitors[1]  # primary physical monitor
                    print(f"[ItemScanner] Full-screen capture: {monitor}")
                    shot = sct.grab(monitor)
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
                self._on_result("\x00__NO_RESULT__")

        except Exception as exc:
            print(f"[ItemScanner] OCR error: {exc}")
            try:
                self._on_result("\x00__ERROR__")
            except Exception:
                pass

    def update_region(self, region: dict) -> None:
        self._fixed_region = region
