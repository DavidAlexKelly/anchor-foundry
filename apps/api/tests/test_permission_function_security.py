"""Every permission helper resolves as the owner (migration 0062).

**A property, not a behaviour**, and that is why it needs a test of its own:
`SECURITY INVOKER` on a permission function is invisible. Nothing errors, no
answer changes on this data, and the only symptom is that resolving one role
runs the whole isolation layer several times over — 1319ms instead of 23ms on
a 178-project workspace.

The failure mode it guards against is the one it was found in: a function that
reads `workspace_members` to decide whether you have a role, while a policy on
`workspace_members` decides what you can read using that role. Today the two
agree and the answer comes out right. A future policy that hides a membership
row would make the resolver under-report, and the app would quietly show
somebody less than they have.

`search_path` is checked with it, because a definer function without one is a
worse problem than the one this fixes: the owner's search path becomes the
caller's to choose.
"""
from __future__ import annotations

import os
import sys

import psycopg
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN  # noqa: E402

#: Reads tables that carry policies, so it must resolve as the owner.
RESOLVERS = (
    "effective_workspace_role",
    "effective_project_role",
    "rls_can_access_workspace",
    "rls_can_access_project",
    "rls_is_org_admin",
    "rls_app_shared_with_user",
    "rls_app_project_id",
    "rls_project_workspace_id",
    "rls_user_org_id",
    "rls_workspace_ids",
    "rls_project_ids",
)

#: Reads settings and no tables, so there is nothing for a policy to filter -
#: named rather than merely absent, so "is this list complete" has an answer.
SETTING_ONLY = ("rls_current_user_id", "rls_worker_for_workspace")


@pytest.fixture(scope="module")
def functions():
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT proname, prosecdef, coalesce(proconfig, '{}') FROM pg_proc"
            " WHERE proname LIKE 'rls\\_%' OR proname LIKE 'effective\\_%'"
        )
        return {name: (secdef, config) for name, secdef, config in cur.fetchall()}


@pytest.mark.parametrize("name", RESOLVERS)
def test_a_resolver_runs_as_the_owner(functions, name: str) -> None:
    assert name in functions, f"{name} is missing - was it renamed?"
    secdef, _ = functions[name]
    assert secdef is True, (
        f"{name} is SECURITY INVOKER, so the policies it reads are applied to the "
        "function that decides those policies"
    )


@pytest.mark.parametrize("name", RESOLVERS)
def test_a_definer_function_pins_its_search_path(functions, name: str) -> None:
    _, config = functions[name]
    assert any(c.startswith("search_path=") for c in config), (
        f"{name} is SECURITY DEFINER with no search_path - the owner's is the "
        "caller's to choose"
    )


def test_the_two_setting_only_helpers_are_still_setting_only(functions) -> None:
    """They are exempt because they touch no table. If one grows a query, this
    list is where the exemption stops being true — and the assertion below is
    what makes somebody look."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn, conn.cursor() as cur:
        for name in SETTING_ONLY:
            cur.execute("SELECT prosrc FROM pg_proc WHERE proname = %s", (name,))
            body = cur.fetchone()[0].lower()
            assert "from " not in body, (
                f"{name} now reads a table, so it needs SECURITY DEFINER like the rest"
            )


def test_the_list_covers_every_permission_helper(functions) -> None:
    """A helper added later and left as invoker would simply not be checked."""
    assert set(functions) == set(RESOLVERS) | set(SETTING_ONLY), (
        "a permission helper was added or removed - decide which list it belongs in"
    )
