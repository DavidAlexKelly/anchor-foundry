"""p.55's conditional-visibility indicators (parity `workshop.md` §1.3;
Foundry p.55).

> "Sections can be configured with conditional visibility to show or hide based
> on variable values. The layout panel displays icons and tooltips to indicate
> which sections have conditional visibility enabled, making it easier to
> identify and manage conditionally visible sections even when they are
> currently hidden in the module view." (p.55)

Which props count as conditions and what each tooltip reads is checked in
`apps/web/src/components/canvas/conditions.test.ts`. What needs a browser is
the sentence's **second half**: a section whose condition is false right now is
still marked and still selectable. That is a claim about the panel and the
canvas disagreeing on purpose — the canvas is showing what is happening now,
the panel is showing what is configured — and nothing short of rendering both
can check they disagree the right way round.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, settled


def module_with(api, name: str, default: bool):
    """A section hidden behind `v_show`, beside one that is always there.

    The unconditioned section is the control: it is what makes "the marked row
    is the marked one" an assertion rather than a count.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "s_cond": {"resolvedName": "CanvasSection", "isCanvas": True,
                       "props": {"direction": "columns", "visibleWhen": "v_show"},
                       "nodes": ["w1"]},
            "w1": {"resolvedName": "CanvasText", "parent": "s_cond",
                   "props": {"tag": "p", "text": "conditional-widget"}},
            "s_plain": {"resolvedName": "CanvasSection", "isCanvas": True,
                        "props": {"direction": "columns"}, "nodes": ["w2"]},
            "w2": {"resolvedName": "CanvasText", "parent": "s_plain",
                   "props": {"tag": "p", "text": "plain-widget"}},
        }),
        "variables": {
            "v_show": {"id": "v_show", "kind": "boolean", "label": "Show details",
                       "default": default},
        },
        "events": {},
    })
    return mod


def markers(page):
    return page.locator('[data-testid="tree-condition"]')


def test_a_conditional_section_is_marked_in_the_layout_panel(page, api) -> None:
    """p.55's first half: an icon, on the row that has a condition."""
    mod = module_with(api, "Condition marked", True)
    open_builder(page, mod)

    # Exactly one, not "at least one": the plain section beside it must not be
    # marked, or the icon would mean "this is a section" rather than "this one
    # is conditional".
    expect(markers(page)).to_have_count(1)


def test_the_tooltip_names_the_variable(page, api) -> None:
    """p.55's "easier to identify and manage".

    An icon saying only *that* there is a condition satisfies the letter and
    none of the purpose — the variable's name is the only part of this an
    author can go and act on.
    """
    mod = module_with(api, "Condition tooltip", True)
    open_builder(page, mod)

    marker = markers(page).first
    expect(marker).to_have_attribute("title", "Visible when Show details")
    # And reachable by something that is not a pointer: a `title` alone is not.
    expect(marker).to_have_attribute("aria-label", "Visible when Show details")


def test_the_marker_stays_while_the_section_is_hidden(page, api) -> None:
    """**The reason p.55 asks for this at all**, and the reason it needs a
    browser.

    With the variable false the canvas marks the section "hidden unless …",
    which is the *value* speaking. The Layout panel must go on showing its
    indicator anyway, because the panel is answering "what is configured" — and
    an indicator that went out when the condition was false would disappear in
    exactly the case the sentence is about.
    """
    mod = module_with(api, "Condition while hidden", False)
    open_builder(page, mod)

    # The canvas agrees the condition is false right now...
    expect(page.locator(".canvas-page, .canvas-section").first).to_be_visible()
    expect(page.get_by_text("hidden unless Show details").first).to_be_visible()

    # ...and the panel still marks the row, and the row still selects.
    expect(markers(page)).to_have_count(1)
    row = page.locator(".canvas-tree-row").filter(has=markers(page)).first
    row.click()
    expect(row).to_have_attribute("aria-current", "true")


def test_a_collapse_backing_is_marked_too(page, api) -> None:
    """p.55 names visibility; p.82's collapse backing is the same question
    about a different bit of state, and a row carrying both says both."""
    mod = Module(api, "Condition both")
    mod.define({
        "format": 2,
        "layout": layout({
            "s1": {"resolvedName": "CanvasSection", "isCanvas": True,
                   "props": {"direction": "columns", "collapsible": True,
                             "visibleWhen": "v_show", "collapsedWhen": "v_shut"},
                   "nodes": ["w1"]},
            "w1": {"resolvedName": "CanvasText", "parent": "s1",
                   "props": {"tag": "p", "text": "both-widget"}},
        }),
        "variables": {
            "v_show": {"id": "v_show", "kind": "boolean", "label": "Show details",
                       "default": True},
            "v_shut": {"id": "v_shut", "kind": "boolean", "label": "Start collapsed",
                       "default": False},
        },
        "events": {},
    })
    open_builder(page, mod)

    expect(markers(page).first).to_have_attribute(
        "title", "Visible when Show details · Collapsed when Start collapsed",
    )


def test_renaming_the_variable_updates_the_tooltip(page, api) -> None:
    """**The bug the split in `conditions.ts` exists to prevent.**

    The tree walk runs inside Craft's node-map selector, which does not re-run
    when the *variable list* changes — so computing the label there left a
    tooltip reading a variable's old name until something unrelated touched
    the layout. Nothing in the unit tests can see that: it is a fact about
    which React hook re-runs when.
    """
    mod = module_with(api, "Condition rename", True)
    open_builder(page, mod)
    expect(markers(page).first).to_have_attribute("title", "Visible when Show details")

    page.get_by_role("button", name="Variables", exact=False).first.click()
    # The row is a toggle; the editor with the Label field opens beneath it.
    page.locator(".vars-row").first.click()
    label = page.locator(".vars-editor").get_by_label("Label")
    label.fill("Renamed thing")
    label.blur()

    expect(markers(page).first).to_have_attribute(
        "title", "Visible when Renamed thing", timeout=15000,
    )
