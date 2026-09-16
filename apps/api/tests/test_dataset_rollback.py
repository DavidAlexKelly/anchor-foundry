"""Roll back a dataset (§361; `data-lineage` p.73-76, build-order item 7).

> "The dataset rollback feature allows you to update the data and job history
>  of a dataset." (p.73)

**A rollback here appends a version rather than rewinding a pointer**, which is
what `models.restore_version` (db 0024) and `ontology.restore_type_version`
(db 0028) already do and for the reason they give: the history stays a true
record, so a model run stamped with v7 still resolves to what v7 was. Foundry
crosses the skipped transactions out instead (p.70, p.76). Most of what is
asserted below is that difference behaving: the data moves, the history does
not lose anything, and the new version says where it came from.

**Versions past the first are made through `add_version`**, the path a sync and
a model run take, because on an uploaded dataset there is no other way to make
one — `test_column_profile.py` records the same constraint. Writing rows
straight into `dataset_versions` would test a shape this platform never
produces.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import dataset_engine as engine  # noqa: E402
from src.services import datasets as ds_service  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

FIRST = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def storage(tmp_path_factory: pytest.TempPathFactory) -> LocalStorageGateway:
    return LocalStorageGateway(str(tmp_path_factory.mktemp("rollback-storage")))


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


def upload(client: TestClient, fx: Fixture, rows: bytes = FIRST) -> str:
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Rollback {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(rows), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def append(
    fx: Fixture, storage: LocalStorageGateway, dataset_id: str, csv: bytes,
    *, kind: str = "model",
) -> dict:
    """One more version, written the way a model run writes one."""
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "src.csv")
        with open(src, "wb") as handle:
            handle.write(csv)
        dest = os.path.join(tmp, "data.parquet")
        schema, rows = engine.ingest_to_parquet(src, ".csv", dest)
        with open(dest, "rb") as handle:
            parquet = handle.read()

    async def write() -> dict:
        from src.lib.db import user_connection

        async with user_connection(uuid.UUID(str(fx.editor))) as conn:
            return await ds_service.add_version(
                conn, storage,
                dataset_id=uuid.UUID(dataset_id),
                workspace_id=uuid.UUID(str(fx.workspace)),
                parquet_bytes=parquet, schema=schema, row_count=rows,
                produced_by_kind=kind, produced_by_id=None,
                created_by=uuid.UUID(str(fx.editor)),
            )

    return asyncio.run(write())


def total(client: TestClient, fx: Fixture, dataset_id: str) -> int:
    r = client.post(
        f"{base(fx)}/datasets/{dataset_id}/query", headers=hdr(fx.viewer_sub),
        json={"sql": "SELECT sum(val) AS total FROM dataset"},
    )
    assert r.status_code == 200, r.text
    return r.json()["rows"][0][0]


def roll_back(client: TestClient, fx: Fixture, dataset_id: str, version: int, **kw) -> object:
    return client.post(
        f"{base(fx)}/datasets/{dataset_id}/rollback",
        headers=hdr(kw.pop("sub", fx.editor_sub)), json={"version_number": version},
    )


@pytest.fixture()
def two_versions(client: TestClient, fx: Fixture, storage: LocalStorageGateway) -> str:
    dataset_id = upload(client, fx)
    append(fx, storage, dataset_id, b"id,val\n1,1\n2,1\n")
    return dataset_id


# ---- the data moves back -----------------------------------------------------

def test_a_rollback_puts_the_earlier_data_back(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """p.73's whole claim, read through the data rather than through the row
    that records it."""
    assert total(client, fx, two_versions) == 2, "v2 is what the dataset reads as"

    r = roll_back(client, fx, two_versions, 1)
    assert r.status_code == 200, r.text
    assert r.json()["current_version"] == 3, "a rollback appends; it does not rewind"
    assert r.json()["row_count"] == 3
    assert total(client, fx, two_versions) == 60


def test_the_history_keeps_the_version_that_was_rolled_away_from(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """**The difference from Foundry, asserted.** p.70 crosses the rolled-back
    transactions out; here they stay readable, because a run or an export
    stamped with v2 has to keep resolving to what v2 was."""
    assert roll_back(client, fx, two_versions, 1).status_code == 200
    versions = client.get(
        f"{base(fx)}/datasets/{two_versions}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert [v["version_number"] for v in versions] == [3, 2, 1]

    v2 = next(v for v in versions if v["version_number"] == 2)
    assert v2["row_count"] == 2, "v2 still describes itself"

    r = client.get(
        f"{base(fx)}/datasets/{two_versions}/preview?version=2",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, "and its bytes are still readable"
    assert len(r.json()["rows"]) == 2


def test_the_new_version_says_which_one_it_came_from(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """Instead of p.70's crossing-out: the same fact, written forwards. A
    version that simply reappeared with old data would read as a build nobody
    can account for."""
    assert roll_back(client, fx, two_versions, 1).status_code == 200
    versions = client.get(
        f"{base(fx)}/datasets/{two_versions}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    newest = versions[0]
    assert newest["produced_by_kind"] == "rollback"
    assert newest["rolled_back_to"] == 1
    assert all(v["rolled_back_to"] is None for v in versions[1:])


def test_the_schema_goes_back_with_the_data(
    client: TestClient, fx: Fixture, storage: LocalStorageGateway
) -> None:
    """**The columns are part of what is rolled back, not just the rows.**

    `version_location` already names this failure from the other direction —
    "reading v3's rows against v7's column list would describe the data
    wrongly" — and a rollback that moved the file without the schema would
    produce exactly that, on the *current* version, where everything reads it.
    A dataset that dropped a column and was then rolled back is the case: the
    rows have it again, so the schema has to as well.
    """
    dataset_id = upload(client, fx)                       # v1: id, val
    append(fx, storage, dataset_id, b"id\n1\n2\n")        # v2: id alone
    current = client.get(
        f"{base(fx)}/datasets/{dataset_id}", headers=hdr(fx.viewer_sub)
    ).json()
    assert [c["name"] for c in current["table_schema"]] == ["id"]

    assert roll_back(client, fx, dataset_id, 1).status_code == 200
    rolled = client.get(
        f"{base(fx)}/datasets/{dataset_id}", headers=hdr(fx.viewer_sub)
    ).json()
    assert [c["name"] for c in rolled["table_schema"]] == ["id", "val"]

    # And the version row says the same thing, since the Schema tab reads that.
    newest = client.get(
        f"{base(fx)}/datasets/{dataset_id}/versions", headers=hdr(fx.viewer_sub)
    ).json()[0]
    assert [c["name"] for c in newest["table_schema"]] == ["id", "val"]


def test_a_rollback_can_itself_be_rolled_back(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """**Which is why the dialog must not repeat p.76's warning.** Foundry says
    a rollback "cannot easily be undone"; nothing here is deleted, so rolling
    back to the version you were on puts it back — and a confirmation that
    claimed otherwise would be frightening somebody out of a reversible act."""
    assert roll_back(client, fx, two_versions, 1).status_code == 200
    assert total(client, fx, two_versions) == 60

    assert roll_back(client, fx, two_versions, 2).status_code == 200
    assert total(client, fx, two_versions) == 2


def test_no_bytes_are_copied(
    client: TestClient, fx: Fixture, two_versions: str, storage: LocalStorageGateway
) -> None:
    """The rollback version points at the file the old version already had.

    Not an implementation detail: it is why this costs nothing on a large
    dataset, and it is what makes the undo above possible — a rollback that
    copied would still work, but a *deleted* old version would not come back.
    """
    before = client.get(
        f"{base(fx)}/datasets/{two_versions}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    v1_size = next(v for v in before if v["version_number"] == 1)["size_bytes"]

    assert roll_back(client, fx, two_versions, 1).status_code == 200
    after = client.get(
        f"{base(fx)}/datasets/{two_versions}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert after[0]["size_bytes"] == v1_size

    async def keys() -> tuple[str, str]:
        from src.lib.db import user_connection

        async with user_connection(uuid.UUID(str(fx.viewer))) as conn:
            one = await ds_service.version_location(
                conn, uuid.UUID(str(fx.project)), uuid.UUID(two_versions), 1
            )
            three = await ds_service.version_location(
                conn, uuid.UUID(str(fx.project)), uuid.UUID(two_versions), 3
            )
        return str(one["s3_manifest_key"]), str(three["s3_manifest_key"])

    old_key, new_key = asyncio.run(keys())
    assert old_key == new_key, "the same object, not a second copy of it"


# ---- refusals ----------------------------------------------------------------

def test_rolling_back_to_where_you_already_are_is_refused(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """A no-op that wrote a version would put a row in the history saying
    something happened when nothing did."""
    r = roll_back(client, fx, two_versions, 2)
    assert r.status_code == 409, r.text
    assert "already at v2" in r.text


def test_rolling_back_to_a_version_that_does_not_exist_is_a_404(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    assert roll_back(client, fx, two_versions, 9).status_code == 404


def test_a_version_whose_file_is_gone_is_refused_as_unreadable_not_missing(
    client: TestClient, fx: Fixture, storage: LocalStorageGateway
) -> None:
    """§357's three states, and the same refusal `fork` makes: a version whose
    bytes are unaddressable is not missing, and "not found" would send somebody
    looking for a deletion that did not happen.

    The key is cleared directly because nothing over HTTP can produce this
    state — `test_dataset_forks.py` reaches it the same way.
    """
    import psycopg

    dataset_id = upload(client, fx)
    append(fx, storage, dataset_id, b"id,val\n1,1\n")
    admin = os.environ.get(
        "TEST_ADMIN_DSN",
        "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
    )
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(
            "UPDATE dataset_versions SET s3_manifest_key = NULL "
            "WHERE dataset_id = %s AND version_number = 1",
            (dataset_id,),
        )

    r = roll_back(client, fx, dataset_id, 1)
    assert r.status_code == 409, r.text
    assert "no stored file recorded" in r.text


def test_rolling_back_needs_more_than_reading(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    """p.74: "you can only roll back a dataset on which you have the Editor
    role" — and it would be this platform's answer anyway, since a rollback
    changes what every reader of the dataset sees."""
    assert roll_back(client, fx, two_versions, 1, sub=fx.viewer_sub).status_code == 403
    assert total(client, fx, two_versions) == 2, "and nothing moved"


def test_an_outsider_cannot_roll_back(
    client: TestClient, fx: Fixture, two_versions: str
) -> None:
    assert roll_back(client, fx, two_versions, 1, sub=fx.outsider_sub).status_code == 404


def test_a_rollback_is_audited(client: TestClient, fx: Fixture, two_versions: str) -> None:
    assert roll_back(client, fx, two_versions, 1).status_code == 200
    entries = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert entries.status_code == 200, entries.text
    assert "dataset.rollback" in {e["action"] for e in entries.json()}
