"""Undoing an action, end to end (§319; db 0076; `action-types` p.154-156).

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

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

PEOPLE = b"person_id,name,email\np1,Ada Lovelace,ada@example.com\np2,Grace Hopper,grace@example.com\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("undo-storage")))
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
        data={"name": f"UndoPeople {fx.tag}"},
        files={"file": ("people.csv", io.BytesIO(PEOPLE), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"undo_person_{fx.tag}",
              "display_name": f"Undo person {fx.tag}",
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


def test_the_apply_says_its_run_can_be_undone(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**p.154 puts Undo in the success message**, so the success message is
    where the run to undo has to be named.

    Without `run_id` in the answer, a screen wanting to offer the button would
    have to go and find its own run in a list and pick one by timestamp.
    """
    ada = an_object(client, fx, world, "Ada Lovelace")
    result = apply(client, fx, world, ada["id"], {"email": "ada@lovelace.test"})
    assert result["ok"] is True
    assert result["run_id"]
    assert result["can_undo"] is True, result["undo_refusal"]
    assert result["undo_refusal"] is None


def test_an_undo_puts_the_object_back(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.154's whole claim, on the object."""
    grace = an_object(client, fx, world, "Grace Hopper")
    before = dict(grace["properties"])
    result = apply(client, fx, world, grace["id"], {"email": "grace@navy.test"})
    assert result["instance"]["properties"]["email"] == "grace@navy.test"

    r = undo(client, fx, world, result["run_id"])
    assert r.status_code == 200, r.text
    assert r.json()["instance"]["properties"]["email"] == before["email"]


def test_the_undo_reaches_the_dataset_and_survives_a_sync(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**The assertion the whole storage argument rests on** (decision 0008).

    The dataset is the record and the instance store is a projection of it, so
    an undo that wrote only the projection would look right on every screen and
    silently come back the next time the source synced. This applies, undoes,
    re-syncs, and then asks the object again — which is the only sequence that
    can tell the two implementations apart.
    """
    ada = an_object(client, fx, world, "Ada Lovelace")
    before = dict(ada["properties"])
    result = apply(client, fx, world, ada["id"], {"name": "Ada L."})
    r = client.get(f"{pbase(fx)}/datasets/{world['dataset_id']}", headers=hdr(fx.viewer_sub))
    after_apply = r.json()["current_version"]

    r = undo(client, fx, world, result["run_id"])
    assert r.status_code == 200, r.text
    # The undo is a **new version**, not a rewind: this dataset is append-only
    # and its history is the record of what happened, including the undo.
    r = client.get(f"{pbase(fx)}/datasets/{world['dataset_id']}", headers=hdr(fx.viewer_sub))
    assert r.json()["current_version"] > after_apply

    r = client.post(
        f"{pbase(fx)}/object-type-sources/{world['source_id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 200, r.text
    assert an_object(client, fx, world, before["name"])["properties"] == before


def test_an_undo_cannot_be_pressed_twice(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.155 calls the toast "your only opportunity". A second press would
    write the old values over whatever the first press left."""
    grace = an_object(client, fx, world, "Grace Hopper")
    result = apply(client, fx, world, grace["id"], {"email": "grace@twice.test"})
    assert undo(client, fx, world, result["run_id"]).status_code == 200
    second = undo(client, fx, world, result["run_id"])
    assert second.status_code == 409, second.text
    assert "already been undone" in second.text


def test_a_later_edit_takes_the_undo_away(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.156: "An action on an object cannot be reverted once any subsequent
    edit has been made to the object.\""""
    ada = an_object(client, fx, world, "Ada Lovelace")
    first = apply(client, fx, world, ada["id"], {"email": "ada@first.test"})
    second = apply(client, fx, world, ada["id"], {"email": "ada@second.test"})
    # The newer one is still undoable; the older one is not.
    assert second["can_undo"] is True
    r = undo(client, fx, world, first["run_id"])
    assert r.status_code == 409, r.text
    assert "edited since" in r.text


def test_only_the_person_who_applied_it_may_undo_it(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.154: "Currently, actions can only be reverted by the user who applied
    the action.\""""
    grace = an_object(client, fx, world, "Grace Hopper")
    result = apply(client, fx, world, grace["id"], {"email": "grace@mine.test"})
    r = undo(client, fx, world, result["run_id"], sub=fx.admin_sub)
    assert r.status_code == 409, r.text
    assert "person who applied" in r.text


def test_an_undo_is_a_run_of_its_own_and_cannot_itself_be_undone(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """A revert appends to the dataset and writes the index exactly as an apply
    does, so it has an author and a time — and an undo of an undo is the action
    applied again, which is not what the word says."""
    ada = an_object(client, fx, world, "Ada Lovelace")
    result = apply(client, fx, world, ada["id"], {"name": "Ada Again"})
    r = undo(client, fx, world, result["run_id"])
    assert r.status_code == 200, r.text
    undo_run = r.json()["run_id"]
    assert undo_run != result["run_id"]

    again = undo(client, fx, world, undo_run)
    assert again.status_code == 409, again.text
    assert "apply the action again" in again.text


def test_turning_the_toggle_off_takes_undo_away_and_turning_it_on_does_not_return_it(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**p.155's whole sentence**: "An action cannot be reverted if action
    reverts has been toggled off after action submission, **even if action
    reverts have been toggled on again**."

    The second half is the one a `allow_revert` check alone would fail: flip
    the switch back and every undo the switch took away would return.
    """
    grace = an_object(client, fx, world, "Grace Hopper")
    result = apply(client, fx, world, grace["id"], {"email": "grace@toggle.test"})
    assert result["can_undo"] is True

    r = client.patch(
        f"{wbase(fx)}/action-types/{world['action_id']}", headers=hdr(fx.editor_sub),
        json={"allow_revert": False},
    )
    assert r.status_code == 200, r.text
    assert r.json()["allow_revert"] is False
    blocked = undo(client, fx, world, result["run_id"])
    assert blocked.status_code == 409, blocked.text
    assert "switched off" in blocked.text

    r = client.patch(
        f"{wbase(fx)}/action-types/{world['action_id']}", headers=hdr(fx.editor_sub),
        json={"allow_revert": True},
    )
    assert r.status_code == 200 and r.json()["allow_revert"] is True
    still_blocked = undo(client, fx, world, result["run_id"])
    assert still_blocked.status_code == 409, still_blocked.text
    assert "switched off" in still_blocked.text


def test_an_application_made_after_the_toggle_came_back_can_be_undone(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The other half of the rule above, and the one that keeps it from being
    "the toggle can never be turned on again": the block is on the runs that
    existed when it went off, not on the action type."""
    ada = an_object(client, fx, world, "Ada Lovelace")
    result = apply(client, fx, world, ada["id"], {"name": "Ada After"})
    assert result["can_undo"] is True, result["undo_refusal"]
    assert undo(client, fx, world, result["run_id"]).status_code == 200


def test_a_run_of_another_action_type_is_not_found(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """Addressed as a pairing, so a run reached through the wrong action type
    is not found rather than quietly undone."""
    grace = an_object(client, fx, world, "Grace Hopper")
    result = apply(client, fx, world, grace["id"], {"email": "grace@pair.test"})
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["type_id"], "api_name": "other_action",
              "display_name": "Other action", "editable_properties": ["name"]},
    )
    assert r.status_code == 201, r.text
    other = r.json()["id"]
    wrong = client.post(
        f"{pbase(fx)}/actions/{other}/runs/{result['run_id']}/undo",
        headers=hdr(fx.editor_sub),
    )
    assert wrong.status_code == 404, wrong.text
    # And the real one still works, so the 404 above was about the pairing
    # rather than about the run having been spoiled by asking.
    assert undo(client, fx, world, result["run_id"]).status_code == 200


def test_a_viewer_cannot_undo(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """An undo is a write to project data, and the floor that governs the write
    governs putting it back."""
    ada = an_object(client, fx, world, "Ada Lovelace")
    result = apply(client, fx, world, ada["id"], {"name": "Ada Viewer"})
    r = undo(client, fx, world, result["run_id"], sub=fx.viewer_sub)
    assert r.status_code == 403, r.text
