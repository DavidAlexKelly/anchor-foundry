"""Per-object edit history (§470; `workshop` p.402–403; db 0104).

> "The Edit History widget displays the list of user edits made to an object's
> properties after Track user edit history has been enabled for the object type
> within Ontology Manager. Edits completed prior to enabling Edit History,
> edits completed by a pipeline … will not be reflected." (p.402)
>
> "Changelog records … cannot be deleted or modified by end users, even if the
> corresponding ontology edits are reverted or deleted." (p.402)

What is recorded is asserted by reading it back through the route the widget
reads, after driving the three action paths that write: execute, execute-batch
and undo. One test goes past the application role to check the table refuses
an UPDATE, because "immutable" that only the application honours is a
convention.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import object_edits  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

APP_DSN = "postgresql://platform_app:devpass@localhost:5432/platform?sslmode=disable"

PEOPLE = (b"person_id,name,email\np1,Ada Lovelace,ada@example.com\n"
          b"p2,Grace Hopper,grace@example.com\np3,Alan Turing,alan@example.com\n"
          b"p4,Kurt Godel,kurt@example.com\n")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("edits-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"EditPeople {fx.tag}"},
        files={"file": ("people.csv", io.BytesIO(PEOPLE), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"edit_person_{fx.tag}", "display_name": f"Edit person {fx.tag}",
              "properties": [{"api_name": "name", "data_type": "string"},
                             {"api_name": "email", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": "person_id",
              "column_mappings": {"name": "name", "email": "email"}},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources/{source_id}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": f"fix_{uuid.uuid4().hex[:6]}",
              "display_name": "Fix contact", "editable_properties": ["name", "email"]},
    )
    assert r.status_code == 201, r.text
    return {"type_id": type_id, "action_id": r.json()["id"], "source_id": source_id}


def instance(client, fx, world, key: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{world['type_id']}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["primary_key"] == key)


def apply(client, fx, action_id: str, instance_id: str, values: dict) -> dict:
    r = client.post(f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
                    json={"instance_id": instance_id, "values": values})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()
    return r.json()


def edits(client, fx, world, key: str, **kw) -> dict:
    r = client.post(f"{wbase(fx)}/object-edits", headers=hdr(fx.viewer_sub),
                    json={"object_type_id": world["type_id"], "primary_key": key, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def track(client, fx, world, on: bool, sub: str | None = None):
    return client.put(f"{wbase(fx)}/object-types/{world['type_id']}/edit-history",
                      headers=hdr(sub or fx.editor_sub), json={"enabled": on})


def test_nothing_is_recorded_before_tracking_is_switched_on(client, fx, world) -> None:
    """p.402: "Edits completed prior to enabling Edit History … will not be
    reflected." Asserted *after* enabling, which is the only order that can
    tell "never recorded" from "recorded and hidden"."""
    ada = instance(client, fx, world, "p1")
    apply(client, fx, world["action_id"], ada["id"], {"email": "ada@before.test"})
    assert track(client, fx, world, True).status_code == 200
    got = edits(client, fx, world, "p1")
    assert got["edits"] == [] and got["tracking_since"], got


def test_a_viewer_cannot_switch_tracking_and_a_second_enable_keeps_the_start(
    client, fx, world
) -> None:
    assert track(client, fx, world, True, sub=fx.viewer_sub).status_code == 403
    first = track(client, fx, world, True).json()["since"]
    again = track(client, fx, world, True).json()["since"]
    assert first == again and first is not None
    r = client.get(f"{wbase(fx)}/object-types/{world['type_id']}/edit-history",
                   headers=hdr(fx.viewer_sub))
    assert r.json()["since"] == first


def test_an_edit_records_each_changed_property_and_who_made_it(client, fx, world) -> None:
    track(client, fx, world, True)
    grace = instance(client, fx, world, "p2")
    run = apply(client, fx, world["action_id"], grace["id"],
                {"name": "Grace M. Hopper", "email": "grace@navy.test"})
    got = edits(client, fx, world, "p2", order="oldest")["edits"]
    assert [(e["kind"], e["property"], e["before"], e["after"]) for e in got] == [
        ("modify", "email", "grace@example.com", "grace@navy.test"),
        ("modify", "name", "Grace Hopper", "Grace M. Hopper"),
    ]
    assert {e["action_run_id"] for e in got} == {run["run_id"]}
    assert all(e["editor"] for e in got) and all(e["edited_by"] for e in got)


def test_an_unchanged_property_is_not_an_edit(client, fx, world) -> None:
    track(client, fx, world, True)
    alan = instance(client, fx, world, "p3")
    apply(client, fx, world["action_id"], alan["id"],
          {"name": "Alan Turing", "email": "alan@bletchley.test"})
    got = edits(client, fx, world, "p3")["edits"]
    assert [e["property"] for e in got] == ["email"]


def test_an_undo_is_a_new_edit_and_the_undone_one_stays(client, fx, world) -> None:
    """p.402: "even if the corresponding ontology edits are reverted"."""
    track(client, fx, world, True)
    kurt = instance(client, fx, world, "p4")
    run = apply(client, fx, world["action_id"], kurt["id"], {"email": "kurt@ias.test"})
    r = client.post(f"{pbase(fx)}/actions/{world['action_id']}/runs/{run['run_id']}/undo",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    got = edits(client, fx, world, "p4", order="oldest")["edits"]
    assert [(e["before"], e["after"]) for e in got] == [
        ("kurt@example.com", "kurt@ias.test"), ("kurt@ias.test", "kurt@example.com")]
    assert got[0]["action_run_id"] == run["run_id"]
    assert got[1]["action_run_id"] == r.json()["run_id"]


def test_the_order_and_the_properties_are_the_readers(client, fx, world) -> None:
    """p.403's "Edits sort order" and "Property configuration"."""
    newest = edits(client, fx, world, "p2", order="newest")["edits"]
    oldest = edits(client, fx, world, "p2", order="oldest")["edits"]
    assert [e["id"] for e in newest] == [e["id"] for e in reversed(oldest)]
    only = edits(client, fx, world, "p2", properties=["name"])["edits"]
    assert [e["property"] for e in only] == ["name"]


def test_a_batch_records_each_object_under_its_own_run(client, fx, world) -> None:
    track(client, fx, world, True)
    ada, alan = instance(client, fx, world, "p1"), instance(client, fx, world, "p3")
    r = client.post(
        f"{pbase(fx)}/actions/{world['action_id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": ada["id"], "values": {"name": "Ada King"}},
                        {"instance_id": alan["id"], "values": {"name": "A. M. Turing"}}]},
    )
    assert r.status_code == 200 and r.json()["ok"], r.text
    ada_edits = edits(client, fx, world, "p1")["edits"]
    alan_edits = edits(client, fx, world, "p3")["edits"]
    assert (ada_edits[0]["property"], ada_edits[0]["after"]) == ("name", "Ada King")
    assert (alan_edits[0]["property"], alan_edits[0]["after"]) == ("name", "A. M. Turing")
    assert ada_edits[0]["action_run_id"] != alan_edits[0]["action_run_id"]


def test_switching_tracking_off_stops_recording(client, fx, world) -> None:
    track(client, fx, world, True)
    count = len(edits(client, fx, world, "p1")["edits"])
    assert track(client, fx, world, False).json()["since"] is None
    ada = instance(client, fx, world, "p1")
    apply(client, fx, world["action_id"], ada["id"], {"email": "ada@off.test"})
    assert len(edits(client, fx, world, "p1")["edits"]) == count
    track(client, fx, world, True)


def test_a_deleted_object_s_history_ends_with_its_deletion(client, fx, world) -> None:
    """A deleted object's history is the one most likely to be asked about, so
    the rows outlive it."""
    track(client, fx, world, True)
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type_id"], "api_name": f"rm_{uuid.uuid4().hex[:6]}",
              "display_name": "Remove", "editable_properties": ["name"]},
    )
    assert r.status_code == 201, r.text
    remove = r.json()["id"]
    r = client.put(f"{wbase(fx)}/action-types/{remove}/definition", headers=hdr(fx.editor_sub),
                   json={"parameters": [], "rules": [{"kind": "delete_object", "config": {}}],
                         "criteria": []})
    assert r.status_code == 200, r.text
    alan = instance(client, fx, world, "p3")
    apply(client, fx, remove, alan["id"], {})
    got = edits(client, fx, world, "p3")["edits"]
    assert got[0]["kind"] == "delete" and got[0]["property"] is None
    assert got[0]["before"]["name"] == "A. M. Turing" and got[0]["after"] is None


def test_the_record_cannot_be_changed_or_removed_by_the_application(client, fx, world) -> None:
    """"Immutable" is the grant, not a promise: the application's own role is
    refused an UPDATE and a DELETE on the table."""
    with psycopg.connect(APP_DSN, autocommit=True) as conn:
        for sql in ("UPDATE object_edits SET after_value = 'null'::jsonb",
                    "DELETE FROM object_edits"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(sql)


def test_the_diff_compares_values_as_json() -> None:
    assert object_edits.diff({"a": 1, "b": [1, 2], "c": "x"},
                             {"a": 1, "b": [1, 2, 3], "d": None}) == [
        ("b", [1, 2], [1, 2, 3]), ("c", "x", None)]
    assert object_edits.diff({"s": {"x": 1, "y": 2}}, {"s": {"y": 2, "x": 1}}) == []


def test_an_object_an_action_creates_starts_its_history_there(client, fx, world) -> None:
    """The subject's edit and the new object's creation, from one run: each
    object's history holds its own."""
    track(client, fx, world, True)
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type_id"], "api_name": f"mk_{uuid.uuid4().hex[:6]}",
              "display_name": "Refer", "editable_properties": ["email"]},
    )
    assert r.status_code == 201, r.text
    refer = r.json()["id"]
    r = client.put(
        f"{wbase(fx)}/action-types/{refer}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "email", "display_name": "Email", "data_type": "string"},
                  {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
                  {"api_name": "new_name", "display_name": "Name", "data_type": "string"}],
              "rules": [
                  {"kind": "modify_object", "config": {"property": "email", "parameter": "email"}},
                  {"kind": "create_object", "config": {
                      "primary_key": "new_key", "properties": {"name": "new_name"}}}],
              "criteria": []},
    )
    assert r.status_code == 200, r.text
    ada = instance(client, fx, world, "p1")
    run = apply(client, fx, refer, ada["id"],
                {"email": "ada@refer.test", "new_key": "p9", "new_name": "Mary Somerville"})
    [created] = edits(client, fx, world, "p9")["edits"]
    assert (created["kind"], created["property"], created["before"]) == ("create", None, None)
    assert created["after"] == {"name": "Mary Somerville"}
    assert created["action_run_id"] == run["run_id"]
    newest = edits(client, fx, world, "p1")["edits"][0]
    assert (newest["property"], newest["after"]) == ("email", "ada@refer.test")


def test_one_run_s_edits_list_in_the_order_they_were_written(client, fx, world) -> None:
    """One run's rows share `edited_at` (the transaction's `now()`), so the
    order within a run is db 0104's `seq`. Several runs, because a random
    tie-break would put two edits in the right order half the time."""
    track(client, fx, world, True)
    grace = instance(client, fx, world, "p2")
    for n in range(6):
        apply(client, fx, world["action_id"], grace["id"],
              {"name": f"Grace {n}", "email": f"grace{n}@navy.test"})
    got = edits(client, fx, world, "p2", order="oldest")["edits"][-12:]
    assert [e["property"] for e in got] == ["email", "name"] * 6, got


def test_an_editor_is_named_by_email_when_they_have_no_name(client, fx, world) -> None:
    """The record stays whoever made it, so the name falls back rather than
    going blank."""
    with psycopg.connect(os.environ.get(
        "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
    ), autocommit=True) as conn:
        conn.execute("UPDATE users SET display_name = '' WHERE id = %s", (str(fx.editor),))
    track(client, fx, world, True)
    kurt = instance(client, fx, world, "p4")
    apply(client, fx, world["action_id"], kurt["id"], {"name": "Kurt Gödel"})
    newest = edits(client, fx, world, "p4")["edits"][0]
    assert newest["editor"] == f"editor-{fx.tag}@example.com", newest
