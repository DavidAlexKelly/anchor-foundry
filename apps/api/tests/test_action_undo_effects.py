"""Undoing an action that created, deleted or changed other objects (§551;
db 0114; `action-types` p.154-156).

    "Reverting a delete action is supported …" (p.156)

The original module's preamble, whose reasoning holds here: the dataset is the
record (decision 0008), so each test re-syncs after the undo.

(From `test_action_undo.py`:) Undoing an action, end to end (§319; db 0076;
`action-types` p.154-156).

    "Action reverts in Ontology Manager allow an action to be reverted (that
     is, undone) immediately after the action has been applied." (p.154)

The refusals are decided by a pure function and tested in
`test_action_revert.py`, which needs no database at all. **What needs one is
the writing**, and specifically the half that is easy to get wrong and
impossible to see: here the dataset is the record and the instance store is a
projection of it (decision 0008), so an undo that restored only the projection
would look perfect and come silently undone at the next sync.

So the assertions below check the *dataset* as well as the object, and one of
them re-syncs the source afterwards to prove the undo survived it.
"""
from __future__ import annotations

import io
import os
import sys

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

PEOPLE = (b"person_id,name,email\np1,Ada Lovelace,ada@example.com\n"
          b"p2,Grace Hopper,grace@example.com\np3,Alan Turing,alan@example.com\n"
          b"p4,Hedy Lamarr,hedy@example.com\n")


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("undo-effects-storage")))
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
    """A dataset, a type mapped to it, an action that edits it, and an object."""
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"UndoEffects {fx.tag}"},
        files={"file": ("people.csv", io.BytesIO(PEOPLE), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"undo_fx_person_{fx.tag}",
              "display_name": f"Undo effects person {fx.tag}",
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

    r = client.post(
        f"{pbase(fx)}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": "fix_contact",
              "display_name": "Fix contact",
              "editable_properties": ["name", "email"]},
    )
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    # p.154: "New actions are revertible by default."
    assert r.json()["allow_revert"] is True

    return {"dataset_id": dataset_id, "type_id": type_id,
            "source_id": source_id, "action_id": action_id}


def an_object(client: TestClient, fx: Fixture, world: dict, name: str) -> dict:
    r = client.get(
        f"{wbase(fx)}/object-types/{world['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["properties"]["name"] == name)


def by_key(client: TestClient, fx: Fixture, world: dict, key: str) -> dict:
    """One object by its **primary key**, which is the only handle that holds.

    `an_object` matches on `name`, and `name` is a property these tests edit —
    so a test that runs after one whose undo was refused looks for a person who
    no longer has that name and raises `StopIteration` from a `next()` four
    frames away. Found exactly that way. The module-scoped fixture is the
    reason: this suite's own house rule is that a test which writes gets its
    own module, and the cheap version of that rule is to address rows by the
    one field nothing here changes.
    """
    r = client.get(
        f"{wbase(fx)}/object-types/{world['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return next(i for i in r.json()["items"] if i["primary_key"] == key)


def apply(client: TestClient, fx: Fixture, world: dict, instance_id: str,
          values: dict, sub: str | None = None) -> dict:
    r = client.post(
        f"{pbase(fx)}/actions/{world['action_id']}/execute",
        headers=hdr(sub or fx.editor_sub),
        json={"instance_id": instance_id, "values": values},
    )
    assert r.status_code == 200, r.text
    return r.json()


def undo(client: TestClient, fx: Fixture, world: dict, run_id: str,
         sub: str | None = None):
    return client.post(
        f"{pbase(fx)}/actions/{world['action_id']}/runs/{run_id}/undo",
        headers=hdr(sub or fx.editor_sub),
    )



def define(client: TestClient, fx: Fixture, world: dict, name: str, parameters: list,
           rules: list) -> str:
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type_id"], "api_name": name,
              "display_name": name, "editable_properties": ["name", "email"]},
    )
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]
    r = client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": parameters, "rules": rules, "criteria": []},
    )
    assert r.status_code == 200, r.text
    return action_id


def run_action(client, fx, action_id: str, instance_id: str, values: dict) -> dict:
    r = client.post(
        f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instance_id, "values": values},
    )
    assert r.status_code == 200, r.text
    return r.json()


def undo_run(client, fx, action_id: str, run_id: str):
    return client.post(
        f"{pbase(fx)}/actions/{action_id}/runs/{run_id}/undo", headers=hdr(fx.editor_sub))


def keys(client, fx, world) -> dict[str, dict]:
    r = client.get(
        f"{wbase(fx)}/object-types/{world['type_id']}/instances",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return {i["primary_key"]: i for i in r.json()["items"]}


def resync(client, fx, world) -> None:
    r = client.post(
        f"{pbase(fx)}/object-type-sources/{world['source_id']}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text


def test_undoing_a_create_deletes_what_it_created(client, fx, world) -> None:
    refer = define(client, fx, world, "refer", [
        {"api_name": "email", "display_name": "Email", "data_type": "string"},
        {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
        {"api_name": "new_name", "display_name": "Name", "data_type": "string"}], [
        {"kind": "modify_object", "config": {"property": "email", "parameter": "email"}},
        {"kind": "create_object", "config": {
            "primary_key": "new_key", "properties": {"name": "new_name"}}}])
    ada = keys(client, fx, world)["p1"]
    run = run_action(client, fx, refer, ada["id"],
                     {"email": "ada@refer.test", "new_key": "p9", "new_name": "Mary Somerville"})
    # Before db 0114 this was refused, "undoing it would leave them behind".
    assert run["can_undo"] is True, run
    assert "p9" in keys(client, fx, world)
    r = undo_run(client, fx, refer, run["run_id"])
    assert r.status_code == 200, r.text
    after = keys(client, fx, world)
    assert "p9" not in after and after["p1"]["properties"]["email"] == "ada@example.com"
    # The dataset is the record: a re-sync reads it and agrees.
    resync(client, fx, world)
    after = keys(client, fx, world)
    assert "p9" not in after and after["p1"]["properties"]["email"] == "ada@example.com"


def test_undoing_a_delete_brings_the_object_back(client, fx, world) -> None:
    """p.156: "Reverting a delete action is supported"."""
    remove = define(client, fx, world, "remove_self", [],
                    [{"kind": "delete_object", "config": {}}])
    grace = keys(client, fx, world)["p2"]
    run = run_action(client, fx, remove, grace["id"], {})
    assert run["can_undo"] is True, run
    assert "p2" not in keys(client, fx, world)
    r = undo_run(client, fx, remove, run["run_id"])
    assert r.status_code == 200, r.text
    assert r.json()["instance"]["primary_key"] == "p2"
    back = keys(client, fx, world)["p2"]["properties"]
    assert back == {"name": "Grace Hopper", "email": "grace@example.com"}, back
    resync(client, fx, world)
    assert keys(client, fx, world)["p2"]["properties"] == back


def test_undoing_the_deletion_of_another_object_brings_it_back(client, fx, world) -> None:
    retire = define(client, fx, world, "retire_other", [
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["type_id"]}],
        [{"kind": "delete_object", "config": {"object_type": world["type_id"], "object": "who"}}])
    everyone = keys(client, fx, world)
    run = run_action(client, fx, retire, everyone["p1"]["id"], {"who": everyone["p3"]["id"]})
    assert "p3" not in keys(client, fx, world)
    r = undo_run(client, fx, retire, run["run_id"])
    assert r.status_code == 200, r.text
    resync(client, fx, world)
    assert keys(client, fx, world)["p3"]["properties"]["name"] == "Alan Turing"


def test_undoing_a_change_to_another_object_puts_it_back(client, fx, world) -> None:
    rename = define(client, fx, world, "rename_other", [
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["type_id"]},
        {"api_name": "name", "display_name": "Name", "data_type": "string"}],
        [{"kind": "modify_object", "config": {
            "object_type": world["type_id"], "object": "who", "property": "name",
            "parameter": "name"}}])
    everyone = keys(client, fx, world)
    run = run_action(client, fx, rename, everyone["p1"]["id"],
                     {"who": everyone["p4"]["id"], "name": "Hedy K."})
    assert keys(client, fx, world)["p4"]["properties"]["name"] == "Hedy K."
    r = undo_run(client, fx, rename, run["run_id"])
    assert r.status_code == 200, r.text
    resync(client, fx, world)
    assert keys(client, fx, world)["p4"]["properties"]["name"] == "Hedy Lamarr"


def test_a_created_object_edited_since_takes_the_undo_away(client, fx, world) -> None:
    make = define(client, fx, world, "make_one", [
        {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
        {"api_name": "new_name", "display_name": "Name", "data_type": "string"}],
        [{"kind": "create_object", "config": {
            "primary_key": "new_key", "properties": {"name": "new_name"}}}])
    ada = keys(client, fx, world)["p1"]
    run = run_action(client, fx, make, ada["id"], {"new_key": "p7", "new_name": "Emmy"})
    fix = define(client, fx, world, "fix_name", [
        {"api_name": "name", "display_name": "Name", "data_type": "string"}],
        [{"kind": "modify_object", "config": {"property": "name", "parameter": "name"}}])
    run_action(client, fx, fix, keys(client, fx, world)["p7"]["id"], {"name": "Emmy Noether"})
    r = undo_run(client, fx, make, run["run_id"])
    assert r.status_code == 409, r.text
    assert "created has been edited or deleted since" in r.json()["detail"], r.text
    assert keys(client, fx, world)["p7"]["properties"]["name"] == "Emmy Noether"


def edits(client, fx, world, key: str) -> list[dict]:
    r = client.post(f"{wbase(fx)}/object-edits", headers=hdr(fx.viewer_sub),
                    json={"object_type_id": world["type_id"], "primary_key": key,
                          "order": "newest"})
    assert r.status_code == 200, r.text
    return r.json()["edits"]


def test_the_undo_is_in_every_objects_edit_history(client, fx, world) -> None:
    """p.402's trail records the revert beside the edit, "even if the
    corresponding ontology edits are reverted" - for every object the undo
    wrote, as the apply records every object it wrote: what the run created is
    deleted, what it deleted created, what it changed changed back."""
    r = client.put(f"{wbase(fx)}/object-types/{world['type_id']}/edit-history",
                   headers=hdr(fx.editor_sub), json={"enabled": True})
    assert r.status_code == 200, r.text
    shuffle = define(client, fx, world, "shuffle", [
        {"api_name": "email", "display_name": "Email", "data_type": "string"},
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["type_id"]},
        {"api_name": "gone", "display_name": "Gone", "data_type": "object",
         "object_type_id": world["type_id"]},
        {"api_name": "name", "display_name": "Name", "data_type": "string"},
        {"api_name": "new_key", "display_name": "Key", "data_type": "string"}], [
        {"kind": "modify_object", "config": {"property": "email", "parameter": "email"}},
        {"kind": "modify_object", "config": {
            "object_type": world["type_id"], "object": "who", "property": "name",
            "parameter": "name"}},
        {"kind": "delete_object", "config": {"object_type": world["type_id"], "object": "gone"}},
        {"kind": "create_object", "config": {
            "primary_key": "new_key", "properties": {"name": "name"}}}])
    everyone = keys(client, fx, world)
    run = run_action(client, fx, shuffle, everyone["p1"]["id"], {
        "email": "ada@shuffle.test", "who": everyone["p3"]["id"], "gone": everyone["p7"]["id"],
        "name": "Alan T.", "new_key": "p8"})
    r = undo_run(client, fx, shuffle, run["run_id"])
    assert r.status_code == 200, r.text
    undone = r.json()["run_id"]
    newest = {key: edits(client, fx, world, key)[0] for key in ("p1", "p3", "p7", "p8")}
    assert {e["action_run_id"] for e in newest.values()} == {undone}, newest
    got = {key: (e["kind"], e["property"], e["before"], e["after"])
           for key, e in newest.items()}
    assert got == {
        "p1": ("modify", "email", "ada@shuffle.test", "ada@example.com"),
        "p3": ("modify", "name", "Alan T.", "Alan Turing"),
        "p7": ("create", None, None, {"name": "Emmy Noether"}),
        "p8": ("delete", None, {"name": "Alan T."}, None),
    }, got

    # A subject the run deleted comes back as a create, not as a change from
    # nothing to everything.
    remove = define(client, fx, world, "remove_tracked", [],
                    [{"kind": "delete_object", "config": {}}])
    run = run_action(client, fx, remove, keys(client, fx, world)["p2"]["id"], {})
    r = undo_run(client, fx, remove, run["run_id"])
    assert r.status_code == 200, r.text
    back = edits(client, fx, world, "p2")[0]
    assert (back["action_run_id"], back["kind"]) == (r.json()["run_id"], "create"), back
