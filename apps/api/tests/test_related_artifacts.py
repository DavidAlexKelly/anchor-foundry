"""p.10's Related artifacts on the lineage graph (§614; `data-lineage` p.10).

> "The related artifacts helper displays artifacts directly linked to the
> nodes selected on the graph." (p.10)

The ids here are made up where the graph's own rows do not matter: the
question is which *modules* and *repositories* name a node, and a module's
document names an id whether or not a dataset behind it exists. Module
documents are written with the admin connection for the same reason - the
definition route validates what a widget names, which is not this unit's
subject.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import related_artifacts  # noqa: E402


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


def pbase(fx: Fixture, project: str | None = None) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{project or fx.project}"


def related(client: TestClient, fx: Fixture, nodes: list[str], sub: str | None = None):
    query = "&".join(f"node={n}" for n in nodes)
    return client.get(f"{pbase(fx)}/pipeline/related?{query}", headers=hdr(sub or fx.viewer_sub))


def module(client: TestClient, fx: Fixture, name: str, document: dict,
           project: str | None = None) -> dict:
    r = client.post(f"{pbase(fx, project)}/canvas-apps", headers=hdr(fx.editor_sub),
                    json={"name": name})
    assert r.status_code == 201, r.text
    made = r.json()
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE canvas_apps SET definition = %s WHERE id = %s",
                     (json.dumps(document), made["id"]))
    return made


def reads(type_id: str) -> dict:
    """A module whose object set variable is over `type_id`."""
    return {"format": 2, "layout": {}, "events": {}, "variables": {
        "v_all": {"id": "v_all", "kind": "object_set",
                  "object_set": {"object_type_id": type_id, "filters": []}}}}


def shows(dataset_id: str) -> dict:
    """A module with a dataset table on `dataset_id`."""
    return {"format": 2, "variables": {}, "events": {}, "layout": {
        "t": {"type": {"resolvedName": "CanvasDatasetTable"},
              "props": {"datasetId": dataset_id}}}}


@pytest.fixture(scope="module")
def ids() -> dict[str, str]:
    return {"type": str(uuid.uuid4()), "other_type": str(uuid.uuid4()),
            "dataset": str(uuid.uuid4()), "unused": str(uuid.uuid4())}


@pytest.fixture(scope="module")
def modules(client: TestClient, fx: Fixture, ids: dict[str, str]) -> dict[str, dict]:
    both = reads(ids["type"])
    both["layout"] = shows(ids["dataset"])["layout"]
    return {
        "type": module(client, fx, f"Type board {fx.tag}", reads(ids["type"])),
        "dataset": module(client, fx, f"Dataset board {fx.tag}", shows(ids["dataset"])),
        "both": module(client, fx, f"Both {fx.tag}", both),
        # The id as a *key*, never a value: a module's own name for something.
        "keyed": module(client, fx, f"Keyed {fx.tag}", {
            "format": 2, "layout": {}, "events": {},
            "variables": {ids["type"]: {"id": "v", "kind": "string"}}}),
        # The id inside a list, which a widget's props may hold.
        "listed": module(client, fx, f"Listed {fx.tag}", {
            "format": 2, "variables": {}, "events": {}, "layout": {
                "t": {"type": {"resolvedName": "CanvasDatasetTable"},
                      "props": {"datasets": ["other", ids["dataset"]]}}}}),
        # The id inside a longer string: text that mentions it is not a link.
        "mention": module(client, fx, f"Mention {fx.tag}", {
            "format": 2, "layout": {}, "events": {}, "variables": {},
            "note": f"see {ids['type']} later"}),
    }


def by_name(body: list[dict]) -> dict[str, dict]:
    return {a["name"]: a for a in body}


def test_a_module_naming_a_selected_node_is_related(
    client: TestClient, fx: Fixture, ids: dict[str, str], modules: dict[str, dict],
) -> None:
    type_node, dataset_node = f"object_type:{ids['type']}", f"dataset:{ids['dataset']}"
    r = related(client, fx, [type_node])
    assert r.status_code == 200, r.text
    got = by_name(r.json())
    assert set(got) == {f"Type board {fx.tag}", f"Both {fx.tag}"}, got
    board = got[f"Type board {fx.tag}"]
    assert board["kind"] == "workshop_module"
    assert board["id"] == modules["type"]["id"]
    assert board["resource_id"] == modules["type"]["resource_id"]
    assert board["project_id"] == str(fx.project)
    assert board["project_name"] == f"Proj {fx.tag}"
    assert board["nodes"] == [type_node]
    # Its own times; the admin write above moved `updated_at` past `created_at`.
    with psycopg.connect(ADMIN_DSN) as conn:
        created, updated = conn.execute(
            "SELECT created_at, updated_at FROM canvas_apps WHERE id = %s",
            (modules["type"]["id"],),
        ).fetchone()
    assert created != updated
    assert datetime.fromisoformat(board["created_at"]) == created
    assert datetime.fromisoformat(board["updated_at"]) == updated

    # Several nodes: each module says which of them it names, in asked order.
    got = by_name(related(client, fx, [type_node, dataset_node]).json())
    assert set(got) == {f"Type board {fx.tag}", f"Dataset board {fx.tag}", f"Both {fx.tag}",
                        f"Listed {fx.tag}"}
    assert got[f"Both {fx.tag}"]["nodes"] == [type_node, dataset_node]
    assert got[f"Dataset board {fx.tag}"]["nodes"] == [dataset_node]
    assert got[f"Listed {fx.tag}"]["nodes"] == [dataset_node]


def test_nothing_links_to_a_node_no_module_names(
    client: TestClient, fx: Fixture, ids: dict[str, str], modules: dict[str, dict],
) -> None:
    assert related(client, fx, [f"object_type:{ids['unused']}"]).json() == []
    assert related(client, fx, []).json() == []
    # A source links to nothing off the graph, even if its id were named.
    assert related(client, fx, [f"connection:{ids['type']}"]).json() == []


def test_a_transform_is_related_to_the_repository_it_is_authored_in(
    client: TestClient, fx: Fixture,
) -> None:
    r = client.post(f"{pbase(fx)}/repositories", headers=hdr(fx.editor_sub),
                    json={"name": f"Transforms {fx.tag}"})
    assert r.status_code == 201, r.text
    repo = r.json()
    made = []
    for name in ("one", "two", "plain"):
        r = client.post(f"{pbase(fx)}/models", headers=hdr(fx.editor_sub),
                        json={"name": f"{name} {fx.tag}", "code": "SELECT 1 AS id", "inputs": []})
        assert r.status_code == 201, r.text
        made.append(r.json()["id"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for model_id, path in ((made[0], "src/one.sql"), (made[1], "src/two.sql")):
            conn.execute("UPDATE models SET source_repo_id = %s, source_path = %s WHERE id = %s",
                         (repo["id"], path, model_id))
        # An edit, so the repository's two times differ and each is read.
        conn.execute("UPDATE code_repos SET description = 'edited' WHERE id = %s", (repo["id"],))
    nodes = [f"model:{made[1]}", f"model:{made[2]}", f"model:{made[0]}"]
    body = related(client, fx, nodes).json()
    # The repository's own times, which p.30's orders sort by.
    with psycopg.connect(ADMIN_DSN) as conn:
        created, updated = conn.execute(
            "SELECT created_at, updated_at FROM code_repos WHERE id = %s", (repo["id"],),
        ).fetchone()
    assert created != updated
    for key, when in (("created_at", created), ("updated_at", updated)):
        assert datetime.fromisoformat(body[0].pop(key)) == when, key
    # One repository, once, naming both of its transforms in asked order.
    assert body == [{
        "kind": "code_repository", "id": repo["id"], "name": f"Transforms {fx.tag}",
        "resource_id": repo["resource_id"], "project_id": str(fx.project),
        "project_name": f"Proj {fx.tag}",
        "nodes": [f"model:{made[1]}", f"model:{made[0]}"],
    }], body
    assert related(client, fx, [f"model:{made[2]}"]).json() == []


def test_a_module_the_reader_cannot_open_is_not_listed(
    client: TestClient, fx: Fixture, ids: dict[str, str],
) -> None:
    """Row-level security decides: naming a module in a project this person
    cannot open would say that it exists."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        project = str(conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode)
               VALUES (%s,%s,%s,%s,'custom') RETURNING id""",
            (fx.workspace, f"Private {fx.tag}", f"private-{fx.tag}", fx.owner),
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'editor')",
            (project, fx.editor))
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'none')",
            (project, fx.viewer))
    module(client, fx, f"Elsewhere {fx.tag}", reads(ids["other_type"]), project=project)
    node = f"object_type:{ids['other_type']}"
    assert related(client, fx, [node]).json() == []
    got = related(client, fx, [node], sub=fx.editor_sub).json()
    assert [(a["name"], a["project_name"]) for a in got] == [
        (f"Elsewhere {fx.tag}", f"Private {fx.tag}")]


def test_another_workspaces_module_is_not_this_graphs(
    client: TestClient, fx: Fixture, ids: dict[str, str],
) -> None:
    """The editor can open a module in a second workspace that names the same
    id; it is still not related to this project's graph."""
    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        wid = uuid.uuid4()
        workspace = conn.execute(
            """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix,
                                       pg_schema, search_prefix, created_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (wid, fx.org, f"WS2 {tag}", f"ws2-{tag}", f"workspaces/ws2-{tag}/",
             f"ws_{wid.hex[:12]}", f"ws-{wid.hex[:12]}-", fx.owner),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s,%s,'editor')",
            (workspace, fx.editor))
        project = conn.execute(
            """INSERT INTO projects (workspace_id, name, slug, created_by)
               VALUES (%s,%s,%s,%s) RETURNING id""",
            (workspace, f"Far {tag}", f"far-{tag}", fx.owner),
        ).fetchone()[0]
    r = client.post(f"/api/workspaces/{workspace}/projects/{project}/canvas-apps",
                    headers=hdr(fx.editor_sub), json={"name": f"Far board {tag}"})
    assert r.status_code == 201, r.text
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE canvas_apps SET definition = %s WHERE id = %s",
                     (json.dumps(reads(ids["unused"])), r.json()["id"]))
    assert related(client, fx, [f"object_type:{ids['unused']}"], sub=fx.editor_sub).json() == []


def test_the_question_is_bounded_and_well_formed(client: TestClient, fx: Fixture) -> None:
    r = related(client, fx, ["dataset:not-a-uuid"])
    assert r.status_code == 422, r.text
    many = [f"dataset:{uuid.uuid4()}" for _ in range(related_artifacts.MAX_NODES + 1)]
    r = client.get(f"{pbase(fx)}/pipeline/related",
                   params=[("node", n) for n in many], headers=hdr(fx.viewer_sub))
    assert r.status_code == 422, r.text
    assert "at most" in r.text
    r = client.get(f"{pbase(fx)}/pipeline/related",
                   params=[("node", n) for n in many[1:]], headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    r = related(client, fx, [f"dataset:{uuid.uuid4()}"], sub=fx.outsider_sub)
    assert r.status_code == 404
