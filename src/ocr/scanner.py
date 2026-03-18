"""Item scanner — screen capture + OCR to auto-look up hovered items.

Optional feature. Requires:
    pip install mss pytesseract Pillow
    + Tesseract OCR binary installed and on PATH
      (https://github.com/UB-Mannheim/tesseract/wiki)
"""

from __future__ import annotations

from typing import Callable, Optional

try:
    import mss
    import mss.tools
    _MSS_OK = True
except ImportError:
    _MSS_OK = False

try:
    from PIL import Image, ImageFilter, ImageEnhance
    import pytesseract
    # TEMP: Replace with bundled Tesseract path when building installer
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    _TESS_OK = True
except ImportError:
    _TESS_OK = False


# Default capture region — centred top-quarter of a 1920x1080 screen.
# Users can adjust via config in a future settings panel.
DEFAULT_REGION = {"top": 200, "left": 760, "width": 400, "height": 60}


class ItemScanner:
    """Captures a screen region and extracts an item name via OCR."""

    def __init__(
        self,
        on_result: Callable[[str], None],
        region: Optional[dict] = None,
    ):
        self._on_result = on_result
        self._region = region or DEFAULT_REGION

    @property
    def available(self) -> bool:
        return _MSS_OK and _TESS_OK

    def scan(self) -> None:
        """Capture region, run OCR, and invoke callback with the result."""
        if not _MSS_OK:
            print("[ItemScanner] mss not installed — OCR unavailable")
            return
        if not _TESS_OK:
            print("[ItemScanner] pytesseract/Pillow not installed — OCR unavailable")
            return

        try:
            with mss.mss() as sct:
                screenshot = sct.grab(self._region)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

            # Pre-process: upscale, sharpen, increase contrast for better OCR accuracy
            img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
            img = img.filter(ImageFilter.SHARPEN)
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img = img.convert("L")  # greyscale

            raw_text = pytesseract.image_to_string(
                img,
                config="--psm 7 --oem 3",  # single line, LSTM
            )
            item_name = raw_text.strip().split("\n")[0].strip()

            if item_name:
                self._on_result(item_name)
        except Exception as exc:
            print(f"[ItemScanner] OCR error: {exc}")

    def update_region(self, region: dict) -> None:
        self._region = region
