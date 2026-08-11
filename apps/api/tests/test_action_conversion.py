"""Migration 0044's conversion, run for real (decision 0007).

**The decision's first acceptance test**: "take an existing action type, run the
migration, execute it with the same payload, and assert the same property values
land." Every other check in `test_action_parameters.py` exercises the *Python*
conversion in `create_action_type`, which is the same rule written twice - and
two implementations of one rule is exactly the arrangement that drifts.

Testing the SQL needs a database where `action_types.editable_properties` still
exists, and 0044 drops it. So this builds one: a scratch database migrated to
0043, seeded with a legacy action type, then migrated the rest of the way. It is
the only test here that runs the migration runner, and it costs a few seconds
for that reason.

What it deliberately does *not* do is re-implement the conversion to compare
against. The assertions are about the meaning the old column had - each name is
writable, with the property's own type - because a test that restated the SQL
would agree with a wrong SQL just as happily.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "packages",
        "db",
    ),
)

import migrate  # noqa: E402

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]
SCRATCH_DB = "action_conversion_test"


def _apply(dsn: str, upto: str) -> None:
    """Apply every migration whose filename sorts at or below `upto`.

    Uses the runner's own discovery and its own per-migration transaction shape
    rather than globbing the directory here, so a migration this test does not
    know about (a `.py` step, say) is applied the way production applies it.
    """
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(migrate.BOOTSTRAP_SQL)
        conn.commit()
        with conn.cursor() as cur:
            cur.execute("SELECT filename FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
        for path in migrate.discover_migrations():
            if path.name > upto or path.name in applied:
                continue
            with conn.transaction():
                with conn.cursor() as cur:
                    if path.suffix == ".py":
                        migrate.apply_python_migration(path, cur)
                    else:
                        cur.execute(path.read_text())
                    cur.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s) "
                        "ON CONFLICT (filename) DO NOTHING",
                        (path.name, migrate.checksum(path)),
                    )
        conn.commit()


@pytest.fixture(scope="module")
def legacy() -> dict[str, str]:
    """A database at 0043 holding an action type of the shape 0044 converts."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
        conn.execute(f"CREATE DATABASE {SCRATCH_DB}")
    dsn = ADMIN_DSN.replace("/platform?", f"/{SCRATCH_DB}?")
    _apply(dsn, "0043_link_side_names.sql")

    tag = uuid.uuid4().hex[:8]
    with psycopg.connect(dsn, autocommit=True) as conn:
        org = conn.execute(
            "INSERT INTO organisations (name, slug) VALUES (%s, %s) RETURNING id",
            (f"Conv {tag}", f"conv-{tag}"),
        ).fetchone()[0]
        workspace = conn.execute(
            "INSERT INTO workspaces "
            "(organisation_id, name, slug, s3_prefix, pg_schema, search_prefix) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (org, f"Conv {tag}", f"conv-{tag}", f"ws/{tag}", f"ws_{tag}", f"ws-{tag}"),
        ).fetchone()[0]
        object_type = conn.execute(
            "INSERT INTO object_types (workspace_id, api_name, display_name) "
            "VALUES (%s, %s, %s) RETURNING id",
            (workspace, f"Ticket{tag}", "Ticket"),
        ).fetchone()[0]
        for order, (name, data_type, display) in enumerate(
            [
                ("status", "string", "Status"),
                ("site", "geopoint", "Site"),
                # Declared on the type but *not* made editable, so "converts
                # what the action listed" has something to be wrong about.
                ("priority", "string", "Priority"),
            ]
        ):
            conn.execute(
                "INSERT INTO object_type_properties "
                "(object_type_id, api_name, display_name, data_type, sort_order) "
                "VALUES (%s, %s, %s, %s, %s)",
                (object_type, name, display, data_type, order),
            )
        action = conn.execute(
            "INSERT INTO action_types (workspace_id, object_type_id, api_name, "
            "display_name, editable_properties) "
            "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
            (workspace, object_type, "close_ticket", "Close ticket",
             '["status", "site", "status"]'),
        ).fetchone()[0]
        # A second action on the same type, so the conversion is checked for
        # putting each action's parameters on the right action.
        other = conn.execute(
            "INSERT INTO action_types (workspace_id, object_type_id, api_name, "
            "display_name, editable_properties) "
            "VALUES (%s, %s, %s, %s, %s::jsonb) RETURNING id",
            (workspace, object_type, "reprioritise", "Reprioritise", '["priority"]'),
        ).fetchone()[0]

    _apply(dsn, "9999_zzz.sql")
    return {"dsn": dsn, "action": str(action), "other": str(other)}


def _rows(dsn: str, sql: str, params: tuple) -> list[tuple]:
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(sql, params).fetchall()


def test_each_editable_property_became_one_parameter_of_its_own_type(
    legacy: dict[str, str]
) -> None:
    parameters = _rows(
        legacy["dsn"],
        "SELECT api_name, display_name, data_type, required, hidden, sort_order "
        "FROM action_parameters WHERE action_type_id = %s ORDER BY sort_order",
        (legacy["action"],),
    )
    assert [p[0] for p in parameters] == ["status", "site"]
    # The property's display name, not the api_name, when it has one.
    assert [p[1] for p in parameters] == ["Status", "Site"]
    # And the property's *own* type: a geopoint parameter, not a string one.
    assert [p[2] for p in parameters] == ["string", "geopoint"]
    # Not required, or the conversion would refuse partial submits that the
    # old executor accepted - the one behaviour change that would look like
    # none until somebody's saved module started failing.
    assert [p[3] for p in parameters] == [False, False]
    assert [p[4] for p in parameters] == [False, False]


def test_each_property_also_became_a_rule_writing_it_back(legacy: dict[str, str]) -> None:
    rules = _rows(
        legacy["dsn"],
        "SELECT kind, config FROM action_rules WHERE action_type_id = %s ORDER BY sort_order",
        (legacy["action"],),
    )
    assert [r[0] for r in rules] == ["modify_object", "modify_object"]
    assert [r[1] for r in rules] == [
        {"property": "status", "parameter": "status"},
        {"property": "site", "parameter": "site"},
    ]


def test_a_duplicated_name_converts_once(legacy: dict[str, str]) -> None:
    """`editable_properties` was a plain array with nothing uniquing it, and
    `["status", "site", "status"]` is above. A duplicate that converted twice
    would break the parameter key outright - the migration would fail mid-run
    on somebody's database and not on ours."""
    count = _rows(
        legacy["dsn"],
        "SELECT count(*) FROM action_parameters WHERE action_type_id = %s AND api_name = 'status'",
        (legacy["action"],),
    )[0][0]
    assert count == 1


def test_the_other_action_kept_its_own_parameters(legacy: dict[str, str]) -> None:
    parameters = _rows(
        legacy["dsn"],
        "SELECT api_name FROM action_parameters WHERE action_type_id = %s",
        (legacy["other"],),
    )
    assert [p[0] for p in parameters] == ["priority"]


def test_the_column_is_gone(legacy: dict[str, str]) -> None:
    """The decision says the JSON column can be dropped *after* the conversion,
    and leaving it would be worse than never having converted: two places
    describing what an action writes, one of them stale."""
    columns = _rows(
        legacy["dsn"],
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'action_types'",
        (),
    )
    assert "editable_properties" not in {c[0] for c in columns}
