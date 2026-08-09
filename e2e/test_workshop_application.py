"""Workshop opens as its own application (parity stage 1a).

Foundry's rule is that "each resource type opens in a different platform
application" (`docs/pal/foundry_getting-started.pdf` p.37). The builder was the
one place we had not applied it: it rendered inside `ProjectLayout`, so a
module with three panels of its own competed with the project sidebar for the
same screen.

Two things are asserted here, and both are meant to be breakable:

  1. **The project sidebar is absent.** Put the builder back under
     `(platform)` and this goes red - which is the point, because "it looks
     full-screen" is not something a reader of the diff can check.
  2. **The old URL still works.** It is in `STATUS.md`, in bookmarks, and was
     in this suite until this commit. A redirect that quietly stopped
     redirecting would be invisible until somebody followed an old link.
"""
from __future__ import annotations

import pytest

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, FIRST_RENDER_MS, no_console_errors, open_builder, settled

ROWS = [
    {"id": "a-1", "region": "north", "name": "North site"},
    {"id": "a-2", "region": "south", "name": "South site"},
]


@pytest.fixture(scope="module")
def module(api):
    built = Module(api, "WorkshopApp")
    type_id = built.object_type(columns=["id", "region", "name"], rows=ROWS, key="id", title="name")
    built.define(
        {
            "format": 2,
            "layout": layout(
                {
                    "tbl": {
                        "resolvedName": "CanvasObjectTable",
                        "props": {"title": "Rows", "objectSetVariable": "v_all"},
                    }
                }
            ),
            "variables": {
                "v_all": {
                    "id": "v_all", "kind": "object_set", "label": "All rows",
                    "object_set": object_set(type_id),
                },
            },
            "events": {},
        }
    )
    return built


def test_module_opens_without_the_project_sidebar(page, module):
    """The assertion this whole item exists for.

    In two halves, because `to_have_count(0)` is the easiest assertion in the
    world to pass for the wrong reason: a selector that matches nothing
    anywhere satisfies it on every page in the product. So the sidebar is
    found first, on the project page it belongs to, and only then looked for
    where it should not be.
    """
    # Half one: the selector is real, and this is what it matches.
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}")
    expect(page.locator("aside.side")).to_have_count(1, timeout=FIRST_RENDER_MS)
    expect(page.locator("nav[aria-label='Project sections']")).to_have_count(1)

    # Half two: the same selector finds nothing once the module is open.
    open_builder(page, module)
    expect(page.locator("header.app-bar")).to_be_visible(timeout=FIRST_RENDER_MS)
    expect(page.locator("aside.side")).to_have_count(0)
    expect(page.locator("nav[aria-label='Project sections']")).to_have_count(0)
    assert not no_console_errors(page)


def test_the_builder_still_builds(page, module):
    """A full-screen builder that cannot build is not an improvement.

    The move touched how ids reach the editor - they come from the resolved
    resource now rather than from slug lookups - so this checks the panels
    that depend on them actually mounted.
    """
    open_builder(page, module)
    settled(page)

    expect(page.locator(".canvas-toolbox")).to_be_visible(timeout=FIRST_RENDER_MS)
    expect(page.locator(".canvas-settings")).to_be_visible()
    # The three right-hand tabs, which is where the variable and event panels
    # live. Named rather than counted: a count passes if a tab is renamed to
    # something meaningless.
    for name in ("Widget", "Variables", "Events"):
        expect(page.get_by_role("button", name=name, exact=False).first).to_be_visible()
    assert not no_console_errors(page)


def test_the_old_url_forwards(page, module):
    """The slug path is a forwarding address, not a 404."""
    old = f"/{module.workspace_slug}/{module.project_slug}/canvas/{module.app_id}"
    page.goto(f"{WEB_BASE}{old}")

    # Lands on the application, by resource id, with the sidebar gone.
    page.wait_for_url(f"**/r/{module.resource_id}", timeout=FIRST_RENDER_MS)
    expect(page.locator("header.app-bar")).to_be_visible(timeout=FIRST_RENDER_MS)
    expect(page.locator("aside.side")).to_have_count(0)
