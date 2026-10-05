"""An Action table's link rows as one batch call (§800; workshop p.512).

Several rows' pairs go into the join table as **one** version, and each
row's run still knows which pair is its own - so undoing one row takes back
that row's link and not its neighbours'. The flights and aircraft are
`test_action_join_links.py`'s.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_action_join_links import (  # noqa: E402,F401
    _fresh_identity_cache, action, client, fx, hdr, instance, linked, pbase, version_of,
    world,
)


def rows(client, fx, world, action_id: str, sent: list[tuple[str, str]]):
    return client.post(
        f"{pbase(fx)}/actions/{action_id}/execute-rows", headers=hdr(fx.editor_sub),
        json={"rows": [
            {"instance_id": instance(client, fx, world["flights"], flight)["id"],
             "values": {"other": instance(client, fx, world["aircraft"], craft)["id"]}}
            for flight, craft in sent]})


def test_link_rows_write_one_version_and_undo_one_pair_each(client, fx, world) -> None:
    link_it, r = action(client, fx, world, "flights", "create_link", "aircraft")
    assert r.status_code == 200, r.text
    before = version_of(client, fx, world)
    r = rows(client, fx, world, link_it, [("F3", "3"), ("F4", "2")])
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert version_of(client, fx, world) == before + 1
    assert "3" in linked(client, fx, world, "F3") and linked(client, fx, world, "F4") == ["2"]

    first, second = r.json()["results"]
    assert first["can_undo"] and second["can_undo"], r.json()
    undone = client.post(f"{pbase(fx)}/actions/{link_it}/runs/{second['run_id']}/undo",
                         headers=hdr(fx.editor_sub))
    assert undone.status_code == 200, undone.text
    assert linked(client, fx, world, "F4") == []
    assert "3" in linked(client, fx, world, "F3")


def test_one_pair_written_by_two_rows_conflicts(client, fx, world) -> None:
    """Two rows writing one pair are p.512's conflicting edits too."""
    link_it, _ = action(client, fx, world, "flights", "create_link", "aircraft")
    before = version_of(client, fx, world)
    r = rows(client, fx, world, link_it, [("F1", "2"), ("F1", "2")])
    assert r.status_code == 422, r.text
    assert "rows 1 and 2 both edit the link F1 - 2" in r.json()["detail"], r.text
    assert version_of(client, fx, world) == before


def test_unlink_rows_remove_every_pair_they_name(client, fx, world) -> None:
    unlink, r = action(client, fx, world, "flights", "delete_link", "aircraft")
    assert r.status_code == 200, r.text
    link_it, _ = action(client, fx, world, "flights", "create_link", "aircraft")
    made = rows(client, fx, world, link_it, [("F2", "3"), ("F3", "2")])
    assert made.status_code == 200 and made.json()["ok"], made.text
    r = rows(client, fx, world, unlink, [("F2", "3"), ("F3", "2")])
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert "3" not in linked(client, fx, world, "F2")
    assert "2" not in linked(client, fx, world, "F3")
