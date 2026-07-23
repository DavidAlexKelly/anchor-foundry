"""Canvas app tests: project-scoped CRUD, definition versioning, publishing
(private/workspace/groups) and its workspace-admin gate, and the
workspace-wide read path for a published app reaching someone who isn't a
member of the app's own project. Mirrors test_actions.py's fixture shape.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]


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


def base(fx: Fixture, project_id: str | None = None) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{project_id or fx.project}/canvas-apps"


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


@pytest.fixture(scope="module")
def custom_project(fx: Fixture) -> dict[str, str]:
    """A second project, permission_mode='custom', where the workspace
    viewer is explicitly revoked ('none') — the case the workspace-wide
    published-app read path exists for: a real workspace member who has no
    access to this project's own resources."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        pid = conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode)
               VALUES (%s,%s,%s,%s,'custom') RETURNING id""",
            (fx.workspace, f"Custom {fx.tag}", f"custom-{fx.tag}", fx.owner),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'editor')",
            (pid, fx.editor),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'none')",
            (pid, fx.viewer),
        )
    return {"id": str(pid)}


@pytest.fixture(scope="module")
def shared_group(fx: Fixture) -> dict[str, str]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        gid = conn.execute(
            "INSERT INTO groups (organisation_id, name) VALUES (%s,%s) RETURNING id",
            (fx.org, f"Canvas Sharees {fx.tag}"),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO group_members (group_id, user_id) VALUES (%s,%s)", (gid, fx.viewer)
        )
    return {"id": str(gid)}


# ---- CRUD ---------------------------------------------------------------------
def test_viewer_cannot_create_but_can_list(client: TestClient, fx: Fixture) -> None:
    r = client.post(base(fx), headers=hdr(fx.viewer_sub), json={"name": "X"})
    assert r.status_code == 403
    r = client.get(base(fx), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200


def test_editor_creates_app(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Dashboard {fx.tag}", "description": "a test app"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == f"dashboard-{fx.tag}"
    assert body["current_version"] == 0
    assert body["publish_scope"] == "private"
    assert body["definition"] == {}


def _app_id(client: TestClient, fx: Fixture) -> str:
    r = client.get(base(fx), headers=hdr(fx.editor_sub))
    return next(a["id"] for a in r.json() if a["name"] == f"Dashboard {fx.tag}")


def test_duplicate_name_conflicts(client: TestClient, fx: Fixture) -> None:
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={"name": f"Dashboard {fx.tag}"})
    assert r.status_code == 409


def test_outsider_gets_404(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    assert client.get(f"{base(fx)}/{aid}", headers=hdr(fx.outsider_sub)).status_code == 404


def test_editor_updates_metadata(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.patch(
        f"{base(fx)}/{aid}", headers=hdr(fx.editor_sub), json={"description": "updated"}
    )
    assert r.status_code == 200
    assert r.json()["description"] == "updated"


# ---- definition versioning ------------------------------------------------------
def test_save_definition_versions(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/definition", headers=hdr(fx.editor_sub),
        json={"definition": {"ROOT": {"type": "Container", "nodes": []}}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 1
    assert r.json()["definition"]["ROOT"]["type"] == "Container"

    r = client.put(
        f"{base(fx)}/{aid}/definition", headers=hdr(fx.editor_sub),
        json={"definition": {"ROOT": {"type": "Container", "nodes": ["a"]}}},
    )
    assert r.status_code == 200
    assert r.json()["current_version"] == 2

    r = client.get(f"{base(fx)}/{aid}/versions", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    versions = r.json()
    assert [v["version_number"] for v in versions] == [2, 1]


def test_viewer_cannot_save_definition(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/definition", headers=hdr(fx.viewer_sub), json={"definition": {}}
    )
    assert r.status_code == 403


# ---- publishing -----------------------------------------------------------------
def test_editor_cannot_publish_beyond_project(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/publish", headers=hdr(fx.editor_sub), json={"scope": "workspace"}
    )
    assert r.status_code == 403
    assert "workspace admin" in r.json()["detail"]


def test_admin_publishes_to_workspace(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/publish", headers=hdr(fx.admin_sub), json={"scope": "workspace"}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["publish_scope"] == "workspace"
    assert body["published_at"] is not None


def test_publish_to_unknown_group_is_422(client: TestClient, fx: Fixture) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/publish", headers=hdr(fx.admin_sub),
        json={"scope": "groups", "group_ids": [str(uuid.uuid4())]},
    )
    assert r.status_code == 422


def test_publish_to_group_and_list_shares(
    client: TestClient, fx: Fixture, shared_group: dict[str, str]
) -> None:
    aid = _app_id(client, fx)
    r = client.put(
        f"{base(fx)}/{aid}/publish", headers=hdr(fx.admin_sub),
        json={"scope": "groups", "group_ids": [shared_group["id"]]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["publish_scope"] == "groups"

    r = client.get(f"{base(fx)}/{aid}/shares", headers=hdr(fx.editor_sub))
    assert r.status_code == 200
    assert [s["group_id"] for s in r.json()] == [shared_group["id"]]

    # Revert to private for the cross-project visibility tests below.
    r = client.put(
        f"{base(fx)}/{aid}/publish", headers=hdr(fx.admin_sub), json={"scope": "private"}
    )
    assert r.status_code == 200
    assert r.json()["publish_scope"] == "private" and r.json()["published_at"] is None


# ---- cross-project visibility via the workspace-wide read path ------------------
def test_revoked_project_member_gets_404_directly(
    client: TestClient, fx: Fixture, custom_project: dict[str, str]
) -> None:
    r = client.post(
        base(fx, custom_project["id"]), headers=hdr(fx.editor_sub), json={"name": "Custom App"}
    )
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    # The revoked viewer can't reach it through the project-scoped route.
    assert client.get(f"{base(fx, custom_project['id'])}/{app_id}", headers=hdr(fx.viewer_sub)).status_code == 404
    # Nor does it show up in the workspace-wide published gallery while private.
    r = client.get(f"{wbase(fx)}/published-canvas-apps", headers=hdr(fx.viewer_sub))
    assert app_id not in {a["id"] for a in r.json()}


def test_published_to_workspace_reaches_revoked_member(
    client: TestClient, fx: Fixture, custom_project: dict[str, str]
) -> None:
    r = client.get(base(fx, custom_project["id"]), headers=hdr(fx.editor_sub))
    app_id = next(a["id"] for a in r.json() if a["name"] == "Custom App")
    r = client.put(
        f"{base(fx, custom_project['id'])}/{app_id}/publish",
        headers=hdr(fx.admin_sub), json={"scope": "workspace"},
    )
    assert r.status_code == 200, r.text

    r = client.get(f"{wbase(fx)}/published-canvas-apps", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert app_id in {a["id"] for a in r.json()}

    r = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.json()["id"] == app_id

    # A true outsider (no workspace role at all) still gets nothing.
    r = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


# ---- delete + audit ---------------------------------------------------------------
def test_delete_removes_app(client: TestClient, fx: Fixture) -> None:
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={"name": "Throwaway"})
    aid = r.json()["id"]
    assert client.delete(f"{base(fx)}/{aid}", headers=hdr(fx.editor_sub)).status_code == 204
    assert client.get(f"{base(fx)}/{aid}", headers=hdr(fx.editor_sub)).status_code == 404


def test_canvas_actions_audited(client: TestClient, fx: Fixture) -> None:
    r = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    actions = {e["action"] for e in r.json()}
    assert {
        "canvas_app.create", "canvas_app.update", "canvas_app.save",
        "canvas_app.publish", "canvas_app.delete",
    } <= actions
