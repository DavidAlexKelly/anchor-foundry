"""Every tab of a repository, by click and by URL (§736; `code-repositories`
p.10).

`code-repositories.md` §10's acceptance test: "**Tabs** — each of the five is
reachable by URL and by click, and a deep link survives a reload." The five
are p.10's - Code, Branches, Pull requests, Checks, Settings - and this
platform's repository has eight, the three more being History, Docs and
Publish. Each tab's own file tests what is on it; this one tests the one thing
none of them does, which is that the address and the tab agree in both
directions for every tab, a typo'd one included.
"""
from __future__ import annotations

import re

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

#: Written out rather than read from `TABS`, so a tab dropped from the
#: product is a failure here rather than a case the test stops checking.
TABS = {
    "files": "Files", "docs": "Docs", "history": "History", "branches": "Branches",
    "pulls": "Pull requests", "checks": "Checks", "publish": "Publish", "settings": "Settings",
}


def repository(api, name: str) -> dict:
    mod = Module(api, name)
    return api.call("POST", f"{mod.base}/repositories", {"name": f"{name} {mod.tag}"})


def tab(page, label: str):
    return page.locator("nav.repo-tabs").get_by_role("button", name=label, exact=True)


def current(page) -> str:
    return page.locator("nav.repo-tabs [aria-current='true']").inner_text()


def test_each_tab_is_reached_by_click_and_named_in_the_address(page, api) -> None:
    repo = repository(api, "Tabs by click")
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}")
    # No tab named is Files, the first of them.
    expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text("Files")
    for key, label in TABS.items():
        tab(page, label).click()
        expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text(label)
        expect(page).to_have_url(re.compile(rf"[?&]tab={key}(&|$)"))


def test_each_tab_is_reached_by_its_address_and_survives_a_reload(page, api) -> None:
    repo = repository(api, "Tabs by address")
    for key, label in TABS.items():
        page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab={key}")
        expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text(label)
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=checks")
    expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text("Checks")
    page.reload()
    expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text("Checks")
    assert current(page) == "Checks"


def test_a_tab_that_does_not_exist_is_files(page, api) -> None:
    repo = repository(api, "Tabs unknown")
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=nonsense")
    expect(page.locator("nav.repo-tabs [aria-current='true']")).to_have_text("Files")
