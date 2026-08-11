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
