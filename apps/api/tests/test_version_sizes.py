"""A version listing asks for its sizes several at a time (§878).

The history and the retention figure each asked S3 for one version's size,
waited, and asked for the next: a few seconds for a hundred versions, minutes
for a dataset synced every five minutes for a month.
"""
from __future__ import annotations

import os
import sys
import threading
import time

import anyio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.routes import datasets as ds_routes  # noqa: E402

DELAY = 0.2


class SlowStore:
    """An object store whose every HEAD takes a fifth of a second."""

    def __init__(self) -> None:
        self.at_once = 0
        self.most_at_once = 0
        self._lock = threading.Lock()

    def size(self, key: str) -> int | None:
        with self._lock:
            self.at_once += 1
            self.most_at_once = max(self.most_at_once, self.at_once)
        time.sleep(DELAY)
        with self._lock:
            self.at_once -= 1
        return None if key.startswith("missing") else len(key)


def test_sizes_come_back_in_order_and_together(monkeypatch) -> None:
    store = SlowStore()
    monkeypatch.setattr(ds_routes, "_storage", store)
    keys = [f"k{'x' * n}" for n in range(40)] + [None, "missing/v1"]

    started = time.monotonic()
    sizes = anyio.run(ds_routes._sizes, keys)
    took = time.monotonic() - started

    assert sizes == [len(k) for k in keys[:40]] + [None, None]
    # 41 HEADs one after another is over eight seconds; sixteen at a time,
    # three rounds.
    assert took < 41 * DELAY / 4, f"{took:.1f}s"
    # And never more than the listing's own share of threads.
    assert store.most_at_once == ds_routes.SIZE_CONCURRENCY


def test_no_keys_is_no_heads(monkeypatch) -> None:
    store = SlowStore()
    monkeypatch.setattr(ds_routes, "_storage", store)
    assert anyio.run(ds_routes._sizes, [None, ""]) == [None, None]
    assert store.most_at_once == 0
