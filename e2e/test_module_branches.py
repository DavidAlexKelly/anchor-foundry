"""Module branches in the builder (§698; Foundry `workshop` p.193, p.617-621).

> "To add a Workshop module to a branch, use the branch selector to switch to
> that branch, open the module, then save any changes." (p.617)

The API half - saves that leave main alone, the merge, the refusal while main
has moved on - is `apps/api/tests/test_module_branches.py`. What needs a
browser is that the selector really swaps the document under the editor (Craft
reads its document once, at mount), that Save writes to whichever head is
open, and that the merge button says when it cannot be pressed.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_builder


def text_doc(text: str) -> dict:
    return {
        "format": 2,
        "layout": layout({
            "t": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": text}},
        }),
        "variables": {},
        "events": {},
    }


def module_on_main(api, name: str) -> Module:
    mod = Module(api, name)
    mod.define(text_doc("ON MAIN"))
    return mod


def shown(page, text: str):
    """The text widget on the canvas - not the layout tree's row for it, which
    carries the same words."""
    return page.locator("p").get_by_text(text, exact=True)


def branches_of(mod: Module) -> dict[str, dict]:
    rows = mod.api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}/branches")
    return {b["name"]: b for b in rows}


def make_branch(mod: Module, name: str, text: str) -> None:
    mod.api.call("POST", f"{mod.base}/canvas-apps/{mod.app_id}/branches",
                 {"name": name, "definition": text_doc(text)})


def main_of(mod: Module) -> dict:
    return mod.api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}")


def test_the_selector_swaps_the_document_under_the_editor(page, api) -> None:
    mod = module_on_main(api, "Branch switch")
    make_branch(mod, "feature", "ON THE BRANCH")
    open_builder(page, mod)
    expect(shown(page, "ON MAIN")).to_be_visible()

    page.get_by_test_id("branch-select").select_option("feature")
    expect(shown(page, "ON THE BRANCH")).to_be_visible()
    expect(shown(page, "ON MAIN")).to_have_count(0)
    expect(page.get_by_test_id("branch-status")).to_contain_text("branch feature · from v1")

    page.get_by_test_id("branch-select").select_option("")
    expect(shown(page, "ON MAIN")).to_be_visible()
    assert not no_console_errors(page)


def test_save_to_new_branch_names_it_and_leaves_main(page, api) -> None:
    """p.617-618: Save to new branch opens a dialog to "Name the branch"."""
    mod = module_on_main(api, "Branch create")
    open_builder(page, mod)
    page.once("dialog", lambda d: d.accept("drafts"))
    page.get_by_role("button", name="Save to new branch").click()

    expect(page.get_by_test_id("branch-select")).to_have_value("drafts")
    expect(page.get_by_test_id("branch-status")).to_contain_text("branch drafts")
    assert "drafts" in branches_of(mod)
    assert main_of(mod)["current_version"] == 1


def test_save_on_a_branch_writes_the_branch(page, api) -> None:
    mod = module_on_main(api, "Branch save")
    make_branch(mod, "work", "ON THE BRANCH")
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("work")
    expect(shown(page, "ON THE BRANCH")).to_be_visible()
    page.get_by_role("button", name="Save to branch").click()

    eventually(lambda: branches_of(mod)["work"]["save_count"], lambda n: n == 2,
               what="the branch's second save")
    assert main_of(mod)["current_version"] == 1


def test_merging_puts_the_branch_on_main(page, api) -> None:
    mod = module_on_main(api, "Branch merge")
    make_branch(mod, "ready", "ON THE BRANCH")
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("ready")
    expect(page.get_by_test_id("merge-branch")).to_be_enabled()
    page.get_by_test_id("merge-branch").click()

    expect(page.get_by_test_id("branch-select")).to_have_value("")
    # Back on main, not on a branch that no longer exists - the select alone
    # cannot say which, since a value with no option shows the first one.
    expect(page.get_by_test_id("branch-status")).to_have_count(0)
    expect(page.get_by_test_id("merge-branch")).to_have_count(0)
    expect(shown(page, "ON THE BRANCH")).to_be_visible()
    main = main_of(mod)
    assert main["current_version"] == 2
    assert "ready" not in branches_of(mod)


def test_a_branch_behind_main_says_so_and_cannot_merge(page, api) -> None:
    """p.193: "you may need to rebase before merging … if main has changed
    since your last save"."""
    mod = module_on_main(api, "Branch behind")
    make_branch(mod, "stale", "ON THE BRANCH")
    mod.define(text_doc("MAIN MOVED"))
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("stale")

    expect(page.get_by_test_id("branch-status")).to_contain_text(
        "main is at v2, rebase required")
    expect(page.get_by_test_id("merge-branch")).to_be_disabled()


def test_a_branch_brings_its_own_variables(page, api) -> None:
    """The variables, events and settings are the branch's as much as its
    layout is. A branch whose text reads a variable only it declares would
    otherwise draw against main's variables - and its next save would write
    main's variables onto the branch."""
    mod = module_on_main(api, "Branch variables")
    document = text_doc("NOTE={{v_note}}")
    document["variables"] = {"v_note": {"id": "v_note", "kind": "string", "label": "Note",
                                        "default": "from the branch"}}
    mod.api.call("POST", f"{mod.base}/canvas-apps/{mod.app_id}/branches",
                 {"name": "noted", "definition": document})
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("noted")
    expect(shown(page, "NOTE=from the branch")).to_be_visible()

    page.get_by_role("button", name="Save to branch").click()
    eventually(lambda: branches_of(mod)["noted"]["save_count"], lambda n: n == 2,
               what="the branch's second save")
    saved = mod.api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}/branches/noted")
    assert "v_note" in saved["definition"]["variables"]
