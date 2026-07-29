"""Dataset schema policy tests (ROADMAP Datasets item 3, migration 0023).

Driven through a model's output dataset, because that is the only way to
produce a *second* version of a dataset through the public API - re-uploading
under the same name is a 409. It is also the case that matters: a model's
output is what downstream models and object mappings read.
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
        LocalStorageGateway(str(tmp_path_factory.mktemp("schema-policy-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture()
def produced(client: TestClient, fx: Fixture) -> dict[str, str]:
    """A model that has run once, so its output dataset has a version 1 with
    columns (id, val) for a second version to be measured against."""
    import uuid as _uuid

    tag = _uuid.uuid4().hex[:6]
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Source {tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]

    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Shape {tag}", "code": "SELECT id, val FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    model = r.json()["id"]
    r = client.post(f"{base(fx)}/models/{model}/run", headers=hdr(fx.editor_sub))
    assert r.json()["ok"], r.text
    return {"model": model, "output": r.json()["output_dataset"]["id"], "source": source}


def rerun_with(client: TestClient, fx: Fixture, model: str, code: str) -> dict:
    r = client.patch(
        f"{base(fx)}/models/{model}", headers=hdr(fx.editor_sub), json={"code": code}
    )
    assert r.status_code == 200, r.text
    return client.post(f"{base(fx)}/models/{model}/run", headers=hdr(fx.editor_sub)).json()


def set_policy(client: TestClient, fx: Fixture, dataset: str, policy: str) -> dict:
    r = client.patch(
        f"{base(fx)}/datasets/{dataset}", headers=hdr(fx.editor_sub),
        json={"schema_policy": policy},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_permissive_is_the_default_and_allows_anything(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    """The default is permissive deliberately (migration 0023): applying the
    migration must not start failing pipelines that worked yesterday."""
    r = client.get(f"{base(fx)}/datasets/{produced['output']}", headers=hdr(fx.viewer_sub))
    assert r.json()["schema_policy"] == "permissive"

    result = rerun_with(client, fx, produced["model"], "SELECT id FROM raw")
    assert result["ok"] is True, result
    assert result["output_dataset"]["current_version"] == 2


def test_strict_refuses_a_removed_column(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    set_policy(client, fx, produced["output"], "strict")

    result = rerun_with(client, fx, produced["model"], "SELECT id FROM raw")
    assert result["ok"] is False, result
    assert "columns removed: val" in result["error"]
    assert "permissive" in result["error"], "the escape hatch should be in the message"

    # Refused, not half-applied: the dataset still has its version 1 shape.
    r = client.get(f"{base(fx)}/datasets/{produced['output']}", headers=hdr(fx.viewer_sub))
    assert r.json()["current_version"] == 1
    assert [c["name"] for c in r.json()["table_schema"]] == ["id", "val"]

    # And the run is recorded as failed rather than left running.
    runs = client.get(f"{base(fx)}/models/{produced['model']}/runs", headers=hdr(fx.viewer_sub))
    assert runs.json()[0]["status"] == "failed"


def test_strict_refuses_a_retype(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    set_policy(client, fx, produced["output"], "strict")
    result = rerun_with(
        client, fx, produced["model"], "SELECT id, CAST(val AS VARCHAR) AS val FROM raw"
    )
    assert result["ok"] is False, result
    assert "columns retyped: val" in result["error"]


def test_strict_allows_an_added_column(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    """Adding a field is the most common drift there is and breaks no reader;
    a policy people have to keep switching off is one nobody leaves on."""
    set_policy(client, fx, produced["output"], "strict")
    result = rerun_with(client, fx, produced["model"], "SELECT id, val, 1 AS extra FROM raw")
    assert result["ok"] is True, result
    assert result["output_dataset"]["current_version"] == 2


def test_switching_to_permissive_is_the_escape_hatch(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    set_policy(client, fx, produced["output"], "strict")
    assert rerun_with(client, fx, produced["model"], "SELECT id FROM raw")["ok"] is False

    set_policy(client, fx, produced["output"], "permissive")
    result = rerun_with(client, fx, produced["model"], "SELECT id FROM raw")
    assert result["ok"] is True, result

    # Back to strict, and the *new* shape is now the baseline.
    set_policy(client, fx, produced["output"], "strict")
    assert rerun_with(client, fx, produced["model"], "SELECT id FROM raw")["ok"] is True


def test_strict_never_blocks_a_first_version(client: TestClient, fx: Fixture) -> None:
    """A dataset can be strict before it has anything to compare against -
    the upload path must not trip over its own first version."""
    import uuid as _uuid

    tag = _uuid.uuid4().hex[:6]
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Fresh {tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert set_policy(client, fx, r.json()["id"], "strict")["schema_policy"] == "strict"


def test_an_unknown_policy_is_refused(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    r = client.patch(
        f"{base(fx)}/datasets/{produced['output']}", headers=hdr(fx.editor_sub),
        json={"schema_policy": "whatever"},
    )
    assert r.status_code == 422


def test_a_viewer_cannot_change_the_policy(
    client: TestClient, fx: Fixture, produced: dict[str, str]
) -> None:
    r = client.patch(
        f"{base(fx)}/datasets/{produced['output']}", headers=hdr(fx.viewer_sub),
        json={"schema_policy": "strict"},
    )
    assert r.status_code == 403
