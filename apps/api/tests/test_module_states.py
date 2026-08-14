"""Saved module states (parity `docs/parity/workshop.md` §7; Foundry
`workshop` p.200-206).

> "State saving … allows module consumers to store the current state of their
> work within a module and then either return to that saved state or share the
> saved state with other users." (p.200)

Two claims carry this feature and both are testable here: a state is stored
**by external ID** (p.203), so it survives the module being rebuilt around it;
and a state is a note by a *consumer*, so it must not need the permission that
edits the module.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
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


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def saved(external_id: str = "region", **extra) -> dict:
    return {
        "id": f"v_{external_id}", "kind": "string", "label": external_id.title(),
        "external_id": external_id, "save_state": True, **extra,
    }


DOCUMENT = {
    "format": 2,
    "layout": {"ROOT": {"type": "Container", "nodes": []}},
    "state_saving": {"enabled": True},
    "variables": {
        "v_region": saved("region"),
        "v_status": saved("status"),
        # Enabled for nothing: proves a state carries only what asked to be in
        # it, rather than everything the viewer has touched.
        "v_scratch": {"id": "v_scratch", "kind": "string", "label": "Scratch"},
    },
    "events": {},
}


def make_module(client: TestClient, fx: Fixture, document: dict) -> str:
    r = client.post(
        f"{pbase(fx)}/canvas-apps",
        headers=hdr(fx.editor_sub),
        json={"name": f"States {uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{app_id}/definition",
        headers=hdr(fx.editor_sub),
        json={"definition": document},
    )
    assert r.status_code == 200, r.text
    return app_id


@pytest.fixture(scope="module")
def module_id(client: TestClient, fx: Fixture) -> str:
    return make_module(client, fx, DOCUMENT)


def save(client, fx, module_id, name, values, sub=None, page_id=None):
    return client.post(
        f"{pbase(fx)}/canvas-apps/{module_id}/states",
        headers=hdr(sub or fx.editor_sub),
        json={"name": name, "values": values, "page_id": page_id},
    )


# ---- the round trip ----------------------------------------------------------
def test_a_state_restores_what_the_viewer_had_chosen(client, fx, module_id):
    r = save(client, fx, module_id, f"north-{uuid.uuid4().hex[:6]}",
             {"v_region": "north", "v_status": "open"})
    assert r.status_code == 201, r.text
    state_id = r.json()["id"]

    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    # Keyed back to variable ids, because that is what a running module holds.
    assert r.json()["values"] == {"v_region": "north", "v_status": "open"}
    assert r.json()["missing"] == []


def test_a_state_carries_only_the_variables_that_asked_to_be_in_it(client, fx, module_id):
    """p.204: "Saving state will preserve the current values of any state
    saving **enabled** variables". A viewer touches many things; a state is
    what the builder said was worth keeping."""
    r = save(client, fx, module_id, f"scratch-{uuid.uuid4().hex[:6]}",
             {"v_region": "north", "v_scratch": "notes to self"})
    state_id = r.json()["id"]
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.json()["values"] == {"v_region": "north"}


def test_an_untouched_variable_is_absent_rather_than_stored_as_nothing(client, fx, module_id):
    """Storing a null would *clear* a default on open - a change the person
    saving never made."""
    r = save(client, fx, module_id, f"partial-{uuid.uuid4().hex[:6]}",
             {"v_region": "north", "v_status": None})
    state_id = r.json()["id"]
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.json()["values"] == {"v_region": "north"}


def test_a_state_survives_the_variable_being_renamed(client, fx):
    """p.203's whole reason for keying on the external ID: "state saving will
    continue to work as long as the output object set from those widgets uses
    the same external ID". The label, the id and the *kind* may all move."""
    module_id = make_module(client, fx, DOCUMENT)
    r = save(client, fx, module_id, "kept", {"v_region": "north"})
    state_id = r.json()["id"]

    rebuilt = {
        **DOCUMENT,
        "variables": {
            # Different variable id, different label - same external ID.
            "v_rebuilt": {
                "id": "v_rebuilt", "kind": "string", "label": "Where",
                "external_id": "region", "save_state": True,
            },
        },
    }
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{module_id}/definition",
        headers=hdr(fx.editor_sub), json={"definition": rebuilt},
    )
    assert r.status_code == 200, r.text

    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.json()["values"] == {"v_rebuilt": "north"}
    assert r.json()["missing"] == []


def test_a_state_that_came_back_incomplete_says_so(client, fx):
    """p.203 warns that changing an external ID "may cause previously
    configured states to reload unsuccessfully". Restoring what still applies
    beats refusing the whole state - but a reader has to be told which part of
    their saved view did not come back."""
    module_id = make_module(client, fx, DOCUMENT)
    r = save(client, fx, module_id, "stale", {"v_region": "north", "v_status": "open"})
    state_id = r.json()["id"]

    narrowed = {**DOCUMENT, "variables": {"v_region": saved("region")}}
    client.put(
        f"{pbase(fx)}/canvas-apps/{module_id}/definition",
        headers=hdr(fx.editor_sub), json={"definition": narrowed},
    )
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.json()["values"] == {"v_region": "north"}
    assert r.json()["missing"] == ["status"]


# ---- the page (p.200) --------------------------------------------------------
def test_a_state_can_carry_the_page_the_viewer_was_on(client, fx, module_id):
    r = save(client, fx, module_id, f"paged-{uuid.uuid4().hex[:6]}",
             {"v_region": "north"}, page_id="notes")
    assert r.json()["page_id"] == "notes"


def test_turning_the_page_option_off_stops_states_carrying_one(client, fx):
    """p.200 calls the page "optional", and off has to mean *not stored* rather
    than merely not written - a state that quietly kept a page would move the
    reader somewhere the module said it would not."""
    module_id = make_module(
        client, fx, {**DOCUMENT, "state_saving": {"enabled": True, "include_page": False}}
    )
    r = save(client, fx, module_id, "nopage", {"v_region": "north"}, page_id="notes")
    assert r.json()["page_id"] is None


# ---- who may do what ---------------------------------------------------------
def test_saving_a_state_is_a_viewer_action(client, fx, module_id):
    """p.200 calls this a feature for "module consumers". Requiring the editor
    role would put it behind exactly the permission its audience lacks."""
    r = save(client, fx, module_id, f"viewer-{uuid.uuid4().hex[:6]}",
             {"v_region": "north"}, sub=fx.viewer_sub)
    assert r.status_code == 201, r.text


def test_saving_over_your_own_state_updates_it(client, fx, module_id):
    name = f"mine-{uuid.uuid4().hex[:6]}"
    first = save(client, fx, module_id, name, {"v_region": "north"}).json()["id"]
    second = save(client, fx, module_id, name, {"v_region": "south"})
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first, "an update, not a second state"
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{first}", headers=hdr(fx.editor_sub)
    )
    assert r.json()["values"] == {"v_region": "south"}


def test_saving_over_somebody_elses_state_is_refused(client, fx, module_id):
    """A shared view replaced without a word is the failure state saving's
    second sentence invites - "share the saved state with other users"."""
    name = f"theirs-{uuid.uuid4().hex[:6]}"
    save(client, fx, module_id, name, {"v_region": "north"}, sub=fx.editor_sub)
    r = save(client, fx, module_id, name, {"v_region": "south"}, sub=fx.viewer_sub)
    assert r.status_code == 403, r.text
    assert "somebody else" in r.json()["detail"]


def test_deleting_somebody_elses_state_is_refused(client, fx, module_id):
    name = f"del-{uuid.uuid4().hex[:6]}"
    state_id = save(client, fx, module_id, name, {"v_region": "north"},
                    sub=fx.editor_sub).json()["id"]
    r = client.delete(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 403, r.text
    r = client.delete(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text


def test_a_state_of_another_module_does_not_open_here(client, fx, module_id):
    """Keyed by external ID, so some of another module's values might even
    match - which is exactly why the module has to be checked rather than
    assumed from the id in the path."""
    other = make_module(client, fx, DOCUMENT)
    state_id = save(client, fx, other, "elsewhere", {"v_region": "north"}).json()["id"]
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 404, r.text


# ---- the module's own settings -----------------------------------------------
def test_a_module_that_does_not_save_state_refuses_to(client, fx):
    module_id = make_module(client, fx, {**DOCUMENT, "state_saving": {"enabled": False}})
    r = save(client, fx, module_id, "nope", {"v_region": "north"})
    assert r.status_code == 409, r.text
    assert "does not save state" in r.json()["detail"]


def test_turning_state_saving_off_closes_the_states_already_saved(client, fx):
    """A state opened after the feature was turned off is a view the module no
    longer offers. Restoring it would be the module disagreeing with its own
    settings - and the states are still there if it is turned back on."""
    module_id = make_module(client, fx, DOCUMENT)
    state_id = save(client, fx, module_id, "before", {"v_region": "north"}).json()["id"]
    client.put(
        f"{pbase(fx)}/canvas-apps/{module_id}/definition",
        headers=hdr(fx.editor_sub),
        json={"definition": {**DOCUMENT, "state_saving": {"enabled": False}}},
    )
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states/{state_id}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 409, r.text


def test_states_are_listed_newest_first_with_their_author(client, fx):
    module_id = make_module(client, fx, DOCUMENT)
    save(client, fx, module_id, "one", {"v_region": "north"})
    save(client, fx, module_id, "two", {"v_region": "south"})
    r = client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}/states", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    names = [s["name"] for s in r.json()]
    assert names == ["two", "one"], names
    assert all(s["created_by_name"] for s in r.json())


# ---- the published path (the audience this exists for) -----------------------
def test_a_published_module_saves_and_opens_states_for_a_workspace_member(client, fx):
    """The whole point of the second router: a published module is reached by
    somebody who is not in its project, and state saving is for consumers."""
    module_id = make_module(client, fx, DOCUMENT)
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{module_id}/publish",
        headers=hdr(fx.admin_sub), json={"scope": "workspace"},
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{wbase(fx)}/published-canvas-apps/{module_id}/states",
        headers=hdr(fx.viewer_sub),
        json={"name": "shared view", "values": {"v_region": "north"}},
    )
    assert r.status_code == 201, r.text
    state_id = r.json()["id"]

    r = client.get(
        f"{wbase(fx)}/published-canvas-apps/{module_id}/states/{state_id}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert r.json()["values"] == {"v_region": "north"}

    # And it is shared: another member sees it in the list.
    r = client.get(
        f"{wbase(fx)}/published-canvas-apps/{module_id}/states", headers=hdr(fx.editor_sub)
    )
    assert [s["name"] for s in r.json()] == ["shared view"]
