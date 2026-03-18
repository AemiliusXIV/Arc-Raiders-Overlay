"""Reusable background worker: runs a callable in a daemon thread, returns via Qt signals.

Usage:
    worker = Worker(fn)
    worker.finished.connect(on_result)
    worker.error.connect(on_error)
    worker.start()
    self._workers.append(worker)  # keep reference until thread finishes

Thread-safety note
------------------
Worker uses threading.Thread (not QThread).  PyQt6 cannot reliably detect that
the emitting thread is foreign to Qt, so a direct signal.emit() from a
threading.Thread may invoke connected slots *in that thread* rather than queuing
them to the main-thread event loop.

To guarantee main-thread delivery we use an inner ``_Signals`` QObject that is
created in (and therefore has affinity to) the caller's thread.  When
``_Signals.finished`` or ``_Signals.error`` is emitted from the background
thread, Qt sees a cross-thread emission (background thread vs. main thread)
and automatically uses a queued connection, delivering the slot call back to
the main-thread event loop.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from PyQt6.QtCore import QObject, pyqtSignal


class Worker(QObject):
    """Run *fn* in a daemon thread; deliver results to the creating thread."""

    class _Signals(QObject):
        finished = pyqtSignal(object)
        error    = pyqtSignal(str)

    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self._fn = fn
        # _signals lives in the creating (main) thread.  Any emit() call from
        # the daemon thread is therefore cross-thread and will be queued.
        self._signals = Worker._Signals()
        # Expose as direct attributes so callers use the same API as before:
        #   worker.finished.connect(slot)
        self.finished = self._signals.finished
        self.error    = self._signals.error

    def start(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        try:
            self._signals.finished.emit(self._fn())
        except Exception as exc:
            self._signals.error.emit(str(exc))
