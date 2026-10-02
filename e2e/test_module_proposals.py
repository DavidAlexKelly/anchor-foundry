"""Protected modules and branch proposals in the builder (§700; Foundry
`workshop` p.617-618).

> "When on the main branch, protected Workshop modules show a Save to new
> branch option instead of Save and publish" (p.617)
> "Within the Changelog tab, reviewers can see the changes made to the module.
> Reviewers can then approve or reject the change" (p.618)

The rules - no direct save, an approval from somebody else, an approval that
lapses on a later save - are `apps/api/tests/test_module_proposals.py`. What
needs a browser is what each person is offered: the author is not shown
buttons that would refuse them, the reviewer sees the changes they are
approving, and Merge says why it is waiting.

Two people, so two callers: the page is the dev owner, who reviews; the
author is the dev editor, through the API.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Api, Module, layout
from conftest import API_BASE, TOKENS_FILE, eventually, no_console_errors, open_builder


@pytest.fixture(scope="session")
def author() -> Api:
    with open(TOKENS_FILE) as handle:
        return Api(API_BASE, json.load(handle)["editor@acme.dev.local"])


def text_doc(text: str) -> dict:
    return {
        "format": 2,
        "layout": layout({
            "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": text}},
        }),
        "variables": {},
        "events": {},
    }


def shown(page, text: str):
    return page.locator("p").get_by_text(text, exact=True)


def protected_module(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define(text_doc("ON MAIN"))
    api.call("PUT", f"{mod.base}/canvas-apps/{mod.app_id}/protection", {"protected": True})
    return mod


def authored_proposal(mod: Module, author: Api) -> None:
    """The editor branches, changes the text, and proposes."""
    path = f"{mod.base}/canvas-apps/{mod.app_id}/branches"
    author.call("POST", path, {"name": "proposal", "definition": text_doc("PROPOSED")})
    author.call("POST", f"{path}/proposal/propose")


def test_a_protected_main_offers_only_a_branch(page, api) -> None:
    """p.617: Save to new branch "instead of" Save."""
    mod = protected_module(api, "Protected main")
    open_builder(page, mod)
    expect(page.get_by_role("button", name="Save to new branch")).to_be_visible()
    expect(page.get_by_role("button", name="Save", exact=True)).to_have_count(0)
    expect(page.get_by_test_id("protected-status")).to_be_visible()
    assert not no_console_errors(page)


def test_a_reviewer_sees_the_changes_and_approves_them(page, api, author) -> None:
    mod = protected_module(api, "Protected review")
    authored_proposal(mod, author)
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("proposal")

    panel = page.get_by_test_id("review-panel")
    expect(panel).to_be_visible()
    expect(panel.get_by_test_id("review-change")).to_contain_text(["Text"])
    expect(page.get_by_test_id("proposal-status")).to_contain_text("proposal open")
    expect(page.get_by_test_id("merge-branch")).to_be_disabled()

    panel.get_by_test_id("approve-branch").click()
    expect(page.get_by_test_id("proposal-status")).to_contain_text("proposal approved by")
    expect(page.get_by_test_id("review-panel")).to_have_count(0)
    expect(page.get_by_test_id("merge-branch")).to_be_enabled()
    # Approved, so there is nothing to propose.
    expect(page.get_by_test_id("propose-branch")).to_have_count(0)
    page.get_by_test_id("merge-branch").click()
    expect(shown(page, "PROPOSED")).to_be_visible()
    eventually(lambda: api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}")["current_version"],
               lambda v: v == 2, what="the approved merge on main")


def test_a_rejection_is_said_and_merge_stays_shut(page, api, author) -> None:
    mod = protected_module(api, "Protected reject")
    authored_proposal(mod, author)
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("proposal")
    page.get_by_test_id("reject-branch").click()
    expect(page.get_by_test_id("proposal-status")).to_contain_text("proposal rejected by")
    expect(page.get_by_test_id("merge-branch")).to_be_disabled()
    # A rejected change can be proposed again once it has been reworked.
    expect(page.get_by_test_id("propose-branch")).to_be_visible()


def test_the_author_is_not_offered_a_review_of_their_own_change(page, api) -> None:
    """The page's user proposes, so they are the author here."""
    mod = protected_module(api, "Protected own")
    api.call("POST", f"{mod.base}/canvas-apps/{mod.app_id}/branches",
             {"name": "mine", "definition": text_doc("MINE")})
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("mine")
    page.get_by_test_id("propose-branch").click()
    expect(page.get_by_test_id("proposal-status")).to_contain_text("proposal open")
    expect(page.get_by_test_id("review-panel")).to_have_count(0)
    expect(page.get_by_test_id("propose-branch")).to_have_count(0)


def test_an_admin_protects_from_the_versions_dialog(page, api) -> None:
    mod = Module(api, "Protect toggle")
    mod.define(text_doc("ON MAIN"))
    open_builder(page, mod)
    page.get_by_role("button", name="Versions", exact=True).click()
    # Controlled by the saved module, so it flips when the save comes back.
    page.get_by_test_id("protect-module").click()
    expect(page.get_by_test_id("protect-module")).to_be_checked()
    eventually(lambda: api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}")["protected"],
               lambda on: on is True, what="the module protected")
