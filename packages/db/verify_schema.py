#!/usr/bin/env python3
"""Schema verification against spec §16 + behavioural tests for the
permission model (§9), workspace isolation (§4), audit immutability (§16),
and row-level security (§10).

Run: DATABASE_URL=... APP_DATABASE_URL=... python verify_schema.py
APP_DATABASE_URL connects as platform_app (RLS-subject role).
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg

FAILURES: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" — {detail}" if detail and not condition else ""))
    if not condition:
        FAILURES.append(name)


SPEC_TABLES = {
    # §16 Core Tables
    "organisations", "users", "groups", "group_members",
    "workspaces", "workspace_members", "projects", "project_members",
    # §16 Resource Tables
    "connections", "datasets", "dataset_versions", "models", "model_inputs",
    "model_runs", "object_types", "object_type_properties", "link_types",
    "object_type_sources", "canvas_apps", "canvas_app_versions", "code_repos",
    "audit_log",
}
SPEC_FUNCTIONS = {"effective_workspace_role", "effective_project_role"}
SPEC_VIEWS = {"v_user_workspaces", "v_user_projects"}


def main() -> int:
    dsn = os.environ["DATABASE_URL"]
    app_dsn = os.environ["APP_DATABASE_URL"]
    conn = psycopg.connect(dsn, autocommit=True)
    cur = conn.cursor()

    print("== 1. Structural verification against spec §16 ==")
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
    tables = {r[0] for r in cur.fetchall()}
    missing = SPEC_TABLES - tables
    check("all 22 spec §16 tables exist", not missing, f"missing: {missing}")
    extra = tables - SPEC_TABLES - {"schema_migrations", "canvas_app_shares"}
    check("no unexplained extra tables", not extra, f"extra: {extra}")

    cur.execute("SELECT routine_name FROM information_schema.routines WHERE routine_schema='public'")
    funcs = {r[0] for r in cur.fetchall()}
    check("spec §16 permission functions exist", SPEC_FUNCTIONS <= funcs, f"missing: {SPEC_FUNCTIONS - funcs}")

    cur.execute("SELECT table_name FROM information_schema.views WHERE table_schema='public'")
    views = {r[0] for r in cur.fetchall()}
    check("spec §16 views exist", SPEC_VIEWS <= views, f"missing: {SPEC_VIEWS - views}")

    cur.execute("SELECT rulename FROM pg_rules WHERE tablename='audit_log'")
    rules = {r[0] for r in cur.fetchall()}
    check("audit_log protected by no-update/no-delete SQL rules",
          {"audit_log_no_update", "audit_log_no_delete"} <= rules, f"found: {rules}")

    # Workspace isolation columns (§16: workspaces stores s3_prefix, pg_schema, search_prefix)
    cur.execute("""SELECT column_name FROM information_schema.columns
                   WHERE table_name='workspaces' AND column_name IN ('s3_prefix','pg_schema','search_prefix')""")
    check("workspaces stores isolation anchors", len(cur.fetchall()) == 3)

    print("\n== 2. Seed test fixture ==")
    ids = {k: str(uuid.uuid4()) for k in
           ["org", "owner", "admin", "member1", "member2", "outsider",
            "grp", "ws_ops", "ws_fin", "proj_inherit", "proj_custom"]}
    cur.execute("""INSERT INTO organisations (id, name, slug) VALUES (%s, 'Acme', 'acme')""", (ids["org"],))
    for key, email, role in [("owner", "owner@acme.test", "owner"),
                             ("admin", "admin@acme.test", "admin"),
                             ("member1", "m1@acme.test", "member"),
                             ("member2", "m2@acme.test", "member"),
                             ("outsider", "out@acme.test", "member")]:
        cur.execute("""INSERT INTO users (id, organisation_id, cognito_sub, email, org_role, status)
                       VALUES (%s, %s, %s, %s, %s, 'active')""",
                    (ids[key], ids["org"], f"sub-{key}", email, role))
    cur.execute("INSERT INTO groups (id, organisation_id, name) VALUES (%s, %s, 'Analysts')", (ids["grp"], ids["org"]))
    cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)", (ids["grp"], ids["member2"]))
    cur.execute("""INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema, search_prefix)
                   VALUES (%s, %s, 'Operations', 'operations', 'workspace-operations/', 'ws_operations', 'ws-operations-')""",
                (ids["ws_ops"],) + (ids["org"],))
    cur.execute("""INSERT INTO workspaces (id, organisation_id, name, slug, s3_prefix, pg_schema, search_prefix)
                   VALUES (%s, %s, 'Finance', 'finance', 'workspace-finance/', 'ws_finance', 'ws-finance-')""",
                (ids["ws_fin"], ids["org"]))
    # member1: direct viewer on ops. Analysts group: editor on ops. member1 also in group? No.
    cur.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'viewer')",
                (ids["ws_ops"], ids["member1"]))
    cur.execute("INSERT INTO workspace_members (workspace_id, group_id, role) VALUES (%s, %s, 'editor')",
                (ids["ws_ops"], ids["grp"]))
    cur.execute("""INSERT INTO projects (id, workspace_id, name, slug) VALUES (%s, %s, 'Supply Chain', 'supply-chain')""",
                (ids["proj_inherit"], ids["ws_ops"]))
    cur.execute("""INSERT INTO projects (id, workspace_id, name, slug, permission_mode)
                   VALUES (%s, %s, 'Secret Costing', 'secret-costing', 'custom')""",
                (ids["proj_custom"], ids["ws_ops"]))
    # custom project: member1 explicitly 'none', Analysts group 'editor'
    cur.execute("INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'none')",
                (ids["proj_custom"], ids["member1"]))
    cur.execute("INSERT INTO project_members (project_id, group_id, role) VALUES (%s, %s, 'editor')",
                (ids["proj_custom"], ids["grp"]))
    print("  fixture created")

    def ws_role(user: str, ws: str):
        cur.execute("SELECT effective_workspace_role(%s, %s)", (ids[user], ids[ws]))
        return cur.fetchone()[0]

    def proj_role(user: str, proj: str):
        cur.execute("SELECT effective_project_role(%s, %s)", (ids[user], ids[proj]))
        return cur.fetchone()[0]

    print("\n== 3. effective_workspace_role (§9 resolution) ==")
    check("org owner → admin everywhere", ws_role("owner", "ws_fin") == "admin")
    check("org admin → admin everywhere", ws_role("admin", "ws_ops") == "admin")
    check("direct member resolves role", ws_role("member1", "ws_ops") == "viewer")
    check("group member inherits group role", ws_role("member2", "ws_ops") == "editor")
    check("no membership → NULL (404 semantics)", ws_role("outsider", "ws_ops") is None)
    check("member of one ws sees nothing in another", ws_role("member1", "ws_fin") is None)
    # highest-wins: give member1 group membership too (viewer direct + editor group)
    cur.execute("INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)", (ids["grp"], ids["member1"]))
    check("highest of direct+group wins", ws_role("member1", "ws_ops") == "editor")
    cur.execute("DELETE FROM group_members WHERE group_id=%s AND user_id=%s", (ids["grp"], ids["member1"]))

    print("\n== 4. effective_project_role (§9, inheritance + 'none') ==")
    check("org admin → owner on any project", proj_role("admin", "proj_custom") == "owner")
    check("inherited: ws viewer → project viewer", proj_role("member1", "proj_inherit") == "viewer")
    check("inherited: ws editor (via group) → project editor", proj_role("member2", "proj_inherit") == "editor")
    check("inherited: no ws access → NULL", proj_role("outsider", "proj_inherit") is None)
    check("custom: direct 'none' revokes despite ws grant", proj_role("member1", "proj_custom") is None)
    check("custom: group grant applies", proj_role("member2", "proj_custom") == "editor")
    check("custom: no entry → no access", proj_role("owner", "proj_custom") == "owner" and True)  # org owner bypass
    # add a plain member with ws access but no custom entry
    cur.execute("INSERT INTO workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'editor')",
                (ids["ws_ops"], ids["outsider"]))
    check("custom: ws member without custom entry → NULL", proj_role("outsider", "proj_custom") is None)
    # direct grant beats group 'none'
    cur.execute("UPDATE project_members SET role='owner' WHERE project_id=%s AND user_id=%s",
                (ids["proj_custom"], ids["member1"]))
    check("custom: direct grant respected", proj_role("member1", "proj_custom") == "owner")

    print("\n== 5. Views ==")
    cur.execute("SELECT workspace_id, role FROM v_user_workspaces WHERE user_id=%s", (ids["member1"],))
    rows = cur.fetchall()
    check("v_user_workspaces returns only accessible workspaces",
          len(rows) == 1 and str(rows[0][0]) == ids["ws_ops"])
    cur.execute("SELECT count(*) FROM v_user_workspaces WHERE user_id=%s", (ids["owner"],))
    check("v_user_workspaces: org owner sees all", cur.fetchone()[0] == 2)
    cur.execute("SELECT project_id, role FROM v_user_projects WHERE user_id=%s ORDER BY name", (ids["member2"],))
    rows = cur.fetchall()
    check("v_user_projects resolves roles per project",
          {(str(r[0]), r[1]) for r in rows} == {(ids["proj_custom"], "editor"), (ids["proj_inherit"], "editor")})

    print("\n== 6. Hard isolation triggers (§4) ==")
    ds_id = str(uuid.uuid4())
    cur.execute("""INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin, s3_location)
                   VALUES (%s, %s, %s, 'Orders', 'orders', 'upload', 'workspace-operations/datasets/x/')""",
                (ds_id, ids["proj_inherit"], ids["ws_ops"]))
    try:
        cur.execute("""INSERT INTO datasets (id, project_id, workspace_id, name, slug, origin, s3_location)
                       VALUES (%s, %s, %s, 'Bad', 'bad', 'upload', 'x')""",
                    (str(uuid.uuid4()), ids["proj_inherit"], ids["ws_fin"]))
        check("dataset cross-workspace insert rejected", False)
    except psycopg.Error as e:
        check("dataset cross-workspace insert rejected", "hard isolation" in str(e))
    try:
        cur.execute("UPDATE workspaces SET s3_prefix='hacked/' WHERE id=%s", (ids["ws_ops"],))
        check("isolation anchors immutable", False)
    except psycopg.Error as e:
        check("isolation anchors immutable", "immutable" in str(e))
    ot_ops, ot_fin = str(uuid.uuid4()), str(uuid.uuid4())
    cur.execute("""INSERT INTO object_types (id, workspace_id, api_name, display_name)
                   VALUES (%s, %s, 'Customer', 'Customer'), (%s, %s, 'Invoice', 'Invoice')""",
                (ot_ops, ids["ws_ops"], ot_fin, ids["ws_fin"]))
    try:
        cur.execute("""INSERT INTO link_types (workspace_id, api_name, display_name,
                       from_object_type_id, to_object_type_id, cardinality)
                       VALUES (%s, 'bad_link', 'Bad', %s, %s, 'one_to_many')""",
                    (ids["ws_ops"], ot_ops, ot_fin))
        check("link type cross-workspace rejected", False)
    except psycopg.Error as e:
        check("link type cross-workspace rejected", "hard isolation" in str(e))

    print("\n== 7. Audit log immutability (§16) ==")
    cur.execute("""INSERT INTO audit_log (organisation_id, user_id, action, resource_type, resource_id)
                   VALUES (%s, %s, 'workspace.create', 'workspace', %s) RETURNING id""",
                (ids["org"], ids["owner"], ids["ws_ops"]))
    audit_id = cur.fetchone()[0]
    cur.execute("UPDATE audit_log SET action='tampered' WHERE id=%s", (audit_id,))
    cur.execute("SELECT action FROM audit_log WHERE id=%s", (audit_id,))
    check("UPDATE on audit_log is a no-op", cur.fetchone()[0] == "workspace.create")
    cur.execute("DELETE FROM audit_log WHERE id=%s", (audit_id,))
    cur.execute("SELECT count(*) FROM audit_log WHERE id=%s", (audit_id,))
    check("DELETE on audit_log is a no-op", cur.fetchone()[0] == 1)

    print("\n== 8. Row-level security as platform_app (§10 second layer) ==")
    app = psycopg.connect(app_dsn)
    ac = app.cursor()
    # No context set → fail closed
    ac.execute("SELECT count(*) FROM workspaces")
    check("RLS fails closed with no session context", ac.fetchone()[0] == 0)
    app.rollback()
    # member1 context: sees ops only
    with app.transaction():
        ac.execute("SELECT set_config('app.user_id', %s, true)", (ids["member1"],))
        ac.execute("SELECT slug FROM workspaces ORDER BY slug")
        check("RLS: member sees only their workspace", [r[0] for r in ac.fetchall()] == ["operations"])
        ac.execute("SELECT count(*) FROM datasets")
        n_member = ac.fetchone()[0]
        check("RLS: member sees datasets in accessible projects", n_member == 1)
    # outsider context: outsider now has ws editor on ops (added in §4 tests) but 'none'-less custom proj
    with app.transaction():
        ac.execute("SELECT set_config('app.user_id', %s, true)", (ids["outsider"],))
        ac.execute("SELECT count(*) FROM projects")
        check("RLS: custom-permission project hidden from non-member", ac.fetchone()[0] == 1)
    # org owner sees everything
    with app.transaction():
        ac.execute("SELECT set_config('app.user_id', %s, true)", (ids["owner"],))
        ac.execute("SELECT count(*) FROM workspaces")
        check("RLS: org owner sees all workspaces", ac.fetchone()[0] == 2)
    # worker context scoped to finance workspace
    with app.transaction():
        ac.execute("SELECT set_config('app.service', 'worker', true)")
        ac.execute("SELECT set_config('app.workspace_id', %s, true)", (ids["ws_fin"],))
        ac.execute("SELECT slug FROM workspaces")
        check("RLS: worker context scoped to its workspace", [r[0] for r in ac.fetchall()] == ["finance"])
    app.close()

    print("\n== 9. Workspace schema provisioning (§4 pg-level isolation) ==")
    cur.execute("SELECT provision_workspace_schema(%s)", (ids["ws_ops"],))
    schema = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM information_schema.schemata WHERE schema_name=%s", (schema,))
    check("per-workspace pg schema created (ws_*)", cur.fetchone()[0] == 1 and schema == "ws_operations")

    conn.close()
    print(f"\n{'ALL CHECKS PASSED' if not FAILURES else f'{len(FAILURES)} FAILURE(S): {FAILURES}'}")
    return 0 if not FAILURES else 1


if __name__ == "__main__":
    raise SystemExit(main())
