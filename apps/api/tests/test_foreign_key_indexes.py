"""Every foreign key to a resource has an index that leads with it (§827).

Postgres indexes the referenced side of a foreign key, never the referencing
side. Without one, deleting the referenced row reads the whole referencing
table to find what to cascade or set NULL, and every read that follows the
reference backwards - most of lineage - does the same. Migration 0162 indexed
the forty-seven there were; this keeps the list empty.
"""
from __future__ import annotations

import os
import sys

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN  # noqa: E402

#: Rows of these are almost never deleted and are read the other way, while
#: `created_by` alone is on nearly every table (db 0162).
EXEMPT_TARGETS = ("users", "workspaces", "organisations")

UNINDEXED = """
    WITH fk AS (
        SELECT c.conrelid, c.conkey, c.conname,
               c.conrelid::regclass::text AS tbl,
               c.confrelid::regclass::text AS ref
          FROM pg_constraint c
         WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
    )
    SELECT tbl, conname, ref FROM fk
     WHERE ref <> ALL(%s)
       AND NOT EXISTS (
           SELECT 1 FROM pg_index i
            WHERE i.indrelid = fk.conrelid
              -- The index's leading columns are exactly the key's, in any
              -- order: a reference check is an equality on all of them.
              AND (i.indkey::int2[])[0:array_length(fk.conkey, 1) - 1] @> fk.conkey::int2[]
              AND (i.indkey::int2[])[0:array_length(fk.conkey, 1) - 1] <@ fk.conkey::int2[]
              -- Whole, or partial on the key being present, which the check's
              -- equality implies. Any other predicate cannot serve it.
              AND (i.indpred IS NULL
                   OR pg_get_expr(i.indpred, i.indrelid) ~ (
                       '^\(?' || (SELECT a.attname FROM pg_attribute a
                                    WHERE a.attrelid = fk.conrelid
                                      AND a.attnum = fk.conkey[1])
                       || ' IS NOT NULL\)?$')))
     ORDER BY 1, 2
"""


def unindexed(conn) -> list[tuple[str, str, str]]:
    return conn.execute(UNINDEXED, (list(EXEMPT_TARGETS),)).fetchall()


def test_every_reference_to_a_resource_is_indexed() -> None:
    with psycopg.connect(ADMIN_DSN) as conn:
        missing = unindexed(conn)
    assert missing == [], (
        "foreign keys with no index leading with their columns - deleting the "
        "row they point at reads the whole table (db 0162): "
        + ", ".join(f"{t}.{name} -> {ref}" for t, name, ref in missing)
    )


def test_the_check_sees_a_missing_index_and_a_partial_one() -> None:
    """The guard against the guard: a new unindexed reference is reported, and
    a partial `IS NOT NULL` index - which answers a reference check - is
    enough."""
    with psycopg.connect(ADMIN_DSN) as conn:
        conn.execute("CREATE TABLE fk_probe (d uuid REFERENCES datasets(id))")
        try:
            assert ("fk_probe", "fk_probe_d_fkey", "datasets") in unindexed(conn)
            # A predicate the reference check does not imply is no index for it
            # - `resources.project_id` had only `WHERE trashed_at IS NULL`.
            conn.execute("ALTER TABLE fk_probe ADD COLUMN gone boolean")
            conn.execute("CREATE INDEX ON fk_probe (d) WHERE gone IS NULL")
            assert ("fk_probe", "fk_probe_d_fkey", "datasets") in unindexed(conn)
            conn.execute("CREATE INDEX ON fk_probe (d) WHERE d IS NOT NULL")
            assert not [r for r in unindexed(conn) if r[0] == "fk_probe"]
        finally:
            conn.rollback()
