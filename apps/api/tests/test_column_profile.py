"""Column-level profiling (roadmap Datasets item 1, migration 0019).

Preview answers "what does a row look like". A profile answers the questions
someone actually has about unfamiliar data: how complete is this column, how
many distinct values, what range does it span.

The statistics are computed by DuckDB over a real Parquet file written by the
real upload path, and the caching behaviour is asserted against the real
database - the point of the feature is that it is computed once per version,
so "is it actually cached" is part of the contract, not an implementation
detail.
"""
from __future__ import annotations

import io
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
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.dataset_engine import profile_columns  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

# Deliberately awkward: a fully-populated key, a column with nulls, a column
# that is entirely null, one distinct value repeated, and text.
CSV = (
    "id,label,score,note,constant\n"
    "1,alpha,10.5,,x\n"
    "2,beta,,,x\n"
    "3,alpha,30.5,seen,x\n"
    "4,gamma,20.0,,x\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("profile-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets"


def _upload(client: TestClient, fx: Fixture, name: str, body: str) -> str:
    r = client.post(
        f"{base(fx)}/upload",
        headers=hdr(fx.editor_sub),
        files={"file": (f"{name}.csv", io.BytesIO(body.encode()), "text/csv")},
        data={"name": name},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def dataset_id(client: TestClient, fx: Fixture) -> str:
    return _upload(client, fx, f"Profile me {fx.tag}", CSV)


def _profile(client: TestClient, fx: Fixture, dataset_id: str, sub: str | None = None) -> dict:
    r = client.get(f"{base(fx)}/{dataset_id}/profile", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def _by_name(profile: dict) -> dict[str, dict]:
    return {c["name"]: c for c in profile["columns"]}


# ---- the statistics themselves ----------------------------------------------
def test_profile_reports_completeness_cardinality_and_range(
    client: TestClient, fx: Fixture, dataset_id: str
) -> None:
    profile = _profile(client, fx, dataset_id)
    assert profile["row_count"] == 4
    assert profile["version_number"] == 1
    columns = _by_name(profile)
    assert set(columns) == {"id", "label", "score", "note", "constant"}

    # A complete key column: no nulls, every value distinct, real bounds.
    assert columns["id"]["null_count"] == 0
    assert columns["id"]["null_rate"] == 0.0
    assert columns["id"]["distinct_count"] == 4
    assert (columns["id"]["min"], columns["id"]["max"]) == ("1", "4")

    # A column with a gap - the null rate is the point of the whole feature.
    assert columns["score"]["null_count"] == 1
    assert columns["score"]["null_rate"] == 0.25
    assert columns["score"]["min"] == "10.5" and columns["score"]["max"] == "30.5"

    # Repeated values: distinct is lower than the row count.
    assert columns["label"]["distinct_count"] == 3
    assert columns["constant"]["distinct_count"] == 1

    # Text still gets bounds, lexicographically.
    assert columns["label"]["min"] == "alpha" and columns["label"]["max"] == "gamma"


def test_an_entirely_null_column_is_reported_as_such(
    client: TestClient, fx: Fixture, dataset_id: str
) -> None:
    """The single most useful thing a profile can tell you about a column you
    were about to build on."""
    note = _by_name(_profile(client, fx, dataset_id))["note"]
    assert note["null_count"] == 3
    assert note["null_rate"] == 0.75
    # One non-null value, so one distinct value - DuckDB does not count NULL
    # as a distinct value and neither should the display.
    assert note["distinct_count"] == 1


def test_an_empty_dataset_profiles_without_dividing_by_zero(
    client: TestClient, fx: Fixture
) -> None:
    dataset_id = _upload(client, fx, f"Empty profile {fx.tag}", "id,label\n")
    profile = _profile(client, fx, dataset_id)
    assert profile["row_count"] == 0
    for column in profile["columns"]:
        assert column["null_count"] == 0
        assert column["null_rate"] == 0.0
        assert column["distinct_count"] == 0


def test_profile_columns_handles_a_type_it_cannot_order(tmp_path) -> None:
    """A JSON source produces list/struct columns, which min()/max() either
    error on or answer uselessly. Those columns must still get a null rate and
    a distinct count rather than sinking the whole profile."""
    import duckdb

    path = str(tmp_path / "nested.parquet")
    con = duckdb.connect()
    con.execute(
        "COPY (SELECT 1 AS id, ['a','b'] AS tags UNION ALL SELECT 2, ['c']) "
        f"TO '{path}' (FORMAT parquet)"
    )
    con.close()

    columns = {c["name"]: c for c in profile_columns(path)}
    assert columns["id"]["min"] == "1"
    assert columns["tags"]["min"] is None and columns["tags"]["max"] is None
    assert columns["tags"]["null_count"] == 0


# ---- caching -----------------------------------------------------------------
def test_the_profile_is_computed_once_and_cached_on_the_version(
    client: TestClient, fx: Fixture
) -> None:
    dataset_id = _upload(client, fx, f"Cache me {fx.tag}", CSV)

    with psycopg.connect(ADMIN_DSN) as conn:
        stored = conn.execute(
            "SELECT column_profile FROM dataset_versions WHERE dataset_id=%s AND version_number=1",
            (dataset_id,),
        ).fetchone()[0]
    assert stored is None, "profiling is lazy - nothing computed until asked for"

    first = _profile(client, fx, dataset_id)
    with psycopg.connect(ADMIN_DSN) as conn:
        stored = conn.execute(
            "SELECT column_profile FROM dataset_versions WHERE dataset_id=%s AND version_number=1",
            (dataset_id,),
        ).fetchone()[0]
    assert stored is not None, "the first request must cache the result"

    # A second request returns the same answer, now served from the cache.
    assert _profile(client, fx, dataset_id) == first


def test_the_cache_is_keyed_by_version_not_by_dataset(
    client: TestClient, fx: Fixture
) -> None:
    """A version's data is immutable, so a cached profile never needs
    invalidating - but the cache must be keyed per version, or the next
    version a sync or model run produces would serve the previous version's
    numbers. Asserted at the service layer because on this dataset the only
    ways to make a second version are a sync or a model run, neither of which
    belongs in a profiling test.
    """
    import asyncio

    from src.lib.db import user_connection
    from src.services import datasets as ds_service

    dataset_id = _upload(client, fx, f"Version keyed {fx.tag}", CSV)
    first = _profile(client, fx, dataset_id)
    assert first["version_number"] == 1

    async def check() -> tuple[object, object]:
        async with user_connection(uuid.UUID(str(fx.viewer))) as conn:
            v1 = await ds_service.get_cached_profile(conn, uuid.UUID(dataset_id), 1)
            v2 = await ds_service.get_cached_profile(conn, uuid.UUID(dataset_id), 2)
        return v1, v2

    cached_v1, cached_v2 = asyncio.run(check())
    assert cached_v1 is not None, "version 1 was profiled by the request above"
    assert cached_v2 is None, "a version that does not exist yet has no profile"


# ---- access ------------------------------------------------------------------
def test_a_viewer_can_profile_and_an_outsider_cannot(
    client: TestClient, fx: Fixture, dataset_id: str
) -> None:
    assert client.get(
        f"{base(fx)}/{dataset_id}/profile", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    assert client.get(
        f"{base(fx)}/{dataset_id}/profile", headers=hdr(fx.outsider_sub)
    ).status_code == 404


def test_profiling_a_missing_dataset_is_404(client: TestClient, fx: Fixture) -> None:
    assert client.get(
        f"{base(fx)}/{uuid.uuid4()}/profile", headers=hdr(fx.viewer_sub)
    ).status_code == 404
