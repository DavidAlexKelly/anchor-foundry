"""An action's link rules on a join table (§553; `action-types` p.20).

    "Create link(s): Can be used to create a many-to-many link between objects
     that are passed via object reference parameters. … Delete link: Can be
     used to delete a many-to-many link between objects that are passed via
     object reference parameters." (p.20)

§552 gave a many-to-many link a join table to be followed through; this lets
an action write one. The flights and aircraft are §552's, with the aircraft
keys held as integers in the join table - so a pair is written into the
column's own type, and read back as text like every other key.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_link_join_tables import (  # noqa: E402
    PAIRS, links_of, object_type, upload, wbase, pbase, instance,
)
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    aircraft = object_type(client, fx, f"aircraft_{tag}",
                           b"id,tail\n1,G-AAAA\n2,G-BBBB\n3,G-CCCC\n", ["tail"])
    flights = object_type(client, fx, f"flight_{tag}",
                          b"id,route\nF1,LHR-JFK\nF2,JFK-SFO\nF3,SFO-LHR\nF4,LHR-CDG\n",
                          ["route"])
    pairs = upload(client, fx, f"flown_{tag}", PAIRS)
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"flown_by_{tag}", "display_name": "Flown by",
        "from_type_id": flights, "to_type_id": aircraft, "cardinality": "many_to_many",
        "join_dataset_id": pairs, "join_from_column": "flight",
        "join_to_column": "aircraft",
    })
    assert r.status_code == 201, r.text
    return {"aircraft": aircraft, "flights": flights, "pairs": pairs, "link": r.json()["id"]}


def action(client, fx, world, on: str, kind: str, other: str, name: str | None = None,
           config: dict | None = None):
    """An action on `on`'s type whose one rule links (or unlinks) the object a
    parameter names, of `other`'s type."""
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world[on], "api_name": name or f"a_{uuid.uuid4().hex[:6]}",
        # The definition below replaces this, but creating one needs a property.
        "display_name": "Link", "editable_properties": [
            "route" if on == "flights" else "tail"]})
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{action_id}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [{"api_name": "other", "display_name": "Other",
                                       "data_type": "object", "object_type_id": world[other]}],
                       "rules": [{"kind": kind, "config": config if config is not None else {
                           "link_type": world["link"], "object": "other"}}],
                       "criteria": []})
    return action_id, r


def run(client, fx, world, action_id: str, on: str, key: str, other: str, other_key: str):
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": instance(client, fx, world[on], key)["id"],
                          "values": {"other": instance(client, fx, world[other], other_key)["id"]}})
    return r


def linked(client, fx, world, key: str) -> list[str]:
    group = links_of(client, fx, world["flights"], key)[world["link"]]
    return sorted(i["primary_key"] for i in group["items"])


def last_type(world) -> str:
    """The join table's newest version's transaction type (§747)."""
    import psycopg

    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN) as conn:
        return conn.execute(
            "SELECT transaction_type FROM dataset_versions WHERE dataset_id = %s "
            "ORDER BY version_number DESC LIMIT 1", (world["pairs"],)).fetchone()[0]


def version_of(client, fx, world) -> int:
    r = client.get(f"{pbase(fx)}/datasets/{world['pairs']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()["current_version"]


# ---- defining one ------------------------------------------------------------

def test_a_join_table_rule_names_the_object_to_link(client, fx, world) -> None:
    _id, r = action(client, fx, world, "flights", "create_link", "aircraft",
                    config={"link_type": world["link"]})
    assert r.status_code == 422 and "needs an `object`" in r.json()["detail"], r.text
    _id, r = action(client, fx, world, "flights", "create_link", "aircraft",
                    config={"link_type": world["link"], "object": "nobody"})
    assert r.status_code == 422 and "not a parameter" in r.json()["detail"], r.text


def test_a_many_to_many_link_with_no_join_table_is_still_refused(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"bare_{uuid.uuid4().hex[:6]}", "display_name": "Bare",
        "from_type_id": world["flights"], "to_type_id": world["aircraft"],
        "cardinality": "many_to_many", "from_property": "route", "to_property": "tail"})
    assert r.status_code == 201, r.text
    _id, r = action(client, fx, world, "flights", "create_link", "aircraft",
                    config={"link_type": r.json()["id"], "object": "other"})
    assert r.status_code == 422, r.text
    assert "set through its join table, and this one has none" in r.json()["detail"]


# ---- applying and undoing ----------------------------------------------------

def test_a_create_link_rule_writes_the_pair(client, fx, world) -> None:
    link_it, r = action(client, fx, world, "flights", "create_link", "aircraft")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F4") == []
    r = run(client, fx, world, link_it, "flights", "F4", "aircraft", "3")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert linked(client, fx, world, "F4") == ["3"]
    # A pair added and none removed: the table only grew (§747).
    assert last_type(world) == "APPEND"
    # Written as the column's own integer, and read back as a key: the
    # aircraft sees the flight too.
    group = links_of(client, fx, world["aircraft"], "3")[world["link"]]
    assert [i["primary_key"] for i in group["items"]] == ["F4"]

    # A link already there is not made twice, and a version that changes
    # nothing is not recorded.
    before = version_of(client, fx, world)
    r = run(client, fx, world, link_it, "flights", "F4", "aircraft", "3")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert version_of(client, fx, world) == before
    assert linked(client, fx, world, "F4") == ["3"]


def test_a_rule_from_the_other_end_writes_the_same_pair(client, fx, world) -> None:
    """The subject is the join table's `to` end here: the aircraft links a
    flight, and the pair still goes in as flight, aircraft."""
    link_it, r = action(client, fx, world, "aircraft", "create_link", "flights")
    assert r.status_code == 200, r.text
    r = run(client, fx, world, link_it, "aircraft", "3", "flights", "F1")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert linked(client, fx, world, "F1") == ["1", "3"]


def test_a_delete_link_rule_removes_the_pair_and_its_undo_puts_it_back(
    client, fx, world
) -> None:
    unlink, r = action(client, fx, world, "flights", "delete_link", "aircraft")
    assert r.status_code == 200, r.text
    assert linked(client, fx, world, "F2") == ["1", "2"]
    r = run(client, fx, world, unlink, "flights", "F2", "aircraft", "2")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert linked(client, fx, world, "F2") == ["1"]
    assert last_type(world) == "UPDATE"
    assert r.json()["can_undo"] is True, r.json()
    undone = client.post(f"{pbase(fx)}/actions/{unlink}/runs/{r.json()['run_id']}/undo",
                         headers=hdr(fx.editor_sub))
    assert undone.status_code == 200, undone.text
    assert linked(client, fx, world, "F2") == ["1", "2"]
    # The undo only puts a pair back.
    assert last_type(world) == "APPEND"


def test_undoing_a_link_made_removes_it(client, fx, world) -> None:
    link_it, _ = action(client, fx, world, "flights", "create_link", "aircraft")
    r = run(client, fx, world, link_it, "flights", "F3", "aircraft", "1")
    assert linked(client, fx, world, "F3") == ["1", "2"]
    undone = client.post(f"{pbase(fx)}/actions/{link_it}/runs/{r.json()['run_id']}/undo",
                         headers=hdr(fx.editor_sub))
    assert undone.status_code == 200, undone.text
    assert linked(client, fx, world, "F3") == ["2"]


def test_a_link_removed_since_takes_the_undo_away(client, fx, world) -> None:
    """p.156's rule for a link: the one the run made has been removed by a
    later action, so there is nothing of it to put back."""
    link_it, _ = action(client, fx, world, "flights", "create_link", "aircraft")
    unlink, _ = action(client, fx, world, "flights", "delete_link", "aircraft")
    made = run(client, fx, world, link_it, "flights", "F4", "aircraft", "1")
    run(client, fx, world, unlink, "flights", "F4", "aircraft", "1")
    r = client.post(f"{pbase(fx)}/actions/{link_it}/runs/{made.json()['run_id']}/undo",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 409 and "has been removed since" in r.json()["detail"], r.text


def test_a_link_made_again_since_takes_the_undo_of_its_removal_away(
    client, fx, world
) -> None:
    link_it, _ = action(client, fx, world, "flights", "create_link", "aircraft")
    unlink, _ = action(client, fx, world, "flights", "delete_link", "aircraft")
    gone = run(client, fx, world, unlink, "flights", "F1", "aircraft", "1")
    assert linked(client, fx, world, "F1") == ["3"]
    run(client, fx, world, link_it, "flights", "F1", "aircraft", "1")
    r = client.post(f"{pbase(fx)}/actions/{unlink}/runs/{gone.json()['run_id']}/undo",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 409 and "made again since" in r.json()["detail"], r.text


def test_a_key_the_join_table_cannot_hold_fails_the_run(client, fx, world) -> None:
    """A link whose aircraft column is an integer cannot take a flight's key
    the wrong way round - here, a self-link over flights using that table."""
    r = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"self_{uuid.uuid4().hex[:6]}", "display_name": "Self",
        "from_type_id": world["flights"], "to_type_id": world["flights"],
        "cardinality": "many_to_many", "join_dataset_id": world["pairs"],
        "join_from_column": "flight", "join_to_column": "aircraft"})
    assert r.status_code == 201, r.text
    link_it, made = action(client, fx, world, "flights", "create_link", "flights",
                           config={"link_type": r.json()["id"], "object": "other"})
    assert made.status_code == 200, made.text
    r = run(client, fx, world, link_it, "flights", "F1", "flights", "F2")
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and "could not add a link" in r.json()["error"], r.text


def test_a_link_whose_join_table_was_deleted_cannot_be_set(client, fx, world) -> None:
    spare = upload(client, fx, f"spare_{uuid.uuid4().hex[:6]}", PAIRS)
    made = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"spare_{uuid.uuid4().hex[:6]}", "display_name": "Spare",
        "from_type_id": world["flights"], "to_type_id": world["aircraft"],
        "cardinality": "many_to_many", "join_dataset_id": spare,
        "join_from_column": "flight", "join_to_column": "aircraft"}).json()
    assert client.delete(f"{pbase(fx)}/datasets/{spare}",
                         headers=hdr(fx.editor_sub)).status_code == 204
    _id, r = action(client, fx, world, "flights", "create_link", "aircraft",
                    config={"link_type": made["id"], "object": "other"})
    assert r.status_code == 422 and "join table has been deleted" in r.json()["detail"], r.text


def test_linking_an_object_of_the_wrong_type_is_not_found(client, fx, world) -> None:
    """The parameter holds a flight where the link's other end is an aircraft:
    there is no aircraft by that id to link."""
    link_it, r = action(client, fx, world, "flights", "create_link", "flights",
                        config={"link_type": world["link"], "object": "other"})
    assert r.status_code == 200, r.text
    r = run(client, fx, world, link_it, "flights", "F1", "flights", "F2")
    assert r.status_code == 404, r.text


def test_two_links_on_one_table_joined_two_ways_are_refused(client, fx, world) -> None:
    """One file cannot be written with its columns read two ways at once."""
    backwards = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"back_{uuid.uuid4().hex[:6]}", "display_name": "Back",
        "from_type_id": world["aircraft"], "to_type_id": world["flights"],
        "cardinality": "many_to_many", "join_dataset_id": world["pairs"],
        "join_from_column": "aircraft", "join_to_column": "flight"}).json()
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["flights"], "api_name": f"both_{uuid.uuid4().hex[:6]}",
        "display_name": "Both", "editable_properties": ["route"]})
    both = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{both}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [{"api_name": "other", "display_name": "Other",
                                         "data_type": "object",
                                         "object_type_id": world["aircraft"]}],
                         "rules": [{"kind": "create_link", "config": {
                                        "link_type": world["link"], "object": "other"}},
                                   {"kind": "create_link", "config": {
                                        "link_type": backwards["id"], "object": "other"}}],
                         "criteria": []})
    assert r.status_code == 200, r.text
    r = run(client, fx, world, both, "flights", "F3", "aircraft", "3")
    assert r.status_code == 422 and "on different columns" in r.json()["detail"], r.text


def test_removing_and_remaking_a_link_in_one_write_leaves_it_made(tmp_path) -> None:
    import duckdb
    from src.services import dataset_engine as engine
    path, dest = str(tmp_path / "in.parquet"), str(tmp_path / "out.parquet")
    duckdb.sql(f"COPY (SELECT * FROM (VALUES ('F1', 1)) t(f, a)) TO '{path}' (FORMAT parquet)")
    _schema, rows, added, removed = engine.write_pairs(
        path, "f", "a", add=[("F1", "1")], remove=[("F1", "1")], dest_path=dest)
    assert (rows, added, removed) == (1, [], [])


def test_an_optional_object_left_empty_links_nothing_and_says_so(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["flights"], "api_name": f"opt_{uuid.uuid4().hex[:6]}",
        "display_name": "Optional", "editable_properties": ["route"]})
    optional = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{optional}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [{"api_name": "other", "display_name": "Other",
                                         "data_type": "object", "required": False,
                                         "object_type_id": world["aircraft"]}],
                         "rules": [{"kind": "create_link", "config": {
                             "link_type": world["link"], "object": "other"}}],
                         "criteria": []})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/actions/{optional}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": instance(client, fx, world["flights"], "F1")["id"],
                          "values": {}})
    assert r.status_code == 422 and "no value was supplied" in r.json()["detail"], r.text


def test_a_join_table_the_runner_cannot_read_is_not_found(client, fx, world) -> None:
    """RLS: the join table sits in a project the person applying cannot see."""
    import psycopg
    from test_link_join_tables import ADMIN_DSN
    tag = uuid.uuid4().hex[:6]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as db:
        hidden = db.execute(
            "INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
            "VALUES (%s, %s, %s, %s, 'custom') RETURNING id",
            (fx.workspace, f"Hidden {tag}", f"hidden-{tag}", fx.owner),
        ).fetchone()[0]
    r = client.post(
        f"{wbase(fx)}/projects/{hidden}/datasets/upload", headers=hdr(fx.admin_sub),
        files={"file": ("pairs.csv", PAIRS, "text/csv")}, data={"name": f"hidden_{tag}"},
    )
    assert r.status_code == 201, r.text
    link = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.admin_sub), json={
        "api_name": f"hidden_{tag}", "display_name": "Hidden", "from_type_id": world["flights"],
        "to_type_id": world["aircraft"], "cardinality": "many_to_many",
        "join_dataset_id": r.json()["id"], "join_from_column": "flight",
        "join_to_column": "aircraft"}).json()
    link_it, r = action(client, fx, world, "flights", "create_link", "aircraft",
                        config={"link_type": link["id"], "object": "other"})
    assert r.status_code == 200, r.text
    r = run(client, fx, world, link_it, "flights", "F1", "aircraft", "2")
    assert r.status_code == 404 and "join table" in r.json()["detail"], r.text


def test_a_join_table_that_also_backs_an_object_this_action_changes_is_refused(
    client, fx, world
) -> None:
    """One dataset, two writes: the object's row and a pair. One version cannot
    be staged from two plans, so the run says so rather than colliding."""
    tag = uuid.uuid4().hex[:6]
    rows = object_type(client, fx, f"pairing_{tag}",
                       b"id,flight,aircraft,note\nP1,F1,1,x\n", ["flight", "aircraft", "note"])
    r = client.get(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub))
    backing = next(s for s in r.json() if s["object_type_id"] == rows)["dataset_id"]
    link = client.post(f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"paired_{tag}", "display_name": "Paired", "from_type_id": world["flights"],
        "to_type_id": world["aircraft"], "cardinality": "many_to_many",
        "join_dataset_id": backing, "join_from_column": "flight",
        "join_to_column": "aircraft"}).json()
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["flights"], "api_name": f"shared_{tag}",
        "display_name": "Shared", "editable_properties": ["route"]})
    shared = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{shared}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [
                       {"api_name": "other", "display_name": "Other", "data_type": "object",
                        "object_type_id": world["aircraft"]},
                       {"api_name": "row", "display_name": "Row", "data_type": "object",
                        "object_type_id": rows},
                       {"api_name": "note", "display_name": "Note", "data_type": "string"}],
                       "rules": [
                           {"kind": "modify_object", "config": {
                               "object_type": rows, "object": "row", "property": "note",
                               "parameter": "note"}},
                           {"kind": "create_link", "config": {
                               "link_type": link["id"], "object": "other"}}],
                       "criteria": []})
    assert r.status_code == 200, r.text
    r = client.post(f"{pbase(fx)}/actions/{shared}/execute", headers=hdr(fx.editor_sub), json={
        "instance_id": instance(client, fx, world["flights"], "F2")["id"],
        "values": {"other": instance(client, fx, world["aircraft"], "3")["id"],
                   "row": instance(client, fx, rows, "P1")["id"], "note": "y"}})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and "also backs an object type" in r.json()["error"], r.text
