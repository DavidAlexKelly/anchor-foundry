"""Cut, copy and paste, and p.55's two paste modes (parity `workshop.md` §1.3;
Foundry p.55, p.68-69).

> "When pasting sections or widgets, builders have two options for managing the
> new section's or widget's input variables:
>
> **Paste with same input variable**: Paste a new section or widget that reuses
> the copied section's or widget's input variables.
>
> **Paste with duplicate input variables**: Pastes a new section or widget that
> uses newly created input variables that match the copied section's or
> widget's input variables." (p.55)

The remap arithmetic is checked directly in
`apps/web/src/components/canvas/clipboard.test.ts`, node by node. What needs a
browser is that the transform survives the round trip Craft.js makes of it:
`getSerializedNodes` out, `deserialize` back in, and then a **save and reload**,
because a paste that only lives in the editor's memory is a paste that
disappears the first time somebody comes back to the module.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, settled


def module_with(api, name: str):
    """A section holding one text widget, bound to a variable by `visibleWhen`.

    **The binding is what makes the two modes distinguishable.** A copied
    widget with no inputs pastes identically either way, so a fixture without
    one would pass against a build that ignored the mode entirely.

    **`visibleWhen` rather than `{{...}}` in the text**, and the difference is
    the point: an interpolation is not a reference prop, so nothing in this
    system counts it as a usage - not the server, not the Variables panel, and
    not the clipboard. A fixture bound that way carries no variables at all,
    which is how the first draft of this file managed to fail three tests for
    a reason that had nothing to do with pasting.

    It also gives the independence check its assertion for free: in the builder
    a widget whose variable is falsy is not hidden, it is marked "hidden unless
    <label>" - so the marker **names the variable the widget is bound to**.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "sec": {"resolvedName": "CanvasSection", "isCanvas": True,
                    "props": {"direction": "rows", "gap": 8},
                    "nodes": ["txt"]},
            "txt": {"resolvedName": "CanvasText", "parent": "sec",
                    "props": {"tag": "p", "text": "COPY ME",
                              "visibleWhen": "v_show"}},
        }),
        "variables": {
            "v_show": {"id": "v_show", "kind": "string", "label": "Show",
                       "default": "yes"},
        },
        "events": {},
    })
    return mod


def tree_rows(page):
    return page.locator(".canvas-tree-row")


def rows_once_drawn(page) -> int:
    """The tree's row count, once the tree has drawn.

    **`settled()` is not enough for this**, and the difference cost a full
    browser run to find: it waits for the *canvas*, and the Layout panel paints
    after it. A baseline captured immediately reads **0**, which turns
    `n == before * 2` into `n == 0` - an assertion nothing can satisfy once a
    paste has added rows.

    The failure that produces is worse than the race, because it blames the
    wrong half: the message reads "still 4", which sounds like the paste
    produced the wrong number when the paste was right and the baseline was
    zero. This test passed on luck until §196 and §197 both added work to the
    Layout panel's first paint.
    """
    return eventually(lambda: tree_rows(page).count(), lambda n: n > 0,
                      what="the layout tree to draw")


def copies(page):
    """The pasted text, **on the canvas only**.

    Scoped, because the Layout panel shows a widget's `text` prop as the row's
    detail (`detailOf`), so an unscoped `get_by_text` counts every widget
    twice - once where it is drawn and once where it is listed. The first
    version of this file asserted two and got four, which reads as the paste
    having run twice.
    """
    return page.locator(".canvas-frame-area").get_by_text("COPY ME")


def select_section(page):
    """Select the Section through the Layout panel.

    Through the tree rather than by clicking the canvas, for
    `test_widget_config_tabs.py`'s reason: a click on a section lands on
    whatever is under the pointer, and the tree row names what it selects.
    """
    row = tree_rows(page).filter(has_text="Section").first
    row.click()
    expect(row).to_have_attribute("aria-current", "true")


def save(page):
    """Click Save and wait for the version line to say it landed."""
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved", timeout=15000)


def variable_rows(page):
    """The Variables panel's rows, which is where a duplicated variable has to
    show up if p.55's second mode did anything."""
    page.get_by_role("button", name="Variables", exact=False).first.click()
    return page.locator(".vars-row")


def test_copy_and_paste_adds_a_second_copy_of_the_section(page, api) -> None:
    """The base case: two sections in the tree where there was one, and the
    copy renders."""
    mod = module_with(api, "Clip copy")
    open_builder(page, mod)
    settled(page)

    before = rows_once_drawn(page)
    select_section(page)
    page.get_by_test_id("clip-copy").click()
    expect(page.get_by_test_id("clip-state")).to_contain_text("Holding")

    page.get_by_test_id("clip-paste-same").click()
    eventually(lambda: tree_rows(page).count(), lambda n: n == before * 2,
               what="the pasted section and its child in the tree")
    # Both copies draw, which is the part `deserialize` has to get right.
    expect(copies(page)).to_have_count(2)


def test_paste_with_the_same_variable_leaves_the_variable_list_alone(page, api) -> None:
    """p.55's first mode: "reuses the copied section's or widget's input
    variables". One variable before, one after."""
    mod = module_with(api, "Clip same")
    open_builder(page, mod)
    settled(page)

    select_section(page)
    page.get_by_test_id("clip-copy").click()
    page.get_by_test_id("clip-paste-same").click()
    eventually(lambda: copies(page).count(), lambda n: n == 2,
               what="the pasted copy on screen")

    expect(variable_rows(page)).to_have_count(1)


def test_paste_as_a_copy_mints_a_new_variable(page, api) -> None:
    """p.55's second mode: "newly created input variables that match the copied
    section's or widget's input variables"."""
    mod = module_with(api, "Clip duplicate")
    open_builder(page, mod)
    settled(page)

    select_section(page)
    page.get_by_test_id("clip-copy").click()
    page.get_by_test_id("clip-paste-duplicate").click()
    eventually(lambda: copies(page).count(), lambda n: n == 2,
               what="the pasted copy on screen")

    rows = variable_rows(page)
    expect(rows).to_have_count(2)
    # Named so the panel is usable: two variables both called "Show" is a list
    # nobody can pick from, and the panel is where an author goes next.
    expect(rows.filter(has_text="Show copy")).to_have_count(1)


def test_the_duplicate_is_independent_of_the_original(page, api) -> None:
    """**The assertion the whole second mode exists for.**

    Both copies look identical after a duplicate paste, so a test that stopped
    at the variable count would pass against a build that minted a variable and
    then left the pasted widget bound to the original - which is the natural
    way to get this half-right and is invisible on the canvas.
    """
    mod = module_with(api, "Clip independent")
    open_builder(page, mod)
    settled(page)

    select_section(page)
    page.get_by_test_id("clip-copy").click()
    page.get_by_test_id("clip-paste-duplicate").click()
    eventually(lambda: copies(page).count(), lambda n: n == 2,
               what="both copies on screen to begin with")

    # **Saved first, and that is not incidental.** The Variables panel counts
    # usages against the *saved* definition, so before a save it reports the
    # duplicate as unused however well the paste worked. Asking early is a
    # question about the wrong document.
    save(page)
    page.reload()
    settled(page)

    # **The usage counts are the readout**, and they name both sides of the
    # question at once. A build that minted the variable and then forgot to
    # repoint the pasted props - the natural way to get this half-right, and
    # invisible on the canvas - would show "Show" used twice and "Show copy"
    # used by nothing.
    rows = variable_rows(page)
    expect(rows.filter(has_text="Show copy")).to_contain_text("used 1")
    original = rows.filter(has_text="Show").filter(has_not_text="copy")
    expect(original).to_contain_text("used 1")


def test_cut_removes_the_section_and_paste_puts_it_back(page, api) -> None:
    """Cut is copy-and-remove as one edit, so a cut with nowhere to paste is
    still recoverable — which is the difference between Cut and Delete."""
    mod = module_with(api, "Clip cut")
    open_builder(page, mod)
    settled(page)

    select_section(page)
    page.get_by_test_id("clip-cut").click()
    eventually(lambda: copies(page).count(), lambda n: n == 0,
               what="the cut section leaving the canvas")

    page.get_by_test_id("clip-paste-same").click()
    eventually(lambda: copies(page).count(), lambda n: n == 1,
               what="the cut section coming back")


def test_a_paste_survives_a_save_and_a_reload(page, api) -> None:
    """**The reason this needs a browser at all.**

    Everything above could pass against a paste that only edited the editor's
    in-memory tree. The document is what a paste has to change, and the only
    honest way to ask is to save it and come back.
    """
    mod = module_with(api, "Clip persists")
    open_builder(page, mod)
    settled(page)

    select_section(page)
    page.get_by_test_id("clip-copy").click()
    page.get_by_test_id("clip-paste-duplicate").click()
    eventually(lambda: copies(page).count(), lambda n: n == 2,
               what="the pasted copy before saving")

    save(page)
    page.reload()
    settled(page)

    eventually(lambda: copies(page).count(), lambda n: n == 2,
               what="both copies still there after a reload")
    # And the minted variable was saved too - the server refuses a document
    # binding to a variable it does not declare, so a save that dropped it
    # would have been refused rather than silently half-applied.
    expect(variable_rows(page)).to_have_count(2)
