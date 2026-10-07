"""Changing and removing workspaces and their members (§910).

The routes were covered only for who may *not* call them. Nothing ran
renaming, deleting, re-roling or removing as somebody who may, and nothing
checked that the row a request names belongs to the workspace or
organisation it came through. Those are the cases here.
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
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def new_workspace(client: TestClient, fx: Fixture) -> str:
    r = client.post("/api/workspaces", headers=hdr(fx.admin_sub),
                    json={"name": f"Admin {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_workspace_admin_renames_it_and_an_editor_may_not(client: TestClient, fx: Fixture) -> None:
    wid = new_workspace(client, fx)
    r = client.patch(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub),
                     json={"name": "Renamed", "description": "Now described"})
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["description"]) == ("Renamed", "Now described")
    # A field left out keeps its value.
    r = client.patch(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub), json={"name": "Again"})
    assert (r.json()["name"], r.json()["description"]) == ("Again", "Now described")
    r = client.patch(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.editor_sub),
                     json={"name": "nope"})
    assert r.status_code == 403


def test_another_organisations_admin_cannot_delete_a_workspace(
    client: TestClient, fx: Fixture
) -> None:
    """The route asks only that the caller administers *an* organisation; the
    row a delete reaches has to be one of theirs."""
    wid = new_workspace(client, fx)
    r = client.delete(f"/api/workspaces/{wid}", headers=hdr(fx.foreign_sub))
    assert r.status_code == 404
    assert client.get(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub)).status_code == 200


def test_an_org_admin_deletes_a_workspace(client: TestClient, fx: Fixture) -> None:
    wid = new_workspace(client, fx)
    assert client.delete(f"/api/workspaces/{wid}", headers=hdr(fx.editor_sub)).status_code == 403
    assert client.delete(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub)).status_code == 204
    assert client.get(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub)).status_code == 404
    assert client.delete(f"/api/workspaces/{wid}", headers=hdr(fx.admin_sub)).status_code == 404


def test_a_member_is_re_roled_and_removed(client: TestClient, fx: Fixture) -> None:
    wid = new_workspace(client, fx)
    r = client.post(f"/api/workspaces/{wid}/members", headers=hdr(fx.admin_sub),
                    json={"user_id": str(fx.outsider), "role": "viewer"})
    assert r.status_code == 201, r.text
    member = r.json()["id"]
    assert client.get(f"/api/workspaces/{wid}", headers=hdr(fx.outsider_sub)).json()[
        "effective_role"] == "viewer"

    r = client.patch(f"/api/workspaces/{wid}/members/{member}", headers=hdr(fx.admin_sub),
                     json={"role": "editor"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "editor"
    auth_mw.clear_identity_cache()
    assert client.get(f"/api/workspaces/{wid}", headers=hdr(fx.outsider_sub)).json()[
        "effective_role"] == "editor"

    r = client.delete(f"/api/workspaces/{wid}/members/{member}", headers=hdr(fx.admin_sub))
    assert r.status_code == 204
    auth_mw.clear_identity_cache()
    assert client.get(f"/api/workspaces/{wid}", headers=hdr(fx.outsider_sub)).status_code == 404
    r = client.delete(f"/api/workspaces/{wid}/members/{member}", headers=hdr(fx.admin_sub))
    assert r.status_code == 404


def test_a_member_is_reached_only_through_its_own_workspace(
    client: TestClient, fx: Fixture
) -> None:
    """An admin of one workspace naming a membership of another changes
    nothing: the member id is looked up within the workspace in the path."""
    mine, theirs = new_workspace(client, fx), new_workspace(client, fx)
    r = client.post(f"/api/workspaces/{theirs}/members", headers=hdr(fx.admin_sub),
                    json={"user_id": str(fx.outsider), "role": "viewer"})
    member = r.json()["id"]
    r = client.patch(f"/api/workspaces/{mine}/members/{member}", headers=hdr(fx.admin_sub),
                     json={"role": "admin"})
    assert r.status_code == 404
    assert client.delete(f"/api/workspaces/{mine}/members/{member}",
                         headers=hdr(fx.admin_sub)).status_code == 404
    auth_mw.clear_identity_cache()
    assert client.get(f"/api/workspaces/{theirs}", headers=hdr(fx.outsider_sub)).json()[
        "effective_role"] == "viewer"


def test_a_role_is_one_of_three_and_only_an_admin_sets_it(client: TestClient, fx: Fixture) -> None:
    wid = new_workspace(client, fx)
    member = client.post(f"/api/workspaces/{wid}/members", headers=hdr(fx.admin_sub),
                         json={"user_id": str(fx.outsider), "role": "viewer"}).json()["id"]
    r = client.patch(f"/api/workspaces/{wid}/members/{member}", headers=hdr(fx.admin_sub),
                     json={"role": "owner"})
    assert r.status_code == 422
    r = client.patch(f"/api/workspaces/{fx.workspace}/members/{member}",
                     headers=hdr(fx.editor_sub), json={"role": "admin"})
    assert r.status_code == 403


# ---- the organisation ---------------------------------------------------------
def test_an_org_admin_promotes_and_demotes_a_member(client: TestClient, fx: Fixture) -> None:
    r = client.patch(f"/api/org/members/{fx.outsider}", headers=hdr(fx.admin_sub),
                     json={"org_role": "admin"})
    assert r.status_code == 200, r.text
    assert r.json()["org_role"] == "admin"
    auth_mw.clear_identity_cache()
    # Now an org admin, the member administers every workspace.
    assert client.get(f"/api/workspaces/{fx.workspace}", headers=hdr(fx.outsider_sub)).json()[
        "effective_role"] == "admin"
    r = client.patch(f"/api/org/members/{fx.outsider}", headers=hdr(fx.admin_sub),
                     json={"org_role": "member"})
    assert r.json()["org_role"] == "member"
    auth_mw.clear_identity_cache()
    assert client.get(f"/api/workspaces/{fx.workspace}",
                      headers=hdr(fx.outsider_sub)).status_code == 404


def test_the_owner_keeps_the_organisation(client: TestClient, fx: Fixture) -> None:
    """The owner's role is not changed here, and the owner is not disabled:
    either would leave an organisation nobody owns."""
    r = client.patch(f"/api/org/members/{fx.owner}", headers=hdr(fx.admin_sub),
                     json={"org_role": "member"})
    assert r.status_code == 422
    assert "owner" in r.json()["detail"]
    assert client.delete(f"/api/org/members/{fx.owner}",
                         headers=hdr(fx.admin_sub)).status_code == 404
    auth_mw.clear_identity_cache()
    assert client.get("/api/auth/me", headers=hdr(fx.owner_sub)).status_code == 200


def test_org_administration_stays_in_its_own_organisation(client: TestClient, fx: Fixture) -> None:
    # Another organisation's owner cannot re-role or disable a member here...
    r = client.patch(f"/api/org/members/{fx.viewer}", headers=hdr(fx.foreign_sub),
                     json={"org_role": "admin"})
    assert r.status_code == 404
    assert client.delete(f"/api/org/members/{fx.viewer}",
                         headers=hdr(fx.foreign_sub)).status_code == 404
    # ...nor take a member out of one of its groups.
    gid = client.post("/api/org/groups", headers=hdr(fx.admin_sub),
                      json={"name": f"Kept {uuid.uuid4().hex[:6]}"}).json()["id"]
    assert client.put(f"/api/org/groups/{gid}/members/{fx.viewer}",
                      headers=hdr(fx.admin_sub)).status_code == 204
    assert client.delete(f"/api/org/groups/{gid}/members/{fx.viewer}",
                         headers=hdr(fx.foreign_sub)).status_code == 404
    # The organisation's own admin can, once.
    assert client.delete(f"/api/org/groups/{gid}/members/{fx.viewer}",
                         headers=hdr(fx.admin_sub)).status_code == 204
    assert client.delete(f"/api/org/groups/{gid}/members/{fx.viewer}",
                         headers=hdr(fx.admin_sub)).status_code == 404
    auth_mw.clear_identity_cache()
    assert client.get("/api/auth/me", headers=hdr(fx.viewer_sub)).json()["org_role"] == "member"


def test_only_an_org_admin_changes_org_roles(client: TestClient, fx: Fixture) -> None:
    r = client.patch(f"/api/org/members/{fx.viewer}", headers=hdr(fx.editor_sub),
                     json={"org_role": "admin"})
    assert r.status_code == 403
    r = client.patch(f"/api/org/members/{fx.viewer}", headers=hdr(fx.admin_sub),
                     json={"org_role": "owner"})
    assert r.status_code == 422
