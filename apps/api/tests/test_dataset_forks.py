"""Dataset fork tests (ROADMAP Datasets item 6, migration 0025).

Independence is the whole claim, so most of these assert it directly: the
fork survives the original being deleted, and neither one's versions,
policy or checks move the other.
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
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("fork-storage")))


@pytest.fixture(scope="module")
def client(storage: LocalStorageGateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(storage)
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture()
def dataset(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Original {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def fork(client: TestClient, fx: Fixture, dataset: str, **body) -> dict:
    body.setdefault("name", f"Fork {uuid.uuid4().hex[:6]}")
    r = client.post(
        f"{base(fx)}/datasets/{dataset}/fork", headers=hdr(fx.editor_sub), json=body
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_a_fork_is_its_own_dataset_with_the_source_s_data(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    forked = fork(client, fx, dataset)
    assert forked["id"] != dataset
    assert forked["origin"] == "fork"
    assert forked["current_version"] == 1
    assert forked["row_count"] == 3
    assert forked["forked_from_dataset_id"] == dataset
    assert forked["forked_from_version"] == 1

    r = client.post(
        f"{base(fx)}/datasets/{forked['id']}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT sum(val) AS total FROM dataset"},
    )
    assert r.json()["rows"] == [[60]], "the fork holds a real copy, not a pointer"


def test_the_fork_survives_the_original_being_deleted(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    """The reason the bytes are copied rather than shared: deleting a dataset
    removes its whole storage prefix."""
    forked = fork(client, fx, dataset)
    assert client.delete(
        f"{base(fx)}/datasets/{dataset}", headers=hdr(fx.editor_sub)
    ).status_code == 204

    r = client.post(
        f"{base(fx)}/datasets/{forked['id']}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT count(*) AS n FROM dataset"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [[3]]

    # The provenance is a historical statement, so it stays true: "copied
    # from dataset X version 1" does not stop being the case when X is gone.
    r = client.get(f"{base(fx)}/datasets/{forked['id']}", headers=hdr(fx.viewer_sub))
    assert r.json()["forked_from_dataset_id"] == dataset
    assert r.json()["forked_from_version"] == 1


def test_forking_a_named_version_goes_back_to_an_overwritten_state(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    """Naming a version is what makes this useful for recovering a state that
    has since been overwritten. Driven through a model, since that is how a
    dataset gets a second version."""
    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Shrink {fx.tag}", "code": "SELECT id, val FROM raw",
              "inputs": [{"dataset_id": dataset, "input_alias": "raw"}]},
    )
    model = r.json()["id"]
    out = client.post(f"{base(fx)}/models/{model}/run", headers=hdr(fx.editor_sub))
    output = out.json()["output_dataset"]["id"]

    client.patch(f"{base(fx)}/models/{model}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM raw"})
    r = client.post(f"{base(fx)}/models/{model}/run", headers=hdr(fx.editor_sub))
    assert r.json()["output_dataset"]["current_version"] == 2

    forked = fork(client, fx, output, version_number=1)
    assert forked["forked_from_version"] == 1
    assert [c["name"] for c in forked["table_schema"]] == ["id", "val"]

    latest = fork(client, fx, output)
    assert latest["forked_from_version"] == 2
    assert [c["name"] for c in latest["table_schema"]] == ["id"]


def test_the_checks_come_with_it_but_not_their_results(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    """Forking is for trying a change and seeing whether it still holds up
    against the same standard, so the rules travel. Results are per version
    and the fork's version 1 is new."""
    r = client.post(
        f"{base(fx)}/datasets/{dataset}/expectations", headers=hdr(fx.editor_sub),
        json={"column_name": "id", "rule_type": "not_null"},
    )
    assert r.status_code == 201, r.text
    assert client.get(
        f"{base(fx)}/datasets/{dataset}/health", headers=hdr(fx.viewer_sub)
    ).json()["status"] == "pass"

    forked = fork(client, fx, dataset)
    rules = client.get(
        f"{base(fx)}/datasets/{forked['id']}/expectations", headers=hdr(fx.viewer_sub)
    ).json()
    assert [(r["rule_type"], r["column_name"]) for r in rules] == [("not_null", "id")]

    import psycopg
    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cached = conn.execute(
            "SELECT expectation_results FROM dataset_versions WHERE dataset_id = %s",
            (forked["id"],),
        ).fetchone()[0]
    assert cached is None, "the fork's own version has not been evaluated yet"
    assert client.get(
        f"{base(fx)}/datasets/{forked['id']}/health", headers=hdr(fx.viewer_sub)
    ).json()["status"] == "pass"

    # Deleting the source's rule must not touch the fork's copy.
    source_rules = client.get(
        f"{base(fx)}/datasets/{dataset}/expectations", headers=hdr(fx.viewer_sub)
    ).json()
    client.delete(
        f"{base(fx)}/datasets/{dataset}/expectations/{source_rules[0]['id']}",
        headers=hdr(fx.editor_sub),
    )
    still = client.get(
        f"{base(fx)}/datasets/{forked['id']}/expectations", headers=hdr(fx.viewer_sub)
    ).json()
    assert len(still) == 1


def test_a_fork_starts_permissive_whatever_the_source_was(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    """A fork is a scratch space. Inheriting strict would make the thing you
    forked in order to experiment with refuse the experiment."""
    client.patch(f"{base(fx)}/datasets/{dataset}", headers=hdr(fx.editor_sub),
                 json={"schema_policy": "strict"})
    assert fork(client, fx, dataset)["schema_policy"] == "permissive"


def test_a_name_clash_and_a_missing_version_are_refused(
    client: TestClient, fx: Fixture, dataset: str
) -> None:
    name = f"Taken {uuid.uuid4().hex[:6]}"
    fork(client, fx, dataset, name=name)
    r = client.post(
        f"{base(fx)}/datasets/{dataset}/fork", headers=hdr(fx.editor_sub),
        json={"name": name},
    )
    assert r.status_code == 409

    r = client.post(
        f"{base(fx)}/datasets/{dataset}/fork", headers=hdr(fx.editor_sub),
        json={"name": f"Nope {uuid.uuid4().hex[:6]}", "version_number": 99},
    )
    assert r.status_code == 404


def test_role_floors(client: TestClient, fx: Fixture, dataset: str) -> None:
    r = client.post(
        f"{base(fx)}/datasets/{dataset}/fork", headers=hdr(fx.viewer_sub),
        json={"name": f"Nope {uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 403, "forking creates a resource"
    r = client.post(
        f"{base(fx)}/datasets/{dataset}/fork", headers=hdr(fx.outsider_sub),
        json={"name": f"Nope {uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 404
