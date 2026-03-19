# Developer Notes

Internal developer notes. Not for public distribution.

---

## Installer — Tesseract OCR

When building the installer, Tesseract must be bundled or auto-installed as part of the
setup process. Users must never be required to install it manually.

- Bundle the Tesseract binary directly into the installer (e.g. via Inno Setup, NSIS, or
  a PyInstaller `--add-binary` directive pointing at the Tesseract install directory).
- After bundling, replace the hardcoded path in `src/ocr/scanner.py`:

  ```python
  # TEMP: Replace with bundled Tesseract path when building installer
  pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
  ```

  with a dynamic path that resolves relative to the application bundle, e.g.:

  ```python
  import sys, os
  base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
  pytesseract.pytesseract.tesseract_cmd = os.path.join(base, 'tesseract', 'tesseract.exe')
  ```

- The Tesseract language data (`tessdata/`) must also be included and the `TESSDATA_PREFIX`
  environment variable set to point at it before any OCR call is made.

---
