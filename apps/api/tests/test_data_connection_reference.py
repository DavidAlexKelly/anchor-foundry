"""`docs/data-connection-reference.md`'s route table, held to the API (§645).

The reference is the platform's answer to Foundry's *Permissions reference*
(`data-connection` TOC §9): what each Data Connection route requires. A table
somebody keeps by hand drifts the day a route is added, so this reads the
roles the running app actually declares - each route's `require_*_role`
dependency - and compares them with the page, both ways: a route the page
does not list fails, and so does a row with no route behind it.
"""
from __future__ import annotations

import os
import re
import sys

from fastapi.routing import APIRoute

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import create_app  # noqa: E402

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs",
                   "data-connection-reference.md")
WORKSPACE = "/api/workspaces/{workspace_id}"
#: The routes the reference covers: Foundry's sources, syncs, exports,
#: webhooks and listeners, and the listener endpoint itself.
COVERED = ("/connections", "/exports", "/webhooks", "/listeners", "/api/listen/")


def declared_role(dependant) -> str | None:
    """The role a route's `require_project_role` / `require_workspace_role`
    dependency was built with, read from the factory's closure."""
    for dep in dependant.dependencies:
        name = getattr(dep.call, "__qualname__", "")
        for factory, scope in (("require_project_role", "project"),
                               ("require_workspace_role", "workspace")):
            if name.startswith(factory) and dep.call.__closure__:
                minimum = next(c.cell_contents for c in dep.call.__closure__
                               if isinstance(c.cell_contents, str))
                return f"{scope} {minimum}"
        found = declared_role(dep)
        if found:
            return found
    return None


def actual() -> dict[str, str]:
    routes: dict[str, str] = {}
    for route in create_app().routes:
        if not isinstance(route, APIRoute) or not any(k in route.path for k in COVERED):
            continue
        path = route.path.removeprefix(WORKSPACE)
        for method in route.methods:
            routes[f"{method} {path}"] = declared_role(route.dependant) or "none"
    return routes


def documented() -> dict[str, str]:
    text = open(DOC, encoding="utf-8").read()
    table = text.split("<!-- routes:start -->")[1].split("<!-- routes:end -->")[0]
    rows: dict[str, str] = {}
    for route, role in re.findall(r"^\| `([A-Z]+ [^`]+)` \| ([^|]+?) \|$", table, re.M):
        assert route not in rows, f"{route} is listed twice"
        # "none: the listener's own verification" - the words after the colon
        # are for the reader; the role is before it.
        rows[route] = role.split(":")[0].strip()
    return rows


def test_every_data_connection_route_is_in_the_reference() -> None:
    missing = sorted(set(actual()) - set(documented()))
    assert missing == [], f"routes the reference does not list: {missing}"


def test_every_row_in_the_reference_is_a_route() -> None:
    stale = sorted(set(documented()) - set(actual()))
    assert stale == [], f"rows with no route behind them: {stale}"


def test_the_reference_states_each_route_s_role() -> None:
    have, said = actual(), documented()
    wrong = {r: (said[r], have[r]) for r in said.keys() & have.keys() if said[r] != have[r]}
    assert wrong == {}, f"(documented, declared): {wrong}"


def test_the_table_is_what_is_read() -> None:
    """A table the parser silently read nothing from would pass the three
    tests above only if the app had no such routes either."""
    assert len(documented()) >= 40
    assert documented()["POST /api/listen/{token}"] == "none"
    assert documented()["GET /webhooks"] == "workspace viewer"
