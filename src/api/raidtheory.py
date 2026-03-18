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
    # Main enrichment entry point
    # ------------------------------------------------------------------

    def enrich(
        self,
        display_name: str,
        mf_quests: list[dict] | None = None,
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
          quests:   list[{"name": str, "trader": str}]
        """
        rt_id, rt_item = self.find_by_name(display_name)

        result: dict = {
            "rt_id": rt_id,
            "rt_item": rt_item,
            "recycle": [],
            "salvage": [],
            "used_in": [],
            "traders": [],
            "quests": [],
        }

        if rt_item and rt_id:
            # Recycle output
            for entry in (rt_item.get("recyclesInto") or []):
                if isinstance(entry, dict):
                    result["recycle"].append({
                        "name": self.get_item_name(entry.get("itemId", "")),
                        "qty": entry.get("quantity", 1),
                    })

            # Salvage output
            for entry in (rt_item.get("salvagesInto") or []):
                if isinstance(entry, dict):
                    result["salvage"].append({
                        "name": self.get_item_name(entry.get("itemId", "")),
                        "qty": entry.get("quantity", 1),
                    })

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
            for quest in mf_quests:
                q_name = quest.get("name") or quest.get("title") or "Unknown Quest"
                q_trader = quest.get("trader") or ""
                if isinstance(q_trader, dict):
                    q_trader = q_trader.get("name", "")
                for req in (quest.get("required_items") or []):
                    if not isinstance(req, dict):
                        continue
                    req_name = (req.get("name") or "").strip().lower()
                    if req_name and (req_name == query_lower or query_lower in req_name):
                        result["quests"].append({
                            "name": str(q_name),
                            "trader": str(q_trader),
                        })
                        break  # one entry per quest

        return result
