"""A function-backed action's table rows as one batch call (§800;
`action-types` p.84 and p.131).

> "the backing function is usually called once per request in sequence, and
> all edits are applied atomically at the end of the action call." (p.84)

> "This limit is reduced to 20 when the action is function-backed and the
> function is not configured to use batched execution." (p.131)

The tickets are `test_function_actions.py`'s.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_function_actions import (  # noqa: E402,F401
    _fresh_identity_cache, abase, client, functionally, fx, hdr, held, tickets,
)


def rows(client, fx, action_id: str, instance_ids: list[str]):
    return client.post(f"{abase(fx)}/{action_id}/execute-rows", headers=hdr(fx.editor_sub),
                       json={"rows": [{"instance_id": i, "values": {}} for i in instance_ids]})


def test_each_row_calls_the_function_and_every_edit_lands_together(
    client, fx, tickets
) -> None:
    """A function that opens a follow-up is a create, which the inline edit's
    batch cannot take - here each row's call makes its own."""
    t = tickets["api_name"]
    act, _fn = functionally(
        client, fx, tickets,
        f"SELECT 'F' || __primary_key AS __primary_key, 'follow up' AS title, "
        f"'open' AS status, region FROM {t} WHERE __primary_key = $ticket")
    r = rows(client, fx, act, [tickets["T1"], tickets["T2"]])
    assert r.status_code == 200 and r.json()["ok"], r.text
    after = held(client, fx, tickets["type_id"])
    assert after["FT1"]["title"] == after["FT2"]["title"] == "follow up"
    assert [len(x["touched"]) for x in r.json()["results"]] == [1, 1]


def test_a_function_backed_batch_takes_twenty_rows(client, fx, tickets) -> None:
    t = tickets["api_name"]
    act, _fn = functionally(
        client, fx, tickets,
        f"SELECT __primary_key, title || '!' AS title FROM {t} WHERE __primary_key = $ticket")
    r = rows(client, fx, act, [tickets["T1"]] * 21)
    assert r.status_code == 422, r.text
    assert "at most 20 times in a batch, and this submission has 21 rows" in r.text
    assert held(client, fx, tickets["type_id"])["T1"]["title"] == "Printer jam"
    # Twenty is the limit, not past it.
    r = rows(client, fx, act, [tickets["T1"]] * 20)
    assert r.status_code == 422 and "both edit" in r.text, r.text
