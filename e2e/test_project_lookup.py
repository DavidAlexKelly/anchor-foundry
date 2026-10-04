"""A project's pages ask for their project, not the workspace's every one (§822).

`useProjectBySlug` fetched the whole project list to find one row by slug -
2.7 MB on the development workspace's 10,000 projects, on every page inside a
project. Watched from the browser: the page asks for its project by slug and
never for the list, and still knows the project it is in.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

WHOLE_LIST = re.compile(r"/api/workspaces/[0-9a-f-]+/projects$")


@pytest.fixture(scope="module")
def mod(api):
    return Module(api, "Lookup")


def test_a_project_page_fetches_its_project_and_not_the_list(page, mod) -> None:
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/api/" in r.url else None)
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    expect(page.get_by_text(f"Lookup {mod.tag}").first).to_be_visible(timeout=30000)
    assert any(f"/projects?slug={mod.project_slug}" in url for url in asked), asked
    assert not [url for url in asked if WHOLE_LIST.search(url.split("?")[0]) and "?" not in url], asked
