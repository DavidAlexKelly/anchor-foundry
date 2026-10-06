"""A deleted workspace's or dataset's files leave the bucket (§864; db 0164).

Deleting a workspace or a project removed its rows and left every file it held
in storage for the life of the stack: the cleanup job dropped schemas only. A
deletion now leaves a tombstone naming the prefix, and the nightly job deletes
what each names. Run against local storage, which deletes the same prefixes
the S3 gateway would list and delete.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker.jobs.cleanup import purge_deleted_storage  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]


@pytest.fixture()
def storage_root(tmp_path, monkeypatch) -> str:
    root = str(tmp_path / "storage")
    monkeypatch.setenv("LOCAL_STORAGE_ROOT", root)
    monkeypatch.delenv("S3_DATA_BUCKET", raising=False)
    return root


def _file(root: str, key: str) -> str:
    path = os.path.join(root, key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(b"bytes")
    return path


@pytest.fixture()
def world(storage_root: str) -> dict:
    """Two workspaces, each with a project holding a dataset whose file is on
    disk at the key its row names."""
    tag = uuid.uuid4().hex[:8]
    out: dict = {"workspaces": []}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"TombOrg {tag}", f"tomb-{tag}")).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,'Tomb','owner',%s,'active') RETURNING id""",
            (org, f"tomb-{tag}@example.com", f"sub-tomb-{tag}")).fetchone()[0]
        for i in range(2):
            wid = uuid.uuid4()
            prefix = f"workspaces/t{i}-{tag}/"
            conn.execute(
                """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                           search_prefix, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (wid, org, f"T{i} {tag}", f"t{i}-{tag}", prefix, f"ws_{wid.hex[:12]}",
                 f"ws-{wid.hex[:12]}-", user))
            pid = conn.execute(
                "INSERT INTO projects (workspace_id, name, slug, created_by) VALUES (%s,%s,%s,%s)"
                " RETURNING id", (wid, f"P{i} {tag}", f"p{i}-{tag}", user)).fetchone()[0]
            did = uuid.uuid4()
            key = f"{prefix}datasets/{did}/v1/data.parquet"
            conn.execute(
                """INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin, s3_location,
                                         table_schema, row_count, current_version, created_by)
                   VALUES (%s,%s,%s,%s,%s,'upload',%s,'[]'::jsonb,1,1,%s)""",
                (did, pid, wid, f"D{i} {tag}", f"d{i}-{tag}", key, user))
            out["workspaces"].append({
                "id": wid, "prefix": prefix, "project": pid, "dataset": did,
                "file": _file(storage_root, key),
                "attachment": _file(storage_root, f"{prefix}attachments/{uuid.uuid4()}/a.png"),
            })
    return out


def _tombstones() -> list[str]:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        return [r[0] for r in conn.execute("SELECT prefix FROM storage_tombstones ORDER BY id")]


def _purge() -> int:
    return purge_deleted_storage(build_op_context(
        resources={"platform_db": PlatformDatabase(dsn=APP_DSN)}))


def test_a_deleted_project_leaves_its_datasets_files_to_be_deleted(world: dict) -> None:
    gone, kept = world["workspaces"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM projects WHERE id = %s", (gone["project"],))
    assert f"{gone['prefix']}datasets/{gone['dataset']}/" in _tombstones()

    _purge()
    assert not os.path.exists(gone["file"])
    # The rest of the workspace is still a workspace's.
    assert os.path.exists(gone["attachment"]) and os.path.exists(kept["file"])
    assert f"{gone['prefix']}datasets/{gone['dataset']}/" not in _tombstones()


def test_a_deleted_workspace_leaves_its_whole_prefix_once(world: dict) -> None:
    gone, kept = world["workspaces"]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM workspaces WHERE id = %s", (gone["id"],))
    mine = [p for p in _tombstones() if p.startswith(gone["prefix"])]
    # The workspace's prefix covers its datasets; they add nothing of their own.
    assert mine == [gone["prefix"]]

    _purge()
    assert not os.path.exists(gone["file"]) and not os.path.exists(gone["attachment"])
    assert os.path.exists(kept["file"]) and os.path.exists(kept["attachment"])
    assert not [p for p in _tombstones() if p.startswith(gone["prefix"])]


def test_a_tombstone_naming_anything_else_deletes_nothing(world: dict) -> None:
    """The prefix is checked before the bucket is touched: `workspaces/` alone
    would be every customer file in the stack."""
    kept = world["workspaces"][1]
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for bad in ("workspaces/", "workspaces/x/attachments/", "elsewhere/"):
            conn.execute("INSERT INTO storage_tombstones (prefix) VALUES (%s)", (bad,))
    _purge()
    assert os.path.exists(kept["file"]) and os.path.exists(kept["attachment"])
    assert not {"workspaces/", "workspaces/x/attachments/", "elsewhere/"} & set(_tombstones())


def test_the_application_role_cannot_reach_the_table() -> None:
    with psycopg.connect(APP_DSN) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM storage_tombstones")
