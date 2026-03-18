"""Load and persist user settings from config/settings.json."""

import json
import os
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.json"

DEFAULTS: dict = {
    "alert_seconds_before": [60, 300],
    "volume": 0.7,
    "always_on_top": True,
    "default_map": "Dam",
    "hotkey_scan": "alt+x",
    "hotkey_overlay": "alt+z",
    "window_geometry": None,
    "overlay_position": None,
    "overlay_visible": False,
    "tracked_quests": [],
    "collected_items": {},
    "completed_upgrades": [],
    "found_blueprints": [],
    "completed_trials": {},
}


class Config:
    def __init__(self):
        self._data: dict = {}
        self.load()

    def load(self) -> None:
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self._data = {**DEFAULTS, **loaded}
            except (json.JSONDecodeError, OSError):
                self._data = dict(DEFAULTS)
        else:
            self._data = dict(DEFAULTS)
            self.save()

    def save(self) -> None:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        self.save()

    # Convenience properties
    @property
    def alert_seconds_before(self) -> list[int]:
        return self._data.get("alert_seconds_before", DEFAULTS["alert_seconds_before"])

    @alert_seconds_before.setter
    def alert_seconds_before(self, value: list[int]) -> None:
        self.set("alert_seconds_before", value)

    @property
    def volume(self) -> float:
        return float(self._data.get("volume", DEFAULTS["volume"]))

    @volume.setter
    def volume(self, value: float) -> None:
        self.set("volume", max(0.0, min(1.0, float(value))))

    @property
    def always_on_top(self) -> bool:
        return bool(self._data.get("always_on_top", DEFAULTS["always_on_top"]))

    @always_on_top.setter
    def always_on_top(self, value: bool) -> None:
        self.set("always_on_top", bool(value))

    @property
    def default_map(self) -> str:
        return self._data.get("default_map", DEFAULTS["default_map"])

    @default_map.setter
    def default_map(self, value: str) -> None:
        self.set("default_map", value)

    @property
    def hotkey_scan(self) -> str:
        return self._data.get("hotkey_scan", DEFAULTS["hotkey_scan"])

    @hotkey_scan.setter
    def hotkey_scan(self, value: str) -> None:
        self.set("hotkey_scan", value)

    @property
    def hotkey_overlay(self) -> str:
        return self._data.get("hotkey_overlay", DEFAULTS["hotkey_overlay"])

    @hotkey_overlay.setter
    def hotkey_overlay(self, value: str) -> None:
        self.set("hotkey_overlay", value)

    @property
    def overlay_position(self) -> list | None:
        return self._data.get("overlay_position", None)

    @overlay_position.setter
    def overlay_position(self, value: list | None) -> None:
        self.set("overlay_position", value)

    @property
    def overlay_visible(self) -> bool:
        return bool(self._data.get("overlay_visible", False))

    @overlay_visible.setter
    def overlay_visible(self, value: bool) -> None:
        self.set("overlay_visible", bool(value))

    @property
    def tracked_quests(self) -> list[str]:
        return self._data.get("tracked_quests", [])

    @tracked_quests.setter
    def tracked_quests(self, value: list[str]) -> None:
        self.set("tracked_quests", value)

    @property
    def collected_items(self) -> dict:
        return self._data.get("collected_items", {})

    @collected_items.setter
    def collected_items(self, value: dict) -> None:
        self.set("collected_items", value)

    @property
    def completed_upgrades(self) -> list:
        return self._data.get("completed_upgrades", [])

    @completed_upgrades.setter
    def completed_upgrades(self, value: list) -> None:
        self.set("completed_upgrades", value)

    @property
    def found_blueprints(self) -> list:
        return self._data.get("found_blueprints", [])

    @found_blueprints.setter
    def found_blueprints(self, value: list) -> None:
        self.set("found_blueprints", value)

    @property
    def completed_trials(self) -> dict:
        return self._data.get("completed_trials", {})

    @completed_trials.setter
    def completed_trials(self, value: dict) -> None:
        self.set("completed_trials", value)
