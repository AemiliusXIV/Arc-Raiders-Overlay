"""Project screen scanner — OCR reader for the in-game project hand-in screen.

Reads the project name, phase fraction, and per-item progress (X/Y) from
the project hand-in UI. Designed to be triggered page-by-page via hotkey.

Requires the same dependencies as item scanner:
    pip install mss pytesseract Pillow
    + Tesseract OCR binary installed
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Optional

# Project root — two levels up from src/ocr/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set the environment variable DEBUG_OCR=1 to save debug images during development.
# Never set in production — end users should see no debug output at all.
_DEBUG_OCR = os.environ.get("DEBUG_OCR", "0") == "1"

try:
    import mss
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    from PIL import Image, ImageEnhance, ImageFilter
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


# Minimum item-fraction pairs required to consider the screen a valid project page.
_MIN_ITEMS = 2

# Project title is assumed to live in the top N% of the screen.
_TITLE_ZONE_FRAC = 0.20

# Screen-relative thresholds — all expressed as fractions of screen dimensions
# so the scanner works correctly at 1080p, 1440p, 4K, ultrawide, etc.
# Derived from 3440×1440 live-capture measurements.
_VERT_GAP_FRAC   = 0.111   # max vertical gap between item name and fraction (% height)
_HORIZ_GAP_FRAC  = 0.087   # max horizontal distance name↔fraction (% width)
_PHASE_PROX_FRAC = 0.035   # phase token row-proximity tolerance (% height)
_FRAC_ROW_FRAC   = 0.042   # fraction-to-title-row tolerance in fallback (% height)

# ALL-CAPS word pattern — same as item scanner.
_CAPS_WORD = re.compile(r'^[A-Z][A-Z0-9]{1,}$')

# Progress fraction pattern: digits / digits  (e.g. "1/10", "8/8", "12/100")
_FRACTION_RE = re.compile(r'^(\d+)/(\d+)$')

# Phase indicator in project title, e.g. "(4/5)"
_PHASE_RE = re.compile(r'\((\d+/\d+)\)')


class ProjectScanError(Exception):
    """Raised when the screen cannot be parsed as a valid project page."""


@dataclass
class ProjectItem:
    name: str
    have: int
    need: int

    @property
    def is_complete(self) -> bool:
        return self.have >= self.need


@dataclass
class ProjectScanResult:
    project: str                    # e.g. "DOMINANT DANGERS"
    phase_fraction: str             # e.g. "4/5"  (empty string if not detected)
    items: list[ProjectItem] = field(default_factory=list)


def _preprocess(img: Image.Image) -> Image.Image:
    """Upscale, sharpen, and contrast-boost the captured image for better OCR accuracy.

    Upscaling 2× before OCR significantly improves digit recognition — small
    characters like "8" vs "9" are far more reliably distinguished at larger size.
    """
    # Upscale 2× using high-quality Lanczos resampling before any filtering.
    w, h = img.size
    img = img.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
    img = img.filter(ImageFilter.SHARPEN)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    return img.convert("L")          # grayscale


def _run_image_to_data(img: Image.Image) -> dict:
    """Run Tesseract image_to_data and return the output dict."""
    return pytesseract.image_to_data(
        img,
        config="--psm 3 --oem 3",
        output_type=pytesseract.Output.DICT,
    )


def _collect_words(data: dict, scale: float = 1.0) -> list[dict]:
    """Convert image_to_data output into a clean list of word dicts.

    ``scale`` divides all pixel coordinates back to the original image size
    when the image was upscaled before OCR (e.g. scale=2.0 for 2× upscale).
    """
    words = []
    for i, raw in enumerate(data["text"]):
        text = (raw or "").strip()
        # Normalise apostrophe/backtick → 'C' (common OCR artefact in this game font)
        text = re.sub(r"['\u2018\u2019`]", "C", text)
        conf_raw = data["conf"][i]
        conf = int(conf_raw) if str(conf_raw).lstrip("-").isdigit() else 0
        h = int(data["height"][i] / scale)
        w = int(data["width"][i] / scale)
        left = int(data["left"][i] / scale)
        top = int(data["top"][i] / scale)
        if not text or conf < 5 or h <= 0:
            continue
        words.append({
            "text": text,
            "h": h,
            "w": w,
            "top": top,
            "left": left,
            "bottom": top + h,
            "cx": left + w // 2,
        })
    return words


def _group_caps_lines(words: list[dict], min_h_frac: float = 0.40) -> list[dict]:
    """
    Group ALL-CAPS words of significant height into text-line blocks.

    Returns a list of block dicts: {text, top, bottom, cx, h}
    """
    if not words:
        return []

    # Compute max height only from CAPS-matching words so that noise artifacts
    # (single-character glyphs, UI borders etc.) don't inflate the threshold
    # and cause real item text to be excluded.
    caps_candidates = [w for w in words if _CAPS_WORD.match(w["text"])]
    if not caps_candidates:
        return []

    max_h = max(w["h"] for w in caps_candidates)
    min_h = max_h * min_h_frac
    large = [w for w in caps_candidates if w["h"] >= min_h]
    rejected = [w for w in caps_candidates if w["h"] < min_h]
    if rejected:
        print(f"[ProjectScanner] CAPS words rejected by height filter "
              f"(min_h={min_h:.0f}, max_h={max_h}):")
        for w in rejected:
            print(f"  REJECTED: {w['text']!r} h={w['h']} top={w['top']}")
    if not large:
        return []

    large.sort(key=lambda w: (w["top"], w["left"]))

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

    blocks = []
    for line in lines:
        line.sort(key=lambda w: w["left"])
        text = " ".join(w["text"] for w in line)
        top = min(w["top"] for w in line)
        bottom = max(w["bottom"] for w in line)
        left = min(w["left"] for w in line)
        right = max(w["left"] + w["w"] for w in line)
        cx = (left + right) // 2
        blocks.append({"text": text, "top": top, "bottom": bottom, "cx": cx})
    return blocks


def _extract_fractions(words: list[dict]) -> list[dict]:
    """Return word dicts whose text matches the N/M fraction pattern.

    Also assembles fractions that Tesseract split across adjacent tokens, e.g.
    "3/" + "10",  "3" + "/10",  or "3" + "/" + "10".  This handles cases where
    OCR confidence on the slash or a digit is borderline and the token is broken.
    """
    fracs: list[dict] = []
    matched: set[int] = set()

    # Pass 1: direct single-token matches.
    for i, w in enumerate(words):
        m = _FRACTION_RE.match(w["text"])
        if m:
            fracs.append({**w, "have": int(m.group(1)), "need": int(m.group(2))})
            matched.add(i)

    # Pass 2: assemble split fractions from adjacent tokens on the same row.
    # Patterns handled:  "N/"+"M",  "N"+"/M",  "N"+"/"+"M"
    _NUM      = re.compile(r"^\d+$")
    _NUM_SL   = re.compile(r"^(\d+)/$")   # "3/"
    _SL_NUM   = re.compile(r"^/(\d+)$")   # "/10"
    _SL_ONLY  = re.compile(r"^/$")

    def _same_row(a: dict, b: dict) -> bool:
        row_tol = max(a["h"], b["h"]) * 0.6
        return abs(a["top"] - b["top"]) <= row_tol

    def _near(a: dict, b: dict) -> bool:
        """b is just to the right of a with a small gap."""
        gap = b["left"] - (a["left"] + a["w"])
        return -5 <= gap <= max(a["h"], b["h"]) * 1.5

    def _make_frac(wa: dict, wb: dict | None, have: int, need: int) -> dict:
        parts = [wa] if wb is None else [wa, wb]
        left  = min(p["left"] for p in parts)
        right = max(p["left"] + p["w"] for p in parts)
        top   = min(p["top"] for p in parts)
        bot   = max(p["bottom"] for p in parts)
        return {
            "text": f"{have}/{need}",
            "have": have, "need": need,
            "top": top, "h": bot - top,
            "w": right - left, "left": left,
            "bottom": bot, "cx": (left + right) // 2,
        }

    for i, wa in enumerate(words):
        if i in matched:
            continue
        for j, wb in enumerate(words):
            if j <= i or j in matched:
                continue
            if not _same_row(wa, wb) or not _near(wa, wb):
                continue

            # "N/" + "M"
            ma = _NUM_SL.match(wa["text"])
            mb = _NUM.match(wb["text"])
            if ma and mb:
                fracs.append(_make_frac(wa, wb, int(ma.group(1)), int(wb["text"])))
                matched.add(i); matched.add(j)
                break

            # "N" + "/M"
            ma = _NUM.match(wa["text"])
            mb = _SL_NUM.match(wb["text"])
            if ma and mb:
                fracs.append(_make_frac(wa, wb, int(wa["text"]), int(mb.group(1))))
                matched.add(i); matched.add(j)
                break

            # "N" + "/" — look for a third token "M"
            ma = _NUM.match(wa["text"])
            mb = _SL_ONLY.match(wb["text"])
            if ma and mb:
                for k, wc in enumerate(words):
                    if k in matched or k == i or k == j:
                        continue
                    if not _same_row(wb, wc) or not _near(wb, wc):
                        continue
                    mc = _NUM.match(wc["text"])
                    if mc:
                        fracs.append(_make_frac(wa, wc, int(wa["text"]), int(wc["text"])))
                        matched.add(i); matched.add(j); matched.add(k)
                        break
                break

    return fracs


def _parse_title(
    blocks: list[dict],
    all_words: list[dict],
    fractions: list[dict],
    screen_height: int,
    screen_width: int,
) -> tuple[str, str]:
    """
    Extract the project name and phase fraction from the title area.

    All proximity thresholds are expressed as fractions of screen dimensions
    so the function works correctly at any resolution.

    Strategy (in priority order):
    1. Look for a "(N/N)" phase-indicator word token in the title zone. The
       CAPS block on the same horizontal row is the project name. This is the
       most reliable anchor because the phase token is unique to the title.
    2. Fall back to the topmost CAPS block in the title zone and look for an
       adjacent fraction on the same row.
    3. Check whether the block text itself embeds a "(N/N)" substring.

    Returns (project_name, phase_fraction_str).
    """
    title_bottom = screen_height * _TITLE_ZONE_FRAC
    phase_prox   = screen_height * _PHASE_PROX_FRAC   # row-proximity for phase token
    frac_row_tol = screen_height * _FRAC_ROW_FRAC     # fraction-to-title-row tolerance

    title_blocks = [b for b in blocks if b["top"] < title_bottom]
    if not title_blocks:
        return "", ""

    # ── Strategy 1: anchor on the "(N/N)" phase-indicator token ────────────
    phase_words = [
        w for w in all_words
        if _PHASE_RE.search(w["text"]) and w["top"] < title_bottom
    ]
    for pw in phase_words:
        pw_center = pw["top"] + pw["h"] // 2
        best_block: Optional[dict] = None
        best_dist = float("inf")
        for block in title_blocks:
            block_center = (block["top"] + block["bottom"]) // 2
            dist = abs(block_center - pw_center)
            if dist < phase_prox and dist < best_dist:
                best_dist = dist
                best_block = block
        if best_block is not None:
            m = _PHASE_RE.search(pw["text"])
            phase_frac = m.group(1) if m else ""
            project = _PHASE_RE.sub("", best_block["text"]).strip()
            return project.strip(), phase_frac

    # ── Strategy 2: topmost block + adjacent fraction ───────────────────────
    title_block = min(title_blocks, key=lambda b: b["top"])
    project = title_block["text"]

    phase_frac = ""
    row_center = (title_block["top"] + title_block["bottom"]) // 2
    for frac in fractions:
        frac_center = (frac["top"] + frac["bottom"]) // 2
        if abs(frac_center - row_center) < frac_row_tol:
            phase_frac = f"{frac['have']}/{frac['need']}"
            break

    # ── Strategy 3: "(N/N)" embedded in block text ──────────────────────────
    if not phase_frac:
        m = _PHASE_RE.search(project)
        if m:
            phase_frac = m.group(1)
            project = _PHASE_RE.sub("", project).strip()

    return project.strip(), phase_frac


def _pair_items_with_fractions(
    blocks: list[dict],
    fractions: list[dict],
    title_bottom: float,
    max_vert_gap: float,
    max_horiz_gap: float,
) -> list[ProjectItem]:
    """
    Pair each fraction with the nearest ALL-CAPS name block above it.

    Only considers blocks below the title zone.  For each fraction finds the
    block that is:
      - above the fraction (block_bottom < fraction_top)
      - within max_vert_gap px vertically
      - within max_horiz_gap px horizontally (centre-to-centre)
    and picks the closest one (smallest vertical distance).

    max_vert_gap and max_horiz_gap should be computed from screen dimensions
    using the _VERT_GAP_FRAC / _HORIZ_GAP_FRAC constants so that the pairing
    works correctly at any resolution.
    """
    # Exclude title-zone blocks from pairing.
    body_blocks = [b for b in blocks if b["top"] >= title_bottom]

    print(f"[ProjectScanner] Pairing: title_bottom={title_bottom:.0f}  "
          f"max_vert_gap={max_vert_gap:.0f}  max_horiz_gap={max_horiz_gap:.0f}")
    print(f"[ProjectScanner] Body blocks ({len(body_blocks)}):")
    for _i, _b in enumerate(body_blocks):
        print(f"  [{_i}] text={_b['text']!r}  top={_b['top']}  bottom={_b['bottom']}  cx={_b['cx']}")

    items: list[ProjectItem] = []
    used_block_texts: set[str] = set()

    for frac in fractions:
        frac_top = frac["top"]
        frac_cx = frac["cx"]

        best_block: Optional[dict] = None
        best_gap = float("inf")

        for block in body_blocks:
            block_h = block["bottom"] - block["top"]
            # Check vertical overlap / proximity.
            # The fraction can be:
            #   a) Below the block (vert_gap > 0) — normal stacked layout
            #   b) On the same row (vert_gap in [-block_h, 0]) — side-by-side layout
            # We detect (b) by checking whether the fraction's centre falls
            # within the block's vertical span (±tolerance).
            frac_center = frac_top + frac["h"] // 2
            block_center = (block["top"] + block["bottom"]) // 2
            vert_gap = frac_top - block["bottom"]   # positive = below block
            same_row = abs(frac_center - block_center) <= block_h * 0.8
            horiz_dist = abs(block["cx"] - frac_cx)

            if not same_row and (vert_gap < 0 or vert_gap > max_vert_gap):
                if vert_gap < 0:
                    print(f"[ProjectScanner]   SKIP {block['text']!r} for frac {frac['text']}: "
                          f"block below fraction (vert_gap={vert_gap})")
                else:
                    print(f"[ProjectScanner]   SKIP {block['text']!r} for frac {frac['text']}: "
                          f"vert_gap={vert_gap:.0f} > max {max_vert_gap:.0f}")
                continue
            if horiz_dist > max_horiz_gap:
                print(f"[ProjectScanner]   SKIP {block['text']!r} for frac {frac['text']}: "
                      f"horiz_dist={horiz_dist:.0f} > max {max_horiz_gap:.0f}")
                continue
            # Sort by closeness: same-row matches score 0 gap, below matches
            # score their actual gap so nearest-above wins.
            effective_gap = 0 if same_row else vert_gap
            if effective_gap < best_gap:
                best_gap = effective_gap
                best_block = block

        if best_block is None:
            print(f"[ProjectScanner]   NO MATCH for fraction {frac['text']} "
                  f"at top={frac_top} cx={frac_cx}")
            continue

        print(f"[ProjectScanner]   MATCHED frac {frac['text']} → {best_block['text']!r} "
              f"(vert_gap={best_gap:.0f})")
        name = best_block["text"]
        # Convert the ALL-CAPS OCR text to Title Case for nicer display.
        display_name = name.title()

        # Allow multiple fractions to reference the same block only if they
        # are on different rows (different item in a two-column layout), but
        # deduplicate exact duplicates.
        key = f"{name}|{frac['have']}/{frac['need']}"
        if key in used_block_texts:
            continue
        used_block_texts.add(key)

        items.append(ProjectItem(
            name=display_name,
            have=frac["have"],
            need=frac["need"],
        ))

    return items


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
            # Centre of the game window in virtual-desktop coordinates.
            game_cx = (rect.left + rect.right) // 2
            game_cy = (rect.top + rect.bottom) // 2
            for mon in sct.monitors[1:]:   # skip monitors[0] (virtual combined)
                if (mon["left"] <= game_cx < mon["left"] + mon["width"]
                        and mon["top"] <= game_cy < mon["top"] + mon["height"]):
                    print(f"[ProjectScanner] Game on monitor: {mon}")
                    return mon
    except Exception as exc:
        print(f"[ProjectScanner] Monitor detection failed: {exc}")

    return sct.monitors[1]   # fallback: primary monitor


def _rescan_fraction_region(
    original_img: Image.Image,
    block: dict,
    frac_cx: int,
    screen_height: int,
) -> dict | None:
    """Targeted OCR pass for a fraction near a specific item name block.

    When full-page OCR misses a fraction (e.g. due to progress-bar visual
    noise), this crops a small region where the fraction should appear and
    runs Tesseract with ``--psm 7`` (single text line) plus a character
    whitelist restricted to digits and ``/``.  This is far more accurate
    for isolated numeric text than full-page mode.

    Returns a fraction dict ``{text, have, need, top, …}`` or ``None``.
    """
    # Crop region: skip past the progress bar (~3% of screen height below
    # block bottom), then capture a narrow vertical band where the fraction
    # text sits.  Centred on the known fraction-column x position.
    crop_half_w = int(original_img.width * 0.05)   # ±5% of screen width
    bar_skip    = int(screen_height * 0.03)         # skip progress bar
    crop_v_span = int(screen_height * 0.04)         # ~58px at 1440p

    y1 = max(0, block["bottom"] + bar_skip)
    y2 = min(original_img.height, y1 + crop_v_span)
    x1 = max(0, frac_cx - crop_half_w)
    x2 = min(original_img.width, frac_cx + crop_half_w)

    if x2 - x1 < 20 or y2 - y1 < 10:
        return None

    crop = original_img.crop((x1, y1, x2, y2))

    # Upscale 3× for better digit recognition on small text.
    cw, ch = crop.size
    crop = crop.resize((cw * 3, ch * 3), Image.Resampling.LANCZOS)
    crop = crop.convert("L")
    # Invert: game uses light text on dark background, but Tesseract
    # works better with dark text on light background.
    from PIL import ImageOps
    crop = ImageOps.invert(crop)
    crop = ImageEnhance.Contrast(crop).enhance(2.0)

    # Save debug crop (only when DEBUG_OCR=1).
    if _DEBUG_OCR:
        try:
            safe = block["text"][:20].replace(" ", "_")
            crop.save(os.path.join(_PROJECT_ROOT, f"debug_frac_crop_{safe}.png"))
        except Exception:
            pass

    try:
        text = pytesseract.image_to_string(
            crop,
            config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789/",
        ).strip()
        print(f"[ProjectScanner] Rescan {block['text']!r}: OCR text={text!r}")

        m = re.search(r"(\d+)\s*/\s*(\d+)", text)
        if m:
            have, need = int(m.group(1)), int(m.group(2))
            if need > 0:
                return {
                    "text": f"{have}/{need}",
                    "have": have,
                    "need": need,
                    "top": y1 + 5,
                    "h": 15,
                    "left": frac_cx - 25,
                    "w": 50,
                    "bottom": y1 + 20,
                    "cx": frac_cx,
                }
    except Exception as exc:
        print(f"[ProjectScanner] Rescan OCR failed for {block['text']!r}: {exc}")

    return None


class ProjectScanner:
    """Reads the in-game project hand-in screen via full-screen OCR."""

    @property
    def available(self) -> bool:
        return _MSS_OK and _TESS_OK

    def scan_page(self) -> ProjectScanResult:
        """
        Capture the primary monitor and parse the project hand-in screen.

        Returns a ProjectScanResult on success.
        Raises ProjectScanError with a human-readable message on failure.
        """
        if not _MSS_OK:
            raise ProjectScanError(
                "Screen capture library (mss) is not installed.\n"
                "Run: pip install mss"
            )
        if not _TESS_OK:
            raise ProjectScanError(
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
            raise ProjectScanError(f"Screen capture failed: {exc}") from exc

        # ── Debug: save raw capture (only when DEBUG_OCR=1) ────────────────
        if _DEBUG_OCR:
            try:
                img.save(os.path.join(_PROJECT_ROOT, "debug_scan_raw.png"))
                print(f"[ProjectScanner] debug_scan_raw.png saved ({img.width}x{img.height})")
            except Exception as e:
                print(f"[ProjectScanner] Could not save debug_scan_raw.png: {e}")

        screen_height = img.height
        screen_width  = img.width

        # ── Pre-process ────────────────────────────────────────────────────
        proc = _preprocess(img)

        # ── Debug: save preprocessed capture (only when DEBUG_OCR=1) ───────
        if _DEBUG_OCR:
            try:
                proc.save(os.path.join(_PROJECT_ROOT, "debug_scan_proc.png"))
                print(f"[ProjectScanner] debug_scan_proc.png saved")
            except Exception as e:
                print(f"[ProjectScanner] Could not save debug_scan_proc.png: {e}")

        # ── Tesseract OCR ─────────────────────────────────────────────────
        try:
            data = _run_image_to_data(proc)
        except Exception as exc:
            raise ProjectScanError(f"OCR failed: {exc}") from exc

        words = _collect_words(data, scale=2.0)
        print(f"[ProjectScanner] words={len(words)}, "
              f"sample={[w['text'] for w in words[:20]]}")
        if not words:
            raise ProjectScanError(
                "No text detected on screen.\n"
                "Make sure the project hand-in screen is fully visible."
            )

        # ── Extract structural elements ────────────────────────────────────
        caps_blocks = _group_caps_lines(words)
        fractions = _extract_fractions(words)

        print(f"[ProjectScanner] ALL-CAPS blocks ({len(caps_blocks)}):")
        for _i, _b in enumerate(caps_blocks):
            print(f"  [{_i}] text={_b['text']!r}  top={_b['top']}  bottom={_b['bottom']}  cx={_b['cx']}")
        print(f"[ProjectScanner] Fractions ({len(fractions)}):")
        for _i, _f in enumerate(fractions):
            print(f"  [{_i}] {_f['text']}  top={_f['top']}  bottom={_f['top']+_f['h']}  cx={_f['cx']}")

        if not fractions:
            raise ProjectScanError(
                "No item progress fractions (e.g. 1/10) detected.\n"
                "Open the project hand-in screen so item requirements are visible, "
                "then try again."
            )

        title_bottom  = screen_height * _TITLE_ZONE_FRAC
        max_vert_gap  = screen_height * _VERT_GAP_FRAC
        max_horiz_gap = screen_width  * _HORIZ_GAP_FRAC
        project_name, phase_frac = _parse_title(
            caps_blocks, words, fractions, screen_height, screen_width
        )

        # Fractions on the title row are not item fractions — exclude them.
        # Only exclude fractions that are *in* the title zone (top < title_bottom).
        body_fractions = [f for f in fractions if f["top"] >= title_bottom]

        # If phase fraction was found, also exclude any matching fraction still
        # lingering in the title zone (but never exclude body-zone fractions).
        if phase_frac:
            ph_have, ph_need = (int(x) for x in phase_frac.split("/"))
            # Also include title-zone fractions that don't match the phase
            for f in fractions:
                if f["top"] < title_bottom:
                    if not (f["have"] == ph_have and f["need"] == ph_need):
                        body_fractions.append(f)

        print(f"[ProjectScanner] Body fractions after title exclusion: {len(body_fractions)}")
        for _i, _f in enumerate(body_fractions):
            print(f"  [{_i}] {_f['text']}  top={_f['top']}  cx={_f['cx']}")

        # ── Pair item names with their fractions ───────────────────────────
        items = _pair_items_with_fractions(
            caps_blocks, body_fractions, title_bottom, max_vert_gap, max_horiz_gap
        )

        # ── Targeted re-scan for unmatched item blocks ─────────────────
        # If full-page OCR missed a fraction (e.g. progress bar visual noise),
        # crop the expected fraction region and re-read with --psm 7.
        matched_names_upper = {it.name.upper() for it in items}
        # Item-column blocks: left third of screen, below title zone.
        item_col_limit = screen_width * 0.35
        unmatched_blocks = [
            b for b in caps_blocks
            if b["top"] >= title_bottom
            and b["cx"] < item_col_limit
            and b["text"] not in matched_names_upper
        ]

        if unmatched_blocks:
            # Determine fraction-column x from successfully matched fractions,
            # or fall back to ~30% of screen width.
            if body_fractions:
                frac_xs = sorted(f["cx"] for f in body_fractions
                                 if f["cx"] < screen_width * 0.5)
                frac_col_cx = frac_xs[len(frac_xs) // 2] if frac_xs else int(screen_width * 0.30)
            else:
                frac_col_cx = int(screen_width * 0.30)

            print(f"[ProjectScanner] Unmatched blocks ({len(unmatched_blocks)}), "
                  f"rescanning at frac_cx={frac_col_cx}:")
            for ub in unmatched_blocks:
                print(f"  → {ub['text']!r}  top={ub['top']}  bottom={ub['bottom']}")
                result = _rescan_fraction_region(
                    img, ub, frac_col_cx, screen_height
                )
                if result:
                    items.append(ProjectItem(
                        name=ub["text"].title(),
                        have=result["have"],
                        need=result["need"],
                    ))
                    print(f"  ✓ Recovered {ub['text']!r} → {result['have']}/{result['need']}")
                else:
                    print(f"  ✗ Could not recover fraction for {ub['text']!r}")

        print(f"[ProjectScanner] project={project_name!r} phase={phase_frac!r} "
              f"items={[(it.name, it.have, it.need) for it in items]}")

        if len(items) < _MIN_ITEMS:
            raise ProjectScanError(
                f"Only {len(items)} item(s) detected (need at least {_MIN_ITEMS}).\n"
                "Ensure the project hand-in screen is fully visible with item "
                "requirements showing, then try again."
            )

        return ProjectScanResult(
            project=project_name or "Unknown Project",
            phase_fraction=phase_frac,
            items=items,
        )
