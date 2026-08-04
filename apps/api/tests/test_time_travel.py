"""Reading a dataset at an earlier version (ROADMAP phase 2, item 3.3).

Time travel needed no migration and no backfill, because every version's bytes
have always been written to their own key and nothing has ever deleted one
(`docs/decisions/0005-dataset-retention.md`). What was missing was a way to ask
for one.

So what these tests protect is not "can we read a parquet file" but the two
things that make an old version *readable honestly*: it is described by its own
schema and row count rather than by the current version's, and the cost of
keeping it is reported rather than left to arrive on a bill.
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

SOURCE = b"id,total,region\n1,10,north\n2,20,south\n3,30,north\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("time-travel-storage")))
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
def versioned(client: TestClient, fx: Fixture) -> str:
    """A model-produced dataset with two versions whose shapes differ.

    Versions come from runs, syncs and write-back - upload always creates a new
    dataset - so this builds them the way a real one gets them: run a transform,
    change it, run it again.
    """
    tag = uuid.uuid4().hex[:8]
    src = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"src_{tag}"},
        files={"file": ("rows.csv", io.BytesIO(SOURCE), "text/csv")},
    )
    assert src.status_code == 201, src.text

    model = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"travel_{tag}", "code": "SELECT id, total FROM raw",
              "inputs": [{"dataset_id": src.json()["id"], "input_alias": "raw"}]},
    )
    assert model.status_code == 201, model.text
    model_id = model.json()["id"]

    first = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert first.json().get("ok") is True, first.text
    dataset_id = first.json()["output_dataset"]["id"]

    # Three versions, all differently shaped, and the *middle* one is neither
    # the first nor the current. Two versions would let a bug that always reads
    # v1 and a bug that always reads the current one both pass half the time.
    client.patch(f"{base(fx)}/models/{model_id}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id, total, region FROM raw WHERE region = 'north'"})
    assert client.post(f"{base(fx)}/models/{model_id}/run",
                       headers=hdr(fx.editor_sub)).json().get("ok") is True

    client.patch(f"{base(fx)}/models/{model_id}", headers=hdr(fx.editor_sub),
                 json={"code": "SELECT id FROM raw"})
    third = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert third.json().get("ok") is True, third.text
    assert third.json()["output_dataset"]["current_version"] == 3
    return dataset_id


def test_the_fixture_really_produced_two_versions(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """Every assertion below is meaningless if it did not."""
    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()
    assert [r["version_number"] for r in rows] == [3, 2, 1]


def test_preview_defaults_to_the_current_version(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    r = client.get(f"{base(fx)}/datasets/{versioned}/preview", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["columns"]] == ["id"]
    assert r.json()["total_rows"] == 3


def test_preview_at_an_earlier_version_returns_that_version(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """The point of the item. v1 had two columns and two rows, and still does."""
    r = client.get(f"{base(fx)}/datasets/{versioned}/preview",
                   headers=hdr(fx.viewer_sub), params={"version": 1})
    assert r.status_code == 200, r.text
    assert [c["name"] for c in r.json()["columns"]] == ["id", "total"]
    assert r.json()["total_rows"] == 3


def test_a_version_is_described_by_its_own_schema_not_the_current_one(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """Reading v1's rows against v2's column list would describe the data
    wrongly in exactly the case somebody looks at an old version: to find out
    what changed."""
    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()
    by_number = {r["version_number"]: r for r in rows}
    assert [c["name"] for c in by_number[1]["table_schema"]] == ["id", "total"]
    assert [c["name"] for c in by_number[2]["table_schema"]] == ["id", "total", "region"]
    assert [c["name"] for c in by_number[3]["table_schema"]] == ["id"]
    assert by_number[1]["row_count"] == 3
    assert by_number[2]["row_count"] == 2
    assert by_number[3]["row_count"] == 3


def test_querying_an_earlier_version(client: TestClient, fx: Fixture, versioned: str) -> None:
    """v2 is the one with a different row count. v1 and v3 both have three, so
    asking either of those proves nothing about whether the parameter is read."""
    r = client.post(
        f"{base(fx)}/datasets/{versioned}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT count(*) AS n FROM dataset", "version": 2},
    )
    assert r.status_code == 200, r.text
    assert r.json()["rows"][0][0] == 2

    now = client.post(
        f"{base(fx)}/datasets/{versioned}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT count(*) AS n FROM dataset"},
    )
    assert now.json()["rows"][0][0] == 3


def test_a_query_against_an_earlier_version_cannot_see_a_later_column(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """`region` arrived in v2. A time-travel read that silently found it would
    mean the version parameter was being ignored."""
    r = client.post(
        f"{base(fx)}/datasets/{versioned}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT region FROM dataset", "version": 1},
    )
    assert r.status_code == 422, r.text


def test_profiling_an_earlier_version_profiles_that_version(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """The *middle* version deliberately: profiling it must be neither the
    first version's answer nor the current one's, and it is cached against its
    own version number rather than overwriting the current one's profile."""
    r = client.get(f"{base(fx)}/datasets/{versioned}/profile",
                   headers=hdr(fx.viewer_sub), params={"version": 2})
    assert r.status_code == 200, r.text
    assert r.json()["version_number"] == 2
    assert [c["name"] for c in r.json()["columns"]] == ["id", "total", "region"]

    now = client.get(f"{base(fx)}/datasets/{versioned}/profile", headers=hdr(fx.viewer_sub))
    assert now.json()["version_number"] == 3
    assert [c["name"] for c in now.json()["columns"]] == ["id"]


def test_a_version_that_does_not_exist_is_a_404_naming_it(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    r = client.get(f"{base(fx)}/datasets/{versioned}/preview",
                   headers=hdr(fx.viewer_sub), params={"version": 99})
    assert r.status_code == 404, r.text
    assert "99" in r.json()["detail"]


def test_version_zero_is_refused_by_the_route_rather_than_the_query(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    r = client.get(f"{base(fx)}/datasets/{versioned}/preview",
                   headers=hdr(fx.viewer_sub), params={"version": 0})
    assert r.status_code == 422, r.text


# ---- the bill (docs/decisions/0005) ------------------------------------------
def test_every_version_reports_what_it_costs_to_keep(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """Time travel is only possible because nothing deletes an old version.
    That bill has always been paid and never shown."""
    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()
    assert all(r["size_bytes"] and r["size_bytes"] > 0 for r in rows), rows


def test_the_retention_report_adds_them_up(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()
    r = client.get(f"{base(fx)}/datasets/{versioned}/retention", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    report = r.json()
    assert report["versions"] == 3
    assert report["current_version"] == 3
    assert report["unmeasured"] == 0
    assert report["total_bytes"] == sum(x["size_bytes"] for x in rows)
    # The whole point: keeping two versions costs more than keeping one.
    assert report["total_bytes"] > max(x["size_bytes"] for x in rows)


def test_a_version_whose_object_is_gone_is_counted_as_unmeasured_not_as_zero(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    """A total that quietly shrank when an object went missing would be a
    number somebody budgets against and is wrong."""
    import pathlib

    rows = client.get(f"{base(fx)}/datasets/{versioned}/versions",
                      headers=hdr(fx.viewer_sub)).json()
    before = client.get(f"{base(fx)}/datasets/{versioned}/retention",
                        headers=hdr(fx.viewer_sub)).json()

    # Reach into the gateway's root the way a bucket lifecycle rule would -
    # scoped to *this* dataset, because the fixture's source upload has a v1 of
    # its own and deleting that one would leave this report unchanged and the
    # assertion below passing for the wrong reason.
    gateway = ds_routes._storage
    root = pathlib.Path(gateway._root)  # type: ignore[attr-defined]
    matches = list(root.rglob(f"datasets/{versioned}/v1/data.parquet"))
    assert len(matches) == 1, matches
    key = matches[0]
    size = key.stat().st_size
    key.unlink()

    after = client.get(f"{base(fx)}/datasets/{versioned}/retention",
                       headers=hdr(fx.viewer_sub)).json()
    assert after["unmeasured"] == 1
    assert after["total_bytes"] == before["total_bytes"] - size
    assert after["versions"] == before["versions"], "the version row was not deleted"

    # And reading it says the bytes are gone rather than 500ing.
    r = client.get(f"{base(fx)}/datasets/{versioned}/preview",
                   headers=hdr(fx.viewer_sub), params={"version": 1})
    assert r.status_code == 409, r.text
    assert len(rows) == 3


def test_a_viewer_can_time_travel_and_an_outsider_cannot(
    client: TestClient, fx: Fixture, versioned: str
) -> None:
    assert client.get(f"{base(fx)}/datasets/{versioned}/preview",
                      headers=hdr(fx.viewer_sub), params={"version": 1}).status_code == 200
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"{base(fx)}/datasets/{versioned}/preview",
                       headers=hdr(sub), params={"version": 1})
        assert r.status_code in (403, 404), (sub, r.text)
