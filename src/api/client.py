"""Shared HTTP client with in-memory TTL cache and basic error handling."""

import time
import requests


class APIError(Exception):
    """Raised when an API call returns a non-200 status or network failure."""
    pass


class APIClient:
    def __init__(self, timeout: int = 10):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "ArcRaidersOverlay/1.0 (companion app; read-only)"
        })
        self._timeout = timeout
        self._cache: dict[str, tuple[float, object]] = {}  # url -> (expires_at, data)

    def get(self, url: str, ttl: int = 60) -> object:
        """Fetch JSON from url, returning cached result if still fresh."""
        now = time.monotonic()
        if url in self._cache:
            expires_at, data = self._cache[url]
            if now < expires_at:
                return data

        try:
            response = self._session.get(url, timeout=self._timeout)
        except requests.RequestException as exc:
            raise APIError(f"Network error fetching {url}: {exc}") from exc

        if response.status_code != 200:
            raise APIError(
                f"HTTP {response.status_code} from {url}: {response.text[:200]}"
            )

        data = response.json()
        self._cache[url] = (now + ttl, data)
        return data

    def invalidate(self, url: str) -> None:
        """Remove a single URL from the cache."""
        self._cache.pop(url, None)

    def clear_cache(self) -> None:
        self._cache.clear()
