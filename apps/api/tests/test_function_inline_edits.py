"""Function-backed inline edits (§776; `workshop` p.240-242, `action-types`
p.84, p.131, p.136-138; decision 0018 option B).

> "The action should either use a single "Modify object" rule or be
> function-backed." (p.240) "Users can stage edits for up to 20 rows at a
> time for function-backed actions and up to 200 rows at a time for actions
> that are not function-backed." (p.242)

> "When an action is triggered in batches, such as in Workshop inline edits
> … the backing function is usually called once per request in sequence, and
> all edits are applied atomically at the end of the action call." (p.84)
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_function_actions import (  # noqa: E402,F401
    _fresh_identity_cache, abase, action, client, define, fx, held, publish, rule, tickets,
    wbase,
)
from src.services import actions  # noqa: E402

TITLE = {"api_name": "title", "display_name": "Title", "data_type": "string"}


def upper_title(client, fx, tickets) -> str:
    t = tickets["api_name"]
    fn = publish(client, fx, tickets,
                 f"SELECT __primary_key, upper($title) AS title FROM {t} "
                 "WHERE __primary_key = $ticket",
                 parameters=[{"api_name": "ticket", "data_type": "object",
                              "object_type_id": tickets["type_id"]},
                             {"api_name": "title", "data_type": "string"}])
    act = action(client, fx, tickets)
    r = define(client, fx, act, [rule(fn, inputs={"ticket": {"subject": True},
                                                  "title": {"parameter": "title"}})], [TITLE])
    assert r.status_code == 200, r.text
    return act


def batch(client, fx, act: str, edits: list[dict]):
    return client.post(f"{abase(fx)}/{act}/execute-batch", headers=hdr(fx.editor_sub),
                       json={"edits": edits})


def test_a_function_backed_action_may_back_inline_edits_twenty_rows_at_a_time(
    client, fx, tickets
) -> None:
    act = upper_title(client, fx, tickets)
    got = client.get(f"{wbase(fx)}/action-types/{act}", headers=hdr(fx.viewer_sub)).json()
    assert got["inline_edit_refusals"] == []
    assert got["inline_edit_row_limit"] == 20
    plain = action(client, fx, tickets)
    got = client.get(f"{wbase(fx)}/action-types/{plain}", headers=hdr(fx.viewer_sub)).json()
    assert got["inline_edit_row_limit"] == 200


def test_each_row_calls_the_function_and_the_batch_lands_whole(client, fx, tickets) -> None:
    act = upper_title(client, fx, tickets)
    r = batch(client, fx, act, [
        {"instance_id": tickets["T1"], "values": {"title": "new one"}},
        # p.135: an untouched parameter is the object's own value.
        {"instance_id": tickets["T2"], "values": {}},
    ])
    assert r.status_code == 200, r.text
    assert (r.json()["ok"], r.json()["rows"]) == (True, 2)
    after = held(client, fx, tickets["type_id"])
    assert (after["T1"]["title"], after["T2"]["title"], after["T3"]["title"]) == (
        "NEW ONE", "NO COFFEE", "Broken chair")


def test_a_function_that_edits_another_row_is_refused(client, fx, tickets) -> None:
    """p.136: an inline edit "May only modify a single object of a single
    object type" - the row it is typed into."""
    t = tickets["api_name"]
    fn = publish(client, fx, tickets,
                 f"SELECT __primary_key, $title AS title FROM {t} "
                 f"WHERE region = (SELECT region FROM {t} WHERE __primary_key = $ticket)",
                 parameters=[{"api_name": "ticket", "data_type": "object",
                              "object_type_id": tickets["type_id"]},
                             {"api_name": "title", "data_type": "string"}])
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(fn, inputs={"ticket": {"subject": True},
                                                     "title": {"parameter": "title"}})],
                  [TITLE]).status_code == 200
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {"title": "x"}}])
    assert r.status_code == 422, r.text
    assert "changes only the row it is typed into" in r.text
    assert held(client, fx, tickets["type_id"])["T2"]["title"] == "No coffee"


def test_more_than_twenty_rows_are_refused_before_any_is_read(client, fx, tickets) -> None:
    act = upper_title(client, fx, tickets)
    r = batch(client, fx, act, [{"instance_id": str(uuid.uuid4()), "values": {}}
                                for _ in range(21)])
    assert r.status_code == 422, r.text
    assert "20 rows at a time" in r.text
    # Twenty is allowed as far as the count goes: these are refused for not
    # existing, which is read after the count.
    r = batch(client, fx, act, [{"instance_id": str(uuid.uuid4()), "values": {}}
                                for _ in range(20)])
    assert "20 rows at a time" not in r.text


def test_the_refusals_and_the_seed_read_the_function_rule() -> None:
    function = {"kind": "function", "config": {"function_id": "f"}}
    assert actions.inline_edit_refusals({"object_type_id": "t", "rules": [function],
                                         "parameters": []}) == []
    assert actions.inline_edit_row_limit({"rules": [function]}) == 20
    assert actions.inline_edit_row_limit({"rules": []}) == 200
    # A Function rule beside a side effect is still refused, as any is (p.137).
    assert actions.inline_edit_refusals({"object_type_id": "t", "rules": [
        function, {"kind": "notify", "config": {}}], "parameters": []})
    # p.241: with no rule naming the property, a parameter named as a
    # property is seeded from it.
    seeded = actions.seed_from_instance(
        {"status": "x"}, parameters=[{"api_name": "title"}, {"api_name": "status"},
                                     {"api_name": "note"}],
        properties={"title": "T", "status": "s"}, rules=[function])
    assert seeded == {"status": "x", "title": "T"}
    # Without a Function rule the name alone seeds nothing.
    assert actions.seed_from_instance(
        {}, parameters=[{"api_name": "title"}], properties={"title": "T"}, rules=[]) == {}
