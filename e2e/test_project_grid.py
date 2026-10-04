"""The workspace grid is searched and paged (§823).

It drew every project the workspace holds - on the development workspace,
9,974 cards from a 2.7 MB response. Now a page at a time, searched by name
or slug, saying how many there are and offering the rest.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def mod(api):
    return Module(api, "Gridded")


def test_a_project_is_found_by_searching_the_grid(page, mod) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}")
    grid = page.get_by_test_id("project-grid")
    expect(grid).to_be_visible(timeout=30000)
    page.get_by_test_id("project-search").fill(f"Gridded {mod.tag}")
    expect(grid.locator(".card")).to_have_count(1)
    expect(grid).to_contain_text(f"Gridded {mod.tag}")
    expect(page.get_by_test_id("project-count")).to_have_text("1 project")
    grid.get_by_role("link", name=f"Gridded {mod.tag}").click()
    expect(page).to_have_url(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}")


def test_the_grid_offers_the_rest_exactly_when_there_is_more(page, mod) -> None:
    """Asserted both ways, so it holds on a fresh database with a handful of
    projects and on one with thousands."""
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}")
    grid = page.get_by_test_id("project-grid")
    expect(grid).to_be_visible(timeout=30000)
    count = page.get_by_test_id("project-count").inner_text()
    cards = grid.locator(".card").count()
    more = page.get_by_test_id("project-more")
    if " of " in count:
        shown, total = (int(n) for n in count.replace(" projects", "").split(" of "))
        assert shown == cards and shown < total
        expect(more).to_be_visible()
        more.click()
        expect(grid.locator(".card")).to_have_count(min(total, shown * 2))
    else:
        assert int(count.split()[0]) == cards
        expect(more).to_have_count(0)
