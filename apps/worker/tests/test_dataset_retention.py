"""The nightly sweep that removes what a dataset's retention policy lets go
(§965; decision 0005; db 0170, 0171).

What is under test is the deleting, so each test builds real version files on
disk and looks at both halves afterwards: the row (kept, marked) and the bytes
(gone, or still there when they had to stay).
"""
from __future__ import annotations

import os
import sys

import duckdb
import psycopg
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.jobs import dataset_retention  # noqa: E402
from test_model_runs import ADMIN_DSN, _ctx, storage_root, workspace  # noqa: E402,F401 (fixtures)


def _versions(workspace: dict, storage_root: str, count: int) -> dict[int, str]:
    """`count` versions of the fixture's dataset, each with its own file."""
    did, tag = workspace["input_dataset_id"], workspace["tag"]
    keys = {}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for n in range(1, count + 1):
            key = f"workspaces/w-{tag}/datasets/{did}/v{n}/data.parquet"
            path = os.path.join(storage_root, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            duckdb.connect().execute(f"COPY (SELECT {n} AS v) TO '{path}' (FORMAT parquet)")
            conn.execute(
                """INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                                 transaction_type)
                   VALUES (%s, %s, %s, 'SNAPSHOT')""", (did, n, key))
            keys[n] = key
        conn.execute("UPDATE datasets SET current_version = %s, s3_location = %s WHERE id = %s",
                     (count, keys[count], did))
    return keys


def _keep(workspace: dict, n) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE datasets SET retention_versions = %s WHERE id = %s",
                     (n, workspace["input_dataset_id"]))


def _expired(workspace: dict) -> list[int]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return [r[0] for r in conn.execute(
            "SELECT version_number FROM dataset_versions WHERE dataset_id = %s"
            " AND expired_at IS NOT NULL ORDER BY version_number",
            (workspace["input_dataset_id"],)).fetchall()]


def _on_disk(storage_root: str, keys: dict[int, str]) -> list[int]:
    return [n for n, key in sorted(keys.items()) if os.path.exists(os.path.join(storage_root, key))]


def test_a_policy_removes_the_old_bytes_and_keeps_the_rows(workspace, storage_root) -> None:
    keys = _versions(workspace, storage_root, 3)
    _keep(workspace, 1)
    assert dataset_retention.expire_dataset_versions(_ctx()) >= 2
    assert _expired(workspace) == [1, 2]
    assert _on_disk(storage_root, keys) == [3]
    # Their rows are still there to say what they were.
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM dataset_versions WHERE dataset_id = %s",
                            (workspace["input_dataset_id"],)).fetchone()[0] == 3
    # Nothing is left to do the next night.
    before = _expired(workspace)
    dataset_retention.expire_dataset_versions(_ctx())
    assert _expired(workspace) == before


def test_without_a_policy_nothing_is_touched(workspace, storage_root) -> None:
    keys = _versions(workspace, storage_root, 3)
    dataset_retention.expire_dataset_versions(_ctx())
    assert _expired(workspace) == []
    assert _on_disk(storage_root, keys) == [1, 2, 3]


def test_the_file_a_rollback_reads_is_never_removed(workspace, storage_root) -> None:
    """v4 rolled back to v1 and reads v1's own file (§361)."""
    keys = _versions(workspace, storage_root, 3)
    did = workspace["input_dataset_id"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            """INSERT INTO dataset_versions (dataset_id, version_number, s3_manifest_key,
                                             transaction_type, produced_by_kind)
               VALUES (%s, 4, %s, 'SNAPSHOT', 'rollback')""", (did, keys[1]))
        conn.execute("UPDATE datasets SET current_version = 4, s3_location = %s WHERE id = %s",
                     (keys[1], did))
    _keep(workspace, 1)
    dataset_retention.expire_dataset_versions(_ctx())
    assert _expired(workspace) == [2, 3]
    assert _on_disk(storage_root, keys) == [1]


class Refusing:
    """A store that will not delete: a permissions error, an outage."""

    def delete_prefix(self, prefix: str) -> None:
        raise PermissionError("AccessDenied")


def test_a_version_whose_bytes_could_not_be_removed_is_kept(workspace, storage_root,
                                                             monkeypatch) -> None:
    keys = _versions(workspace, storage_root, 2)
    _keep(workspace, 1)
    monkeypatch.setattr(dataset_retention, "gateway_from_env", lambda: Refusing())
    dataset_retention.expire_dataset_versions(_ctx())
    # Said to be kept, and it is: the mark was undone.
    assert _expired(workspace) == []
    assert _on_disk(storage_root, keys) == [1, 2]


@pytest.mark.parametrize("key, expected", [
    ("workspaces/w-a/datasets/{did}/v3/data.parquet", "workspaces/w-a/datasets/{did}/v3/"),
    # Another dataset's file, or anything not shaped like a version's own.
    ("workspaces/w-a/datasets/00000000-0000-0000-0000-000000000000/v3/data.parquet", None),
    ("workspaces/w-a/datasets/{did}/original/rows.csv", None),
    ("workspaces/w-a/datasets/{did}/v3/../v4/data.parquet", None),
    ("workspaces/w-a/datasets/{did}/data.parquet", None),
])
def test_only_a_versions_own_directory_is_ever_removed(key, expected) -> None:
    did = "11111111-2222-3333-4444-555555555555"
    want = expected.format(did=did) if expected else None
    assert dataset_retention.version_directory(did, key.format(did=did)) == want


def test_an_unexpected_key_is_kept_not_guessed_at(workspace, storage_root) -> None:
    keys = _versions(workspace, storage_root, 2)
    odd = keys[1].replace("/v1/data.parquet", "/v1/other.parquet")
    os.rename(os.path.join(storage_root, keys[1]), os.path.join(storage_root, odd))
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET s3_manifest_key = %s WHERE dataset_id = %s"
                     " AND version_number = 1", (odd, workspace["input_dataset_id"]))
    _keep(workspace, 1)
    dataset_retention.expire_dataset_versions(_ctx())
    assert _expired(workspace) == []
    assert os.path.exists(os.path.join(storage_root, odd))


def test_a_version_that_may_not_go_is_refused_when_asked_directly(workspace, storage_root) -> None:
    """The mark asks again under the lock rather than trusting the list it was
    called from: the current version, and one of the newest N, stay."""
    _versions(workspace, storage_root, 3)
    _keep(workspace, 1)
    did = str(workspace["input_dataset_id"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        assert conn.execute("SELECT expire_dataset_version(%s, 3)", (did,)).fetchone()[0] is None
        _keep(workspace, 2)
        assert conn.execute("SELECT expire_dataset_version(%s, 2)", (did,)).fetchone()[0] is None
    assert _expired(workspace) == []


def test_versions_sharing_a_file_go_together(workspace, storage_root) -> None:
    keys = _versions(workspace, storage_root, 3)
    did = workspace["input_dataset_id"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET s3_manifest_key = %s WHERE dataset_id = %s"
                     " AND version_number = 2", (keys[1], did))
    # v2 never had a file of its own, as a rollback's version does not.
    os.remove(os.path.join(storage_root, keys[2]))
    _keep(workspace, 1)
    dataset_retention.expire_dataset_versions(_ctx())
    assert _expired(workspace) == [1, 2]
    assert _on_disk(storage_root, keys) == [3]


def test_marking_one_marks_every_version_sharing_its_file_at_once(workspace, storage_root) -> None:
    """No moment where v2 is said to be kept and v1's mark has let its
    shared file be removed."""
    keys = _versions(workspace, storage_root, 3)
    did = str(workspace["input_dataset_id"])
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE dataset_versions SET s3_manifest_key = %s WHERE dataset_id = %s"
                     " AND version_number = 2", (keys[1], did))
        _keep(workspace, 1)
        assert conn.execute("SELECT expire_dataset_version(%s, 1)", (did,)).fetchone()[0] == keys[1]
    assert _expired(workspace) == [1, 2]
