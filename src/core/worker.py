"""Reusable background worker: runs a callable in a daemon thread, returns via Qt signals.

Usage:
    worker = Worker(fn)
    worker.finished.connect(on_result)
    worker.error.connect(on_error)
    worker.start()
    self._worker = worker  # keep reference so it isn't GC'd

Always create Worker in the main thread. Qt delivers the signals back to the
main thread automatically via its queued-connection mechanism.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal


class Worker(QObject):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self._fn = fn

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        try:
            self.finished.emit(self._fn())
        except Exception as exc:
            self.error.emit(str(exc))
