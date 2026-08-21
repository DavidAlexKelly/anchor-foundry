"""The Changelog panel (parity `workshop.md` §6; Foundry p.193).

> "Use the Changelog panel to visualize differences between module versions…
> The Changelog panel highlights additions, deletions, changes, moves, and
> newly unused elements."

The diff itself is arithmetic and is checked directly in
`apps/web/src/components/canvas/changelog.test.ts`. What is here is the part
that needed a browser: that the panel asks for the **right two versions** and
draws what came back. A diff function that is perfect and wired to the wrong
version numbers produces a confident, wrong answer, and only the round trip
through two real saves can catch it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder


def two_saves(api, name: str) -> Module:
    """A module saved twice: v1 has a text widget, v2 adds a button."""
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FIRST"}},
        }),
        "variables": {},
        "events": {},
    }, description="first")
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FIRST"}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
        }),
        "variables": {},
        "events": {},
    }, description="added a button")
    return mod


def open_changes(page, mod: Module, version: int) -> None:
    open_builder(page, mod)
    page.get_by_role("button", name="Versions").click()
    page.get_by_test_id(f"changes-v{version}").click()


def test_the_panel_names_the_two_versions_and_the_added_widget(page, api):
    """p.193's single selection: "select a single version to compare it to the
    previous version"."""
    mod = two_saves(api, "Changelog")
    open_changes(page, mod, 2)

    changelog = page.get_by_test_id("changelog")
    expect(changelog).to_contain_text("v1 → v2")
    added = changelog.locator("li[data-change='added']")
    expect(added).to_have_count(1)
    expect(added).to_contain_text("CanvasButton")


def test_the_first_version_says_there_is_nothing_before_it(page, api):
    """v1 has no predecessor. Diffing it against an empty document would report
    the whole module as additions - true of nothing anybody did, and the kind of
    confident wrong answer a panel should refuse to give."""
    mod = two_saves(api, "Changelog first")
    open_changes(page, mod, 1)

    expect(page.get_by_test_id("changelog-empty")).to_contain_text("first version")


def test_a_save_that_changed_nothing_says_so(page, api):
    """Saving an unchanged module is allowed, so this state is reachable - and
    three empty lists would read as a panel that failed to load."""
    mod = two_saves(api, "Changelog empty")
    # A third save, byte-identical to the second.
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FIRST"}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
        }),
        "variables": {},
        "events": {},
    }, description="no change")

    open_changes(page, mod, 3)
    expect(page.get_by_test_id("changelog-empty")).to_contain_text("Nothing changed")


# ---- p.193's other two halves (§183) ----------------------------------------
def nested_saves(api, name: str) -> Module:
    """A section holding two widgets, saved three times.

    v1 → v2 changes the text inside the section, which is the case the visual
    hierarchy exists for: a flat list says "CanvasText changed" and loses the
    section it is in. v3 deletes the button, so a deletion has somewhere to be
    drawn even though it is gone from the newest document.
    """
    def document(text: str, with_button: bool = True) -> dict:
        nodes = {
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True, "props": {},
                    "nodes": ["txt"] + (["btn"] if with_button else [])},
            "txt": {"resolvedName": "CanvasText", "parent": "sec",
                    "props": {"tag": "p", "text": text}},
        }
        if with_button:
            nodes["btn"] = {"resolvedName": "CanvasButton", "parent": "sec",
                            "props": {"label": "Go"}}
        return {"format": 2, "layout": layout(nodes), "variables": {}, "events": {}}

    mod = Module(api, name)
    mod.define(document("FIRST"), description="first")
    mod.define(document("SECOND"), description="changed the text")
    mod.define(document("SECOND", with_button=False), description="dropped the button")
    return mod


def test_a_change_is_drawn_inside_the_section_that_holds_it(page, api):
    """**p.193's visual hierarchy**: "review a visual hierarchy to understand
    how changes relate to nested components".

    The section did not change and carries no chip — it is context, not news —
    but it is on screen, and the changed text is *inside* it. Asserted as
    containment through the DOM rather than by reading indentation, because a
    tree that renders flat with a margin would pass a positional check.
    """
    mod = nested_saves(api, "Changelog hierarchy")
    open_changes(page, mod, 2)

    hierarchy = page.get_by_test_id("changelog-hierarchy")
    expect(hierarchy).to_be_visible()
    section = hierarchy.locator("li[data-node='sec']")
    expect(section).to_have_attribute("data-change", "context")
    # **And it carries no chip of its own.** Labelling it would claim a change
    # nobody made. Scoped to its direct children, since the changed node
    # underneath it does have one — an unscoped check would find that instead
    # and pass whatever the section rendered.
    expect(section.locator(":scope > .chip")).to_have_count(0)
    # The changed node is a descendant of the section's own list item.
    expect(section.locator("li[data-node='txt'][data-change='changed']")).to_have_count(1)
    # ...and the untouched button is not drawn at all: the unpruned tree is the
    # whole module, and a changelog that redraws the module buries the change.
    expect(hierarchy.locator("li[data-node='btn']")).to_have_count(0)


def test_a_deleted_widget_is_still_placed_in_its_old_section(page, api):
    """The one kind of change with no node left to hang off. Built from the
    newest document alone, the hierarchy would drop deletions entirely."""
    mod = nested_saves(api, "Changelog deletion")
    open_changes(page, mod, 3)

    section = page.get_by_test_id("changelog-hierarchy").locator("li[data-node='sec']")
    expect(section.locator("li[data-node='btn'][data-change='deleted']")).to_have_count(1)


def test_a_change_expands_to_the_exact_modification(page, api):
    """**p.193's JSON diff**: "inspect JSON diffs to see the exact
    modifications".

    Collapsed first — the list answers *what* changed and this answers *how*,
    and only one of those is the question somebody arrives with. Both halves
    are asserted, because a detail that is always open and a detail that never
    opens both look like "the text is on the page" to a check that only asks
    whether it exists.
    """
    mod = nested_saves(api, "Changelog detail")
    open_changes(page, mod, 2)

    row = page.locator("li[data-node='txt'] tr[data-field='text']")
    expect(row).to_have_count(1)
    expect(row).not_to_be_visible()

    page.locator("li[data-node='txt']").get_by_test_id("changelog-detail").locator(
        "summary"
    ).click()
    expect(row).to_be_visible()
    # The leaf that changed, named as itself rather than as the props object
    # around it, with both values.
    expect(row).to_contain_text("FIRST")
    expect(row).to_contain_text("SECOND")


def test_a_move_reports_the_position_it_moved_to(page, api):
    """A move's props are identical by definition — that is what makes it a
    move — so the position is the only modification there is to show. An empty
    detail here would read as a panel that failed to load one."""
    mod = Module(api, "Changelog move")
    both = {
        "a": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "A"}},
        "b": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "B"}},
    }
    mod.define({"format": 2, "layout": layout(both), "variables": {}, "events": {}},
               description="first")
    mod.define({"format": 2,
                "layout": layout({"b": both["b"], "a": both["a"]}),
                "variables": {}, "events": {}},
               description="swapped them")
    open_changes(page, mod, 2)

    moved = page.locator("li[data-change='moved']").first
    expect(moved).to_have_count(1)
    moved.get_by_test_id("changelog-detail").locator("summary").click()
    expect(moved.locator("tr[data-field='index']")).to_be_visible()
