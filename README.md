# Arc Raiders Overlay

A lightweight desktop companion app for ARC Raiders. Pulls live data from the MetaForge public API and displays event timers, item lookups, map POIs, quest tracking, and more. Runs on a second screen or as a toggleable always-on-top overlay.

**No Overwolf. No game process interaction. Read-only API companion.**

---

## Requirements

- Python 3.11 or newer
- Windows 10/11 (Linux/macOS should work but are untested; click-through overlay requires Windows)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed and on PATH *(optional — only needed for the item scanner hotkey)*

---

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/AemiliusXIV/Arc-Raiders-Overlay.git
cd Arc-Raiders-Overlay

# 2. Create a virtual environment (recommended)
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # Linux/macOS

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

---

## Features

### Tabs

| Tab | Description |
|-----|-------------|
| **Events** | Live countdown timers for all map events (storms, night raids, etc.) with configurable audio/visual alerts at custom thresholds |
| **Items** | Searchable item database — sell value, recycle output, quest requirement flag; double-click for full item detail |
| **Map** | POI viewer for all five maps: Dam, Spaceport, Buried City, Blue Gate, Stella Montis |
| **Quests** | Quest list with trader filter, text search, and manual progress tracking (persisted) |
| **Needed Items** | Aggregates required items across all quests; track how many you have vs. still need — persisted between sessions |
| **Hideout** | Workshop/hideout upgrade tracker with completion checkboxes; falls back to showing workbench items if the dedicated API endpoint isn't live yet |
| **Blueprints** | Track which blueprints you've found; filters the item database for blueprint-category items |
| **Weekly Trials** | Tracks the current week's trials with completion state that auto-resets each Monday |

### In-game overlay (Alt+Z)

A separate always-on-top transparent window showing live event countdowns, designed to sit in a corner of your game screen.

- **Click-through** — the overlay never blocks mouse clicks to the game underneath
- **Becomes interactive when you hover** — move your cursor over it to drag it to a new position
- **Drag position is saved** and restored on next launch
- Toggle with **Alt+Z** (or View → Show In-Game Overlay)

### Item scanner (Alt+X)

Press **Alt+X** while hovering an item name in-game. The app captures a screen region, reads the text via OCR, and automatically searches the Items tab.

Requires Tesseract OCR to be installed — see Requirements above.

---

## Hotkeys

| Action | Default | Change in |
|--------|---------|-----------|
| Toggle in-game overlay | `Alt+Z` | Settings → Configure Hotkeys |
| Item scanner (OCR) | `Alt+X` | Settings → Configure Hotkeys |

Hotkeys are global (work even when the app window is not focused). Change them at any time in **Settings → Configure Hotkeys…** — click the field and press your desired key combination. Changes take effect immediately.

---

## Configuration

Settings are stored in `config/settings.json` and are editable in-app.

| Setting | Default | Where to change |
|---------|---------|-----------------|
| Event alert thresholds | `[60, 300]` seconds | Events tab → Alert Settings |
| Alert volume | `0.7` | Events tab → Alert Settings |
| Always on top | `true` | View → Always on Top |
| Item scanner hotkey | `alt+x` | Settings → Configure Hotkeys |
| Overlay toggle hotkey | `alt+z` | Settings → Configure Hotkeys |
| Needed items "have" counts | — | Needed Items tab |
| Hideout upgrade completions | — | Hideout tab |
| Blueprint found status | — | Blueprints tab |
| Weekly trial completions | — | Weekly Trials tab |

---

## Data Sources

- Primary: [MetaForge](https://metaforge.app/arc-raiders/api) public API
- Fallback: [ARDB](https://ardb.app/api) for items and quests

---

## Legal

This app reads only from public, officially documented APIs. It does not read game memory, inject into processes, intercept network traffic, or automate any in-game actions.
