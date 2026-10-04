"""An app carries its workspace, set by the database (§826).

The workspace-wide reads of apps - the published gallery, an action type's
usages, an object type's related artifacts - asked each app's workspace with
`rls_project_workspace_id(project_id)`, a function Postgres may not run before
the row policy, so the policy ran on every tenant's apps first. Migration
0161 puts the project's workspace on the row, where an index finds it. What
has to stay true for that to be the same rule: the column is the project's
workspace whatever a writer says, a project cannot move from under its apps,
and the policy admits exactly who it admitted.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture  # noqa: E402
from test_object_instance_workspace import admin, as_user, workspace  # noqa: E402

APP_DSN = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


def project(fx, wid, mode: str = "inherited") -> uuid.UUID:
    return admin("INSERT INTO projects (workspace_id, name, slug, created_by, permission_mode) "
                 "VALUES (%s,'P',%s,%s,%s) RETURNING id",
                 (wid, f"p-{uuid.uuid4().hex[:8]}", fx.owner, mode))[0][0]


def app(fx, pid, scope: str = "private", **extra) -> uuid.UUID:
    cols = ["project_id", "name", "slug", "created_by", "publish_scope", *extra]
    vals = [pid, "A", f"a-{uuid.uuid4().hex[:8]}", fx.owner, scope, *extra.values()]
    return admin(f"INSERT INTO canvas_apps ({', '.join(cols)}) "
                 f"VALUES ({', '.join(['%s'] * len(vals))}) RETURNING id", tuple(vals))[0][0]


def test_an_app_takes_its_projects_workspace_whatever_it_is_told(fx) -> None:
    elsewhere = workspace(fx, fx.org)
    aid = app(fx, fx.project, workspace_id=elsewhere)
    assert admin("SELECT workspace_id FROM canvas_apps WHERE id = %s", (aid,)) == [(fx.workspace,)]
    got = admin("UPDATE canvas_apps SET workspace_id = %s WHERE id = %s RETURNING workspace_id",
                (elsewhere, aid))
    assert got == [(fx.workspace,)]


def test_an_app_moved_to_another_project_takes_that_projects_workspace(fx) -> None:
    aid = app(fx, fx.project)
    other_ws = workspace(fx, fx.org)
    got = admin("UPDATE canvas_apps SET project_id = %s WHERE id = %s RETURNING workspace_id",
                (project(fx, other_ws), aid))
    assert got == [(other_ws,)]


def test_a_project_cannot_move_workspace(fx) -> None:
    pid = project(fx, fx.workspace)
    with pytest.raises(psycopg.errors.CheckViolation):
        admin("UPDATE projects SET workspace_id = %s WHERE id = %s",
              (workspace(fx, fx.org), pid))
    # Anything else about a project still changes.
    admin("UPDATE projects SET name = 'Renamed' WHERE id = %s", (pid,))


def test_the_resources_registry_gets_the_projects_workspace_too(fx) -> None:
    """`register_resource` reads a row's `workspace_id` when it has one, so
    the column must be right before it runs - on insert and on a move."""
    elsewhere = workspace(fx, fx.org)
    aid = app(fx, fx.project, workspace_id=elsewhere)
    registered = "SELECT r.workspace_id FROM resources r JOIN canvas_apps a " \
                 "ON a.resource_id = r.id WHERE a.id = %s"
    assert admin(registered, (aid,)) == [(fx.workspace,)]
    moved_to = workspace(fx, fx.org)
    admin("UPDATE canvas_apps SET project_id = %s, workspace_id = %s WHERE id = %s",
          (project(fx, moved_to), elsewhere, aid))
    assert admin(registered, (aid,)) == [(moved_to,)]


def test_an_app_in_a_project_its_writer_cannot_see_still_gets_the_right_workspace(fx) -> None:
    """The trigger reads past the caller's view of `projects`, so the value
    never depends on who wrote it - and the write is still refused."""
    hidden = project(fx, fx.workspace, mode="custom")
    admin("INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'none')",
          (hidden, fx.editor))
    with pytest.raises((psycopg.errors.InsufficientPrivilege, psycopg.errors.RaiseException)):
        as_user(fx.editor, "INSERT INTO canvas_apps (project_id, name, slug, created_by) "
                           "VALUES (%s,'A',%s,%s)", (hidden, f"a-{uuid.uuid4().hex[:8]}", fx.editor))
    aid = app(fx, hidden)
    assert admin("SELECT workspace_id FROM canvas_apps WHERE id = %s", (aid,)) == [(fx.workspace,)]


def test_the_policy_admits_what_it_admitted(fx) -> None:
    """Each disjunct by its own route: the project, workspace publication,
    and a group share - and nothing to somebody outside the workspace."""
    hidden = project(fx, fx.workspace, mode="custom")
    admin("INSERT INTO project_members (project_id, user_id, role) VALUES (%s,%s,'none')",
          (hidden, fx.viewer))
    private = app(fx, hidden, "private")
    published = app(fx, hidden, "workspace")
    shared = app(fx, hidden, "groups")
    theirs = app(fx, project(fx, workspace(fx, fx.other_org)), "workspace")
    group = admin("INSERT INTO groups (organisation_id, name) VALUES (%s,%s) RETURNING id",
                  (fx.org, f"g-{uuid.uuid4().hex[:8]}"))[0][0]
    admin("INSERT INTO group_members (group_id, user_id) VALUES (%s,%s)", (group, fx.viewer))
    admin("INSERT INTO canvas_app_shares (canvas_app_id, group_id) VALUES (%s,%s)", (shared, group))
    ids = (private, published, shared, theirs)

    def seen(user) -> set:
        rows = as_user(user, "SELECT id FROM canvas_apps WHERE id = ANY(%s)", (list(ids),))
        return {r[0] for r in rows}

    assert seen(fx.owner) == {private, published, shared}
    assert seen(fx.viewer) == {published, shared}
    assert seen(fx.outsider) == set()
    assert seen(fx.foreign) == {theirs}


def test_the_gallery_reads_only_its_workspaces_apps(fx) -> None:
    """The point of the column: a member's plan for the gallery finds the
    workspace's apps by index, before any row's policy is checked."""
    with psycopg.connect(APP_DSN) as conn:
        conn.execute("SELECT set_config('app.user_id', %s, true)", (str(fx.owner),))
        # A table this small is cheaper to scan, so ask whether the index
        # *can* be used: a filter the policy must precede cannot use it.
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = conn.execute("EXPLAIN SELECT id FROM canvas_apps "
                            "WHERE publish_scope <> 'private' AND workspace_id = %s",
                            (fx.workspace,)).fetchall()
    text = "\n".join(r[0] for r in plan)
    assert "idx_canvas_apps_workspace" in text, text


def test_every_existing_app_has_its_projects_workspace() -> None:
    """The backfill, and the trigger since: no row disagrees with its project."""
    assert admin("SELECT count(*) FROM canvas_apps a JOIN projects p ON p.id = a.project_id "
                 "WHERE a.workspace_id <> p.workspace_id") == [(0,)]


# ---- the reads that use the column: each is about one workspace -------------
def as_service(user_id, call):
    """`call(conn)` as the API makes it: platform_app, the user's context."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def go():
        engine = create_async_engine(os.environ["DATABASE_URL"])
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT set_config('app.user_id', :u, true)"),
                                   {"u": str(user_id)})
                return await call(conn)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_the_gallery_lists_this_workspaces_apps_not_its_neighbours(fx) -> None:
    """An org owner can see every workspace's published apps; the gallery of
    one workspace is still that workspace's."""
    from src.services import canvas

    here = app(fx, fx.project, "workspace")
    there = app(fx, project(fx, workspace(fx, fx.org)), "workspace")
    listed = {r["id"] for r in as_service(fx.owner, lambda c: canvas.list_published(c, fx.workspace))}
    assert here in listed and there not in listed


def test_an_action_types_usages_are_its_workspaces_modules(fx) -> None:
    """A module in another workspace that happens to name this action's id
    (a copy, say) is not one a rename here would break."""
    from src.services import actions

    action_id = uuid.uuid4()
    definition = ('{"format": 2, "events": {"e": {"effects": [{"type": "run_action", '
                  f'"config": {{"action": "{action_id}", "values": {{"status": "x"}}}}}}]}}}}}}')
    here, there = app(fx, fx.project), app(fx, project(fx, workspace(fx, fx.org)))
    for aid in (here, there):
        admin("UPDATE canvas_apps SET definition = %s::jsonb, name = %s WHERE id = %s",
              (definition, f"M {aid}", aid))
    usages = as_service(fx.owner, lambda c: actions.parameter_usages(c, fx.workspace, action_id))
    assert usages == {"status": [f"M {here}"]}


def test_an_object_view_cannot_point_at_another_workspaces_module(fx) -> None:
    from src.lib.errors import NotFoundError
    from src.services import object_views

    there = app(fx, project(fx, workspace(fx, fx.org)), "workspace")
    with pytest.raises(NotFoundError):
        as_service(fx.owner, lambda c: object_views._checked_module(c, fx.workspace, there, "v"))
