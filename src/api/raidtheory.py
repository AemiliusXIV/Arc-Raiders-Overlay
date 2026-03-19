"""RaidTheory/arcraiders-data community dataset client.

MIT-licensed community dataset maintained by RaidTheory.
Required attribution (shown in README and About):
  Data: https://github.com/RaidTheory/arcraiders-data
  Site: https://arctracker.io
"""

from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import requests

_RAW = "https://raw.githubusercontent.com/RaidTheory/arcraiders-data/main"
_TREE_URL = (
    "https://api.github.com/repos/RaidTheory/arcraiders-data/git/trees/main"
    "?recursive=1"
)

ATTRIBUTION = (
    "Community item data from arcraiders-data (MIT licence) — "
    "github.com/RaidTheory/arcraiders-data · arctracker.io"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_json(url: str, timeout: int = 10) -> dict | list | None:
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def _name_to_id(name: str) -> str:
    """Normalise a display name to a probable RaidTheory snake-case file ID."""
    s = name.lower()
    s = re.sub(r"[''`'\u2019]", "", s)       # drop apostrophes
    s = re.sub(r"[^a-z0-9]+", "_", s)        # non-alphanumeric → underscore
    return s.strip("_")


def _en_name(item: dict) -> str:
    """Extract the English display name from an RT item dict."""
    name = item.get("name", {})
    if isinstance(name, dict):
        return name.get("en", "")
    return str(name) if name else ""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class RaidTheoryClient:
    """
    Background-loaded client for the RaidTheory arcraiders-data dataset.

    Loading stages (all run on a daemon thread — never blocks the UI):
      1. trades.json      — single file, all trader prices
      2. GitHub tree API  — get list of all item file paths
      3. All item JSONs   — fetched concurrently (10 workers), indexes built

    Before loading completes individual items can still be fetched lazily
    (one HTTP request per item miss). Trades are available once stage 1 finishes.
    """

    def __init__(self, on_ready: Callable[[], None] | None = None) -> None:
        self._lock = threading.Lock()
        self._trades: list[dict] = []
        self._items: dict[str, dict] = {}        # rt_id → item dict
        self._used_in: dict[str, list[str]] = {}  # ingredient_id → [item_ids]
        self._name_map: dict[str, str] = {}       # lowercase en name → rt_id
        self._loaded = False
        self._on_ready = on_ready

        threading.Thread(
            target=self._load_all, daemon=True, name="rt-loader"
        ).start()

    # ------------------------------------------------------------------
    # Background loader
    # ------------------------------------------------------------------

    def _load_all(self) -> None:
        # Stage 1 — trades.json (single request, high value)
        trades_raw = _get_json(f"{_RAW}/trades.json")
        if isinstance(trades_raw, list):
            with self._lock:
                self._trades = trades_raw

        # Stage 2 — item file list via GitHub tree API
        tree = _get_json(_TREE_URL)
        if not tree:
            with self._lock:
                self._loaded = True
            return

        item_ids = [
            node["path"][len("items/"):-len(".json")]
            for node in tree.get("tree", [])
            if node.get("path", "").startswith("items/")
            and node["path"].endswith(".json")
        ]

        # Stage 3 — fetch all item files concurrently
        def _fetch(iid: str) -> tuple[str, dict | None]:
            return iid, _get_json(f"{_RAW}/items/{iid}.json")

        items: dict[str, dict] = {}
        used_in: dict[str, list[str]] = {}
        name_map: dict[str, str] = {}

        with ThreadPoolExecutor(max_workers=10) as pool:
            for iid, data in pool.map(_fetch, item_ids):
                if not data:
                    continue
                items[iid] = data

                # English name → RT ID mapping
                en = _en_name(data).lower()
                if en:
                    name_map[en] = iid

                # Inverted index: ingredient_id → items that use it in recipe
                recipe = data.get("recipe") or {}
                if isinstance(recipe, dict):
                    for ingredient_id in recipe:
                        used_in.setdefault(ingredient_id, []).append(iid)
                elif isinstance(recipe, list):
                    for entry in recipe:
                        if isinstance(entry, dict):
                            ing = entry.get("itemId") or entry.get("id") or ""
                            if ing:
                                used_in.setdefault(ing, []).append(iid)

        with self._lock:
            self._items.update(items)
            self._used_in = used_in
            self._name_map = name_map
            self._loaded = True

        if self._on_ready:
            self._on_ready()

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        with self._lock:
            return self._loaded

    # ------------------------------------------------------------------
    # Item lookup
    # ------------------------------------------------------------------

    def _get_cached(self, rt_id: str) -> dict | None:
        with self._lock:
            return self._items.get(rt_id)

    def get_item(self, rt_id: str) -> dict | None:
        """Return item dict by RT id, fetching lazily if not yet in cache."""
        cached = self._get_cached(rt_id)
        if cached is not None:
            return cached
        data = _get_json(f"{_RAW}/items/{rt_id}.json")
        if data:
            with self._lock:
                self._items[rt_id] = data
        return data

    def get_item_name(self, rt_id: str) -> str:
        """Return the English display name for an RT item ID."""
        item = self._get_cached(rt_id)
        if item:
            en = _en_name(item)
            return en if en else rt_id.replace("_", " ").title()
        return rt_id.replace("_", " ").title()

    def find_by_name(self, display_name: str) -> tuple[str | None, dict | None]:
        """
        Locate an RT item by its in-game display name.
        Returns (rt_id, item_dict). item_dict may be fetched lazily.
        """
        query = display_name.strip().lower()
        with self._lock:
            rt_id = self._name_map.get(query)
        if rt_id:
            return rt_id, self.get_item(rt_id)
        # Fallback: guess the ID from the name
        guessed = _name_to_id(display_name)
        item = self.get_item(guessed)
        return (guessed if item else None, item)

    # ------------------------------------------------------------------
    # Trades
    # ------------------------------------------------------------------

    def get_trader_listings(self, rt_id: str) -> list[dict]:
        with self._lock:
            return [t for t in self._trades if t.get("itemId") == rt_id]

    # ------------------------------------------------------------------
    # Used-in index
    # ------------------------------------------------------------------

    def get_used_in(self, rt_id: str) -> list[str]:
        with self._lock:
            return list(self._used_in.get(rt_id, []))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_material_list(self, raw) -> list[dict]:
        """Parse a recyclesInto / salvagesInto value into a normalised list.

        The RT dataset uses two formats:
          • List:  [{"itemId": "battery", "quantity": 2}, ...]
          • Dict:  {"battery": 2, "exodus_modules": 1}

        Both are normalised to [{"name": str, "qty": int}].
        """
        out: list[dict] = []
        if not raw:
            return out
        if isinstance(raw, dict):
            for iid, qty in raw.items():
                if iid:
                    out.append({
                        "name": self.get_item_name(iid),
                        "qty": int(qty) if qty else 1,
                    })
        elif isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    iid = entry.get("itemId") or entry.get("id") or entry.get("item_id", "")
                    qty = entry.get("quantity") or entry.get("qty") or entry.get("amount") or 1
                    if iid:
                        out.append({
                            "name": self.get_item_name(iid),
                            "qty": int(qty),
                        })
        return out

    # ------------------------------------------------------------------
    # Main enrichment entry point
    # ------------------------------------------------------------------

    def enrich(
        self,
        display_name: str,
        mf_quests: list[dict] | None = None,
        expedition_projects: list[dict] | None = None,
    ) -> dict:
        """
        Return a merged enrichment dict for the named item.

        Keys:
          rt_id:    str | None
          rt_item:  dict | None   (raw RT item)
          recycle:  list[{"name": str, "qty": int}]
          salvage:  list[{"name": str, "qty": int}]
          used_in:  list[{"name": str, "bench": str}]
          traders:  list[{"trader", "qty", "cost_item", "cost_qty", "daily_limit"}]
          quests:   list[{"name": str, "trader": str, "qty": int|None}]
          found_in: list[str]   (loot locations / zones)
        """
        rt_id, rt_item = self.find_by_name(display_name)

        result: dict = {
            "rt_id":    rt_id,
            "rt_item":  rt_item,
            "recycle":  [],
            "salvage":  [],
            "used_in":  [],
            "traders":  [],
            "quests":   [],
            "found_in": [],
        }

        if rt_item and rt_id:
            # Recycle output — RT data may use list-of-dicts OR plain dict format
            result["recycle"] = self._parse_material_list(rt_item.get("recyclesInto"))

            # Salvage output — same dual-format handling
            result["salvage"] = self._parse_material_list(rt_item.get("salvagesInto"))

            # Found-in locations — try several possible field names
            found_raw = (
                rt_item.get("foundIn")
                or rt_item.get("locations")
                or rt_item.get("zones")
                or []
            )
            if isinstance(found_raw, list):
                result["found_in"] = [str(loc) for loc in found_raw if loc]
            elif isinstance(found_raw, str) and found_raw:
                result["found_in"] = [found_raw]

            # Trader listings
            for trade in self.get_trader_listings(rt_id):
                cost = trade.get("cost") or {}
                cost_id = cost.get("itemId", "")
                cost_name = (
                    cost_id if cost_id in ("creds", "coins", "")
                    else self.get_item_name(cost_id)
                )
                result["traders"].append({
                    "trader": trade.get("trader", "?"),
                    "qty": trade.get("quantity", 1),
                    "cost_item": cost_name,
                    "cost_qty": cost.get("quantity", 0),
                    "daily_limit": trade.get("dailyLimit"),
                })

            # Used-in (items whose recipe includes this item)
            for used_id in self.get_used_in(rt_id):
                used_item = self._get_cached(used_id)
                if used_item:
                    result["used_in"].append({
                        "name": _en_name(used_item) or used_id.replace("_", " ").title(),
                        "bench": used_item.get("craftBench", ""),
                    })

        # Quest requirements from MetaForge quest data
        if mf_quests:
            query_lower = display_name.strip().lower()
            print(f"[Enrich] Checking {len(mf_quests)} quests for {repr(display_name)}")
            if mf_quests:
                first_req = (mf_quests[0].get("required_items") or [])
                print(f"[Enrich] Sample required_items[0]: {first_req[:2] if first_req else '(empty)'}")
            for quest in mf_quests:
                q_name = quest.get("name") or quest.get("title") or "Unknown Quest"
                q_trader = quest.get("trader") or ""
                if isinstance(q_trader, dict):
                    q_trader = q_trader.get("name", "")
                for req in (quest.get("required_items") or []):
                    if not isinstance(req, dict):
                        continue
                    # MetaForge format: {"item": {"id": "geiger-counter", "name": "Geiger Counter", ...}, "quantity": N}
                    item_obj = req.get("item")
                    if isinstance(item_obj, dict):
                        req_raw_name = (item_obj.get("name") or "").strip().lower()
                        # "id" field on the nested item is the slug (e.g. "geiger-counter")
                        req_slug_raw = (item_obj.get("id") or item_obj.get("slug") or "").strip().lower()
                    else:
                        # Flat format: {"slug": "...", "name": "...", "quantity": N}
                        req_raw_name = (req.get("name") or "").strip().lower()
                        req_slug_raw = (req.get("slug") or req.get("item_id") or "").strip().lower()
                    # Normalise underscores/hyphens → spaces for slug-as-name matching
                    req_name = re.sub(r"[_\-]+", " ", req_raw_name)
                    req_slug = re.sub(r"[_\-]+", " ", req_slug_raw)
                    matched = (
                        (req_raw_name and (req_raw_name == query_lower or query_lower in req_raw_name))
                        or (req_name and (req_name == query_lower or query_lower in req_name))
                        or (req_slug and (req_slug == query_lower or query_lower in req_slug))
                    )
                    if matched:
                        qty = req.get("qty") or req.get("quantity") or req.get("amount") or req.get("count")
                        result["quests"].append({
                            "name": str(q_name),
                            "trader": str(q_trader),
                            "qty": int(qty) if qty else None,
                        })
                        break  # one entry per quest
        else:
            print(f"[Enrich] mf_quests is {'empty list' if mf_quests is not None else 'None'} — quests may not have loaded yet")

        # Expedition project requirements from MetaForge /expedition endpoint
        if expedition_projects:
            query_lower_exp = display_name.strip().lower()
            print(f"[Enrich] Checking {len(expedition_projects)} expedition phases for {repr(display_name)}")
            for phase_entry in expedition_projects:
                for req in (phase_entry.get("requirements") or []):
                    req_name = (req.get("name") or "").strip().lower()
                    # "id" field is the slug, e.g. "geiger-counter"
                    req_id_norm = re.sub(r"[_\-]+", " ", (req.get("id") or "")).strip().lower()
                    if req_name == query_lower_exp or req_id_norm == query_lower_exp:
                        project = phase_entry.get("project", "Unknown Project")
                        phase   = phase_entry.get("phase", "")
                        category = phase_entry.get("category", "")
                        phase_label = f"{phase}: {category}" if category else phase
                        need = req.get("need") or req.get("quantity") or req.get("qty") or 1
                        result["quests"].append({
                            "name":   project,
                            "trader": phase_label,
                            "qty":    int(need),
                        })
                        break  # one entry per expedition phase
        else:
            print(f"[Enrich] No expedition project data available")

        return result
