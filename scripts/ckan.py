"""Shared utilities for the data.gov.uk CKAN API scripts."""

import json
import threading
import time
from pathlib import Path

BASE_URL = "https://www.data.gov.uk/api/3/action"
MAX_RPS = 4


def write_json(data: list[dict], path: Path | str) -> None:
    content = json.dumps(data, indent=2, ensure_ascii=False)
    Path(path).write_text(content, encoding="utf-8")


def create_rate_limiter(max_per_second: int):
    """Return a callable that blocks until a slot is free (sliding window)."""

    window: list[float] = []
    lock = threading.Lock()

    def wait_for_slot() -> None:
        while True:
            with lock:
                now = time.monotonic()
                while window and window[0] <= now - 1.0:
                    window.pop(0)

                if len(window) < max_per_second:
                    window.append(time.monotonic())
                    return

                # Window is full — sleep until the oldest slot ages out.
                # Compute the delay under the lock but sleep outside it, so
                # other threads can take slots (or one can age out) meanwhile.
                delay = window[0] + 1.0 - now
            time.sleep(delay)

    return wait_for_slot


def sleep(ms: float) -> None:
    """Sleep for ms milliseconds (used for 429 backoff)."""
    time.sleep(ms / 1000)
