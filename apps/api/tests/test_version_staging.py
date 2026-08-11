"""Staging and committing dataset versions (decision 0008).

> "An action is a **single transaction** that changes the properties of one or
> more objects." (Foundry `action-types` p.2)

`add_version` used to write the Parquet object and bump `current_version` in
one breath, which is fine for one write and impossible to make atomic for two.
The split is what an action needs before it can have more than one rule:

  * `stage_version` writes the bytes and touches no metadata,
  * `commit_versions` makes a *set* of staged versions current, in one
    transaction.

The tests here are decision 0008's own acceptance list, less the two that
belong to rules that do not exist yet. They drive the service directly rather
than through HTTP, because what is being checked is a boundary rather than an
endpoint - and because "the second write failed" is a state no route offers a
way to ask for.
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

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import datasets as dataset_service  # noqa: E402
from src.services.dataset_engine import ColumnSchema  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

CSV = b"id,name\n1,Ada\n2,Grace\n"


def _uid(value) -> uuid.UUID:
    """The fixture hands back ids as UUIDs in some places and strings in
    others; the services want UUIDs."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("staging-storage")))


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


def upload(client: TestClient, fx: Fixture, name: str) -> str:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": name},
        files={"file": ("rows.csv", io.BytesIO(CSV), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def state(dataset_id: str) -> dict:
    """What a reader would see, straight from the database."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        current, location = conn.execute(
            "SELECT current_version, s3_location FROM datasets WHERE id = %s", (dataset_id,)
        ).fetchone()
        versions = conn.execute(
            "SELECT count(*) FROM dataset_versions WHERE dataset_id = %s", (dataset_id,)
        ).fetchone()[0]
    return {"current_version": current, "s3_location": location, "versions": versions}


SCHEMA = [ColumnSchema(name="id", data_type="BIGINT"), ColumnSchema(name="name", data_type="VARCHAR")]


async def stage(conn, storage, fx: Fixture, dataset_id: str, body: bytes = b"parquet"):
    return await dataset_service.stage_version(
        conn, storage,
        dataset_id=_uid(dataset_id), workspace_id=_uid(fx.workspace),
        parquet_bytes=body, schema=SCHEMA, row_count=2,
        produced_by_kind="action", produced_by_id=None, created_by=_uid(fx.editor),
    )


@pytest.mark.anyio
async def test_a_staged_version_is_invisible(client: TestClient, fx: Fixture, storage) -> None:
    """**The property the whole ordering rests on.** Bytes are written first
    because they are the part that cannot be rolled back; what makes that safe
    is that nothing can see them until the metadata says so."""
    from src.lib.db import user_connection

    dataset_id = upload(client, fx, f"Staged {uuid.uuid4().hex[:6]}")
    before = state(dataset_id)

    async with user_connection(_uid(fx.editor)) as conn:
        staged = await stage(conn, storage, fx, dataset_id)

    assert staged.version == before["current_version"] + 1
    # The object exists...
    assert storage.read(staged.parquet_key) == b"parquet"
    # ...and the dataset does not know about it.
    assert state(dataset_id) == before


@pytest.mark.anyio
async def test_committing_makes_it_current(client: TestClient, fx: Fixture, storage) -> None:
    from src.lib.db import user_connection

    dataset_id = upload(client, fx, f"Committed {uuid.uuid4().hex[:6]}")
    before = state(dataset_id)

    async with user_connection(_uid(fx.editor)) as conn:
        staged = await stage(conn, storage, fx, dataset_id)
        await dataset_service.commit_versions(conn, [staged])

    after = state(dataset_id)
    assert after["current_version"] == before["current_version"] + 1
    assert after["versions"] == before["versions"] + 1
    assert after["s3_location"] == staged.parquet_key


@pytest.mark.anyio
async def test_two_datasets_commit_together_or_not_at_all(
    client: TestClient, fx: Fixture, storage
) -> None:
    """**Decision 0008's acceptance test, and `ontology.md` §8's requirement.**

    The second staged version names a dataset that does not exist, so the
    commit raises partway through. Both datasets must be untouched - not the
    first one applied and an error returned, which is what a per-write commit
    would leave behind and what nobody downstream could tell from success.
    """
    from src.lib.db import user_connection
    from src.lib.errors import NotFoundError

    first = upload(client, fx, f"Pair A {uuid.uuid4().hex[:6]}")
    second = upload(client, fx, f"Pair B {uuid.uuid4().hex[:6]}")
    before = (state(first), state(second))

    with pytest.raises(NotFoundError):
        async with user_connection(_uid(fx.editor)) as conn:
            good = await stage(conn, storage, fx, first)
            missing = await stage(conn, storage, fx, second)
            # Same record, pointed at a dataset that is not there.
            doomed = dataset_service.StagedVersion(
                dataset_id=uuid.uuid4(), version=missing.version,
                parquet_key=missing.parquet_key, schema_json=missing.schema_json,
                row_count=missing.row_count, produced_by_kind="action",
                produced_by_id=None, created_by=_uid(fx.editor),
            )
            await dataset_service.commit_versions(conn, [good, doomed])

    assert (state(first), state(second)) == before, "the first write survived a failed second"


@pytest.mark.anyio
async def test_a_stale_staged_version_is_refused_by_name(
    client: TestClient, fx: Fixture, storage
) -> None:
    """Staging reads `current_version`; the commit happens later. Another
    writer landing in between would make the INSERT collide with the row it
    created, and taking whatever number is free instead would write these bytes
    into the history under somebody else's version."""
    from src.lib.db import user_connection
    from src.lib.errors import ConflictError

    dataset_id = upload(client, fx, f"Stale {uuid.uuid4().hex[:6]}")

    async with user_connection(_uid(fx.editor)) as conn:
        staged = await stage(conn, storage, fx, dataset_id)

    # Somebody else versions it while ours is staged.
    async with user_connection(_uid(fx.editor)) as conn:
        other = await stage(conn, storage, fx, dataset_id, b"theirs")
        await dataset_service.commit_versions(conn, [other])

    between = state(dataset_id)
    with pytest.raises(ConflictError, match="versioned by something else"):
        async with user_connection(_uid(fx.editor)) as conn:
            await dataset_service.commit_versions(conn, [staged])

    assert state(dataset_id) == between, "the refusal left the other write alone"


@pytest.mark.anyio
async def test_add_version_still_stages_and_commits_in_one_call(
    client: TestClient, fx: Fixture, storage
) -> None:
    """The single-write callers did not change, and this is what says so."""
    from src.lib.db import user_connection

    dataset_id = upload(client, fx, f"One call {uuid.uuid4().hex[:6]}")
    before = state(dataset_id)

    async with user_connection(_uid(fx.editor)) as conn:
        updated = await dataset_service.add_version(
            conn, storage,
            dataset_id=_uid(dataset_id), workspace_id=_uid(fx.workspace),
            parquet_bytes=b"one", schema=SCHEMA, row_count=2,
            produced_by_kind="action", produced_by_id=None,
            created_by=_uid(fx.editor),
        )

    assert int(updated["current_version"]) == before["current_version"] + 1
    assert state(dataset_id)["versions"] == before["versions"] + 1
