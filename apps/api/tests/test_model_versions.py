"""Model definition history tests (ROADMAP Models item 5, migration 0024).

The point of this feature is auditability, so the assertions are about what
the record says, not just that a restore puts old text back: which definition
each run executed, and that rolling back is itself recorded rather than
erasing the thing being rolled back from.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

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
        LocalStorageGateway(str(tmp_path_factory.mktemp("model-versions-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/models"


@pytest.fixture(scope="module")
def source(client: TestClient, fx: Fixture) -> dict[str, str]:
    out = {}
    for label in ("a", "b"):
        r = client.post(
            f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
            headers=hdr(fx.editor_sub),
            data={"name": f"MV {label} {fx.tag}"},
            files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
        )
        assert r.status_code == 201, r.text
        out[label] = r.json()["id"]
    return out


@pytest.fixture()
def model(client: TestClient, fx: Fixture, source: dict[str, str]) -> str:
    r = client.post(
        base(fx), headers=hdr(fx.editor_sub),
        json={"name": f"Versioned {uuid.uuid4().hex[:6]}", "code": "SELECT id FROM raw",
              "inputs": [{"dataset_id": source["a"], "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def versions(client: TestClient, fx: Fixture, model: str, sub: str | None = None) -> list[dict]:
    r = client.get(f"{base(fx)}/{model}/versions", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_new_model_starts_at_version_one(
    client: TestClient, fx: Fixture, model: str, source: dict[str, str]
) -> None:
    """The invariant every read path relies on: a model always has at least
    one definition version, from the moment it exists."""
    history = versions(client, fx, model)
    assert [v["version_number"] for v in history] == [1]
    assert history[0]["code"] == "SELECT id FROM raw"
    assert history[0]["inputs"] == [
        {"dataset_id": source["a"], "input_alias": "raw"}
    ]
    assert history[0]["restored_from"] is None
    assert history[0]["created_by_email"].startswith("editor-")


def test_editing_code_or_inputs_appends_a_version(
    client: TestClient, fx: Fixture, model: str, source: dict[str, str]
) -> None:
    client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, val FROM raw"})
    client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
                 json={"inputs": [{"dataset_id": source["b"], "input_alias": "raw"}]})

    history = versions(client, fx, model)
    assert [v["version_number"] for v in history] == [3, 2, 1]
    assert history[0]["inputs"][0]["dataset_id"] == source["b"]
    assert history[0]["code"] == "SELECT id, val FROM raw", "v3 carries the code v2 set"


def test_scheduling_and_policy_changes_are_not_definition_changes(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """Migration 0024 draws the line at what the model *computes*. Versioning
    trigger settings would fill the history with entries nobody would roll
    back to."""
    for body in (
        {"trigger_mode": "cron", "cron_schedule": "0 * * * *"},
        {"input_health_policy": "warn"},
        {"name": f"Renamed {fx.tag}"},
        {"description": "now with a description"},
    ):
        r = client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub), json=body)
        assert r.status_code == 200, r.text

    assert [v["version_number"] for v in versions(client, fx, model)] == [1]


def test_saving_the_same_code_again_does_not_add_a_version(
    client: TestClient, fx: Fixture, model: str
) -> None:
    client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM raw"})
    assert [v["version_number"] for v in versions(client, fx, model)] == [1]


def test_restoring_appends_rather_than_rewinds(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """History has to stay a true record - including the fact that somebody
    reverted. Rewinding would make a run's model_version ambiguous the moment
    anyone rolled back twice."""
    client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, val * 2 AS doubled FROM raw"})

    r = client.post(f"{base(fx)}/{model}/versions/1/restore", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["code"] == "SELECT id FROM raw"

    history = versions(client, fx, model)
    assert [v["version_number"] for v in history] == [3, 2, 1]
    assert history[0]["code"] == "SELECT id FROM raw"
    assert history[0]["restored_from"] == 1
    assert history[1]["code"] == "SELECT id, val * 2 AS doubled FROM raw", (
        "the version being rolled back from must survive the rollback"
    )


def test_restoring_brings_the_inputs_back_too(
    client: TestClient, fx: Fixture, model: str, source: dict[str, str]
) -> None:
    """Aliases are half the contract - restoring code that says FROM raw into
    a model whose input was renamed would restore something that cannot run."""
    client.patch(
        f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
        json={"code": "SELECT id FROM other",
              "inputs": [{"dataset_id": source["b"], "input_alias": "other"}]},
    )
    r = client.post(f"{base(fx)}/{model}/versions/1/restore", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert [i["input_alias"] for i in r.json()["inputs"]] == ["raw"]
    assert r.json()["inputs"][0]["dataset_id"] == source["a"]

    # And it runs, which is the whole point of restoring the pair together.
    assert client.post(f"{base(fx)}/{model}/run", headers=hdr(fx.editor_sub)).json()["ok"]


def test_a_run_records_the_definition_it_executed(
    client: TestClient, fx: Fixture, model: str
) -> None:
    """The asymmetry migration 0024 exists to fix: model_runs.output_version
    has always pointed at the exact data; now model_version points at the
    exact code."""
    assert client.post(f"{base(fx)}/{model}/run", headers=hdr(fx.editor_sub)).json()["ok"]
    v1 = versions(client, fx, model)[0]["id"]

    client.patch(f"{base(fx)}/{model}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, val FROM raw"})
    assert client.post(f"{base(fx)}/{model}/run", headers=hdr(fx.editor_sub)).json()["ok"]
    v2 = versions(client, fx, model)[0]["id"]
    assert v1 != v2

    runs = client.get(f"{base(fx)}/{model}/runs", headers=hdr(fx.viewer_sub)).json()
    assert [r["model_version"] for r in runs] == [v2, v1]


def test_restoring_a_version_that_does_not_exist_is_404(
    client: TestClient, fx: Fixture, model: str
) -> None:
    r = client.post(f"{base(fx)}/{model}/versions/99/restore", headers=hdr(fx.editor_sub))
    assert r.status_code == 404


def test_role_floors(client: TestClient, fx: Fixture, model: str) -> None:
    assert versions(client, fx, model, fx.viewer_sub), "a viewer can read history"
    r = client.post(f"{base(fx)}/{model}/versions/1/restore", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403, "but cannot restore"
    r = client.get(f"{base(fx)}/{model}/versions", headers=hdr(fx.outsider_sub))
    assert r.status_code == 404
