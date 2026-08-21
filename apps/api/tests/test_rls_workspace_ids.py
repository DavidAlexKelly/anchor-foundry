"""`rls_workspace_ids()` says exactly what `rls_can_access_workspace` says
(migration 0058).

Migration 0058 replaced a per-row function call in eleven isolation policies
with a per-*query* array membership test, because the old shape cost 0.56ms per
row: a `SELECT id FROM object_types WHERE workspace_id = $1` returning 425 rows
took **237ms**, of which the isolation predicate was ~98%. Afterwards the same
query is **1.3ms**.

**Speed is not what these tests are about.** This is the security backstop, and
a faster predicate that admits one extra row is a data leak rather than an
optimisation. So what is asserted here is *equivalence*: for every way a caller
can reach a workspace, and for a caller who cannot, the two predicates agree.

The sample is drawn from **real rows** rather than from a fixture, and it is
drawn per access source rather than at random. A uniformly random (user,
workspace) pair almost never intersects — the first version of this check ran
3,600 pairs, agreed on all of them, and granted access in none, which proves
only that the two agree about strangers.
"""
from __future__ import annotations

import os
import sys

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN  # noqa: E402

#: How many pairs to draw from each source. Small enough to stay fast on a
#: fresh database, large enough to cover a shared one.
SAMPLE = 50

#: One query per access route `effective_workspace_role` resolves, plus the
#: denial control. Named, because a source missing from this list is a source
#: nothing here compares — which is how an equivalence test passes while the
#: two predicates disagree about the one case somebody actually uses.
SOURCES = {
    "direct membership": """
        SELECT wm.user_id, wm.workspace_id FROM workspace_members wm
         WHERE wm.user_id IS NOT NULL ORDER BY random() LIMIT %(n)s
    """,
    "membership through a group": """
        SELECT gm.user_id, wm.workspace_id FROM workspace_members wm
          JOIN group_members gm ON gm.group_id = wm.group_id
         ORDER BY random() LIMIT %(n)s
    """,
    "org owner or admin": """
        SELECT u.id, w.id FROM users u
          JOIN workspaces w ON w.organisation_id = u.organisation_id
         WHERE u.org_role IN ('owner', 'admin') AND u.status = 'active'
         ORDER BY random() LIMIT %(n)s
    """,
    "a different organisation": """
        SELECT u.id, w.id FROM users u, workspaces w
         WHERE w.organisation_id <> u.organisation_id
         ORDER BY random() LIMIT %(n)s
    """,
}


def _pairs(cur, sql: str) -> list[tuple[str, str]]:
    cur.execute(sql, {"n": SAMPLE})
    return [(str(u), str(w)) for u, w in cur.fetchall()]


@pytest.fixture(scope="module")
def admin():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        yield conn


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_two_predicates_agree(admin, source: str) -> None:
    """One test per access route, so a failure names which one moved."""
    with admin.cursor() as cur:
        pairs = _pairs(cur, SOURCES[source])
        if not pairs:
            pytest.skip(f"no rows for {source!r} in this database")
        granted = 0
        for user_id, workspace_id in pairs:
            cur.execute("SELECT set_config('app.user_id', %s, false)", (user_id,))
            cur.execute("SELECT set_config('app.service', '', false)")
            # **`COALESCE`, and it is not tidying.** `rls_can_access_workspace`
            # returns NULL rather than false on the ordinary denial, because
            # `current_setting('app.service', true)` is NULL when unset and
            # `NULL = 'worker'` is NULL. A policy reads NULL as "no row", so the
            # two are equivalent *as policies* - but comparing them as values
            # without this reports every denial as a mismatch, which is what the
            # first run of this check did.
            cur.execute(
                "SELECT COALESCE(rls_can_access_workspace(%(w)s), false),"
                "       %(w)s::uuid = ANY (rls_workspace_ids())",
                {"w": workspace_id},
            )
            old, new = cur.fetchone()
            assert old == new, (
                f"{source}: rls_can_access_workspace said {old} and "
                f"rls_workspace_ids said {new} for user {user_id} / "
                f"workspace {workspace_id}"
            )
            granted += bool(old)

        if source != "a different organisation":
            # **The assertion that keeps this from passing vacuously.** Every
            # other source is supposed to grant; a sample that granted nothing
            # would agree perfectly and prove nothing.
            assert granted > 0, f"{source} granted access to nothing - the sample is empty"
        else:
            assert granted == 0, "a user reached a workspace in another organisation"


def test_the_worker_sees_its_own_workspace_and_no_other(admin) -> None:
    """The route the sampled pairs cannot reach: `app.service = 'worker'`
    with a single workspace pinned, which is how scheduled jobs read rows for
    a workspace no user is signed in to."""
    with admin.cursor() as cur:
        cur.execute("SELECT id FROM workspaces ORDER BY created_at LIMIT 2")
        rows = cur.fetchall()
        if len(rows) < 2:
            pytest.skip("needs two workspaces")
        mine, other = str(rows[0][0]), str(rows[1][0])

        cur.execute("SELECT set_config('app.user_id', '', false)")
        cur.execute("SELECT set_config('app.service', 'worker', false)")
        cur.execute("SELECT set_config('app.workspace_id', %s, false)", (mine,))
        for workspace_id, expected in ((mine, True), (other, False)):
            cur.execute(
                "SELECT COALESCE(rls_can_access_workspace(%(w)s), false),"
                "       %(w)s::uuid = ANY (rls_workspace_ids())",
                {"w": workspace_id},
            )
            old, new = cur.fetchone()
            assert old == expected
            assert new == expected
        cur.execute("SELECT set_config('app.service', '', false)")


def test_a_worker_with_no_workspace_pinned_reaches_nothing(admin) -> None:
    """**A misconfiguration, and it has to fail closed.**

    `app.service = 'worker'` with `app.workspace_id` unset is a worker
    connection that was half set up. The worker branch then contributes a NULL,
    and without the `WHERE id IS NOT NULL` guard that NULL reaches the array —
    where `= ANY ('{NULL}')` is *NULL* rather than false for every row.

    A policy denies on both, so the two spellings are indistinguishable through
    the API, which is exactly why this is asserted on the function directly:
    the guard's whole job is to keep the answer a total boolean, and the only
    thing that can see the difference is a caller composing it.
    """
    with admin.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', '', false)")
        cur.execute("SELECT set_config('app.service', 'worker', false)")
        cur.execute("SELECT set_config('app.workspace_id', '', false)")
        cur.execute("SELECT rls_workspace_ids()")
        assert cur.fetchone()[0] == [], "a half-configured worker got a workspace"

        cur.execute("SELECT id FROM workspaces LIMIT 1")
        row = cur.fetchone()
        if row is not None:
            cur.execute("SELECT %s::uuid = ANY (rls_workspace_ids())", (str(row[0]),))
            # `is False`, not falsy: NULL would deny too, and would be a
            # different answer to the question this function is asked.
            assert cur.fetchone()[0] is False
        cur.execute("SELECT set_config('app.service', '', false)")


def test_a_caller_with_no_context_reaches_nothing(admin) -> None:
    """Neither a user nor the worker. The empty array matters as much as the
    contents: `= ANY ('{}')` is false for every row, which is the fail-closed
    behaviour a policy needs from a helper that returns a set."""
    with admin.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', '', false)")
        cur.execute("SELECT set_config('app.service', '', false)")
        cur.execute("SELECT rls_workspace_ids()")
        assert cur.fetchone()[0] == []
        cur.execute("SELECT id FROM workspaces LIMIT 1")
        row = cur.fetchone()
        if row is None:
            pytest.skip("no workspaces")
        cur.execute("SELECT %s::uuid = ANY (rls_workspace_ids())", (str(row[0]),))
        assert cur.fetchone()[0] is False
