"""The Check access panel's route (Foundry `workshop` p.92).

    "You can use the Check access panel in the sidebar to easily check a
     user's access on a Workshop module. This will show if they meet the
     access requirement on the Workshop module, as well as additional data
     requirements to see object types, link types, action types, and
     functions."

`test_module_access.py` covers what a module *references* and is pure. This
covers the half that can only be asked of a database: what one named user may
do with those references, resolved on a connection opened as them.

The case p.92's warning is about, and the one these tests are built around: a
module published to the workspace opens for a viewer, and **running** an
action is a project editor's right. The panel is the only place that pairing
is visible before somebody presses the button.
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

#: A well-formed id that names nothing. §210's distinction lives on this: the
#: panel must call it unknown rather than hidden, because a builder sent to ask
#: an administrator for a grant would be sent for nothing.
NOWHERE = "00000000-0000-4000-8000-0000000000ff"


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


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def base(fx: Fixture, project_id: str | None = None) -> str:
    return f"{wbase(fx)}/projects/{project_id or fx.project}/canvas-apps"


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """One of each kind p.92 names, plus a reference to nothing."""
    def declare(api_name: str, properties: list[dict]) -> str:
        r = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": api_name, "display_name": api_name.title(),
                  "properties": properties},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    customer = declare(f"access_customer_{fx.tag}", [
        {"api_name": "name", "data_type": "string"},
    ])
    order = declare(f"access_order_{fx.tag}", [
        {"api_name": "customer_id", "data_type": "string"},
        {"api_name": "total", "data_type": "integer"},
    ])

    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"access_placed_by_{fx.tag}", "display_name": "Placed by",
              "from_type_id": order, "to_type_id": customer,
              "cardinality": "one_to_many",
              "from_property": "customer_id", "to_property": "$primary_key",
              "from_side_name": "Orders", "to_side_name": "Placed by"},
    )
    assert r.status_code == 201, r.text
    link = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": customer, "api_name": f"rename_{fx.tag}",
              "display_name": "Rename customer", "editable_properties": ["name"]},
    )
    assert r.status_code == 201, r.text
    return {"customer": customer, "order": order, "link": link,
            "action": r.json()["id"]}


def document(world: dict) -> dict:
    """A module naming every kind, with the link type buried in a widget prop
    so the stored document is the source rather than a rendered page."""
    return {
        "format": 2, "variables": {}, "events": {},
        "layout": {
            "ROOT": {"type": "Container", "nodes": ["t", "g"]},
            "t": {"type": {"resolvedName": "CanvasObjectTable"},
                  "props": {"objectTypeId": world["customer"],
                            "actionTypeId": world["action"],
                            "traversal": {"base": {"link_type_id": world["link"]}}}},
            "g": {"type": {"resolvedName": "CanvasObjectTable"},
                  "props": {"objectTypeId": NOWHERE}},
        },
    }


def make_app(client: TestClient, fx: Fixture, world: dict,
             project_id: str | None = None) -> str:
    r = client.post(base(fx, project_id), headers=hdr(fx.editor_sub),
                    json={"name": f"Access {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(f"{base(fx, project_id)}/{app_id}/definition",
                   headers=hdr(fx.editor_sub),
                   json={"definition": document(world)})
    assert r.status_code == 200, r.text
    return app_id


@pytest.fixture(scope="module")
def app_id(client: TestClient, fx: Fixture, world: dict) -> str:
    return make_app(client, fx, world)


def check(client: TestClient, fx: Fixture, app_id: str, subject: str,
          project_id: str | None = None, sub: str | None = None):
    return client.get(
        f"{base(fx, project_id)}/{app_id}/access",
        headers=hdr(sub or fx.editor_sub), params={"user_id": subject},
    )


def by_id(body: dict) -> dict[str, dict]:
    return {r["id"]: r for r in body["resources"]}


def test_a_builder_meets_every_requirement(
    client: TestClient, fx: Fixture, world: dict, app_id: str
) -> None:
    """The baseline, and it has to be established before any refusal below
    means anything: the same module, the same resources, all met."""
    r = check(client, fx, app_id, str(fx.editor))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["id"] == str(fx.editor)
    assert body["user"]["active"] is True
    assert body["can_open"] is True
    assert body["can_edit"] is True
    assert body["project_role"] == "editor"
    assert body["workspace_role"] == "editor"

    found = by_id(body)
    assert found[world["customer"]]["status"] == "visible"
    assert found[world["link"]]["status"] == "visible"
    assert found[world["action"]]["status"] == "visible"
    assert {r["kind"] for r in body["resources"]} == {
        "object_type", "link_type", "action_type"}


def test_a_reader_can_open_the_module_and_cannot_run_its_action(
    client: TestClient, fx: Fixture, world: dict, app_id: str
) -> None:
    """p.92's warning, as a fact about this platform rather than a quotation.

    The viewer opens the module and reads every type in the workspace; running
    an action is a project editor's right, so the Action Form draws and the
    button refuses. `unusable` is the word for that, and it is the one thing
    the panel knows that the module itself never says.
    """
    r = check(client, fx, app_id, str(fx.viewer))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_open"] is True
    assert body["can_edit"] is False
    assert body["project_role"] == "viewer"

    found = by_id(body)
    assert found[world["customer"]]["status"] == "visible"
    assert found[world["link"]]["status"] == "visible"
    assert found[world["action"]]["status"] == "unusable"
    # Named, not just refused: "you cannot run Rename customer" is actionable
    # and "you cannot run 7f3a-..." is not.
    assert found[world["action"]]["name"] == "Rename customer"


def test_somebody_outside_the_workspace_sees_none_of_it(
    client: TestClient, fx: Fixture, world: dict, app_id: str
) -> None:
    """The outsider is a member of the organisation and of nothing else, so
    every requirement fails at once - and each named resource still comes back
    with its display name, resolved on the *asker's* connection. Without that
    the panel would report three hidden uuids, which says something is wrong
    and nothing about what."""
    r = check(client, fx, app_id, str(fx.outsider))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_open"] is False
    assert body["can_edit"] is False
    assert body["project_role"] is None
    assert body["workspace_role"] is None

    found = by_id(body)
    assert found[world["customer"]]["status"] == "hidden"
    assert found[world["customer"]]["name"] == f"Access_Customer_{fx.tag}".title()
    assert found[world["link"]]["status"] == "hidden"
    assert found[world["link"]]["name"] == "Placed by"
    assert found[world["action"]]["status"] == "hidden"
    assert found[world["action"]]["name"] == "Rename customer"


def test_a_reference_to_nothing_is_unknown_rather_than_hidden(
    client: TestClient, fx: Fixture, app_id: str
) -> None:
    """§210. The asker cannot name it either, so it is not a permission
    problem - and reporting it as one would send the builder to an
    administrator for a grant that could not help. It is the same answer for
    the builder and for the outsider, which is what makes it about the id."""
    for subject in (fx.editor, fx.outsider):
        body = check(client, fx, app_id, str(subject)).json()
        row = by_id(body)[NOWHERE]
        assert row["status"] == "unknown", (subject, row)
        assert row["name"] is None


def test_publishing_opens_a_module_for_somebody_the_project_shuts_out(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The module half's second door.

    In a custom-permission project the viewer is revoked outright, so they hold
    no project role at all - and a module they cannot reach is the honest
    answer until it is published. Publishing changes that without changing
    their role, which is exactly the state a builder is checking for.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        pid = str(conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode)
               VALUES (%s,%s,%s,%s,'custom') RETURNING id""",
            (fx.workspace, f"Shut {fx.tag}", f"shut-{fx.tag}", fx.owner),
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'editor')",
            (pid, fx.editor),
        )
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'none')",
            (pid, fx.viewer),
        )

    private = make_app(client, fx, world, project_id=pid)
    body = check(client, fx, private, str(fx.viewer), project_id=pid).json()
    assert body["project_role"] is None
    assert body["can_open"] is False

    r = client.put(f"{base(fx, pid)}/{private}/publish", headers=hdr(fx.owner_sub),
                   json={"scope": "workspace", "group_ids": []})
    assert r.status_code == 200, r.text

    body = check(client, fx, private, str(fx.viewer), project_id=pid).json()
    assert body["project_role"] is None, "publishing grants no role"
    assert body["can_open"] is True
    assert body["can_edit"] is False


def test_a_reader_of_the_module_cannot_use_the_panel(
    client: TestClient, fx: Fixture, app_id: str
) -> None:
    """One person's access to another is a builder's question. The bar is the
    role that can change what the module requires, not the one that reads it."""
    r = check(client, fx, app_id, str(fx.editor), sub=fx.viewer_sub)
    assert r.status_code == 403, r.text


def test_a_user_of_another_organisation_is_not_found(
    client: TestClient, fx: Fixture, app_id: str
) -> None:
    """The id comes out of a URL. Without the organisation clause on the
    lookup, the panel would confirm the existence of accounts in organisations
    the asker has nothing to do with."""
    r = check(client, fx, app_id, str(fx.foreign))
    assert r.status_code == 404, r.text


def test_a_disabled_account_reaches_nothing_whatever_its_roles_say(
    client: TestClient, fx: Fixture, app_id: str
) -> None:
    """`get_current_user` refuses a non-active account before any route runs,
    so every role it still holds is a role it cannot use.

    `effective_workspace_role` checks `status` only on its org-admin branch, so
    it goes on reporting `editor` for this account - which is the honest answer
    to "what would they have if re-enabled" and the wrong one to "can they open
    it". The panel has to hold both, because a builder looking at a disabled
    account is about to ask the first question.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        uid = str(conn.execute(
            """INSERT INTO users (organisation_id, email, display_name,
                                  org_role, cognito_sub, status)
               VALUES (%s,%s,%s,'member',%s,'disabled') RETURNING id""",
            (fx.org, f"gone-{fx.tag}@example.com", "Gone Away",
             f"sub-gone-{fx.tag}"),
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'editor')",
            (fx.workspace, uid),
        )

    body = check(client, fx, app_id, uid).json()
    assert body["user"]["active"] is False
    assert body["can_open"] is False
    assert body["can_edit"] is False
    # Still reported, because re-enabling is the remedy and this says whether
    # it would be enough.
    assert body["project_role"] == "editor"
    assert body["workspace_role"] == "editor"
