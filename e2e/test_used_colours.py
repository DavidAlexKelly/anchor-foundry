"""p.213-214's Used colors panel (parity `workshop.md` §9; Foundry p.213-214).

> "Used colors can be accessed by navigating to a module's Settings tab in
> edit mode." (p.213)

> "Unsaved colors represent custom colors used in layouts and widgets
> throughout the module that are not defined as saved colors. You can select
> the hex code of an unsaved color to copy it for use elsewhere, and you can
> also see the usage of these colors in layouts and widgets within the
> module." (p.214)

Which colours count, how they are ordered and how a use reads are all values,
and they are checked directly in
`apps/web/src/components/canvas/used-colours.test.ts`. What needs a browser is
everything that function cannot see: that the panel is in edit mode and only
there, that it reads the document being **edited** rather than the one last
saved, and that the hex reaches the clipboard.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, select_node

# Two custom colours, one of them used twice, so the panel has an order to get
# right and a count to get right.
TEAL = "#1f7a70"
RUST = "#a4471f"


def coloured_module(api, name: str, props_by_node: dict) -> Module:
    nodes = {}
    for node_id, props in props_by_node.items():
        nodes[node_id] = {
            "resolvedName": "CanvasSection", "isCanvas": True,
            "props": {"direction": "columns", "gap": 12, **props},
            "nodes": [],
        }
    mod = Module(api, name)
    mod.define({"format": 2, "layout": layout(nodes), "variables": {}, "events": {}})
    return mod


def test_the_panel_lists_a_custom_colour_and_counts_its_places(page, api) -> None:
    """p.214's two facts about a row: the hex, and where it is used."""
    mod = coloured_module(api, "Colours listed", {
        "a": {"background": TEAL},
        "b": {"background": TEAL},
        "c": {"background": RUST},
    })
    open_builder(page, mod)

    rows = page.locator('[data-testid="used-colours-rows"] > li')
    expect(rows).to_have_count(2)
    # The widely used one first — p.214's purpose is swapping a colour out.
    expect(rows.nth(0).locator("button").first).to_have_text(TEAL)
    expect(rows.nth(0)).to_contain_text("2 places")
    expect(rows.nth(1).locator("button").first).to_have_text(RUST)
    expect(rows.nth(1)).to_contain_text("1 place")


def test_a_preset_background_is_not_a_used_colour(page, api) -> None:
    """p.213: "usage of intent colors will not be displayed in the Used colors
    panel". `shade-2` is an intent — a name for a role — and the panel that
    listed it would be listing the platform's own palette back at its author.

    The custom colour in the same module is what stops this passing because
    the panel is broken rather than because the rule works.
    """
    mod = coloured_module(api, "Colours presets", {
        "a": {"background": "shade-2"},
        "b": {"background": "shade-4"},
        "c": {"background": RUST},
    })
    open_builder(page, mod)

    rows = page.locator('[data-testid="used-colours-rows"] > li')
    expect(rows).to_have_count(1)
    expect(rows.first).to_contain_text(RUST)


def test_a_module_with_no_custom_colours_says_so(page, api) -> None:
    """Not "no colours": a module themed entirely from the presets is fully
    coloured and has nothing to tidy."""
    mod = coloured_module(api, "Colours none", {"a": {"background": "shade-2"}})
    open_builder(page, mod)

    # The sentence first, then the absence of the list: an absence asserted
    # before anything has rendered is a check that cannot fail (§318).
    expect(page.locator('[data-testid="used-colours-empty"]')).to_contain_text(
        "standard shades only"
    )
    expect(page.locator('[data-testid="used-colours-rows"]')).to_have_count(0)


def test_the_uses_name_the_widget_and_the_prop(page, api) -> None:
    """p.214: "see the usage of these colors in layouts and widgets within the
    module". The node's *name*, which is the half the pure module cannot
    supply — it has ids and the editor has the tree."""
    mod = coloured_module(api, "Colours uses", {"a": {"background": TEAL}})
    open_builder(page, mod)

    page.locator(f'[data-testid="colour-uses-{TEAL[1:]}"]').click()
    uses = page.locator(f'[data-testid="colour-use-list-{TEAL[1:]}"] > li')
    expect(uses).to_have_count(1)
    # "Section", not "a". A list of node ids would be a list nobody can act on.
    expect(uses.first).to_contain_text("Section")
    expect(uses.first).to_contain_text("background")


def test_a_renamed_widget_is_named_by_its_new_name(page, api) -> None:
    """p.68: renaming a widget "will affect how the current widget is
    referenced through Workshop, most notably as a component in the Layout
    panel". This panel is another of those references, and it is the one where
    the rename matters most — an author renames a section *because* "Section"
    told them nothing, and a colour audit still calling it "Section" would
    leave them exactly where they started.
    """
    mod = coloured_module(api, "Colours renamed", {"a": {"background": TEAL}})
    open_builder(page, mod)

    select_node(page, "Section")
    # p.68's rename lives on the widget's Metadata tab, which is where the
    # builder puts it and therefore where an author will do it.
    page.get_by_role("tab", name="Metadata").click()
    page.locator('[data-testid="widget-name"]').fill("Alert banner")

    page.locator(f'[data-testid="colour-uses-{TEAL[1:]}"]').click()
    uses = page.locator(f'[data-testid="colour-use-list-{TEAL[1:]}"] > li')
    expect(uses.first).to_contain_text("Alert banner")
    expect(uses.first).not_to_contain_text("Section")


def test_the_list_follows_the_edit_not_the_save(page, api) -> None:
    """**The reason this panel reads Craft's live node map.**

    A colour audit is looked at *while* colours are being changed. One that
    only caught up on save would describe the module as it was a minute ago,
    which is the one moment the audit is useless — and it would pass every
    check above, because they all load a document that is already saved.
    """
    mod = coloured_module(api, "Colours live", {"a": {"background": "shade-2"}})
    open_builder(page, mod)
    expect(page.locator('[data-testid="used-colours-empty"]')).to_have_count(1)

    # Select the section and give it a custom background, without saving.
    select_node(page, "Section")
    page.locator('[data-testid="style-background"]').select_option("custom")
    page.locator('[data-testid="style-background-hex"]').fill(TEAL)
    page.locator('[data-testid="style-background-hex"]').blur()

    expect(page.locator('[data-testid="used-colours-rows"] > li')).to_have_count(1)
    expect(page.locator(f'[data-testid="colour-hex-{TEAL[1:]}"]')).to_have_text(TEAL)
    expect(page.locator('[data-testid="used-colours-empty"]')).to_have_count(0)


def test_the_hex_copies(page, api) -> None:
    """p.214: "You can select the hex code of an unsaved color to copy it for
    use elsewhere". Read back out of the clipboard rather than trusting the
    label — a button that says "Copied" and wrote nothing is §214's control
    that looks like it works."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    mod = coloured_module(api, "Colours copy", {"a": {"background": RUST}})
    open_builder(page, mod)

    page.locator(f'[data-testid="colour-hex-{RUST[1:]}"]').click()
    expect(page.locator(f'[data-testid="colour-hex-{RUST[1:]}"]')).to_have_text("Copied")
    assert page.evaluate("() => navigator.clipboard.readText()") == RUST


def test_a_reader_never_sees_the_panel(page, api) -> None:
    """p.213 puts it behind "edit mode", and it is an authoring tool: a reader
    has nothing to do with a hex code, and the panel names every widget in the
    module including the ones a reader cannot see."""
    mod = coloured_module(api, "Colours reader", {"a": {"background": TEAL}})
    open_module(page, mod)

    # The module itself first (§318). Without it this passes against a page
    # that never finished loading, which is every page for a moment.
    expect(page.locator(".canvas-section").first).to_be_visible()
    expect(page.locator('[data-testid="used-colours"]')).to_have_count(0)
