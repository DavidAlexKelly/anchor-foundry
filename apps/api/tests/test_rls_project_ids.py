"""`rls_project_ids()` says exactly what `rls_can_access_project` says
(migration 0060), and is **not in use** (migration 0061).

**Why a test file for an unused function.** 0060 replaced twenty-five project
policies with this set and 0061 put them back: the function is equivalent and
5x slower on `GET /workspaces/{id}/projects`, because `v_user_projects`
resolves `effective_project_role` *per project* and a workspace holding 881 of
them then built 881 arrays of 881 ids. The set idiom trades a per-row cost for
a per-statement one, which is a win when the statement is paid once and a loss
when something upstream already loops.

Fixing `v_user_projects` is the prerequisite, and it is its own unit. Until
then this stays proven rather than re-derived: the equivalence is the hard
part, it is established here over real rows and four constructed cases, and
thirteen mutants die on it.

The project half of §186. Same idiom, same reason, and the same thing being
asserted: **equivalence, not speed.** A faster predicate that admits one extra
row is a data leak rather than an optimisation.

`effective_project_role` is a good deal more involved than its workspace
counterpart — five outcomes, and two of them are *revocations* — so this file
is in two halves.

**Sampled from real rows**, per access route, the way §186 does it: a
uniformly random pair almost never intersects, so a sample drawn without
regard to route agrees perfectly while proving nothing.

**And constructed**, for the two rules the corpus cannot exercise. The shared
dev database holds 267 direct `'none'` entries but exactly **one** group
entry and **no** group `'none'` at all — so "a direct `none` beats a group
grant" and "every group entry is `none`" have no rows to be sampled from.
Those get a fixture built for them and rolled back, because the alternative is
a suite that reports full agreement on the two rules most likely to be wrong.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN  # noqa: E402

SAMPLE = 40

#: One query per route `effective_project_role` resolves, plus a denial
#: control. A route missing here is a route nothing compares.
SOURCES = {
    "a direct project member": """
        SELECT pm.user_id, pm.project_id FROM project_members pm
         WHERE pm.user_id IS NOT NULL ORDER BY random() LIMIT %(n)s
    """,
    "a project member through a group": """
        SELECT gm.user_id, pm.project_id FROM project_members pm
          JOIN group_members gm ON gm.group_id = pm.group_id
         ORDER BY random() LIMIT %(n)s
    """,
    "workspace membership, inherited mode": """
        SELECT wm.user_id, p.id FROM workspace_members wm
          JOIN projects p ON p.workspace_id = wm.workspace_id
         WHERE wm.user_id IS NOT NULL AND p.permission_mode = 'inherited'
         ORDER BY random() LIMIT %(n)s
    """,
    "org owner or admin": """
        SELECT u.id, p.id FROM users u
          JOIN workspaces w ON w.organisation_id = u.organisation_id
          JOIN projects p ON p.workspace_id = w.id
         WHERE u.org_role IN ('owner', 'admin') AND u.status = 'active'
         ORDER BY random() LIMIT %(n)s
    """,
    "a different organisation": """
        SELECT u.id, p.id FROM users u, projects p
          JOIN workspaces w ON w.id = p.workspace_id
         WHERE w.organisation_id <> u.organisation_id
         ORDER BY random() LIMIT %(n)s
    """,
}


@pytest.fixture(scope="module")
def admin():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        yield conn


def _agree(cur, user_id: str, project_id: str) -> tuple[bool, bool]:
    cur.execute("SELECT set_config('app.user_id', %s, false)", (user_id,))
    cur.execute("SELECT set_config('app.service', '', false)")
    # COALESCE for §186's reason: the old predicate returns NULL rather than
    # false on an ordinary denial, and a policy reads the two the same way.
    cur.execute(
        "SELECT COALESCE(rls_can_access_project(%(p)s), false),"
        "       %(p)s::uuid = ANY (rls_project_ids())",
        {"p": project_id},
    )
    return cur.fetchone()


@pytest.mark.parametrize("source", sorted(SOURCES))
def test_the_two_predicates_agree(admin, source: str) -> None:
    with admin.cursor() as cur:
        cur.execute(SOURCES[source], {"n": SAMPLE})
        pairs = [(str(u), str(p)) for u, p in cur.fetchall()]
        if not pairs:
            pytest.skip(f"no rows for {source!r} in this database")
        granted = 0
        for user_id, project_id in pairs:
            old, new = _agree(cur, user_id, project_id)
            assert old == new, (
                f"{source}: rls_can_access_project said {old} and rls_project_ids "
                f"said {new} for user {user_id} / project {project_id}"
            )
            granted += bool(old)

        if source == "a different organisation":
            assert granted == 0, "a user reached a project in another organisation"
        elif source == "a direct project member":
            # This route is the one that includes revocations, so it is the one
            # route that legitimately grants nothing on some samples.
            pass
        else:
            assert granted > 0, f"{source} granted nothing - the sample is empty"


# ---- the two rules the corpus cannot exercise -------------------------------
def _build(cur) -> dict[str, str]:
    """An org, a workspace, a project in custom mode, a group, and a user in
    that group who also has a direct entry. Rolled back by the caller."""
    tag = uuid.uuid4().hex[:8]
    ids = {k: str(uuid.uuid4()) for k in ("org", "ws", "proj", "grp", "user")}
    cur.execute(
        "INSERT INTO organisations (id, name, slug, stack_status, plan)"
        " VALUES (%s, %s, %s, 'ready', 'standard')",
        (ids["org"], f"rls {tag}", f"rls-{tag}"),
    )
    cur.execute(
        "INSERT INTO users (id, organisation_id, email, display_name, org_role, status)"
        " VALUES (%s, %s, %s, 'Member', 'member', 'active')",
        (ids["user"], ids["org"], f"rls-{tag}@test.local"),
    )
    cur.execute(
        "INSERT INTO workspaces (id, organisation_id, name, slug, description,"
        " s3_prefix, pg_schema, search_prefix)"
        " VALUES (%s, %s, %s, %s, '', %s, %s, %s)",
        (ids["ws"], ids["org"], f"ws {tag}", f"ws-{tag}", tag, f"s{tag}", tag),
    )
    # Workspace membership, so the project is not refused at step 2.
    cur.execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role)"
        " VALUES (%s, %s, 'editor')",
        (ids["ws"], ids["user"]),
    )
    cur.execute(
        "INSERT INTO projects (id, workspace_id, name, slug, description, permission_mode)"
        " VALUES (%s, %s, %s, %s, '', 'custom')",
        (ids["proj"], ids["ws"], f"proj {tag}", f"proj-{tag}"),
    )
    cur.execute(
        "INSERT INTO groups (id, organisation_id, name, description)"
        " VALUES (%s, %s, %s, '')",
        (ids["grp"], ids["org"], f"grp {tag}"),
    )
    cur.execute(
        "INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)",
        (ids["grp"], ids["user"]),
    )
    return ids


@pytest.mark.parametrize(
    "direct, group_role, expected, why",
    [
        ("none", "editor", False,
         "a direct 'none' revokes, even against a group that grants"),
        (None, "none", False,
         "every group entry is 'none', so there is nothing left to grant"),
        (None, "editor", True,
         "a group grant with no direct entry is the ordinary case"),
        ("viewer", "none", True,
         "a direct grant wins over a group revocation, the mirror of the first"),
    ],
)
def test_custom_mode_revocations(admin, direct, group_role, expected, why) -> None:
    """**Built rather than sampled**, because the shared database has 267 direct
    `'none'` rows and one group entry between them — so the interaction of the
    two, which is the subtlest rule `effective_project_role` has, cannot be
    drawn from real data at all.

    A direct entry always wins, including a revocation: p.§9's "explicit,
    per-user assignments are more specific than group grants". Getting that
    backwards is the single most consequential thing this function could do,
    in either direction — a revoked user reading a project, or a granted one
    locked out.
    """
    with psycopg.connect(ADMIN_DSN) as conn:  # not autocommit: rolled back below
        with conn.cursor() as cur:
            ids = _build(cur)
            if direct is not None:
                cur.execute(
                    "INSERT INTO project_members (project_id, user_id, role)"
                    " VALUES (%s, %s, %s)",
                    (ids["proj"], ids["user"], direct),
                )
            cur.execute(
                "INSERT INTO project_members (project_id, group_id, role)"
                " VALUES (%s, %s, %s)",
                (ids["proj"], ids["grp"], group_role),
            )
            old, new = _agree(cur, ids["user"], ids["proj"])
            assert old == expected, f"the existing predicate disagrees: {why}"
            assert new == expected, f"rls_project_ids disagrees: {why}"
        conn.rollback()


def test_a_direct_grant_does_not_survive_losing_the_workspace(admin) -> None:
    """**Step 2 of the rule, and mutation testing is what found it missing.**

    "Without workspace membership the project does not exist for the user" —
    so a `project_members` row is not on its own enough. Dropping the
    workspace gate from the custom branch survived the sampled comparison,
    because every direct grant in the corpus happens to sit in a workspace its
    user is also a member of. The interesting case has to be built.
    """
    with psycopg.connect(ADMIN_DSN) as conn:
        with conn.cursor() as cur:
            ids = _build(cur)
            # Take the workspace membership away, leaving the project grant.
            cur.execute(
                "DELETE FROM workspace_members WHERE workspace_id = %s AND user_id = %s",
                (ids["ws"], ids["user"]),
            )
            cur.execute(
                "INSERT INTO project_members (project_id, user_id, role)"
                " VALUES (%s, %s, 'editor')",
                (ids["proj"], ids["user"]),
            )
            old, new = _agree(cur, ids["user"], ids["proj"])
            assert old is False, "the existing predicate let a non-member in"
            assert new is False, "rls_project_ids let a non-member in"
        conn.rollback()


def test_an_org_admin_reaches_a_custom_project_they_are_not_a_member_of(admin) -> None:
    """**The one case where the org-admin branch is load-bearing.**

    Dropping that branch entirely survived the sampled comparison, because an
    org admin can see every workspace in the organisation and therefore
    reaches every *inherited* project through the workspace gate anyway. It is
    only a `custom` project with no entry for them that the branch alone
    grants — §9's "full access to everything in the org" is unconditional, and
    custom mode does not opt out of it.
    """
    with psycopg.connect(ADMIN_DSN) as conn:
        with conn.cursor() as cur:
            ids = _build(cur)
            cur.execute(
                "UPDATE users SET org_role = 'admin' WHERE id = %s", (ids["user"],)
            )
            # No project_members row at all: custom mode's own answer is "no".
            old, new = _agree(cur, ids["user"], ids["proj"])
            assert old is True, "the existing predicate shut an org admin out"
            assert new is True, "rls_project_ids shut an org admin out"
        conn.rollback()


def test_a_deactivated_org_admin_reaches_nothing(admin) -> None:
    """`u.status = 'active'` in the org-admin branch. Removing it survived the
    sample because this database has no deactivated admins — and "a suspended
    account keeps full access to the organisation" is precisely the kind of
    thing that stays true for a long time before anybody notices."""
    with psycopg.connect(ADMIN_DSN) as conn:
        with conn.cursor() as cur:
            ids = _build(cur)
            cur.execute(
                "UPDATE users SET org_role = 'admin', status = 'disabled' WHERE id = %s",
                (ids["user"],),
            )
            cur.execute(
                "DELETE FROM workspace_members WHERE workspace_id = %s AND user_id = %s",
                (ids["ws"], ids["user"]),
            )
            old, new = _agree(cur, ids["user"], ids["proj"])
            assert old is False, "the existing predicate let a disabled admin in"
            assert new is False, "rls_project_ids let a disabled admin in"
        conn.rollback()


def test_a_worker_sees_the_projects_of_its_own_workspace_only(admin) -> None:
    """The route no sampled pair reaches. A worker is pinned to one workspace
    and reads every project in it, whatever the permission mode says — there is
    no user for a project role to resolve against."""
    with admin.cursor() as cur:
        cur.execute(
            "SELECT p.id, p.workspace_id FROM projects p"
            " JOIN projects q ON q.workspace_id <> p.workspace_id LIMIT 1"
        )
        row = cur.fetchone()
        if row is None:
            pytest.skip("needs projects in two workspaces")
        mine, workspace = str(row[0]), str(row[1])
        cur.execute(
            "SELECT id FROM projects WHERE workspace_id <> %s LIMIT 1", (workspace,)
        )
        other = str(cur.fetchone()[0])

        cur.execute("SELECT set_config('app.user_id', '', false)")
        cur.execute("SELECT set_config('app.service', 'worker', false)")
        cur.execute("SELECT set_config('app.workspace_id', %s, false)", (workspace,))
        for project_id, expected in ((mine, True), (other, False)):
            cur.execute(
                "SELECT COALESCE(rls_can_access_project(%(p)s), false),"
                "       %(p)s::uuid = ANY (rls_project_ids())",
                {"p": project_id},
            )
            old, new = cur.fetchone()
            assert old == expected
            assert new == expected
        cur.execute("SELECT set_config('app.service', '', false)")


def test_a_caller_with_no_context_reaches_nothing(admin) -> None:
    """Fail closed, and as a *total boolean* — `= ANY ('{}')` is false, where a
    NULL in the array would make it NULL. §186's guard, same argument."""
    with admin.cursor() as cur:
        cur.execute("SELECT set_config('app.user_id', '', false)")
        cur.execute("SELECT set_config('app.service', '', false)")
        cur.execute("SELECT rls_project_ids()")
        assert cur.fetchone()[0] == []
        cur.execute("SELECT id FROM projects LIMIT 1")
        row = cur.fetchone()
        if row is not None:
            cur.execute("SELECT %s::uuid = ANY (rls_project_ids())", (str(row[0]),))
            assert cur.fetchone()[0] is False
