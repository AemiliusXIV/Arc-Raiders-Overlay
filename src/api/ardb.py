"""ARDB fallback API for items and quests."""

from .client import APIClient

BASE_URL = "https://ardb.app/api"


class ARDBApi:
    def __init__(self, client: APIClient):
        self._client = client

    def get_items(self) -> list[dict]:
        return self._client.get(f"{BASE_URL}/items", ttl=300)

    def get_quests(self) -> list[dict]:
        return self._client.get(f"{BASE_URL}/quests", ttl=300)
