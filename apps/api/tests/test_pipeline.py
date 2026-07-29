"""Pipeline graph tests (ROADMAP Models item 2).

Its own project rather than a case in test_models.py: this endpoint returns
*everything* in a project, so sharing a project with tests that create models
would make the assertions depend on test order.
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("pipeline-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def graph(client: TestClient, fx: Fixture, sub: str | None = None) -> dict:
    r = client.get(f"{base(fx)}/pipeline", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def node(g: dict, name: str, kind: str) -> dict:
    # Kind is required, not a convenience: a model's output dataset is named
    # after the model, so every chain here has two nodes per name.
    matches = [n for n in g["nodes"] if n["name"] == name and n["kind"] == kind]
    assert len(matches) == 1, f"{kind} {name!r} not in {[(n['kind'], n['name']) for n in g['nodes']]}"
    return matches[0]


@pytest.fixture(scope="module")
def chain(client: TestClient, fx: Fixture) -> dict[str, str]:
    """source -> A -> A out -> B -> B out. Built through the real API, so
    the output datasets exist because the models actually ran."""
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Source {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]

    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"A {fx.tag}", "code": "SELECT id, val * 2 AS doubled FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    a = r.json()["id"]
    r = client.post(f"{base(fx)}/models/{a}/run", headers=hdr(fx.editor_sub))
    assert r.json()["ok"], r.text
    a_out = r.json()["output_dataset"]["id"]

    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"B {fx.tag}", "code": "SELECT sum(doubled) AS total FROM a",
              "inputs": [{"dataset_id": a_out, "input_alias": "a"}]},
    )
    assert r.status_code == 201, r.text
    b = r.json()["id"]
    r = client.post(f"{base(fx)}/models/{b}/run", headers=hdr(fx.editor_sub))
    assert r.json()["ok"], r.text
    b_out = r.json()["output_dataset"]["id"]

    return {"source": source, "a": a, "a_out": a_out, "b": b, "b_out": b_out,
            "a_name": f"A {fx.tag}", "b_name": f"B {fx.tag}",
            "source_name": f"Source {fx.tag}"}


def test_chain_layers_strictly_left_to_right(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    g = graph(client, fx)
    assert g["cycles"] == []
    assert g["layer_count"] == 5

    layers = {n["id"]: n["layer"] for n in g["nodes"]}
    # Every edge must point strictly rightwards - that is the whole promise
    # the frontend lays out against.
    for e in g["edges"]:
        assert layers[e["to"]] > layers[e["from"]], e

    assert node(g, chain["source_name"], "dataset")["layer"] == 0
    assert node(g, chain["a_name"], "model")["layer"] == 1
    assert node(g, chain["b_name"], "model")["layer"] == 3


def test_nodes_carry_the_state_the_view_renders(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    g = graph(client, fx)

    source = node(g, chain["source_name"], "dataset")
    assert source["kind"] == "dataset" and source["origin"] == "upload"
    assert source["row_count"] == 3 and source["current_version"] == 1
    # Nothing has asked for this dataset's health, so it is not computed
    # here - one project-wide request must not trigger a DuckDB pass per
    # dataset (services/pipeline.py's docstring).
    assert source["health_status"] is None

    a = node(g, chain["a_name"], "model")
    assert a["kind"] == "model" and a["language"] == "sql"
    assert a["trigger_mode"] == "manual"
    assert a["last_run_status"] == "succeeded" and a["last_run_at"] is not None
    assert a["row_count"] is None, "model nodes carry no dataset fields"

    aliased = [e for e in g["edges"] if e["to"] == a["id"]]
    assert [e["label"] for e in aliased] == ["raw"]


def test_health_appears_once_something_has_evaluated_it(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    r = client.post(
        f"{base(fx)}/datasets/{chain['source']}/expectations", headers=hdr(fx.editor_sub),
        json={"column_name": "id", "rule_type": "not_null"},
    )
    assert r.status_code == 201, r.text
    assert client.get(
        f"{base(fx)}/datasets/{chain['source']}/health", headers=hdr(fx.viewer_sub)
    ).json()["status"] == "pass"

    assert node(graph(client, fx), chain["source_name"], "dataset")["health_status"] == "pass"


def test_a_cycle_is_reported_rather_than_hidden(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    """Migration 0021 defers cycle detection to this item: two models feeding
    each other oscillate forever under upstream triggers, and nothing in the
    product could see it. Close the loop by feeding B's output back into A."""
    r = client.patch(
        f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.editor_sub),
        json={"inputs": [{"dataset_id": chain["source"], "input_alias": "raw"},
                         {"dataset_id": chain["b_out"], "input_alias": "loop"}]},
    )
    assert r.status_code == 200, r.text
    try:
        g = graph(client, fx)
        assert len(g["cycles"]) == 1, g["cycles"]
        members = set(g["cycles"][0])
        assert members == {
            f"model:{chain['a']}", f"dataset:{chain['a_out']}",
            f"model:{chain['b']}", f"dataset:{chain['b_out']}",
        }, members
        # A cyclic node still lands somewhere sensible rather than vanishing.
        assert node(g, chain["a_name"], "model")["in_cycle"] is True
        assert node(g, chain["source_name"], "dataset")["in_cycle"] is False
        assert all(n["layer"] >= 0 for n in g["nodes"])
    finally:
        client.patch(
            f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.editor_sub),
            json={"inputs": [{"dataset_id": chain["source"], "input_alias": "raw"}]},
        )


def test_an_empty_project_is_an_empty_graph(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
        json={"name": f"Empty {fx.tag}", "slug": f"empty-{fx.tag}"},
    )
    assert r.status_code == 201, r.text
    empty = r.json()["id"]
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{empty}/pipeline", headers=hdr(fx.owner_sub)
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"nodes": [], "edges": [], "cycles": [], "layer_count": 0}


def test_an_outsider_cannot_read_the_graph(client: TestClient, fx: Fixture) -> None:
    assert client.get(f"{base(fx)}/pipeline", headers=hdr(fx.outsider_sub)).status_code == 404
