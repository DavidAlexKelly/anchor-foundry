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
import pytest

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


# ---- retention from one listing (§898) -----------------------------------------
class ListingStore:
    def __init__(self, objects: dict[str, int]) -> None:
        self.objects = objects
        self.listed: list[str] = []
        self.heads: list[str] = []

    def sizes_under(self, prefix: str) -> dict[str, int]:
        self.listed.append(prefix)
        return {k: v for k, v in self.objects.items() if k.startswith(prefix)}

    def size(self, key: str) -> int | None:
        self.heads.append(key)
        return self.objects.get(key)


PREFIX = "workspaces/acme-1/datasets/d1/"


def test_retention_reads_every_size_from_one_listing(monkeypatch) -> None:
    keys = [f"{PREFIX}v{n}/data.parquet" for n in range(1, 2001)]
    store = ListingStore({k: n for n, k in enumerate(keys, start=1)})
    del store.objects[keys[5]]  # one version's object is gone
    monkeypatch.setattr(ds_routes, "_storage", store)

    sizes = anyio.run(ds_routes._sizes_by_listing, keys + [None])
    assert store.listed == [PREFIX] and store.heads == []
    assert sizes[0] == 1 and sizes[5] is None and sizes[-1] is None
    assert sum(s for s in sizes if s) == sum(range(1, 2001)) - 6


def test_a_key_outside_the_dataset_is_asked_about_on_its_own(monkeypatch) -> None:
    keys = [f"{PREFIX}v1/data.parquet", "workspaces/acme-1/elsewhere/x.parquet"]
    store = ListingStore({k: 10 for k in keys})
    monkeypatch.setattr(ds_routes, "_storage", store)
    assert anyio.run(ds_routes._sizes_by_listing, keys) == [10, 10]
    assert store.listed == [] and sorted(store.heads) == sorted(keys)


def test_the_local_gateway_lists_what_is_under_a_prefix(tmp_path) -> None:
    import uuid

    from src.services.storage import LocalStorageGateway, StorageKeyError

    gateway = LocalStorageGateway(str(tmp_path))
    mine = f"workspaces/acme-1/datasets/{uuid.uuid4()}/"
    gateway.put(f"{mine}v1/data.parquet", b"12345")
    gateway.put(f"{mine}v2/data.parquet", b"12")
    gateway.put(f"workspaces/acme-1/datasets/{uuid.uuid4()}/v1/data.parquet", b"1")
    assert gateway.sizes_under(mine) == {f"{mine}v1/data.parquet": 5, f"{mine}v2/data.parquet": 2}
    assert gateway.sizes_under(f"workspaces/acme-1/datasets/{uuid.uuid4()}/") == {}
    with pytest.raises(StorageKeyError):
        gateway.sizes_under("../etc/")
