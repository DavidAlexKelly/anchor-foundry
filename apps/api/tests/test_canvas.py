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
    viewer is explicitly revoked ('none') - the case the workspace-wide
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
    """Versioning, which has nothing to do with the format - this used to save
    v1 documents because they were shorter, and now saves the format the
    builder writes (see `test_saving_a_v1_definition_is_refused`)."""
    aid = _app_id(client, fx)
    first = {"format": 2, "variables": {}, "events": {},
             "layout": {"ROOT": {"type": "Container", "nodes": []}}}
    r = client.put(f"{base(fx)}/{aid}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": first})
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 1
    assert r.json()["definition"]["layout"]["ROOT"]["type"] == "Container"

    second = {**first, "layout": {"ROOT": {"type": "Container", "nodes": ["a"]}}}
    r = client.put(f"{base(fx)}/{aid}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": second})
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


def test_publishing_shares_the_layout_not_access_to_the_data(
    client: TestClient, fx: Fixture, custom_project: dict[str, str]
) -> None:
    """The thing a published app must never become is a way to launder access
    to data somebody was not given (roadmap Canvas item 6, which built the
    route that opens one).

    The viewer here can read the app - the test above proves it - and still
    cannot read the project's datasets, models or objects. That is the design,
    not a gap: every widget in a published app reads as whoever is looking, so
    an app published to the workspace shows a `permission_mode='custom'`
    project's data only to the people that project already trusted. The UI
    says what it could not read rather than rendering an empty table.
    """
    pid = custom_project["id"]
    for path in ("datasets", "models", "object-type-sources"):
        r = client.get(f"/api/workspaces/{fx.workspace}/projects/{pid}/{path}",
                       headers=hdr(fx.viewer_sub))
        assert r.status_code == 404, f"{path}: {r.status_code} {r.text}"

    # And the editor who does belong to the project still can.
    r = client.get(f"/api/workspaces/{fx.workspace}/projects/{pid}/datasets",
                   headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text


# ---- typed variables (roadmap phase 2, item 1.2) -----------------------------
# The service tests (test_workshop_variables.py) cover the graph. These cover
# the two things only the HTTP layer can prove: that a bad document is refused
# at *save* rather than discovered at view, and that evaluation is reachable.


def _module(variables: dict, layout: dict | None = None) -> dict:
    return {"format": 2, "layout": layout or {}, "variables": variables, "events": {}}


def _new_app(client: TestClient, fx: Fixture) -> str:
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Vars {uuid.uuid4().hex[:8]}"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_saving_a_module_with_a_dangling_binding_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """The save is where this has to be caught. A document with a binding to
    nothing renders as a widget showing everything, which looks like data."""
    app_id = _new_app(client, fx)
    layout = {"f1": {"type": {"resolvedName": "CanvasParameterControl"},
                     "props": {"filterParameter": "v_gone"}}}
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": _module({}, layout)})
    assert r.status_code == 422, r.text
    assert "v_gone" in r.json()["detail"]


def test_saving_a_module_with_a_variable_cycle_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    app_id = _new_app(client, fx)
    variables = {
        "v_a": {"id": "v_a", "kind": "string", "label": "Alpha",
                "derivation": {"transform": "concat", "inputs": ["v_b"]}},
        "v_b": {"id": "v_b", "kind": "string", "label": "Beta",
                "derivation": {"transform": "concat", "inputs": ["v_a"]}},
    }
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": _module(variables)})
    assert r.status_code == 422, r.text
    assert "loop" in r.json()["detail"]


# ---- run_action (roadmap phase 2, item 1.3) ----------------------------------
# The service tests cover the effect's own refusals. These cover the one thing
# only the HTTP layer can prove: that the save path looks the workspace's
# actions up at all, so a `run_action` naming one that is not there is refused
# by the person who wrote it rather than by whoever clicks it a month later.


def _action_module(action_id: str, values: dict) -> dict:
    return {
        "format": 2,
        "layout": {"btn": {"type": {"resolvedName": "CanvasButton"}, "props": {}}},
        "variables": {"v_obj": {"id": "v_obj", "kind": "single_object", "label": "Picked"}},
        "events": {
            "e_1": {
                "id": "e_1",
                "trigger": {"node": "btn", "on": "click"},
                "effects": [{
                    "type": "run_action",
                    "config": {"action": action_id, "subject": "v_obj", "values": values},
                }],
            }
        },
    }


def test_saving_a_run_action_for_an_action_the_workspace_lacks_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    app_id = _new_app(client, fx)
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": _action_module(str(uuid.uuid4()), {"status": "done"})})
    assert r.status_code == 422, r.text
    assert "does not have" in r.json()["detail"]


def test_a_run_action_naming_a_real_action_saves(client: TestClient, fx: Fixture) -> None:
    """And the properties it writes are checked against that action's own
    editable list - the same sentence the execute route would produce, said
    while the person who typed it is still looking."""
    tag = uuid.uuid4().hex[:8]
    otype = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ticket_{tag}", "display_name": f"Ticket {tag}",
              "properties": [
                  {"api_name": "key", "display_name": "Key", "data_type": "string",
                   "required": True},
                  {"api_name": "status", "display_name": "Status", "data_type": "string"},
              ],
              "title_property": "key"},
    )
    assert otype.status_code == 201, otype.text
    action = client.post(
        f"/api/workspaces/{fx.workspace}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": otype.json()["id"], "api_name": f"close_{tag}",
              "display_name": "Close", "editable_properties": ["status"]},
    )
    assert action.status_code == 201, action.text
    action_id = action.json()["id"]

    app_id = _new_app(client, fx)
    ok = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                    json={"definition": _action_module(action_id, {"status": "closed"})})
    assert ok.status_code == 200, ok.text

    bad = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                     json={"definition": _action_module(action_id, {"key": "X-1"})})
    assert bad.status_code == 422, bad.text
    assert "does not make editable" in bad.json()["detail"]


def test_a_saved_run_action_still_opens_after_its_action_is_deleted(
    client: TestClient, fx: Fixture
) -> None:
    """A document is checked against the workspace when it is *written*. An
    action deleted afterwards must not stop the app opening: a record of what
    somebody built does not become invalid because live state moved. The click
    reports it instead."""
    tag = uuid.uuid4().hex[:8]
    otype = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"order_{tag}", "display_name": f"Order {tag}",
              "properties": [{"api_name": "state", "display_name": "State",
                              "data_type": "string"}]},
    ).json()
    action = client.post(
        f"/api/workspaces/{fx.workspace}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": otype["id"], "api_name": f"ship_{tag}",
              "display_name": "Ship", "editable_properties": ["state"]},
    ).json()

    app_id = _new_app(client, fx)
    assert client.put(
        f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
        json={"definition": _action_module(action["id"], {"state": "shipped"})},
    ).status_code == 200

    assert client.delete(
        f"/api/workspaces/{fx.workspace}/action-types/{action['id']}",
        headers=hdr(fx.editor_sub),
    ).status_code in (204, 200)

    opened = client.get(f"{base(fx)}/{app_id}", headers=hdr(fx.viewer_sub))
    assert opened.status_code == 200, opened.text
    evaluated = client.post(
        f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.viewer_sub),
        json={"values": {}},
    )
    assert evaluated.status_code == 200, evaluated.text


def test_saving_a_v1_definition_is_refused(client: TestClient, fx: Fixture) -> None:
    """This case used to assert the opposite, and the premise it rested on -
    "every unconverted app must keep working" - stopped being true when
    migration 0034 converted every stored app (§71). The migration container
    runs before this code does, so an unconverted app cannot reach this route;
    what can is a script or a client older than the conversion, and what it
    would write is an app with no variables, events or pages.

    Reading v1 is untouched: 0034 deliberately leaves historical version rows
    in the format they were written in, and the browser still renders them.
    """
    app_id = _new_app(client, fx)
    v1 = {"ROOT": {"type": {"resolvedName": "CanvasContainer"}, "nodes": ["f1"]},
          "f1": {"type": {"resolvedName": "CanvasParameterControl"},
                 "props": {"name": "region", "filterParameter": "region"}}}
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": v1})
    assert r.status_code == 422, r.text
    assert "pre-Workshop" in r.json()["detail"]


def test_an_empty_definition_still_saves(client: TestClient, fx: Fixture) -> None:
    """`{}` is not a v1 document, it is an app with nothing in it - which is
    what every app is before somebody drags a widget onto it."""
    app_id = _new_app(client, fx)
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": {}})
    assert r.status_code == 200, r.text


def test_evaluating_variables_resolves_derived_ones(
    client: TestClient, fx: Fixture
) -> None:
    app_id = _new_app(client, fx)
    variables = {
        "v_first": {"id": "v_first", "kind": "string", "label": "First"},
        "v_last": {"id": "v_last", "kind": "string", "label": "Last", "default": "Lovelace"},
        "v_full": {"id": "v_full", "kind": "string", "label": "Full",
                   "derivation": {"transform": "concat", "inputs": ["v_first", "v_last"],
                                  "config": {"separator": " "}}},
    }
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": _module(variables)})
    assert r.status_code == 200, r.text

    r = client.post(f"{base(fx)}/{app_id}/variables/evaluate",
                    headers=hdr(fx.viewer_sub), json={"values": {"v_first": "Ada"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["values"]["v_full"] == "Ada Lovelace"
    assert body["values"]["v_last"] == "Lovelace", "an untouched variable keeps its default"
    assert body["order"].index("v_full") > body["order"].index("v_first")


def test_a_viewer_may_evaluate_but_not_save(client: TestClient, fx: Fixture) -> None:
    """Evaluating is reading an app you can already open. Saving is not."""
    app_id = _new_app(client, fx)
    r = client.post(f"{base(fx)}/{app_id}/variables/evaluate",
                    headers=hdr(fx.viewer_sub), json={"values": {}})
    assert r.status_code == 200, r.text
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.viewer_sub),
                   json={"definition": _module({})})
    assert r.status_code == 403, r.text


def test_bad_filter_clauses_blame_the_request_not_the_saved_app(
    client: TestClient, fx: Fixture
) -> None:
    """A Filter List sends clauses with the evaluate call, so a bad clause is
    now a bad *request* against a perfectly valid document. Reporting it as a
    409 - "this saved app no longer validates" - would send whoever reads it to
    edit an app that has nothing wrong with it.
    """
    app_id = _new_app(client, fx)
    type_id = "11111111-1111-1111-1111-111111111111"
    variables = {
        "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                  "object_set": {"object_type_id": type_id, "filters": []}},
        "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Chosen"},
        "v_visible": {"id": "v_visible", "kind": "object_set", "label": "Visible",
                      "derivation": {"transform": "narrow_set",
                                     "inputs": ["v_all", "v_clauses"]}},
    }
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": _module(variables)})
    assert r.status_code == 200, r.text

    good = client.post(f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.viewer_sub),
                       json={"values": {"v_clauses": [
                           {"property": "region", "op": "eq", "value": "north"}]}})
    assert good.status_code == 200, good.text
    assert good.json()["values"]["v_visible"]["filters"] == [
        {"property": "region", "op": "eq", "value": "north"}
    ]

    bad = client.post(f"{base(fx)}/{app_id}/variables/evaluate", headers=hdr(fx.viewer_sub),
                      json={"values": {"v_clauses": [
                          {"property": "capacity", "op": "gt", "value": 40}]}})
    assert bad.status_code == 422, bad.text
    assert "not supported yet" in bad.json()["detail"]


# ---- publishing pins a version (roadmap 1.7) ---------------------------------
def _publish(client: TestClient, fx: Fixture, app_id: str, scope: str = "workspace") -> dict:
    r = client.put(f"{base(fx)}/{app_id}/publish", headers=hdr(fx.admin_sub),
                   json={"scope": scope})
    assert r.status_code == 200, r.text
    return r.json()


def _save(client: TestClient, fx: Fixture, app_id: str, definition: dict) -> dict:
    r = client.put(f"{base(fx)}/{app_id}/definition", headers=hdr(fx.editor_sub),
                   json={"definition": definition})
    assert r.status_code == 200, r.text
    return r.json()


def _text_module(text: str) -> dict:
    return _module({}, {"t1": {"type": {"resolvedName": "CanvasText"},
                               "props": {"text": text}}})


def test_publishing_pins_the_version_viewers_see(client: TestClient, fx: Fixture) -> None:
    app_id = _new_app(client, fx)
    _save(client, fx, app_id, _text_module("as published"))
    published = _publish(client, fx, app_id)
    assert published["published_version"] == published["current_version"] == 1


def test_saving_after_publishing_does_not_move_the_viewers(
    client: TestClient, fx: Fixture
) -> None:
    """The failure this exists to remove: today every save is immediately what
    everyone else sees, half-finished layouts included."""
    app_id = _new_app(client, fx)
    _save(client, fx, app_id, _text_module("as published"))
    _publish(client, fx, app_id)
    after = _save(client, fx, app_id, _text_module("still being worked on"))
    assert after["current_version"] == 2
    assert after["published_version"] == 1, "a save moved the published pointer"

    seen = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}",
                      headers=hdr(fx.viewer_sub))
    assert seen.status_code == 200, seen.text
    body = seen.json()
    assert body["definition"]["layout"]["t1"]["props"]["text"] == "as published"
    # The author's progress is still *reported* - "published v1, editing v2" is
    # the sentence the builder needs, and one number cannot say it.
    assert body["current_version"] == 2 and body["published_version"] == 1


def test_publishing_again_moves_the_viewers_forward(client: TestClient, fx: Fixture) -> None:
    app_id = _new_app(client, fx)
    _save(client, fx, app_id, _text_module("first"))
    _publish(client, fx, app_id)
    _save(client, fx, app_id, _text_module("second"))
    again = _publish(client, fx, app_id)
    assert again["published_version"] == 2
    seen = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}",
                      headers=hdr(fx.viewer_sub)).json()
    assert seen["definition"]["layout"]["t1"]["props"]["text"] == "second"


def test_going_private_forgets_the_pin(client: TestClient, fx: Fixture) -> None:
    """So a later re-publish pins what is current *then*, rather than
    resurrecting a version nobody has looked at since."""
    app_id = _new_app(client, fx)
    _save(client, fx, app_id, _text_module("first"))
    _publish(client, fx, app_id)
    private = _publish(client, fx, app_id, scope="private")
    assert private["published_version"] is None
    _save(client, fx, app_id, _text_module("second"))
    again = _publish(client, fx, app_id)
    assert again["published_version"] == 2


def test_a_published_app_that_was_never_saved_still_opens(
    client: TestClient, fx: Fixture
) -> None:
    """Publishing before saving pins nothing - there is no version row to point
    at. Its viewers get the live (empty) definition, which is the same thing,
    rather than a 404 for a row that does not exist."""
    app_id = _new_app(client, fx)
    published = _publish(client, fx, app_id)
    assert published["published_version"] is None
    seen = client.get(f"{wbase(fx)}/published-canvas-apps/{app_id}",
                      headers=hdr(fx.viewer_sub))
    assert seen.status_code == 200, seen.text


def test_variables_resolve_against_the_published_version_not_the_live_one(
    client: TestClient, fx: Fixture
) -> None:
    """The evaluate route reads the document too, so it has to read the same
    one the widgets do - otherwise a viewer's app renders one version and
    resolves another."""
    app_id = _new_app(client, fx)
    _save(client, fx, app_id, _module(
        {"v_a": {"id": "v_a", "kind": "string", "label": "A", "default": "published"}}))
    _publish(client, fx, app_id)
    _save(client, fx, app_id, _module(
        {"v_a": {"id": "v_a", "kind": "string", "label": "A", "default": "unpublished"},
         "v_b": {"id": "v_b", "kind": "string", "label": "B", "default": "new"}}))

    r = client.post(f"{wbase(fx)}/published-canvas-apps/{app_id}/variables/evaluate",
                    headers=hdr(fx.viewer_sub), json={"values": {}})
    assert r.status_code == 200, r.text
    values = r.json()["values"]
    assert values["v_a"] == "published"
    assert "v_b" not in values, "a variable added after publishing reached a viewer"
