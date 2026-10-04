"""Row-level policies compute what does not depend on the row once per
statement (§804; roadmap phase 3, E.4).

`rls_workspace_ids()` is SECURITY DEFINER, so the planner cannot inline it;
called bare inside a policy it can run once per row - 20,000 calls to list a
10,000-object type, half a second of a one-second request. Migration 0155
wrapped every call as `(SELECT rls_workspace_ids())`, an InitPlan, and this
keeps a later policy from being written the old way.
"""
from __future__ import annotations

import os
import re

import psycopg

ADMIN_DSN = os.environ["TEST_ADMIN_DSN"]

#: A call not directly inside a `SELECT`, as Postgres deparses a policy.
BARE = re.compile(r"(?<!SELECT )rls_workspace_ids\(\)")


def policies() -> list[tuple[str, str, str]]:
    with psycopg.connect(ADMIN_DSN) as conn:
        return [(t, p, f"{q or ''} {c or ''}") for t, p, q, c in conn.execute(
            "SELECT tablename, policyname, qual, with_check FROM pg_policies").fetchall()]


def test_no_policy_calls_rls_workspace_ids_once_per_row() -> None:
    bare = [(table, name) for table, name, text in policies() if BARE.search(text)]
    assert bare == [], (
        f"{bare} call rls_workspace_ids() per row; write it as "
        "(SELECT rls_workspace_ids())::uuid[] (migration 0155)")


def test_the_workspace_policies_are_still_there() -> None:
    """The rewrite changed when the workspaces are computed, not whether a
    policy asks: the policies it touched still name them."""
    wrapped = [(table, name) for table, name, text in policies()
               if "SELECT rls_workspace_ids()" in text]
    assert ("object_instances", "oi_isolation") in wrapped
    assert ("object_types", "ot_isolation") in wrapped
    assert len(wrapped) >= 25, wrapped


#: A kiosk check not preceded by the once-per-statement "kiosk is off".
KIOSK_BARE = re.compile(r"(?<!''::text\)\) OR )rls_kiosk_allows\(")


def test_no_policy_asks_whether_this_is_a_kiosk_once_per_row() -> None:
    """Migration 0157: `(SELECT ... app.kiosk ...) OR rls_kiosk_allows(...)`,
    so an ordinary request decides it once."""
    bare = [(table, name) for table, name, text in policies() if KIOSK_BARE.search(text)]
    assert bare == [], bare
    kiosk = [(table, name) for table, name, text in policies() if "rls_kiosk_allows(" in text]
    assert ("object_instances", "oi_kiosk") in kiosk and len(kiosk) >= 6, kiosk


def test_no_policy_asks_whether_a_workspace_is_reachable_once_per_row() -> None:
    """Migration 0159: thirteen policies written after 0058 called
    `rls_can_access_workspace(...)` row by row - the ontology cleanup page took
    five seconds summing `object_type_usage` through one of them. The set,
    once per statement, says the same (`test_rls_workspace_ids.py`)."""
    bare = [(table, name) for table, name, text in policies()
            if "rls_can_access_workspace(" in text]
    assert bare == [], (
        f"{bare} check workspace access per row; write it as "
        "x = ANY ((SELECT rls_workspace_ids())::uuid[]) (migration 0159)")
    wrapped = {(table, name) for table, name, text in policies()
               if "SELECT rls_workspace_ids()" in text}
    assert {("object_type_usage", "otu_isolation"), ("canvas_apps", "app_isolation"),
            ("object_edits", "object_edits_write")} <= wrapped


def test_the_pattern_tells_the_two_spellings_apart() -> None:
    assert BARE.search("(workspace_id = ANY (rls_workspace_ids()))")
    assert not BARE.search(
        "(workspace_id = ANY (( SELECT rls_workspace_ids() AS rls_workspace_ids)::uuid[]))")
    assert KIOSK_BARE.search("rls_kiosk_allows('apps'::text, id)")
    assert not KIOSK_BARE.search(
        "(( SELECT (COALESCE(current_setting('app.kiosk'::text, true), ''::text) = ''::text))"
        " OR rls_kiosk_allows('apps'::text, id))")


def test_the_rewrite_finds_a_call_inside_a_call() -> None:
    """0159's argument is found by matching parentheses, since some are calls
    themselves; a rewrite that stopped at the first `)` would leave a policy
    that does not parse, or worse, one that parses and means something else."""
    import importlib.util

    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "packages", "db", "migrations",
        "0159_rls_workspace_access_once.py")
    spec = importlib.util.spec_from_file_location("m0159", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hoisted = "(SELECT rls_workspace_ids())::uuid[]"
    assert module.rewrite(
        "(rls_can_access_project(project_id) OR "
        "rls_can_access_workspace(rls_project_workspace_id(project_id)))"
    ) == (
        "(rls_can_access_project(project_id) OR "
        f"((rls_project_workspace_id(project_id)) = ANY ({hoisted})))"
    )
    assert module.rewrite("a AND rls_can_access_workspace(w) AND rls_can_access_workspace(v)") == (
        f"a AND ((w) = ANY ({hoisted})) AND ((v) = ANY ({hoisted}))")
    assert module.rewrite("no call here") == "no call here"
