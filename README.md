# Arc Raiders Overlay  v0.1.0-alpha

> ⚠️ **ALPHA — Internal Testing Only**
> This app is in early alpha and intended for testing purposes only. Expect bugs, missing features, and breaking changes. Not recommended for general use yet.

A lightweight desktop companion app for ARC Raiders. Pulls live data from the MetaForge public API and displays event timers, item lookups, interactive maps, quest tracking, and more. Runs on a second screen or as a toggleable always-on-top overlay.

**No Overwolf. No game process interaction. Read-only API companion.**

---

## Requirements

- Python 3.11 or newer
- Windows 10/11 (Linux/macOS should work but are untested; click-through overlay requires Windows)
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) installed and on PATH *(optional — only needed for the item scanner hotkey)*

> **Note:** Installing `requirements.txt` will pull in `PyQt6-WebEngine`, which bundles a Chromium engine (~200 MB). This is required for the embedded map viewer. If disk space is a concern you can omit it and the app will fall back to a clickable link for the map tab.

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
| **Items** | Searchable item database with sell value, recycle output, workbench, and quest flag; double-click any row for full item detail |
| **Map** | Embedded interactive map loaded directly from ArcMaps.com (recommended), MetaForge, or ArcRaidersMaps.app — switch sources and jump to any of the five maps from the toolbar |
| **Quests** | Quest list with trader filter, text search, and manual progress tracking (persisted) |
| **Needed Items** | Aggregates required items across all quests; track how many you have vs. still need — persisted between sessions |
| **Hideout** | Workshop/hideout upgrade tracker with completion checkboxes; falls back to workbench items if the dedicated API endpoint isn't live |
| **Blueprints** | Track which blueprints you've found; merges MetaForge and ARDB data, filtered to blueprint-category items |
| **Weekly Trials** | Tracks the current week's trials with completion state that auto-resets each Monday |

### Interactive map (Map tab)

The Map tab embeds a full interactive map directly inside the app window using a built-in Chromium browser. Website chrome (nav bars, footers, cookie banners, scrollbars) is stripped via CSS injection so only the map canvas is shown.

- **Source switcher** — swap between ArcMaps.com (recommended), MetaForge, and ArcRaidersMaps.app at any time
- **Map selector** — jump directly to Dam, Spaceport, Buried City, Blue Gate, or Stella Montis
- **Refresh** button to reload the page; **Open in Browser** to pop out to your default browser
- Map begins loading in the background at app startup so there is no delay when you first open the tab

### Minimap overlay (Alt+M)

A compact always-on-top floating window showing the same map source as the Map tab, designed to sit in a corner of your game screen alongside your game.

- **Draggable** — click and drag the header bar to reposition anywhere on screen
- **Resizable** — drag the bottom-right grip to resize
- **Adjustable opacity** — slider in the header bar (20 %–100 %); also configurable in Settings
- **Position and size persist** across sessions
- Toggle with **Alt+M** (or View → Show Minimap Overlay)

### In-game overlay (Alt+Z)

A separate always-on-top transparent window showing live event countdowns, designed to sit in a corner of your game screen.

- **Click-through** — the overlay never blocks mouse clicks to the game underneath
- **Becomes interactive when you hover** — move your cursor over it to drag it to a new position
- **Drag position is saved** and restored on next launch
- Toggle with **Alt+Z** (or View → Show In-Game Overlay)

### Item scanner (Alt+X)

Press **Alt+X** while hovering an item name in-game. The app captures a screen region, reads the text via OCR, and displays a rich floating popup card showing:

| Field | Source |
|-------|--------|
| Name, rarity, type, description | MetaForge API |
| Sell value, weight, stack size | MetaForge / arcraiders-data |
| Recycle / salvage output | arcraiders-data (exact materials + quantities) |
| Sold by (trader, cost, daily limit) | arcraiders-data |
| Used in (what items craft with this) | arcraiders-data |
| Required by quests | MetaForge quest data |
| Sources / loot locations | MetaForge API |

The popup stays on screen for 15 seconds and pauses the timer while you hover over it. Click **×** to dismiss early.

Requires Tesseract OCR to be installed — see Requirements above.

---

## Hotkeys

| Action | Default | Change in |
|--------|---------|-----------|
| Toggle in-game overlay | `Alt+Z` | Settings → Configure Hotkeys |
| Toggle minimap overlay | `Alt+M` | Settings → Configure Hotkeys |
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
| Minimap toggle hotkey | `alt+m` | Settings → Configure Hotkeys |
| Minimap opacity | `0.85` | Settings → Configure Hotkeys / minimap header slider |
| Map source | `ArcMaps.com` | Map tab → Source dropdown |
| Default map | `Dam` | Map tab → Map dropdown |
| Needed items "have" counts | — | Needed Items tab |
| Hideout upgrade completions | — | Hideout tab |
| Blueprint found status | — | Blueprints tab |
| Weekly trial completions | — | Weekly Trials tab |

---

## Data Sources

| Source | Used for |
|--------|----------|
| [MetaForge](https://metaforge.app/arc-raiders/api) public API | Events, items, quests, map POIs, hideout, trials (primary) |
| [ARDB](https://ardb.app/api) | Items and quests fallback |
| [arcraiders-data](https://github.com/RaidTheory/arcraiders-data) by RaidTheory | Recycle/salvage output, trader prices, crafting recipes, quest item cross-reference |
| [ArcMaps.com](https://arcmaps.com) | Embedded interactive map (default source) |
| [MetaForge web map](https://metaforge.app/arc-raiders/map) | Embedded interactive map (alternative source) |
| [ArcRaidersMaps.app](https://arcraidersmaps.app) | Embedded interactive map (alternative source) |

The arcraiders-data dataset is MIT-licensed. Per its licence terms this app links to the source repository and to [arctracker.io](https://arctracker.io).

The embedded map sources (ArcMaps.com, metaforge.app, arcraidersmaps.app) are third-party websites displayed via an in-app browser — equivalent to visiting them in a normal web browser. All map data, POI data, and map imagery remain the property of their respective owners.

---

## Legal

This app reads only from public, officially documented APIs and embeds third-party websites via a standard web browser component. It does not read game memory, inject into processes, intercept network traffic, or automate any in-game actions.

Arc Raiders is a trademark of Embark Studios AB. This project is not affiliated with, endorsed by, or sponsored by Embark Studios AB.

The embedded map sites (ArcMaps.com, metaforge.app, arcraidersmaps.app) are independent community resources. Their content, map data, and imagery are the property of their respective owners. This app does not host, redistribute, or claim ownership of any map data.

© 2026 AemiliusXIV. All Rights Reserved. This software is shared for testing purposes only. Viewing and personal use is permitted. Copying, modifying, distributing, or using this code in other projects is strictly prohibited. See [LICENSE](LICENSE) for full details.
