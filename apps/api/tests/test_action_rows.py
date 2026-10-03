"""An Action table's rows as one batch call (§800; workshop p.512,
`action-types` p.84 and p.131).

> "When an action is triggered in batches, such as in Workshop inline edits
> or in Automate, the backing function is usually called once per request in
> sequence, and all edits are applied atomically at the end of the action
> call." (`action-types` p.84)

> "Also note that batch call limits apply to the table layout, as well as the
> requirement that edits do not conflict." (workshop p.512)

`execute-batch` takes an inline edit, which changes only its own row. These
are the actions it cannot take - a create, a delete - sent a row each and
written as one: every row or none, one version per dataset, and each row its
own run with its own undo. The people are `test_action_undo_effects.py`'s.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_action_undo_effects import (  # noqa: E402,F401
    ADMIN_DSN, _fresh_identity_cache, client, define, fx, hdr, keys, pbase, undo_run,
    wbase, world,
)

REFER = (
    [{"api_name": "email", "display_name": "Email", "data_type": "string"},
     {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
     {"api_name": "new_name", "display_name": "Name", "data_type": "string"}],
    [{"kind": "modify_object", "config": {"property": "email", "parameter": "email"}},
     {"kind": "create_object", "config": {
         "primary_key": "new_key", "properties": {"name": "new_name"}}}],
)


def rows(client, fx, action_id: str, sent: list[tuple[str, dict]]):
    return client.post(f"{pbase(fx)}/actions/{action_id}/execute-rows",
                       headers=hdr(fx.editor_sub),
                       json={"rows": [{"instance_id": i, "values": v} for i, v in sent],
                             "application": "workshop"})


def workshop_writes(world) -> int:
    import psycopg

    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute(
            "SELECT coalesce(sum(writes), 0) FROM object_type_usage "
            "WHERE object_type_id = %s AND application = 'workshop'",
            (world["type_id"],)).fetchone()[0]


def version(client, fx, world) -> int:
    r = client.get(f"{pbase(fx)}/datasets/{world['dataset_id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()["current_version"]


def test_rows_that_create_land_as_one_version_each_its_own_run(client, fx, world) -> None:
    refer = define(client, fx, world, "refer_rows", *REFER)
    people = keys(client, fx, world)
    before = version(client, fx, world)
    writes = workshop_writes(world)
    r = rows(client, fx, refer, [
        (people["p1"]["id"], {"email": "ada@rows.test", "new_key": "r1", "new_name": "One"}),
        (people["p2"]["id"], {"email": "grace@rows.test", "new_key": "r2", "new_name": "Two"}),
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["error"] is None, body
    # p.84's "applied atomically at the end": one commit, one version.
    assert version(client, fx, world) == before + 1
    after = keys(client, fx, world)
    assert after["r1"]["properties"]["name"] == "One"
    assert after["r2"]["properties"]["name"] == "Two"
    assert after["p1"]["properties"]["email"] == "ada@rows.test"
    assert after["p2"]["properties"]["email"] == "grace@rows.test"

    first, second = body["results"]
    assert first["run_id"] != second["run_id"]
    # Both runs are the batch's, and so is the version they wrote - not
    # either run's alone (db 0063) - and the submission is audited once.
    runs = client.get(f"{wbase(fx)}/action-types/{refer}/runs", headers=hdr(fx.editor_sub))
    assert runs.status_code == 200, runs.text
    assert {r["batch_id"] for r in runs.json()} == {body["batch_id"]}
    import psycopg

    with psycopg.connect(ADMIN_DSN) as conn:
        assert conn.execute(
            "SELECT produced_by_kind, produced_by_id::text FROM dataset_versions "
            "WHERE dataset_id = %s ORDER BY version_number DESC LIMIT 1",
            (world["dataset_id"],)).fetchone() == ("action_batch", body["batch_id"])
        assert conn.execute(
            "SELECT action, count(*) FROM audit_log WHERE resource_id = %s "
            "AND action LIKE 'action.execute%%' GROUP BY action",
            (refer,)).fetchall() == [("action.execute_rows", 1)]
    # And p.32's write is counted once for it too.
    assert workshop_writes(world) == writes + 1
    assert first["instance"]["primary_key"] == "p1" and second["instance"]["primary_key"] == "p2"
    assert {(t["primary_key"], t["change"]) for t in first["touched"]} == {
        ("p1", "modified"), ("r1", "created")}
    assert {(t["primary_key"], t["change"]) for t in second["touched"]} == {
        ("p2", "modified"), ("r2", "created")}

    # Each row is its own run, and undoing one leaves the other.
    assert second["can_undo"] is True, second
    undone = undo_run(client, fx, refer, second["run_id"])
    assert undone.status_code == 200, undone.text
    after = keys(client, fx, world)
    assert "r2" not in after and after["p2"]["properties"]["email"] == "grace@example.com"
    assert "r1" in after and after["p1"]["properties"]["email"] == "ada@rows.test"


def test_a_refused_row_refuses_every_row(client, fx, world) -> None:
    refer = define(client, fx, world, "refer_refused", *REFER)
    people = keys(client, fx, world)
    before = version(client, fx, world)
    r = rows(client, fx, refer, [
        (people["p3"]["id"], {"email": "alan@rows.test", "new_key": "r3", "new_name": "Three"}),
        # No key for the object it creates.
        (people["p4"]["id"], {"email": "hedy@rows.test", "new_name": "Four"}),
    ])
    assert r.status_code == 422, r.text
    assert version(client, fx, world) == before
    after = keys(client, fx, world)
    assert "r3" not in after and after["p3"]["properties"]["email"] == "alan@example.com"


def test_two_rows_editing_one_object_conflict(client, fx, world) -> None:
    refer = define(client, fx, world, "refer_conflict", *REFER)
    people = keys(client, fx, world)
    before = version(client, fx, world)
    r = rows(client, fx, refer, [
        (people["p3"]["id"], {"email": "a@rows.test", "new_key": "c1", "new_name": "C1"}),
        (people["p4"]["id"], {"email": "b@rows.test", "new_key": "c2", "new_name": "C2"}),
        (people["p3"]["id"], {"email": "c@rows.test", "new_key": "c3", "new_name": "C3"}),
    ])
    assert r.status_code == 422, r.text
    assert "rows 1 and 3 both edit the object p3" in r.json()["detail"], r.text
    # Creating one key twice is the same conflict.
    r = rows(client, fx, refer, [
        (people["p3"]["id"], {"email": "a@rows.test", "new_key": "same", "new_name": "A"}),
        (people["p4"]["id"], {"email": "b@rows.test", "new_key": "same", "new_name": "B"}),
    ])
    assert r.status_code == 422, r.text
    assert "both edit the object same" in r.json()["detail"], r.text
    assert version(client, fx, world) == before
    assert not {"c1", "c2", "c3", "same"} & set(keys(client, fx, world))


def test_two_rows_deleting_one_object_conflict(client, fx, world) -> None:
    """A delete is an edit of its object as much as a change is: the delete
    rule's object is named by a parameter, so two rows can name one."""
    retire = define(client, fx, world, "retire_rows", [
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["type_id"]}],
        [{"kind": "delete_object", "config": {"object_type": world["type_id"], "object": "who"}}])
    people = keys(client, fx, world)
    before = version(client, fx, world)
    r = rows(client, fx, retire, [(people["p3"]["id"], {"who": people["p4"]["id"]}),
                                  (people["p1"]["id"], {"who": people["p4"]["id"]})])
    assert r.status_code == 422, r.text
    assert "rows 1 and 2 both edit the object p4" in r.json()["detail"], r.text
    assert version(client, fx, world) == before and "p4" in keys(client, fx, world)


def test_rows_that_delete_go_together_and_come_back_one_by_one(client, fx, world) -> None:
    refer = define(client, fx, world, "refer_for_delete", *REFER)
    people = keys(client, fx, world)
    made = rows(client, fx, refer, [
        (people["p3"]["id"], {"email": "alan@example.com", "new_key": "d1", "new_name": "D1"}),
        (people["p4"]["id"], {"email": "hedy@example.com", "new_key": "d2", "new_name": "D2"}),
    ])
    assert made.status_code == 200 and made.json()["ok"], made.text
    remove = define(client, fx, world, "remove_rows", [],
                    [{"kind": "delete_object", "config": {}}])
    people = keys(client, fx, world)
    before = version(client, fx, world)
    r = rows(client, fx, remove, [(people["d1"]["id"], {}), (people["d2"]["id"], {})])
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert version(client, fx, world) == before + 1
    assert not {"d1", "d2"} & set(keys(client, fx, world))
    undone = undo_run(client, fx, remove, r.json()["results"][0]["run_id"])
    assert undone.status_code == 200, undone.text
    assert "d1" in keys(client, fx, world) and "d2" not in keys(client, fx, world)


def test_a_batch_that_fails_to_write_reports_no_results(client, fx, world) -> None:
    """A write failure is `ok: false` with every run closed failed - and no
    row's answer, since none of them happened."""
    from src.routes import actions as routes

    refer = define(client, fx, world, "refer_fails", *REFER)
    people = keys(client, fx, world)
    real = routes._commit_rows

    async def broken(*args, **kwargs):
        raise routes.DatasetEngineError("the disk is full")

    routes._commit_rows = broken
    try:
        r = rows(client, fx, refer, [
            (people["p3"]["id"], {"email": "x@rows.test", "new_key": "f1", "new_name": "F"})])
    finally:
        routes._commit_rows = real
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["error"] == "the disk is full"
    assert r.json()["results"] == []
    assert "f1" not in keys(client, fx, world)
