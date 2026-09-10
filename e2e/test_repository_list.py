"""The Code pillar, as a list of repositories (§291; B.1).

**The deletion, and the hole it exposed.** `code/page.tsx` opened with "There
is no 'new repository' button, and its absence is the design" — true when
decision 0001 made the pillar a view over `model_versions`, and false since
§94 gave the project real `code_repos`. Grepping for the create call turns up
nothing in `apps/web` at all: a repository could only be made by calling the
API directly, and none could be listed anywhere, so the repository application
was reachable only by a `/r/{id}` link somebody already had.

§275's adopt dialog had already been caught by it — "Create one on the Code
screen, then move this transform into it" named a screen with no such control.
The same shape §290 found in the Pull requests tab: a pointer at a place that
cannot do what it says, which no test notices because every test of it asserts
its wording.

The rules are in `apps/web/src/lib/repository-list.test.ts`. What needs a
browser is that a repository can be made here, that it opens into the
application, and that a viewer is not offered a control the server refuses.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def code_screen(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/code")
    expect(page.get_by_test_id("repository-list")).to_be_visible(timeout=30000)


def test_a_repository_can_be_made_here_and_opens_into_the_application(page, api) -> None:
    """**The capability that existed only in the test suite.**

    Nothing in `apps/web` called `POST /repositories`, so every repository in
    the product had been created by a script. A feature reachable only by API
    is a feature the people it is for do not have.
    """
    mod = Module(api, "Repo list create")
    name = f"Transforms {uuid.uuid4().hex[:6]}"

    code_screen(page, mod)
    page.get_by_test_id("repository-new").click()
    page.get_by_test_id("repository-name").fill(name)
    page.get_by_test_id("repository-create").click()

    # **Straight into it.** A repository with no files is not something to
    # admire in a list; the next thing anybody does is put code in it.
    expect(page.get_by_role("button", name="Pull requests")).to_be_visible(timeout=30000)
    # By resource id, not by slug: a link built from slugs stops working the
    # moment somebody renames the workspace or the project.
    assert "/r/" in page.url, page.url

    # And it is in the list afterwards, reached by clicking rather than by the
    # redirect - which is the half that makes a *list* worth having, and the
    # half a test that only followed the redirect would never see.
    code_screen(page, mod)
    row = page.get_by_test_id("repository-list").get_by_text(name)
    expect(row).to_be_visible()
    row.click()
    expect(page.get_by_role("button", name="Pull requests")).to_be_visible(timeout=30000)
    assert "/r/" in page.url, page.url


def test_an_empty_project_says_what_a_repository_is_for(page, api) -> None:
    """Somebody who has never made one cannot be expected to know why they
    would, and an empty list with a bare button teaches nothing."""
    mod = Module(api, "Repo list empty")

    code_screen(page, mod)
    note = page.get_by_test_id("repository-empty")
    expect(note).to_contain_text("branches, review and history")
    expect(note).to_contain_text("create one")


def test_the_adopt_dialog_points_at_a_screen_that_can_do_it(page, api) -> None:
    """**The sentence that was already false.** §275 told people to create a
    repository on the Code screen while the Code screen had no such control —
    §290's shape, found by reading rather than by a failure."""
    mod = Module(api, "Repo list adopt")
    mod.api.call("POST", f"{mod.base}/models",
                 {"name": f"orphan_{uuid.uuid4().hex[:6]}", "language": "sql",
                  "code": "SELECT 1", "inputs": []})

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/models")
    expect(page.locator(".table tbody tr").first).to_be_visible(timeout=30000)
    page.get_by_test_id("model-adopt").first.click()
    link = page.get_by_test_id("adopt-no-repositories").get_by_role("link")
    expect(link).to_be_visible()
    link.click()
    # And it lands somewhere that can actually do it, rather than on a screen
    # that only mentions repositories.
    expect(page.get_by_test_id("repository-new")).to_be_visible(timeout=30000)
