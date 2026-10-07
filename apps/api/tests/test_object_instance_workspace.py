"""An object carries its workspace, set by the database (§817; roadmap phase
3, E.4).

`oi_isolation` checked each object's type with a join per row - most of a
million-object count. Migration 0158 puts the type's workspace on the row and
compares that. What has to stay true for the shortcut to be the same rule:
the column is the type's workspace whatever a writer says, a type cannot move
from under its objects, and the policy refuses what the join refused.
"""
from __future__ import annotations

import os
import re
import sys
import uuid

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture  # noqa: E402

APP_DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


def admin(sql: str, params: tuple = ()):
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        cur = conn.execute(sql, params)
        return cur.fetchall() if cur.description else None


def workspace(fx, org) -> uuid.UUID:
    wid = uuid.uuid4()
    short = wid.hex[:12]
    admin("""INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema,
                                     search_prefix, created_by)
             VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
          (wid, org, f"W {short}", f"w-{short}", f"workspaces/w-{short}/", f"ws_{short}",
           f"ws-{short}-", fx.owner))
    return wid


def typed(fx, wid) -> tuple[uuid.UUID, uuid.UUID]:
    """An object type in `wid` with one source, both made by the owner role."""
    project = admin("INSERT INTO projects (workspace_id, name, slug, created_by) "
                    "VALUES (%s,%s,%s,%s) RETURNING id",
                    (wid, "P", f"p-{uuid.uuid4().hex[:8]}", fx.owner))[0][0]
    dataset = admin("""INSERT INTO datasets (project_id, workspace_id, name, slug, origin, s3_location,
                                             table_schema, row_count, current_version, created_by)
                       VALUES (%s,%s,%s,%s,'upload',%s,'[]'::jsonb,0,1,%s) RETURNING id""",
                    (project, wid, "D", f"d-{uuid.uuid4().hex[:8]}", "k", fx.owner))[0][0]
    type_id = admin("INSERT INTO object_types (workspace_id, api_name, display_name, created_by) "
                    "VALUES (%s,%s,'T',%s) RETURNING id",
                    (wid, f"t_{uuid.uuid4().hex[:8]}", fx.owner))[0][0]
    source = admin("INSERT INTO object_type_sources (object_type_id, dataset_id, primary_key_column, "
                   "column_mappings) VALUES (%s,%s,'k','{}'::jsonb) RETURNING id",
                   (type_id, dataset))[0][0]
    return type_id, source


def as_user(user_id, sql: str, params: tuple = ()):
    """As the API connects: platform_app, with the user's RLS context."""
    with psycopg.connect(APP_DSN) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(user_id),))
        cur = conn.execute(sql, params)
        rows = cur.fetchall() if cur.description else None
        conn.commit()
        return rows


def test_an_object_takes_its_types_workspace_whatever_it_is_told(fx) -> None:
    home, elsewhere = fx.workspace, workspace(fx, fx.org)
    type_id, source = typed(fx, home)
    got = admin("INSERT INTO object_instances (object_type_id, source_id, primary_key, workspace_id) "
                "VALUES (%s,%s,'a',%s) RETURNING workspace_id", (type_id, source, elsewhere))
    assert str(got[0][0]) == str(home)
    got = admin("UPDATE object_instances SET workspace_id = %s WHERE source_id = %s "
                "RETURNING workspace_id", (elsewhere, source))
    assert str(got[0][0]) == str(home)


def test_an_object_moved_to_another_type_takes_that_types_workspace(fx) -> None:
    first, _ = typed(fx, fx.workspace)
    other_ws = workspace(fx, fx.org)
    second, source = typed(fx, other_ws)
    admin("INSERT INTO object_instances (object_type_id, source_id, primary_key) "
          "VALUES (%s,%s,'m')", (first, source))
    got = admin("UPDATE object_instances SET object_type_id = %s WHERE source_id = %s "
                "RETURNING workspace_id", (second, source))
    assert str(got[0][0]) == str(other_ws)


def test_a_type_cannot_move_workspace(fx) -> None:
    type_id, _ = typed(fx, fx.workspace)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin("UPDATE object_types SET workspace_id = %s WHERE id = %s",
              (workspace(fx, fx.org), type_id))
    # Anything else about a type still changes.
    admin("UPDATE object_types SET display_name = 'Renamed' WHERE id = %s", (type_id,))


def test_the_policy_refuses_what_the_join_refused(fx) -> None:
    """A member sees and writes their workspace's objects and no other's."""
    mine, my_source = typed(fx, fx.workspace)
    theirs_ws = workspace(fx, fx.other_org)
    theirs, their_source = typed(fx, theirs_ws)
    admin("INSERT INTO object_instances (object_type_id, source_id, primary_key) "
          "VALUES (%s,%s,'x'), (%s,%s,'y')", (mine, my_source, theirs, their_source))

    seen = as_user(fx.owner, "SELECT primary_key FROM object_instances "
                             "WHERE object_type_id IN (%s, %s)", (mine, theirs))
    assert [r[0] for r in seen] == ["x"]
    as_user(fx.owner, "INSERT INTO object_instances (object_type_id, source_id, primary_key) "
                      "VALUES (%s,%s,'x2')", (mine, my_source))
    # Into another organisation's type - even naming one's own workspace,
    # which the trigger replaces with the type's.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(fx.owner, "INSERT INTO object_instances (object_type_id, source_id, primary_key, "
                          "workspace_id) VALUES (%s,%s,'z',%s)", (theirs, their_source, fx.workspace))
    # Nor moved there.
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_user(fx.owner, "UPDATE object_instances SET object_type_id = %s "
                          "WHERE source_id = %s AND primary_key = 'x2'", (theirs, my_source))
    # A user outside every workspace sees nothing.
    assert as_user(fx.outsider, "SELECT count(*) FROM object_instances "
                                "WHERE object_type_id = %s", (mine,)) == [(0,)]


def test_a_count_does_not_visit_object_types(fx) -> None:
    """The point of the column: the plan for counting a type's objects, as a
    member runs it, no longer joins each row to its type."""
    type_id, _ = typed(fx, fx.workspace)
    plan = as_user(fx.owner, "EXPLAIN SELECT count(*) FROM object_instances "
                             "WHERE object_type_id = %s", (type_id,))
    text = "\n".join(r[0] for r in plan)
    # A scan of the relation, not the kiosk setting that shares its name.
    assert not re.search(r" on object_types\b", text), text
    assert "workspace_id = ANY" in text, text


def test_every_existing_object_has_its_types_workspace() -> None:
    """The backfill, and the trigger since: no row disagrees with its type."""
    assert admin("SELECT count(*) FROM object_instances i JOIN object_types t "
                 "ON t.id = i.object_type_id WHERE i.workspace_id <> t.workspace_id") == [(0,)]


def analyze_count() -> int:
    """Manual ANALYZEs of the table; autovacuum's are counted elsewhere."""
    return admin("SELECT analyze_count FROM pg_stat_user_tables "
                 "WHERE relname = 'object_instances'")[0][0]


def counted_after(before: int) -> int:
    """The count as soon as it moves, or as it stands after two seconds:
    a backend reports its statistics when its transaction ends, not at once."""
    import time

    for _ in range(20):
        now = analyze_count()
        if now != before:
            return now
        time.sleep(0.1)
    return analyze_count()


def upsert(fx, rows: int, monkeypatch, threshold: int) -> None:
    import asyncio
    from datetime import datetime, timezone

    from sqlalchemy.ext.asyncio import create_async_engine

    from src.services import instances

    monkeypatch.setattr(instances, "ANALYZE_AFTER_ROWS", threshold)
    type_id, source = typed(fx, fx.workspace)

    async def go() -> None:
        engine = create_async_engine(ADMIN_DSN.replace("postgresql://", "postgresql+psycopg://", 1))
        try:
            async with engine.begin() as conn:
                await instances.upsert_instances(
                    conn, object_type_id=type_id, source_id=source,
                    rows=[(str(i), {"n": i}) for i in range(rows)],
                    synced_at=datetime.now(timezone.utc))
        finally:
            await engine.dispose()

    asyncio.run(go())


def test_a_large_write_brings_the_statistics_up_to_date(fx, monkeypatch) -> None:
    """Straight after a big sync a stale plan was a slow one (db 0158), so a
    write past the threshold analyzes the table itself."""
    before = analyze_count()
    upsert(fx, 3, monkeypatch, threshold=3)
    assert counted_after(before) == before + 1


def test_a_small_write_leaves_the_statistics_to_autovacuum(fx, monkeypatch) -> None:
    before = analyze_count()
    upsert(fx, 2, monkeypatch, threshold=3)
    assert counted_after(before) == before


def test_a_count_can_be_answered_from_the_index_alone(fx) -> None:
    """Both policies read only columns the type-and-workspace index holds, so
    a count need not visit the table. Asked of the planner with the other
    routes closed, since which one it picks for a handful of rows says
    nothing about a million."""
    type_id, _ = typed(fx, fx.workspace)
    with psycopg.connect(APP_DSN) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(fx.owner),))
        conn.execute("SET LOCAL enable_seqscan = off")
        conn.execute("SET LOCAL enable_bitmapscan = off")
        plan = "\n".join(r[0] for r in conn.execute(
            "EXPLAIN SELECT count(*) FROM object_instances WHERE object_type_id = %s",
            (type_id,)).fetchall())
    assert "Index Only Scan using idx_object_instances_type_workspace" in plan, plan


def test_the_stamp_reads_the_type_as_its_owner() -> None:
    """§899: under `object_types`' policies, evaluated per row, the trigger
    was nine tenths of a sync's write. As the owner it is a key lookup, with a
    search path of its own; `test_the_policy_refuses_what_the_join_refused`
    is what says nothing more is admitted."""
    [(definer, config)] = admin(
        "SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'object_instances_set_workspace'")
    assert definer is True
    assert config == ["search_path=public"]
