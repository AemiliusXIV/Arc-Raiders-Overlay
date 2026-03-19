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

## Installer — PyQt6-WebEngine (Chromium)

`PyQt6-WebEngine` bundles a full Chromium engine and requires **special PyInstaller
handling** that differs from ordinary Python packages.

### Why it's non-trivial

PyInstaller's standard analysis does not walk the Qt plugin tree, so the Chromium
subprocess binary (`QtWebEngineProcess.exe`) and its supporting files are not collected
automatically. Without them the web view silently fails to render anything.

### Required PyInstaller options

```bash
pyinstaller main.py \
  --collect-all PyQt6.QtWebEngineWidgets \
  --collect-all PyQt6.QtWebEngineCore \
  --collect-all PyQt6.QtWebEngine \
  --add-binary ".venv/Lib/site-packages/PyQt6/Qt6/bin/QtWebEngineProcess.exe;PyQt6/Qt6/bin" \
  --add-data  ".venv/Lib/site-packages/PyQt6/Qt6/resources;PyQt6/Qt6/resources" \
  --add-data  ".venv/Lib/site-packages/PyQt6/Qt6/translations;PyQt6/Qt6/translations"
```

Adjust paths if your venv is named differently or if you're on a non-Windows platform.

### QtWebEngineProcess.exe

This subprocess binary **must** end up alongside the main executable (or in the
`PyQt6/Qt6/bin/` subfolder, depending on your spec file layout). If it's missing,
the web view area will be blank and the app log will show a renderer crash message.

### Qt WebEngine data files

The following must be present at runtime relative to the app root:

| Path | Contents |
|------|----------|
| `PyQt6/Qt6/resources/qtwebengine_resources.pak` | Core Chromium resources |
| `PyQt6/Qt6/resources/qtwebengine_devtools_resources.pak` | DevTools (can omit in release) |
| `PyQt6/Qt6/translations/qtwebengine_*.qm` | Chromium locale strings |

### Recommended approach

Use a `.spec` file rather than bare CLI flags so the collection rules are reproducible.
Consider using [pyinstaller-hooks-contrib](https://github.com/pyinstaller/pyinstaller-hooks-contrib)
which ships a maintained `hook-PyQt6.QtWebEngineWidgets.py` — install it with:

```bash
pip install pyinstaller-hooks-contrib
```

and PyInstaller will pick it up automatically.

### Fallback behaviour

`src/ui/map_viewer.py` and `src/ui/minimap_overlay.py` both guard the import:

```python
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _WEBENGINE = True
except ImportError:
    _WEBENGINE = False
```

If the bundle is broken or the package is absent the map tab degrades gracefully to
a clickable link that opens the map in the user's default browser — so a failed
WebEngine bundle does not crash the app.

---
