"""The search at the top of a workspace's pages (§990).

What it matches and in what order is the API's tests' (`apps/api/tests/
test_workspace_search.py`) and the wording and keys `apps/web/src/lib/
workspace-search.test.ts`'. What needs a browser is that `/` reaches it from
anywhere in a workspace, that what is typed finds a resource in a project the
page is not in, and that choosing one opens it.
"""
from __future__ import annotations

import re
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def test_a_resource_in_another_project_is_found_and_opened(page, api) -> None:
    here = Module(api, "Searching from")
    there = Module(api, "Searched in")
    name = f"findable_{uuid.uuid4().hex[:6]}"
    api.upload_csv(f"{there.base}/datasets/upload", name=name, csv=b"id\n1\n")

    page.goto(f"{WEB_BASE}/{here.workspace_slug}/{here.project_slug}")
    box = page.get_by_test_id("workspace-search-input")
    expect(box).to_be_visible(timeout=30000)
    page.locator("body").click()

    def pressed() -> bool:
        # The box is drawn before the page hydrates, and `/` is heard only
        # after: a press in between lands on the page and does nothing.
        page.keyboard.press("/")
        return box.evaluate("el => el === document.activeElement")

    eventually(pressed, bool, what="the search box, focused by /")
    expect(box).to_have_value("")
    box.fill(name[:12])
    hit = page.get_by_test_id("workspace-search-hit").filter(has_text=name)
    expect(hit).to_contain_text(f"Dataset · Searched in {there.tag}", timeout=15000)

    box.press("ArrowDown")
    expect(hit).to_have_attribute("aria-selected", "true")
    box.press("Enter")
    # A client-side navigation: the URL changes, no `load` follows.
    expect(page).to_have_url(re.compile(r"/r/[0-9a-f-]{36}"), timeout=30000)
    expect(page.get_by_text(name).first).to_be_visible(timeout=30000)


def test_a_name_nothing_has_says_so(page, api) -> None:
    here = Module(api, "Searching nothing")
    page.goto(f"{WEB_BASE}/{here.workspace_slug}/{here.project_slug}")
    box = page.get_by_test_id("workspace-search-input")
    expect(box).to_be_visible(timeout=30000)
    box.fill(f"nothing_called_{uuid.uuid4().hex}")
    expect(page.get_by_test_id("workspace-search-none")).to_have_text(
        "Nothing in this workspace is called that.", timeout=15000)


def test_it_is_not_offered_outside_a_workspace(page) -> None:
    page.goto(f"{WEB_BASE}/home")
    expect(page.locator("header.topbar")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("workspace-search")).to_have_count(0)


def test_its_words_are_handed_to_the_object_explorer(page, api) -> None:
    """Objects are searched by what they hold, not by name - the last row
    asks the Object Explorer the same words (§991), and asks it again from
    the Explorer itself."""
    here = Module(api, "Handing over")
    page.goto(f"{WEB_BASE}/{here.workspace_slug}/{here.project_slug}")
    box = page.get_by_test_id("workspace-search-input")
    expect(box).to_be_visible(timeout=30000)
    box.fill("heathrow t5")
    objects = page.get_by_test_id("workspace-search-objects")
    expect(objects).to_have_text("Search objects for “heathrow t5”", timeout=15000)
    objects.click()
    expect(page).to_have_url(re.compile(r"/explore\?q=heathrow(%20|\+)t5$"), timeout=30000)
    explorer_box = page.get_by_role("searchbox", name="Search instances")
    expect(explorer_box).to_have_value("heathrow t5", timeout=30000)

    box.fill("gatwick")
    expect(objects).to_have_text("Search objects for “gatwick”", timeout=15000)
    box.press("ArrowUp")
    expect(objects).to_have_attribute("aria-selected", "true")
    box.press("Enter")
    expect(page).to_have_url(re.compile(r"/explore\?q=gatwick$"), timeout=30000)
    expect(explorer_box).to_have_value("gatwick")
