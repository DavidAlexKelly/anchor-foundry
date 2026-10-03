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


# ---- §779: batched execution (`action-types` p.84-85) ----------------------------

def batched(client, fx, tickets, sql: str | None = None) -> dict:
    """p.85's example, `updateDestinationBatch(batch: {flight, destination}[])`,
    as SQL: a batch of a ticket and a title."""
    t = tickets["api_name"]
    return publish(client, fx, tickets,
                   sql or ("SELECT b.ticket AS k, upper(b.title) AS title "
                           "FROM (SELECT unnest($batch) AS b)"),
                   parameters=[{"api_name": "batch", "data_type": "batch", "fields": [
                       {"api_name": "ticket", "data_type": "object",
                        "object_type_id": tickets["type_id"]},
                       {"api_name": "title", "data_type": "string"}]}])


def batched_action(client, fx, tickets, fn: dict) -> str:
    act = action(client, fx, tickets)
    r = define(client, fx, act, [{"kind": "function", "config": {
        "function_id": fn["id"], "version": "1.0.0", "batched": True,
        "inputs": {"ticket": {"subject": True}, "title": {"parameter": "title"}}}}], [TITLE])
    assert r.status_code == 200, r.text
    return act


def test_a_batched_function_takes_the_whole_batch_in_one_call(client, fx, tickets) -> None:
    act = batched_action(client, fx, tickets, batched(client, fx, tickets))
    got = client.get(f"{wbase(fx)}/action-types/{act}", headers=hdr(fx.viewer_sub)).json()
    # p.131: the 20 is for a function "not configured to use batched execution".
    assert (got["inline_edit_refusals"], got["inline_edit_row_limit"]) == ([], 200)
    r = batch(client, fx, act, [
        {"instance_id": tickets["T1"], "values": {"title": "one"}},
        {"instance_id": tickets["T3"], "values": {"title": "three"}},
    ])
    assert r.status_code == 200, r.text
    after = held(client, fx, tickets["type_id"])
    assert (after["T1"]["title"], after["T2"]["title"], after["T3"]["title"]) == (
        "ONE", "No coffee", "THREE")


def test_a_single_submission_is_a_batch_of_one(client, fx, tickets) -> None:
    """p.85: "A single action call will invoke a single function execution
    with a single entry in the list input parameter"."""
    act = batched_action(client, fx, tickets, batched(client, fx, tickets))
    r = client.post(f"{abase(fx)}/{act}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": tickets["T2"], "values": {"title": "solo"}})
    assert r.status_code == 200, r.text
    assert held(client, fx, tickets["type_id"])["T2"]["title"] == "SOLO"


def test_a_batched_function_may_edit_only_the_batchs_rows(client, fx, tickets) -> None:
    fn = batched(client, fx, tickets, sql=(
        f"SELECT __primary_key, 'x' AS title FROM {tickets['api_name']} "
        "WHERE list_contains((SELECT list(b.ticket) FROM (SELECT unnest($batch) AS b)), "
        "__primary_key) OR __primary_key = 'T2'"))
    act = batched_action(client, fx, tickets, fn)
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {}}])
    assert r.status_code == 422, r.text
    assert "changes only the row it is typed into" in r.text
    # And a row of the batch it gives nothing for is said, not skipped.
    fn = batched(client, fx, tickets, sql=(
        "SELECT b.ticket AS k, b.title AS title FROM (SELECT unnest($batch) AS b) "
        "WHERE b.ticket <> 'T3'"))
    act = batched_action(client, fx, tickets, fn)
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {"title": "a"}},
                                {"instance_id": tickets["T3"], "values": {"title": "b"}}])
    assert r.status_code == 422, r.text
    assert "made no edit for T3" in r.text


def test_batched_must_match_the_function(client, fx, tickets) -> None:
    fn = batched(client, fx, tickets)
    act = action(client, fx, tickets)
    r = define(client, fx, act, [{"kind": "function", "config": {
        "function_id": fn["id"], "version": "1.0.0",
        "inputs": {"ticket": {"subject": True}}}}], [TITLE])
    assert r.status_code == 422, r.text
    assert "receives a batch, so the rule runs it batched" in r.text
    plain = publish(client, fx, tickets,
                    f"SELECT __primary_key, 'x' AS title FROM {tickets['api_name']} "
                    "WHERE __primary_key = $ticket")
    r = define(client, fx, act, [{"kind": "function", "config": {
        "function_id": plain["id"], "version": "1.0.0", "batched": True,
        "inputs": {"ticket": {"subject": True}}}}], [TITLE])
    assert r.status_code == 422, r.text
    assert "receives no batch, so the rule cannot run it batched" in r.text
    r = define(client, fx, act, [{"kind": "function", "config": {
        "function_id": fn["id"], "version": "1.0.0", "batched": "yes",
        "inputs": {"ticket": {"subject": True}}}}], [TITLE])
    assert "batched is true or false" in r.text
    # A field it does not have is named like a parameter it does not have.
    r = define(client, fx, act, [{"kind": "function", "config": {
        "function_id": fn["id"], "version": "1.0.0", "batched": True,
        "inputs": {"ticket": {"subject": True}, "colour": {"value": "red"}}}}], [TITLE])
    assert "takes no parameter colour" in r.text


def test_a_newer_release_that_changes_batching_fails_the_action(client, fx, tickets) -> None:
    fn = batched(client, fx, tickets)
    r = client.post(f"{wbase(fx)}/functions/{fn['id']}/versions", headers=hdr(fx.editor_sub),
                    json={"version": "1.1.0", "inputs": [tickets["type_id"]],
                          "parameters": [{"api_name": "ticket", "data_type": "object",
                                          "object_type_id": tickets["type_id"]}],
                          "output": {"kind": "edits", "object_type_id": tickets["type_id"]},
                          "sql": f"SELECT __primary_key, 'x' AS title "
                                 f"FROM {tickets['api_name']} WHERE __primary_key = $ticket"})
    assert r.status_code == 201, r.text
    act = action(client, fx, tickets)
    assert define(client, fx, act, [{"kind": "function", "config": {
        "function_id": fn["id"], "version": "1.0.0", "batched": True, "auto_upgrade": True,
        "inputs": {"ticket": {"subject": True}}}}], [TITLE]).status_code == 200
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {}}])
    assert r.status_code == 422, r.text
    assert "changes whether it takes a batch" in r.text


def test_the_row_limit_reads_whether_the_rule_is_batched() -> None:
    batched_rule = {"kind": "function", "config": {"function_id": "f", "batched": True}}
    assert actions.inline_edit_row_limit({"rules": [batched_rule]}) == 200
    assert actions.inline_edit_row_limit({"rules": [
        {"kind": "function", "config": {"function_id": "f", "batched": False}}]}) == 20


def test_an_unbatched_function_may_not_edit_a_row_beside_its_own(client, fx, tickets) -> None:
    """Called once per row (p.84), each call may edit only its own row - even
    one that is in the same submission."""
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
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {"title": "x"}},
                                {"instance_id": tickets["T2"], "values": {"title": "y"}}])
    assert r.status_code == 422, r.text
    assert "changes only the row it is typed into" in r.text


def test_a_function_that_deletes_the_row_is_refused(client, fx, tickets) -> None:
    """§783's typed edits, through an inline edit: p.136's "modify a single
    object", so not a delete of the row it is typed into."""
    t = tickets["api_name"]
    made = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [],
            "parameters": [{"api_name": "ticket", "data_type": "object",
                            "object_type_id": tickets["type_id"]},
                           {"api_name": "title", "data_type": "string"}],
            "output": {"kind": "edits", "object_type_ids": [tickets["type_id"]]},
            "sql": (f"SELECT '{t}' AS __object_type, $ticket AS __primary_key, "
                    "'delete' AS __edit, NULL::JSON AS __properties "
                    "WHERE $title IS NOT NULL")}})
    assert made.status_code == 201, made.text
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(made.json(), inputs={
        "ticket": {"subject": True}, "title": {"parameter": "title"}})],
        [TITLE]).status_code == 200
    r = batch(client, fx, act, [{"instance_id": tickets["T1"], "values": {"title": "x"}}])
    assert r.status_code == 422, r.text
    assert "changes only the row it is typed into" in r.text
    assert "T1" in held(client, fx, tickets["type_id"])
