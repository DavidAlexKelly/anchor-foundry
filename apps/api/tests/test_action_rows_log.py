"""A logged action's table rows as one batch call (§800; `action-types`
p.167-168).

Each row is its own submission, so each has its own log entry linked to the
objects *it* edited - and undoing one row takes back that row's log link
and leaves its neighbour's. The alerts are `test_action_log.py`'s.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_action_log import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, hdr, objects, pbase, wbase, world,
)


def logged(client, fx, world, alert: str) -> list[str]:
    """The log entries linked to one alert."""
    a = objects(client, fx, world["type_id"])[alert]
    r = client.get(f"{wbase(fx)}/object-types/{world['type_id']}/instances/{a['id']}/links",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    group = next((g for g in r.json() if g["link_type_id"] == world["log_link_type_id"]),
                 {"items": []})
    return [i["primary_key"] for i in group["items"]]


def test_each_row_logs_and_unlinks_its_own(client, fx, world) -> None:
    alerts = objects(client, fx, world["type_id"])
    r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/execute-rows",
                    headers=hdr(fx.editor_sub), json={"rows": [
                        {"instance_id": alerts["A1"]["id"],
                         "values": {"status": "closed", "also": alerts["A2"]["id"]}},
                        {"instance_id": alerts["A3"]["id"],
                         "values": {"status": "closed", "also": alerts["A3"]["id"]}}]})
    assert r.status_code == 200 and r.json()["ok"], r.text
    first, second = (x["run_id"] for x in r.json()["results"])
    assert first in logged(client, fx, world, "A1") and second in logged(client, fx, world, "A3")
    assert second not in logged(client, fx, world, "A1")

    undone = client.post(f"{pbase(fx)}/actions/{world['action_id']}/runs/{first}/undo",
                         headers=hdr(fx.editor_sub))
    assert undone.status_code == 200, undone.text
    assert second in logged(client, fx, world, "A3")
