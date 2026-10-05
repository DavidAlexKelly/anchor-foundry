"""Function-backed actions (§773; decision 0018 option B; `action-types`
p.22, p.75-83, p.166).

> "Function rule: Can be used to reference an Ontology edit function whose
> inputs are derived from parameters of the action. When this rule is
> present, no other rule may be configured" (p.22)

p.78's tutorial is the first test: `addPriorityToTitle`, which prefixes a
ticket's title with its priority, written as the SQL edit function this build
runs.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import action_functions  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

TICKETS = (b"key,title,priority,status,region\n"
           b"T1,Printer jam,P2,open,north\n"
           b"T2,No coffee,P1,open,north\n"
           b"T3,Broken chair,P3,closed,south\n")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("function-actions"))))
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def abase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/actions"


def object_type(client, fx, name: str, rows: bytes, properties: list[str]) -> dict:
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"{name} {tag}"},
        files={"file": (f"{name}.csv", io.BytesIO(rows), "text/csv")})
    assert dataset.status_code == 201, dataset.text
    made = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"{name}_{tag}", "display_name": f"{name} {tag}",
        "properties": [{"api_name": p, "data_type": "string"} for p in properties],
        "title_property": "key"})
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key", "column_mappings": {p: p for p in properties}})
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub))
    assert synced.status_code == 200, synced.text
    return {"type_id": type_id, "api_name": made.json()["api_name"]}


@pytest.fixture
def tickets(client, fx) -> dict:
    """A fresh set per test, because the actions below change them."""
    made = object_type(client, fx, "ticket", TICKETS,
                       ["key", "title", "priority", "status", "region"])
    return {**made, **ids(client, fx, made["type_id"])}


def ids(client, fx, type_id: str) -> dict[str, str]:
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {i["primary_key"]: i["id"] for i in items}


def held(client, fx, type_id: str) -> dict[str, dict]:
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {i["primary_key"]: i["properties"] for i in items}


def publish(client, fx, tickets, sql: str, *, version: str = "1.0.0", parameters=None,
            edits: str | None = None, function_id: str | None = None) -> dict:
    body = {"version": version, "inputs": [tickets["type_id"]],
            "parameters": parameters if parameters is not None else [
                {"api_name": "ticket", "data_type": "object",
                 "object_type_id": tickets["type_id"]}],
            "output": {"kind": "edits", "object_type_id": edits or tickets["type_id"]},
            "sql": sql}
    if function_id:
        r = client.post(f"{wbase(fx)}/functions/{function_id}/versions",
                        headers=hdr(fx.editor_sub), json=body)
    else:
        r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
            "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": body})
    assert r.status_code == 201, r.text
    return r.json()


def action(client, fx, tickets) -> str:
    made = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": tickets["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": "Act", "editable_properties": ["title"]})
    assert made.status_code == 201, made.text
    return made.json()["id"]


def define(client, fx, action_id: str, rules: list[dict], parameters=None):
    return client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters or [], "rules": rules, "criteria": []})


def rule(fn: dict, version: str = "1.0.0", inputs=None, auto_upgrade: bool = False) -> dict:
    return {"kind": "function", "config": {
        "function_id": fn["id"], "version": version, "auto_upgrade": auto_upgrade,
        "inputs": inputs if inputs is not None else {"ticket": {"subject": True}}}}


def run(client, fx, action_id: str, instance_id: str, values=None):
    return client.post(f"{abase(fx)}/{action_id}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance_id, "values": values or {}})


def failures(client, fx, action_id: str) -> dict[str, int]:
    r = client.get(f"{wbase(fx)}/action-types/{action_id}/metrics", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {f["category"]: f["failures"] for f in r.json()["failures"]}


def functionally(client, fx, tickets, sql: str, **kw) -> tuple[str, dict]:
    fn = publish(client, fx, tickets, sql, **kw.pop("publish", {}))
    act = action(client, fx, tickets)
    r = define(client, fx, act, [rule(fn, **kw.pop("rule", {}))], **kw)
    assert r.status_code == 200, r.text
    return act, fn


def test_p78_add_priority_to_title(client, fx, tickets) -> None:
    t = tickets["api_name"]
    act, _fn = functionally(client, fx, tickets,
                            f"SELECT __primary_key, '[' || priority || '] ' || title AS title "
                            f"FROM {t} WHERE __primary_key = $ticket")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    after = held(client, fx, tickets["type_id"])
    assert after["T1"]["title"] == "[P2] Printer jam"
    # Nothing else was touched.
    assert after["T2"]["title"] == "No coffee"


def test_edits_to_other_objects_and_a_new_one(client, fx, tickets) -> None:
    """p.75's "Modify multiple objects" and "Create several … objects": every
    open ticket of the subject's region is closed, and a follow-up opened."""
    t = tickets["api_name"]
    act, _fn = functionally(
        client, fx, tickets,
        f"SELECT __primary_key, 'closed' AS status, region FROM {t} "
        f"WHERE region = (SELECT region FROM {t} WHERE __primary_key = $ticket) "
        "AND status = 'open' "
        "UNION ALL SELECT 'T9' || $suffix, 'open', 'north'",
        publish={"parameters": [
            {"api_name": "ticket", "data_type": "object", "object_type_id": tickets["type_id"]},
            {"api_name": "suffix", "data_type": "string"}]},
        rule={"inputs": {"ticket": {"subject": True}, "suffix": {"parameter": "suffix"}}},
        parameters=[{"api_name": "suffix", "display_name": "Suffix", "data_type": "string"}])
    r = run(client, fx, act, tickets["T1"], {"suffix": "a"})
    assert r.status_code == 200, r.text
    after = held(client, fx, tickets["type_id"])
    assert {k: v["status"] for k, v in after.items()} == {
        "T1": "closed", "T2": "closed", "T3": "closed", "T9a": "open"}
    assert after["T9a"]["region"] == "north"
    # One run, as any action's, which its history and its undo read.
    runs = client.get(f"{wbase(fx)}/action-types/{act}/runs", headers=hdr(fx.editor_sub))
    assert runs.status_code == 200, runs.text
    assert runs.json()[0]["status"] == "succeeded"


def test_a_fixed_value_and_a_parameter_feed_the_function(client, fx, tickets) -> None:
    t = tickets["api_name"]
    act, _fn = functionally(
        client, fx, tickets,
        f"SELECT __primary_key, $word || ': ' || $note AS title FROM {t} "
        "WHERE __primary_key = $ticket",
        publish={"parameters": [
            {"api_name": "ticket", "data_type": "object", "object_type_id": tickets["type_id"]},
            {"api_name": "word", "data_type": "string"},
            {"api_name": "note", "data_type": "string"}]},
        rule={"inputs": {"ticket": {"parameter": "which"}, "word": {"value": "Seen"},
                         "note": {"parameter": "note"}}},
        parameters=[{"api_name": "which", "display_name": "Which", "data_type": "object",
                     "object_type_id": tickets["type_id"]},
                    {"api_name": "note", "display_name": "Note", "data_type": "string"}])
    # Run on T1, editing the ticket a parameter names.
    r = run(client, fx, act, tickets["T1"], {"which": tickets["T2"], "note": "ok"})
    assert r.status_code == 200, r.text
    after = held(client, fx, tickets["type_id"])
    assert (after["T1"]["title"], after["T2"]["title"]) == ("Printer jam", "Seen: ok")


def test_the_version_run_is_the_pinned_one_or_p81_s_range(client, fx, tickets) -> None:
    t = tickets["api_name"]
    sql = f"SELECT __primary_key, '{{}}' AS title FROM {t} WHERE __primary_key = $ticket"
    fn = publish(client, fx, tickets, sql.format("one"))
    publish(client, fx, tickets, sql.replace("{}", "one-one"), version="1.1.0",
            function_id=fn["id"])
    publish(client, fx, tickets, sql.replace("{}", "rc"), version="1.2.0-rc.1",
            function_id=fn["id"])
    publish(client, fx, tickets, sql.replace("{}", "two"), version="2.0.0",
            function_id=fn["id"])
    pinned, ranged = action(client, fx, tickets), action(client, fx, tickets)
    assert define(client, fx, pinned, [rule(fn)]).status_code == 200
    assert define(client, fx, ranged, [rule(fn, auto_upgrade=True)]).status_code == 200
    assert run(client, fx, pinned, tickets["T1"]).status_code == 200
    assert run(client, fx, ranged, tickets["T2"]).status_code == 200
    after = held(client, fx, tickets["type_id"])
    # Not 2.0.0, a breaking change; not 1.2.0-rc.1, not a release.
    assert (after["T1"]["title"], after["T2"]["title"]) == ("one", "one-one")


def test_a_newer_release_editing_another_type_fails_the_action(client, fx, tickets) -> None:
    """p.83: "If a newer release of the function returns edits outside of this
    provenance (for example, an additional object type), action execution
    will fail." Counted as p.166's function failure."""
    t = tickets["api_name"]
    other = object_type(client, fx, "alert", b"key,status\nA1,new\n", ["key", "status"])
    fn = publish(client, fx, tickets,
                 f"SELECT __primary_key, 'x' AS title FROM {t} WHERE __primary_key = $ticket")
    publish(client, fx, tickets, "SELECT 'A1' AS k, 'seen' AS status", version="1.1.0",
            function_id=fn["id"], edits=other["type_id"], parameters=[])
    act = action(client, fx, tickets)
    assert define(client, fx, act, [rule(fn, auto_upgrade=True)]).status_code == 200
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert "edits another object type than 1.0.0" in r.text
    assert failures(client, fx, act) == {"function": 1}


def test_the_querys_own_error_is_said_to_the_user(client, fx, tickets) -> None:
    """p.166's user-facing function failure: "threw an error intended to be
    displayed to the user"."""
    t = tickets["api_name"]
    act, _fn = functionally(
        client, fx, tickets,
        f"SELECT __primary_key, CASE WHEN status = 'closed' THEN error('That ticket is closed') "
        f"ELSE 'closed' END AS status FROM {t} WHERE __primary_key = $ticket")
    r = run(client, fx, act, tickets["T3"])
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "That ticket is closed"
    assert run(client, fx, act, tickets["T1"]).status_code == 200
    assert failures(client, fx, act) == {"user_facing_function": 1}


def test_a_function_that_fails_otherwise_is_a_function_failure(client, fx, tickets) -> None:
    t = tickets["api_name"]
    act, fn = functionally(client, fx, tickets,
                           f"SELECT __primary_key, 'x' AS title FROM {t} "
                           "WHERE __primary_key = $ticket AND false")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert "made no edits" in r.text
    assert client.delete(f"{wbase(fx)}/functions/{fn['id']}",
                         headers=hdr(fx.editor_sub)).status_code == 204
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert "the function this action calls is not here" in r.text
    assert failures(client, fx, act) == {"function": 2}


def test_an_edit_the_object_type_refuses_is_refused_as_a_rule_would_be(client, fx, tickets):
    """The edits run through the executor's own checks: a key column is not
    a property an action may write (p.62)."""
    t = tickets["api_name"]
    act, _fn = functionally(client, fx, tickets,
                            f"SELECT __primary_key, 'T7' AS key FROM {t} "
                            "WHERE __primary_key = $ticket")
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 422, r.text
    assert "primary key" in r.text


@pytest.mark.parametrize("rules,parameters,said", [
    (lambda fn: [rule(fn), {"kind": "modify_object", "config": {
        "property": "title", "parameter": "p"}}],
     [{"api_name": "p", "display_name": "P", "data_type": "string"}],
     "cannot be combined with other rules (modify_object)"),
    (lambda fn: [rule(fn), rule(fn)], [], "has two Function rules"),
    (lambda fn: [rule(fn, version="9.9.9")], [], "has no version 9.9.9"),
    (lambda fn: [{"kind": "function", "config": {"function_id": str(uuid.uuid4()),
                                                 "version": "1.0.0", "inputs": {}}}],
     [], "names a function this workspace does not have"),
    (lambda fn: [rule(fn, inputs={})], [], "needs ticket, which the rule does not supply"),
    (lambda fn: [rule(fn, inputs={"ticket": {"parameter": "gone"}})], [],
     "reads gone, which is not a parameter"),
    (lambda fn: [rule(fn, inputs={"ticket": {"subject": True}, "nope": {"value": 1}})], [],
     "takes no parameter nope"),
    (lambda fn: [rule(fn, inputs={"ticket": {"subject": True, "value": 1}})], [],
     "comes from a parameter, a value or this object"),
    (lambda fn: [rule(fn, inputs={"ticket": {"subject": "yes"}})], [],
     "cannot be the object the action is run on"),
    (lambda fn: [rule(fn, inputs={"ticket": {"subject": True},
                                  "other": {"subject": True}})], [],
     "other is not an object of this action's type"),
    (lambda fn: [rule(fn, inputs={"ticket": "T1"})], [],
     "comes from a parameter, a value or this object"),
    (lambda fn: [{**rule(fn), "config": {**rule(fn)["config"], "inputs": []}}], [],
     "inputs are an object"),
    (lambda fn: [{**rule(fn), "config": {**rule(fn)["config"], "auto_upgrade": "yes"}}], [],
     "auto_upgrade is true or false"),
])
def test_a_rule_that_could_not_run_is_refused_at_save(client, fx, tickets, rules, parameters,
                                                      said) -> None:
    t = tickets["api_name"]
    other = object_type(client, fx, "site", b"key\nS1\n", ["key"])
    fn = publish(client, fx, tickets,
                 f"SELECT __primary_key, 'x' AS title FROM {t} "
                 "WHERE __primary_key = $ticket OR $other = 'never'",
                 parameters=[
                     {"api_name": "ticket", "data_type": "object",
                      "object_type_id": tickets["type_id"]},
                     {"api_name": "other", "data_type": "object", "required": False,
                      "object_type_id": other["type_id"]}])
    r = define(client, fx, action(client, fx, tickets), rules(fn), parameters)
    assert r.status_code == 422, r.text
    assert said in r.text


def test_a_side_effect_may_sit_beside_it() -> None:
    """p.22's "no other rule" is the Ontology rules: a notification or a
    webhook is a side effect (p.87), not an edit."""
    action_functions.check_rules([{"kind": "function"}, {"kind": "notify"},
                                  {"kind": "webhook"}])
    action_functions.check_rules([{"kind": "modify_object"}, {"kind": "create_object"}])


def test_a_zero_version_cannot_auto_upgrade(client, fx, tickets) -> None:
    t = tickets["api_name"]
    fn = publish(client, fx, tickets,
                 f"SELECT __primary_key, 'x' AS title FROM {t} WHERE __primary_key = $ticket",
                 version="0.3.0")
    act = action(client, fx, tickets)
    r = define(client, fx, act, [rule(fn, version="0.3.0", auto_upgrade=True)])
    assert r.status_code == 422, r.text
    assert "0.y.z" in r.text
    assert define(client, fx, act, [rule(fn, version="0.3.0")]).status_code == 200


def test_a_function_that_is_not_an_edit_function_is_refused(client, fx, tickets) -> None:
    t = tickets["api_name"]
    r = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [tickets["type_id"]], "parameters": [],
            "output": {"kind": "value", "data_type": "integer"},
            "sql": f"SELECT count(*) FROM {t}"}})
    assert r.status_code == 201, r.text
    got = define(client, fx, action(client, fx, tickets), [rule(r.json(), inputs={})])
    assert got.status_code == 422, got.text
    assert "is not an edit function: it returns value" in got.text


# ---- the pure halves ---------------------------------------------------------

def versions(*names: str) -> dict:
    return {"versions": [{"version": n, "output": {"kind": "edits"}} for n in names]}


@pytest.mark.parametrize("pinned,auto,expected", [
    ("1.1.0", False, "1.1.0"),
    ("1.1.0", True, "1.2.1"),
    ("1.2.1", True, "1.2.1"),
    ("0.3.0", True, "0.3.0"),
    ("1.3.0-rc.1", True, "1.3.0-rc.1"),
    ("9.0.0", True, None),
])
def test_resolve_version(pinned, auto, expected) -> None:
    fn = versions("2.0.0", "1.3.0-rc.1", "1.2.1", "1.2.0", "1.1.0", "0.4.0", "0.3.0")
    got = action_functions.resolve_version(fn, {"version": pinned, "auto_upgrade": auto})
    assert (got or {}).get("version") == expected


def test_a_prerelease_floor_upgrades_to_the_release_above_it() -> None:
    fn = versions("1.3.0", "1.3.0-rc.1", "1.2.0")
    got = action_functions.resolve_version(fn, {"version": "1.3.0-rc.1", "auto_upgrade": True})
    assert got["version"] == "1.3.0"


def test_edit_rules_split_the_subject_the_existing_and_the_new() -> None:
    rules, bound = action_functions.edit_rules(
        [{"primary_key": "T1", "properties": {"title": "a"}},
         {"primary_key": "T2", "properties": {"title": "b", "status": None}},
         {"primary_key": "T9", "properties": {"title": "c"}}],
        object_type_id="t", subject_type_id="t", subject_key="T1",
        existing={"T1": "id1", "T2": "id2"})
    assert rules == [
        {"kind": "modify_object", "config": {"property": "title", "parameter": "function.0.title"}},
        {"kind": "modify_object", "config": {"object": "function.1", "object_type": "t",
                                             "property": "title",
                                             "parameter": "function.1.title"}},
        {"kind": "modify_object", "config": {"object": "function.1", "object_type": "t",
                                             "property": "status",
                                             "parameter": "function.1.status"}},
        {"kind": "create_object", "config": {"object_type": "t", "primary_key": "function.2",
                                             "properties": {"title": "function.2.title"}}},
    ]
    assert bound == {"function.0.title": "a", "function.1.title": "b",
                     "function.1.status": None, "function.1": "id2",
                     "function.2.title": "c", "function.2": "T9"}


def test_edit_rules_of_another_type_never_touch_the_subject() -> None:
    rules, _bound = action_functions.edit_rules(
        [{"primary_key": "T1", "properties": {"status": "x"}}],
        object_type_id="alerts", subject_type_id="t", subject_key="T1",
        existing={"T1": "a1"})
    assert rules[0]["config"]["object"] == "function.0"


def test_the_action_log_links_every_object_the_function_edited(client, fx, tickets) -> None:
    """p.168: "To configure the action log for a function-backed action type,
    the backing Ontology edit function must have Edits provenance configured" -
    here the edits output's object type. The entry is the ordinary one: it
    links the subject and the other ticket the function edited."""
    import json

    t = tickets["api_name"]
    act, _fn = functionally(client, fx, tickets,
                            f"SELECT __primary_key, 'closed' AS status FROM {t} "
                            f"WHERE region = (SELECT region FROM {t} "
                            "WHERE __primary_key = $ticket) ORDER BY 1")
    made = client.post(f"{abase(fx)}/{act}/log", headers=hdr(fx.editor_sub))
    assert made.status_code == 201, made.text
    r = run(client, fx, act, tickets["T1"])
    assert r.status_code == 200, r.text
    entries = held(client, fx, made.json()["log_object_type_id"])
    entry = entries[r.json()["run_id"]]
    assert sorted(json.loads(entry["edited_objects"])) == ["T1", "T2"]
