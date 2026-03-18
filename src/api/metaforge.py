"""MetaForge public API wrappers."""

from .client import APIClient

BASE_URL = "https://metaforge.app"

VALID_MAPS = ["Dam", "Spaceport", "Buried City", "Blue Gate", "Stella Montis"]


def _unwrap(response) -> list:
    """All list endpoints return {"data": [...]} — extract the inner list."""
    if isinstance(response, dict):
        return response.get("data") or []
    if isinstance(response, list):
        return response
    return []


class MetaForgeAPI:
    def __init__(self, client: APIClient):
        self._client = client

    def get_items(self) -> list[dict]:
        """Fetch all items, walking the paginated API (534 items, 11 pages)."""
        cache_key = f"{BASE_URL}/api/arc-raiders/items?all"
        # Use a sentinel key so the cache stores the full merged list
        try:
            cached = self._client.get(cache_key, ttl=300)
            if isinstance(cached, list):
                return cached
        except Exception:
            pass

        items: list[dict] = []
        page = 1
        while True:
            url = f"{BASE_URL}/api/arc-raiders/items?page={page}&limit=50"
            try:
                resp = self._client.get(url, ttl=300)
            except Exception:
                break
            page_items = _unwrap(resp)
            items.extend(page_items)
            pagination = resp.get("pagination", {}) if isinstance(resp, dict) else {}
            if not pagination.get("hasNextPage"):
                break
            page += 1

        # Cache the merged list under the sentinel key
        self._client._cache[cache_key] = (
            __import__("time").monotonic() + 300,
            items,
        )
        return items

    def get_item(self, slug: str) -> dict:
        return self._client.get(f"{BASE_URL}/api/arc-raiders/item/{slug}", ttl=300)

    def get_arcs(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/arcs", ttl=300))

    def get_quests(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/quests", ttl=300))

    def get_traders(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/traders", ttl=300))

    def get_map_data(self, map_name: str) -> list[dict]:
        if map_name not in VALID_MAPS:
            raise ValueError(f"Unknown map '{map_name}'. Valid maps: {VALID_MAPS}")
        return _unwrap(self._client.get(
            f"{BASE_URL}/api/game-map-data?map={map_name}", ttl=600
        ))

    def get_events(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/events", ttl=60))

    def get_workshop(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/workshop", ttl=300))

    def get_trials(self) -> list[dict]:
        return _unwrap(self._client.get(f"{BASE_URL}/api/arc-raiders/trials", ttl=3600))
