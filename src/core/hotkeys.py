"""Global hotkey registration using the `keyboard` library."""

from __future__ import annotations
from typing import Callable

try:
    import keyboard as _keyboard
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False


class HotkeyManager:
    def __init__(self):
        self._registered: list[str] = []

    @property
    def available(self) -> bool:
        return _AVAILABLE

    def register(self, hotkey: str, callback: Callable) -> bool:
        """Register a global hotkey. Returns True on success."""
        if not _AVAILABLE:
            return False
        try:
            _keyboard.add_hotkey(hotkey, callback, suppress=False)
            self._registered.append(hotkey)
            return True
        except Exception:
            return False

    def unregister(self, hotkey: str) -> None:
        if not _AVAILABLE:
            return
        try:
            _keyboard.remove_hotkey(hotkey)
            self._registered = [h for h in self._registered if h != hotkey]
        except Exception:
            pass

    def unregister_all(self) -> None:
        if not _AVAILABLE:
            return
        for hotkey in list(self._registered):
            self.unregister(hotkey)
