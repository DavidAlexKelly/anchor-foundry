"""Webhooks as rows: what may be saved, by whom, and what a delete costs (§259).

The half that needs a database. What a definition *means* is
`test_webhooks.py`; what actually goes over a socket is
`test_webhook_calls.py`. Nothing here makes a request.
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
from src.routes import connections as conn_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def new_connection(client: TestClient, fx: Fixture, source_type="rest", **over) -> str:
    payload = {
        "name": f"C {uuid.uuid4().hex[:8]}", "source_type": source_type,
        "scope": "project", "secret": {},
        "config": {"base_url": "https://example.invalid"} if source_type == "rest"
        else {"host": "db.invalid", "port": 5432, "database": "d", "user": "u"},
    }
    payload.update(over)
    r = client.post(f"{base(fx)}/connections", headers=hdr(fx.editor_sub), json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def connection(client: TestClient, fx: Fixture) -> str:
    return new_connection(client, fx)


def payload(connection: str, **over) -> dict:
    out = {
        "connection_id": connection,
        "api_name": f"hook_{uuid.uuid4().hex[:8]}",
        "display_name": "Modify ticket priority",
        "method": "POST",
        "path": "items",
    }
    out.update(over)
    return out


def create(client: TestClient, fx: Fixture, connection: str, sub=None, **over):
    return client.post(
        f"{base(fx)}/webhooks", headers=hdr(sub or fx.editor_sub),
        json=payload(connection, **over),
    )


# ---- what may be saved -----------------------------------------------------------
def test_a_webhook_round_trips(client: TestClient, fx: Fixture, connection: str) -> None:
    r = create(
        client, fx, connection,
        body={"text": "{{{name}}}"}, inputs=[{"api_name": "name"}],
        outputs=[{"api_name": "id", "path": "results.id"}],
    )
    assert r.status_code == 201, r.text
    made = r.json()
    got = client.get(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert got["body"] == {"text": "{{{name}}}"}
    assert got["inputs"] == [{"api_name": "name", "data_type": "string", "required": True}]
    assert got["outputs"] == [
        {"api_name": "id", "data_type": "string", "path": "results.id"}
    ]
    # The connection is named on the way out, because a list of webhooks that
    # only carried ids would need a second fetch to be readable.
    assert got["connection_name"]


def test_a_definition_the_service_refuses_never_reaches_a_row(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """Save time rather than click time — §129's argument, and here the click
    is a request to somebody else's production system."""
    r = create(client, fx, connection, path="items/{{{nope}}}")
    assert r.status_code == 422
    assert "not an input" in r.json()["detail"]


def test_two_webhooks_cannot_share_an_api_name(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    name = f"hook_{uuid.uuid4().hex[:8]}"
    assert create(client, fx, connection, api_name=name).status_code == 201
    clash = create(client, fx, connection, api_name=name)
    assert clash.status_code == 409
    assert name in clash.json()["detail"]


def test_a_webhook_needs_a_rest_connection(client: TestClient, fx: Fixture) -> None:
    """p.220: "Some other source types also support webhooks." Ours support
    one, and saying which beats a request that fails at call time against a
    Postgres connection."""
    postgres = new_connection(client, fx, source_type="postgres")
    r = create(client, fx, postgres)
    assert r.status_code == 409
    assert "REST connection" in r.json()["detail"]


def test_a_connection_in_another_project_does_not_exist(
    client: TestClient, fx: Fixture
) -> None:
    """Resolved before the insert rather than left to the foreign key: the FK
    answers "no such row" for a connection somewhere else and for one of the
    wrong type alike, and those are different sentences."""
    other = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}"},
    )
    assert other.status_code == 201, other.text
    elsewhere = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{other.json()['id']}/connections",
        headers=hdr(fx.owner_sub),
        json={"name": "Far", "source_type": "rest", "scope": "project",
              "config": {"base_url": "https://example.invalid"}, "secret": {}},
    )
    assert elsewhere.status_code == 201, elsewhere.text

    r = create(client, fx, elsewhere.json()["id"])
    assert r.status_code == 404


def test_a_workspace_scoped_connection_is_usable_from_this_project(
    client: TestClient, fx: Fixture
) -> None:
    """The other side of the check above, and the one that makes it a rule
    rather than a project-id comparison: db 0003's `workspace` scope means
    "shared across the workspace's projects", so refusing it would be refusing
    what the scope is for."""
    shared = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.owner_sub),
        json={"name": f"Shared {uuid.uuid4().hex[:6]}", "source_type": "rest",
              "scope": "workspace",
              "config": {"base_url": "https://example.invalid"}, "secret": {}},
    )
    assert shared.status_code == 201, shared.text
    assert create(client, fx, shared.json()["id"]).status_code == 201


def test_an_edit_replaces_the_whole_definition(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """A PUT is the whole document, so a field dropped from the body is dropped
    from the row. Checked because `create` and `update` write the same twelve
    columns through one helper, and the failure the helper prevents is a field
    that saves on create and vanishes on the next edit."""
    made = create(
        client, fx, connection, body={"a": 1}, timeout_seconds=45,
        retry_statuses=[503], store_responses=False,
    ).json()
    r = client.put(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.editor_sub),
        json={
            "connection_id": connection, "display_name": "Renamed",
            "method": "GET", "path": "other", "body": None,
            "timeout_seconds": 45, "retry_statuses": [503],
            "store_responses": False,
        },
    )
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["display_name"] == "Renamed"
    assert got["method"] == "GET" and got["body"] is None
    # The fields that were *not* in the previous shape survive the round trip,
    # which is what says the helper writes them on both paths.
    assert got["timeout_seconds"] == 45
    assert got["retry_statuses"] == [503]
    assert got["store_responses"] is False


def test_the_api_name_is_not_editable(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """Absent rather than unchecked. A rename is a different operation from an
    edit — one that has to ask who points at the old name — and nothing points
    at a webhook until §260's action rule. §252's implements column is the
    argument: offer it when it can be answered."""
    made = create(client, fx, connection).json()
    r = client.put(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.editor_sub),
        json={"connection_id": connection, "display_name": "X",
              "api_name": "something_else", "method": "POST", "path": ""},
    )
    assert r.status_code == 200, r.text
    assert r.json()["api_name"] == made["api_name"]


def test_a_webhook_can_be_deleted(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    made = create(client, fx, connection).json()
    assert client.delete(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.get(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 404


def test_deleting_a_connection_a_webhook_uses_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """db 0067 makes the foreign key `ON DELETE RESTRICT` so the database
    refuses; the point of the check is that the refusal is a *sentence* rather
    than a 500 from a constraint name."""
    doomed = new_connection(client, fx)
    create(client, fx, doomed, display_name="Still in use")
    r = client.delete(
        f"{base(fx)}/connections/{doomed}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 409, r.text
    assert "Still in use" in r.json()["detail"]


# ---- who may do it ----------------------------------------------------------------
def test_a_viewer_may_read_and_may_not_write(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    made = create(client, fx, connection).json()
    assert client.get(
        f"{base(fx)}/webhooks", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    assert create(client, fx, connection, sub=fx.viewer_sub).status_code == 403
    assert client.delete(
        f"{base(fx)}/webhooks/{made['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 403


def test_a_viewer_may_not_make_the_test_call(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """It reaches out of the platform, which is why `POST /connections/{id}/test`
    sits at editor too. A read that can make an outbound request to somebody
    else's system is not a read."""
    made = create(client, fx, connection).json()
    r = client.post(
        f"{base(fx)}/webhooks/{made['id']}/test", headers=hdr(fx.viewer_sub),
        json={"values": {}},
    )
    assert r.status_code == 403


def test_a_stranger_sees_no_webhooks(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{base(fx)}/webhooks", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


# ---- the workspace-wide listing (§262) ------------------------------------------
def test_the_workspace_listing_crosses_projects(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """**Not the project listing, and the difference is the whole point.**

    An action type is a workspace resource and can be run from any project that
    maps an instance of its object type, so `_validate_definition` resolves a
    rule's webhook workspace-wide. A picker fed by the *project* listing would
    offer a narrower set than the server accepts — §258's defect, which is why
    this endpoint exists rather than the editor reusing the one next door.

    Asserted as a strict superset rather than as a count, so it stays a claim
    about the two listings answering different questions.
    """
    here = create(client, fx, connection, display_name="In this project").json()
    other = client.post(
        f"{wbase(fx)}/projects", headers=hdr(fx.owner_sub),
        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}"},
    )
    assert other.status_code == 201, other.text
    far_connection = client.post(
        f"{wbase(fx)}/projects/{other.json()['id']}/connections",
        headers=hdr(fx.owner_sub),
        json={"name": "Far", "source_type": "rest", "scope": "project",
              "config": {"base_url": "https://example.invalid"}, "secret": {}},
    )
    assert far_connection.status_code == 201, far_connection.text
    far = client.post(
        f"{wbase(fx)}/projects/{other.json()['id']}/webhooks", headers=hdr(fx.owner_sub),
        json={"connection_id": far_connection.json()["id"],
              "api_name": f"hook_{uuid.uuid4().hex[:8]}",
              "display_name": "In another project", "method": "POST", "path": ""},
    )
    assert far.status_code == 201, far.text

    workspace_wide = {
        row["id"] for row in client.get(
            f"{wbase(fx)}/webhooks", headers=hdr(fx.editor_sub)
        ).json()
    }
    project_only = {
        row["id"] for row in client.get(
            f"{base(fx)}/webhooks", headers=hdr(fx.editor_sub)
        ).json()
    }
    assert here["id"] in workspace_wide and far.json()["id"] in workspace_wide
    assert here["id"] in project_only and far.json()["id"] not in project_only
    assert project_only < workspace_wide


def test_a_stranger_sees_no_workspace_webhooks(
    client: TestClient, fx: Fixture
) -> None:
    """It names what an action may call, so it is gated by seeing the workspace
    at all — and db 0067's project policy narrows it further to the projects
    the caller can actually reach, which is the same narrowing the validation
    gets."""
    r = client.get(f"{wbase(fx)}/webhooks", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"
