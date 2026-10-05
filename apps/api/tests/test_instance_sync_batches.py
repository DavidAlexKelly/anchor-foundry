"""A sync writes its objects a batch at a time (§804; roadmap phase 3, E.4).

One statement per object made a 10,000-row sync take 16 seconds; one per
thousand takes half of one. The batching must not change what a sync makes:
a key repeated in the file is still one object holding the later row's
values, and a sync longer than a batch loses nothing at the seams.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_restore_check import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, hdr, storage, sync, typed, wbase,
)


def objects(client, fx, type_id: str) -> dict[str, dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances?limit=100",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i["properties"] for i in r.json()["items"]}


def test_a_repeated_key_is_one_object_with_the_later_rows_values(client, fx) -> None:
    made = typed(client, fx, "repeats", b"code,label\nA,one\nB,two\nA,again\n", "code", "label")
    assert objects(client, fx, made["type_id"]) == {"A": {"label": "again"},
                                                    "B": {"label": "two"}}


def test_a_sync_longer_than_a_batch_loses_nothing_at_the_seams(
    client, fx, monkeypatch
) -> None:
    from src.services import instances

    monkeypatch.setattr(instances, "UPSERT_BATCH", 3)
    # Seven rows over batches of three, with a repeat that straddles a seam
    # (rows 3 and 4) and one inside a batch (rows 5 and 6).
    rows = b"code,label\nK1,a\nK2,b\nK3,c\nK3,c2\nK4,d\nK4,d2\nK5,e\n"
    made = typed(client, fx, "seams", rows, "code", "label")
    assert objects(client, fx, made["type_id"]) == {
        "K1": {"label": "a"}, "K2": {"label": "b"}, "K3": {"label": "c2"},
        "K4": {"label": "d2"}, "K5": {"label": "e"}}
    # Syncing again changes nothing, and removes nothing.
    sync(client, fx, made["source_id"])
    assert len(objects(client, fx, made["type_id"])) == 5
