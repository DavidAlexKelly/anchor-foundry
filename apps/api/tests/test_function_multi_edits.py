"""A function's edits across object types, and its deletions (§783; decision
0018 option B; `action-types` p.75, p.83).

> "Modify multiple objects that are currently linked together. For example,
> you may want to set the status field of an Incident object to Closed, and
> also set the status of all linked Alert objects to Resolved." … "Create
> several different types of objects and set up links between them." (p.75)

An edit function over several types says each row's type: its query gives
`__object_type`, `__primary_key`, `__edit` (create, modify or delete) and
`__properties`, a JSON object of the properties to set. §773's one-type shape
is unchanged.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_function_actions import (  # noqa: E402,F401
    action, client, define, failures, fx, held, ids, object_type, rule, run, tickets, wbase,
    _fresh_identity_cache,
)
from src.services import action_functions  # noqa: E402
from src.services.function_engine import FunctionError  # noqa: E402

ALERTS = (b"key,ticket,status\n"
          b"A1,T1,new\n"
          b"A2,T1,new\n"
          b"A3,T2,new\n")


@pytest.fixture
def alerts(client, fx) -> dict:
    made = object_type(client, fx, "alert", ALERTS, ["key", "ticket", "status"])
    return {**made, **ids(client, fx, made["type_id"])}


def publish(client, fx, types: list[dict], sql: str, *, version: str = "1.0.0",
            function_id: str | None = None, parameters=None, inputs=None):
    body = {"version": version, "inputs": inputs or [t["type_id"] for t in types],
            "parameters": parameters if parameters is not None else [
                {"api_name": "ticket", "data_type": "object",
                 "object_type_id": types[0]["type_id"]}],
            "output": {"kind": "edits", "object_type_ids": [t["type_id"] for t in types]},
            "sql": sql}
    if function_id:
        return client.post(f"{wbase(fx)}/functions/{function_id}/versions",
                           headers=hdr(fx.editor_sub), json=body)
    return client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": body})


def backed(client, fx, tickets, types, sql: str) -> str:
    made = publish(client, fx, types, sql)
    assert made.status_code == 201, made.text
    act = action(client, fx, tickets)
    r = define(client, fx, act, [rule(made.json())])
    assert r.status_code == 200, r.text
    return act


def test_p75_closes_an_incident_and_resolves_its_alerts(client, fx, tickets, alerts) -> None:
    t, a = tickets["api_name"], alerts["api_name"]
    act = backed(client, fx, tickets, [tickets, alerts],
                 f"SELECT '{t}' AS __object_type, __primary_key, 'modify' AS __edit, "
                 f"json_object('status', 'closed') AS __properties FROM {t} "
                 "WHERE __primary_key = $ticket "
                 f"UNION ALL SELECT '{a}', __primary_key, 'modify', "
                 f"json_object('status', 'resolved') FROM {a} WHERE ticket = $ticket")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    assert held(client, fx, tickets["type_id"])["T1"]["status"] == "closed"
    assert {k: v["status"] for k, v in held(client, fx, alerts["type_id"]).items()} == {
        "A1": "resolved", "A2": "resolved", "A3": "new"}
    # Nothing it did not name: T1's other properties, and T2.
    after = held(client, fx, tickets["type_id"])
    assert (after["T1"]["title"], after["T2"]["status"]) == ("Printer jam", "open")


def test_p75_creates_an_object_of_another_type_linked_to_this_one(client, fx, tickets,
                                                                 alerts) -> None:
    """And deletes one, which §773's one-type shape could not say."""
    t, a = tickets["api_name"], alerts["api_name"]
    act = backed(client, fx, tickets, [tickets, alerts],
                 f"SELECT '{a}' AS __object_type, 'A9' AS __primary_key, 'create' AS __edit, "
                 "json_object('ticket', $ticket, 'status', 'new') AS __properties "
                 f"UNION ALL SELECT '{a}', 'A3', 'delete', NULL "
                 f"UNION ALL SELECT '{t}', 'T3', 'delete', NULL")
    r = run(client, fx, act, tickets["T2"])
    assert r.status_code == 200, r.text
    after = held(client, fx, alerts["type_id"])
    assert sorted(after) == ["A1", "A2", "A9"]
    assert (after["A9"]["ticket"], after["A9"]["status"]) == ("T2", "new")
    assert sorted(held(client, fx, tickets["type_id"])) == ["T1", "T2"]


def test_a_function_may_delete_the_object_it_runs_on(client, fx, tickets) -> None:
    t = tickets["api_name"]
    act = backed(client, fx, tickets, [tickets],
                 f"SELECT '{t}' AS __object_type, $ticket AS __primary_key, "
                 "'delete' AS __edit, NULL::JSON AS __properties")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    assert sorted(held(client, fx, tickets["type_id"])) == ["T2", "T3"]


@pytest.mark.parametrize("row, said", [
    ("'{a}', 'A1', 'create', json_object('status', 'x')",
     "creates A1, which already exists"),
    ("'{a}', 'A7', 'modify', json_object('status', 'x')",
     "modifies A7, which does not exist"),
    ("'{a}', 'A7', 'delete', NULL", "deletes A7, which does not exist"),
    ("'{t}', $ticket, 'create', json_object('title', 'x')",
     "creates T1, which already exists"),
    ("'{a}', 'A1', 'upsert', json_object('status', 'x')",
     "'upsert' is not an edit"),
    ("'{a}', 'A1', 'modify', json_object('colour', 'x')",
     "sets 'colour', which is not a property of"),
    ("'{a}', 'A1', 'modify', json_object()", "says nothing to set on A1"),
    ("'{a}', 'A1', 'delete', json_object('status', 'x')",
     "deletes A1 and sets properties on it"),
    ("'{a}', 'A1', 'modify', '[1]'::JSON", "__properties is a JSON object"),
    ("'nothing', 'A1', 'modify', json_object('status', 'x')",
     "edits nothing, which is not an object type it declares (action-types p.83)"),
])
def test_an_edit_that_cannot_be_made_fails_the_action(client, fx, tickets, alerts, row,
                                                      said) -> None:
    act = backed(client, fx, tickets, [tickets, alerts],
                 "SELECT * FROM (VALUES (" + row.format(t=tickets["api_name"],
                                                       a=alerts["api_name"])
                 + ")) AS e(__object_type, __primary_key, __edit, __properties) "
                 "WHERE $ticket IS NOT NULL")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert said in r.json()["detail"], r.text
    assert failures(client, fx, act) == {"function": 1}
    # Nothing was written.
    assert held(client, fx, alerts["type_id"])["A1"]["status"] == "new"


def test_one_object_is_edited_once(client, fx, tickets, alerts) -> None:
    a = alerts["api_name"]
    act = backed(client, fx, tickets, [tickets, alerts],
                 f"SELECT '{a}' AS __object_type, 'A1' AS __primary_key, 'modify' AS __edit, "
                 "json_object('status', 'x') AS __properties "
                 f"UNION ALL SELECT '{a}', 'A1', 'delete', NULL WHERE $ticket IS NOT NULL")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert f"edits {a} A1 twice" in r.json()["detail"]


def test_the_same_key_in_two_types_is_two_objects(client, fx, tickets, alerts) -> None:
    t, a = tickets["api_name"], alerts["api_name"]
    other = object_type(client, fx, "alert", b"key,ticket,status\nT1,T1,new\n",
                        ["key", "ticket", "status"])
    act = backed(client, fx, tickets, [tickets, other],
                 f"SELECT '{t}' AS __object_type, 'T1' AS __primary_key, 'modify' AS __edit, "
                 "json_object('status', 'closed') AS __properties "
                 f"UNION ALL SELECT '{other['api_name']}', $ticket, 'modify', "
                 "json_object('status', 'seen')")
    assert a != other["api_name"]
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    assert held(client, fx, tickets["type_id"])["T1"]["status"] == "closed"
    assert held(client, fx, other["type_id"])["T1"]["status"] == "seen"


@pytest.mark.parametrize("sql, said", [
    # Several types, and rows that do not say whose they are.
    ("SELECT __primary_key, 'x' AS status FROM {t}",
     "an edit function over several object types says each row's type"),
    ("SELECT '{t}' AS __object_type, __primary_key, 'modify' AS __edit, "
     "json_object('status', 'x') AS __properties, 1 AS extra FROM {t}",
     "an edit function over several object types says each row's type"),
    ("SELECT __primary_key AS __object_type, __primary_key, 'modify' AS __edit "
     "FROM {t}", "an edit function over several object types says each row's type"),
])
def test_a_query_without_the_typed_shape_is_refused_at_publish(client, fx, tickets, alerts,
                                                               sql, said) -> None:
    r = publish(client, fx, [tickets, alerts], sql.format(t=tickets["api_name"]),
                parameters=[])
    assert r.status_code == 422, r.text
    assert said in r.text


@pytest.mark.parametrize("ids_, said", [
    ([], "an edit output names its object types"),
    ("x", "an edit output names its object types"),
    (["a", "a"], "names an object type twice"),
])
def test_the_declared_types_are_a_list_of_distinct_types(client, fx, tickets, ids_,
                                                        said) -> None:
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [], "parameters": [],
            "output": {"kind": "edits", "object_type_ids": ids_},
            "sql": "SELECT 1 AS __object_type"}})
    assert r.status_code == 422, r.text
    assert said in r.text


def test_one_declared_type_may_use_either_shape(client, fx, tickets) -> None:
    t = tickets["api_name"]
    made = publish(client, fx, [tickets],
                   f"SELECT __primary_key, 'x' AS title FROM {t} WHERE __primary_key = $ticket")
    assert made.status_code == 201, made.text
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(made.json())]).status_code == 200
    assert run(client, fx, act, tickets["T1"]).status_code == 200
    assert held(client, fx, tickets["type_id"])["T1"]["title"] == "x"


def test_p83_a_newer_release_may_edit_fewer_types_but_not_more(client, fx, tickets,
                                                               alerts) -> None:
    t, a = tickets["api_name"], alerts["api_name"]
    third = object_type(client, fx, "note", b"key,status\nN1,new\n", ["key", "status"])
    one = (f"SELECT '{t}' AS __object_type, $ticket AS __primary_key, 'modify' AS __edit, "
           "json_object('status', '{}') AS __properties")
    made = publish(client, fx, [tickets, alerts], one.format("one"))
    assert made.status_code == 201, made.text
    fn = made.json()
    # 1.1.0 edits only the tickets: inside what 1.0.0 was set up against.
    assert publish(client, fx, [tickets], one.format("fewer"), version="1.1.0",
                   function_id=fn["id"]).status_code == 201
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(fn, auto_upgrade=True)]).status_code == 200
    assert run(client, fx, act, tickets["T1"]).status_code == 200
    assert held(client, fx, tickets["type_id"])["T1"]["status"] == "fewer"
    # 1.2.0 adds a third type: outside it.
    more = (f"SELECT '{a}' AS __object_type, 'A1' AS __primary_key, 'modify' AS __edit, "
            "json_object('status', 'more') AS __properties WHERE $ticket IS NOT NULL")
    assert publish(client, fx, [tickets, alerts, third], more, version="1.2.0",
                   function_id=fn["id"]).status_code == 201
    r = run(client, fx, act, tickets["T2"])
    assert r.status_code == 422, r.text
    assert "edits another object type than 1.0.0" in r.json()["detail"]


def test_edit_rules_make_each_verb_the_rule_that_does_it() -> None:
    rules, bound = action_functions.edit_rules(
        [{"object_type_id": "t", "primary_key": "T1", "edit": "delete", "properties": {}},
         {"object_type_id": "a", "primary_key": "A1", "edit": "delete", "properties": {}},
         {"object_type_id": "a", "primary_key": "A2", "edit": "modify",
          "properties": {"status": "x"}},
         {"object_type_id": "a", "primary_key": "A9", "edit": "create",
          "properties": {"status": "y"}}],
        subject_type_id="t", subject_key="T1",
        existing={("t", "T1"): "id-t1", ("a", "A1"): "id-a1", ("a", "A2"): "id-a2"})
    assert rules == [
        {"kind": "delete_object", "config": {}},
        {"kind": "delete_object", "config": {"object_type": "a", "object": "function.1"}},
        {"kind": "modify_object", "config": {"object": "function.2", "object_type": "a",
                                             "property": "status",
                                             "parameter": "function.2.status"}},
        {"kind": "create_object", "config": {"object_type": "a", "primary_key": "function.3",
                                             "properties": {"status": "function.3.status"}}},
    ]
    assert bound == {"function.1": "id-a1", "function.2": "id-a2", "function.2.status": "x",
                     "function.3": "A9", "function.3.status": "y"}


@pytest.mark.parametrize("edit, said", [
    ({"object_type_id": "a", "primary_key": "A1", "edit": "create", "properties": {}},
     "creates A1, which already exists"),
    ({"object_type_id": "a", "primary_key": "A7", "edit": "modify",
      "properties": {"s": 1}}, "modifies A7, which does not exist"),
    ({"object_type_id": "a", "primary_key": "A7", "edit": "delete", "properties": {}},
     "deletes A7, which does not exist"),
    ({"object_type_id": "t", "primary_key": "T1", "edit": "create", "properties": {}},
     "creates T1, which already exists"),
])
def test_edit_rules_refuse_a_verb_the_object_cannot_take(edit, said) -> None:
    with pytest.raises(FunctionError, match=said):
        action_functions.edit_rules([edit], subject_type_id="t", subject_key="T1",
                                    existing={("a", "A1"): "id-a1"})


def test_a_row_naming_no_object_is_no_edit(client, fx, tickets, alerts) -> None:
    a = alerts["api_name"]
    act = backed(client, fx, tickets, [tickets, alerts],
                 f"SELECT '{a}' AS __object_type, 'A1' AS __primary_key, 'modify' AS __edit, "
                 "json_object('status', 'seen') AS __properties "
                 f"UNION ALL SELECT '{a}', NULL, 'bogus', '[1]'::JSON WHERE $ticket IS NOT NULL")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    assert held(client, fx, alerts["type_id"])["A1"]["status"] == "seen"


def test_every_declared_type_is_one_this_workspace_has(client, fx, tickets) -> None:
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [], "parameters": [],
            "output": {"kind": "edits", "object_type_ids": [
                tickets["type_id"], "00000000-0000-0000-0000-000000000000"]},
            "sql": "SELECT 'x' AS __object_type, 'k' AS __primary_key, 'delete' AS __edit, "
                   "NULL::JSON AS __properties"}})
    assert r.status_code == 422, r.text
    assert "no object type 00000000-0000-0000-0000-000000000000" in r.text


def test_p83_a_newer_release_that_stops_returning_edits_fails(client, fx, tickets) -> None:
    t = tickets["api_name"]
    made = publish(client, fx, [tickets],
                   f"SELECT '{t}' AS __object_type, $ticket AS __primary_key, 'modify' AS __edit, "
                   "json_object('status', 'x') AS __properties")
    assert made.status_code == 201, made.text
    fn = made.json()
    r = client.post(f"{wbase(fx)}/functions/{fn['id']}/versions", headers=hdr(fx.editor_sub),
                    json={"version": "1.1.0", "inputs": [], "parameters": [
                        {"api_name": "ticket", "data_type": "object",
                         "object_type_id": tickets["type_id"]}],
                          "output": {"kind": "table"}, "sql": "SELECT $ticket AS k"})
    assert r.status_code == 201, r.text
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(fn, auto_upgrade=True)]).status_code == 200
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert "1.1.0 returns table rather than edits" in r.json()["detail"]

