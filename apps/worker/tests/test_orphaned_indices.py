"""A deleted workspace's object indices leave the domain (§876; db 0166).

Deleting a workspace deletes its object types by cascade, which no route sees,
so the index each type had in OpenSearch stayed there for the life of the
stack, holding every object the workspace had. The nightly cleanup now lists
the domain's workspace indices, asks the database which prefixes belong to no
workspace, and deletes those. Driven over a real socket against the API's
OpenSearch fixture server, as `test_instance_index.py` is.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from dagster import build_op_context

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from anchor_worker import instance_index  # noqa: E402
from anchor_worker.jobs.cleanup import drop_orphaned_indices  # noqa: E402
from anchor_worker.resources import PlatformDatabase  # noqa: E402
from test_instance_index import call, cluster  # noqa: E402,F401

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
APP_DSN = os.environ["WORKER_DATABASE_URL"]


def _workspaces(n: int) -> list[dict]:
    tag = uuid.uuid4().hex[:8]
    made: list[dict] = []
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s,%s) RETURNING id",
            (f"IdxOrg {tag}", f"idx-{tag}")).fetchone()[0]
        user = conn.execute(
            """INSERT INTO users (organisation_id, email, display_name, org_role, cognito_sub, status)
               VALUES (%s,%s,'Idx','owner',%s,'active') RETURNING id""",
            (org, f"idx-{tag}@example.com", f"sub-idx-{tag}")).fetchone()[0]
        for i in range(n):
            wid = uuid.uuid4()
            short = wid.hex[:12]
            conn.execute(
                """INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                           search_prefix, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (wid, org, f"I{i} {tag}", f"i{i}-{tag}", f"workspaces/i{i}-{tag}-{short}/",
                 f"ws_{short}", f"ws-{short}-", user))
            made.append({"id": wid, "prefix": f"ws-{short}-"})
    return made


def _indices(base: str) -> set[str]:
    return {row["index"] for row in call(base, "GET", "/_cat/indices/ws-*?format=json&h=index")}


def _run() -> list[str]:
    return drop_orphaned_indices(build_op_context(
        resources={"platform_db": PlatformDatabase(dsn=APP_DSN)}))


@pytest.fixture()
def domain(cluster: str, monkeypatch) -> str:  # noqa: F811
    call(cluster, "POST", "/__reset", {})
    monkeypatch.setattr(instance_index, "from_env",
                        lambda: instance_index.InstanceIndex(cluster, "admin", "admin"))
    return cluster


def test_a_deleted_workspaces_indices_are_deleted_and_a_live_ones_kept(domain: str) -> None:
    gone, kept = _workspaces(2)
    names = {
        "gone_type": f"{gone['prefix']}objects-{uuid.uuid4()}",
        "gone_legacy": f"{gone['prefix']}object-instances",
        "kept_type": f"{kept['prefix']}objects-{uuid.uuid4()}",
        "kept_legacy": f"{kept['prefix']}object-instances",
        # Under the dead prefix, but not a name the platform makes.
        "gone_other": f"{gone['prefix']}something-else",
    }
    for name in names.values():
        call(domain, "PUT", f"/{name}", {})
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("DELETE FROM workspaces WHERE id = %s", (gone["id"],))

    dropped = _run()
    assert sorted(dropped) == sorted([names["gone_type"], names["gone_legacy"]])
    left = _indices(domain)
    assert names["gone_type"] not in left and names["gone_legacy"] not in left
    assert {names["kept_type"], names["kept_legacy"], names["gone_other"]} <= left
    # Nothing left to do the second night.
    assert _run() == []


def test_a_name_that_is_not_a_workspaces_is_left(domain: str) -> None:
    """The prefix shape is checked twice, here and in the database: an index
    an operator made on the domain is not the cleanup's to delete."""
    for name in ("ws-notaworkspace-objects-x", "ws-ABCDEF012345-object-instances"):
        call(domain, "PUT", f"/{name}", {})
    assert _run() == []
    assert {"ws-notaworkspace-objects-x", "ws-ABCDEF012345-object-instances"} <= _indices(domain)


def test_without_an_index_there_is_nothing_to_do(monkeypatch) -> None:
    monkeypatch.setattr(instance_index, "from_env", lambda: None)
    assert _run() == []


def test_the_database_says_only_which_well_formed_prefixes_are_orphaned() -> None:
    (live,) = _workspaces(1)
    dead = f"ws-{uuid.uuid4().hex[:12]}-"
    with psycopg.connect(APP_DSN) as conn:
        rows = conn.execute(
            "SELECT orphaned_search_prefixes(%s)",
            ([live["prefix"], dead, dead, "ws-", "ws-%-", "anything"],)).fetchall()
    assert [r[0] for r in rows] == [dead]
