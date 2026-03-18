"""Lightweight diagnostic logger — prints timestamped messages with thread name."""

import threading
import time

_T0 = time.perf_counter()


def log(msg: str) -> None:
    elapsed = time.perf_counter() - _T0
    thread = threading.current_thread().name
    print(f"[{elapsed:7.3f}s] [{thread}] {msg}", flush=True)
