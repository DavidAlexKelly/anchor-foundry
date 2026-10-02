"""Rebasing a module branch onto main (§699; Foundry `workshop` p.193, p.619-621).

> "Rebasing applies the changes made on the branch to the latest main version
> of the module. Resolve any merge conflicts manually to proceed." (p.619)
> "When you are satisfied with how your module looks and have resolved any
> merge conflicts, save the module to finish rebasing." (p.621)

The merge itself - what auto-merges, what is a conflict, how a choice
rebuilds the document - is `module-merge.test.ts`. What needs a browser is the
flow around it: the canvas shows the merged module, choosing a side changes
it there and then, and saving moves the branch onto main so it can merge.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, no_console_errors, open_builder, stays


def two_texts(a: str, b: str) -> dict:
    return {
        "format": 2,
        "layout": layout({
            "a": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": a}},
            "b": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": b}},
        }),
        "variables": {},
        "events": {},
    }


def shown(page, text: str):
    return page.locator("p").get_by_text(text, exact=True)


def behind(api, name: str, *, main: tuple[str, str], branch: tuple[str, str]) -> Module:
    """A module whose branch was taken at v1 and whose main has since moved."""
    mod = Module(api, name)
    mod.define(two_texts("A BASE", "B BASE"))
    mod.api.call("POST", f"{mod.base}/canvas-apps/{mod.app_id}/branches",
                 {"name": "work", "definition": two_texts(*branch)})
    mod.define(two_texts(*main))
    return mod


def branch_of(mod: Module) -> dict:
    return mod.api.call("GET", f"{mod.base}/canvas-apps/{mod.app_id}/branches/work")


def start_rebase(page, mod: Module) -> None:
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("work")
    expect(page.get_by_test_id("branch-status")).to_contain_text("rebase required")
    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("begin-rebase").click()
    expect(page.get_by_test_id("rebase-panel")).to_be_visible()


def test_changes_that_do_not_overlap_merge_and_save_finishes_it(page, api) -> None:
    mod = behind(api, "Rebase clean", main=("A MAIN", "B BASE"), branch=("A BASE", "B BRANCH"))
    start_rebase(page, mod)
    expect(page.get_by_test_id("rebase-panel")).to_contain_text("No conflicts")
    expect(shown(page, "A MAIN")).to_be_visible()
    expect(shown(page, "B BRANCH")).to_be_visible()

    page.get_by_role("button", name="Save to branch").click()
    eventually(lambda: branch_of(mod)["base_version"], lambda v: v == 2,
               what="the branch based on main's v2")
    expect(page.get_by_test_id("rebase-panel")).to_have_count(0)
    expect(page.get_by_test_id("merge-branch")).to_be_enabled()
    # Up to date now, so there is nothing to rebase.
    expect(page.get_by_test_id("begin-rebase")).to_have_count(0)
    saved = branch_of(mod)["definition"]["layout"]
    assert (saved["a"]["props"]["text"], saved["b"]["props"]["text"]) == ("A MAIN", "B BRANCH")
    assert not no_console_errors(page)


def test_a_conflict_starts_on_main_and_can_be_switched_to_the_branch(page, api) -> None:
    """p.620: "A widget or variable was modified on both main and your branch."
    p.621: switch "between three states to test how each option affects the
    module in real time"."""
    mod = behind(api, "Rebase conflict", main=("A MAIN", "B BASE"), branch=("A BRANCH", "B BASE"))
    start_rebase(page, mod)
    conflict = page.get_by_test_id("rebase-conflict")
    expect(conflict).to_have_count(1)
    expect(conflict).to_contain_text("edited on main and on this branch")
    expect(shown(page, "A MAIN")).to_be_visible()

    conflict.get_by_label("Branch").check()
    expect(shown(page, "A BRANCH")).to_be_visible()
    expect(shown(page, "A MAIN")).to_have_count(0)
    conflict.get_by_label("Main").check()
    expect(shown(page, "A MAIN")).to_be_visible()
    conflict.get_by_label("Branch").check()

    page.get_by_role("button", name="Save to branch").click()
    eventually(lambda: branch_of(mod)["base_version"], lambda v: v == 2,
               what="the rebase saved")
    assert branch_of(mod)["definition"]["layout"]["a"]["props"]["text"] == "A BRANCH"


def test_cancelling_a_rebase_leaves_the_branch_as_it_was(page, api) -> None:
    mod = behind(api, "Rebase cancel", main=("A MAIN", "B BASE"), branch=("A BASE", "B BRANCH"))
    start_rebase(page, mod)
    expect(shown(page, "A MAIN")).to_be_visible()
    page.get_by_role("button", name="Cancel rebase").click()
    expect(page.get_by_test_id("rebase-panel")).to_have_count(0)
    expect(shown(page, "A BASE")).to_be_visible()
    assert branch_of(mod)["base_version"] == 1


def test_main_moving_during_the_rebase_refuses_the_save(page, api) -> None:
    """A rebase merged against main's v2. Saved after main reached v3, it would
    claim to be based on a main it never saw - so the server refuses and says
    to rebase again."""
    mod = behind(api, "Rebase raced", main=("A MAIN", "B BASE"), branch=("A BASE", "B BRANCH"))
    start_rebase(page, mod)
    mod.define(two_texts("A MAIN AGAIN", "B BASE"))
    page.get_by_role("button", name="Save to branch").click()
    expect(page.locator(".ws-actions .state.error")).to_contain_text("rebase again")
    assert branch_of(mod)["base_version"] == 1


def test_the_rebase_reads_main_as_it_is_when_it_starts(page, api) -> None:
    """Main moving after the page opened is the case a cached copy gets wrong:
    the rebase would merge against a main that is already gone, and the save
    finishing it would be refused."""
    mod = behind(api, "Rebase fresh", main=("A MAIN", "B BASE"), branch=("A BASE", "B BRANCH"))
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("work")
    expect(page.get_by_test_id("branch-status")).to_contain_text("rebase required")
    mod.define(two_texts("A NEWER", "B BASE"))

    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("begin-rebase").click()
    expect(page.get_by_test_id("rebase-panel")).to_contain_text("onto main v3")
    expect(shown(page, "A NEWER")).to_be_visible()
    page.get_by_role("button", name="Save to branch").click()
    eventually(lambda: branch_of(mod)["base_version"], lambda v: v == 3,
               what="the branch based on main's v3")


def test_declining_the_warning_does_not_start_a_rebase(page, api) -> None:
    """p.619's "Save before rebasing": unsaved edits are lost, so the rebase
    asks first - and a no keeps the editor as it was."""
    mod = behind(api, "Rebase declined", main=("A MAIN", "B BASE"), branch=("A BASE", "B BRANCH"))
    open_builder(page, mod)
    page.get_by_test_id("branch-select").select_option("work")
    expect(page.get_by_test_id("begin-rebase")).to_be_visible()
    page.once("dialog", lambda d: d.dismiss())
    page.get_by_test_id("begin-rebase").click()
    # Held for a while rather than checked once: a rebase that started anyway
    # appears after two reads, so an absence checked at once proves nothing.
    stays(lambda: page.get_by_test_id("rebase-panel").count(), lambda n: n == 0,
          what="no rebase", for_ms=3000)
    expect(shown(page, "A BASE")).to_be_visible()


def test_the_saved_rebase_keeps_mains_new_variables(page, api) -> None:
    """The variables are merged as the layout is. A rebase that kept the
    branch's variables would save main's new text reading a variable that is
    no longer declared."""
    mod = Module(api, "Rebase variables")
    mod.define(two_texts("A BASE", "B BASE"))
    mod.api.call("POST", f"{mod.base}/canvas-apps/{mod.app_id}/branches",
                 {"name": "work", "definition": two_texts("A BASE", "B BRANCH")})
    with_variable = two_texts("M={{v_main}}", "B BASE")
    with_variable["variables"] = {"v_main": {"id": "v_main", "kind": "string",
                                             "label": "Main's", "default": "x"}}
    mod.define(with_variable)

    start_rebase(page, mod)
    expect(page.get_by_test_id("rebase-panel")).to_contain_text("No conflicts")
    page.get_by_role("button", name="Save to branch").click()
    eventually(lambda: branch_of(mod)["base_version"], lambda v: v == 2,
               what="the rebase saved")
    assert "v_main" in branch_of(mod)["definition"]["variables"]
