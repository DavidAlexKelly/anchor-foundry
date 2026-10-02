"""A page that leaves out properties its reader loads on demand (§693;
`workshop` p.266, p.595-597).

> "Some large properties, such as Geoshape and Vector, are not loaded by
> default to improve performance. In View mode, users can select Load next to
> an unsupported property to reveal its value on demand." (p.266)

The widgets say which properties they will not draw; the page leaves those
out of every row and nothing else changes.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_object_set_traversal import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, linked, wbase,
)


def page(client, fx, definition, **extra) -> dict:
    r = client.post(f"{wbase(fx)}/object-sets/evaluate", headers=hdr(fx.editor_sub),
                    json={"definition": definition, "limit": 50, "sort": "key", **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_an_omitted_property_is_left_out_of_every_row(client, fx, linked) -> None:
    customers = {"object_type_id": linked["customer_type"], "filters": []}
    whole = page(client, fx, customers)["instances"]
    assert all("region" in row["properties"] for row in whole)
    lean = page(client, fx, customers, omit=["region"])
    assert [row["properties"] for row in lean["instances"]] == [
        {k: v for k, v in row["properties"].items() if k != "region"} for row in whole]
    # The rows are the same rows: only what they carry changes.
    assert [r["primary_key"] for r in lean["instances"]] == [r["primary_key"] for r in whole]
    assert lean["total"] == 3


def test_a_union_leaves_it_out_of_every_type(client, fx, linked) -> None:
    union = {"union": [{"object_type_id": linked["customer_type"], "filters": []},
                       {"object_type_id": linked["order_type"], "filters": []}]}
    rows = page(client, fx, union, omit=["region", "total"])["instances"]
    assert len(rows) == 6
    assert all("region" not in r["properties"] and "total" not in r["properties"] for r in rows)
    assert any("placed" in r["properties"] for r in rows)
