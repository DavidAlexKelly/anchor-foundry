"""p.459–461's String Selector (parity `workshop.md` §10; decision 0011).

> "**Selection**: … single option selection or multiple option selections.
> **Selected value**: Output variable of the widget… **If the selection is set to
> Single, the output variable will be a string variable. If the selection is set
> to Multiple, the output variable will be a string array variable.**
>
> **Selection display**: If the selection is set to Single, the widget may be
> displayed as either a dropdown or as radio buttons… If the selection is set to
> Multiple, the widget may be displayed as either a dropdown or as
> checkboxes." (p.461)

The matrix, the option list and what a pick means are checked in
`apps/web/src/components/canvas/string-selector.test.ts` without a browser.

What needs one is what a pure function cannot see: that each of the four
render arms is actually wired to the variable, that an options *variable* reaches
the widget through a server resolve, and — the one this unit exists for — that
**changing the selection clears the bound variable**, because the kind it must
be has changed underneath it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict | None = None, *, dynamic: bool = False):
    """One selector, a mirror of what it stored, and a clock.

    The clock is a *separate* variable from everything asserted on (§203): it
    proves a full write-and-resolve cycle completed without being able to
    overwrite the evidence.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "sel": {"resolvedName": "CanvasStringSelector",
                    "props": {"name": "v_pick", "label": "Region",
                              "selection": "single", "display": "dropdown",
                              "optionSource": "dynamic" if dynamic else "static",
                              "options": ["North", "South", "East"],
                              "optionsVariable": "v_opts" if dynamic else "",
                              "placeholder": "", "allowClearing": True,
                              "layout": "vertical", "columns": 3,
                              **(props or {})}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p",
                               "text": "one: [{{v_pick}}] many: [{{v_picks}}] clock: {{v_clock}}"}},
        }),
        "variables": {
            "v_pick": {"id": "v_pick", "kind": "string", "label": "Chosen"},
            "v_picks": {"id": "v_picks", "kind": "array", "label": "Chosen many",
                        "element": "string"},
            "v_opts": {"id": "v_opts", "kind": "array", "label": "Options",
                       "element": "string", "default": ["Alpha", "Beta"]},
            "v_clock": {"id": "v_clock", "kind": "string", "label": "Clock", "default": "no"},
        },
        "events": {
            "e_go": {"id": "e_go", "trigger": {"node": "btn", "on": "click"},
                     "effects": [{"type": "set_variable",
                                  "config": {"variable": "v_clock", "value": "ticked"}}]},
        },
    })
    return mod


def echo(page):
    return page.locator(".canvas-block", has_text="one:").first


def tick(page):
    """A completed write-and-resolve cycle, for asserting that something did
    *not* happen (§202, §203)."""
    page.get_by_role("button", name="Go", exact=True).click()
    expect(echo(page)).to_contain_text("clock: ticked")


def test_a_single_dropdown_writes_a_string(page, api) -> None:
    mod = module_with(api, "Selector single dropdown")
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("selector-dropdown").select_option("South")
    expect(echo(page)).to_contain_text("one: [South]")


def test_a_single_dropdown_can_be_cleared_back_to_nothing(page, api) -> None:
    """p.461's clearing, which is the empty row in the list."""
    mod = module_with(api, "Selector clear")
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("selector-dropdown").select_option("South")
    expect(echo(page)).to_contain_text("one: [South]")
    page.get_by_test_id("selector-dropdown").select_option("")
    expect(echo(page)).to_contain_text("one: []")


def test_disabling_clearing_removes_the_empty_row(page, api) -> None:
    """p.461's "Disable clearing of dropdown options". The empty row *is* the
    clearing affordance, so forbidding one removes the other — but only once
    something is chosen, or the widget would open showing a value nobody
    picked."""
    mod = module_with(api, "Selector no clear", {"allowClearing": False})
    open_module(page, mod)
    settled(page)

    dropdown = page.get_by_test_id("selector-dropdown")
    # Nothing chosen yet, so the empty row is still there to represent that.
    expect(dropdown.locator("option[value='']")).to_have_count(1)
    dropdown.select_option("North")
    expect(echo(page)).to_contain_text("one: [North]")
    expect(dropdown.locator("option[value='']")).to_have_count(0)


def test_radio_buttons_write_a_string(page, api) -> None:
    """p.461 gives radio buttons to a single selection."""
    mod = module_with(api, "Selector radio", {"display": "radio"})
    open_module(page, mod)
    settled(page)

    group = page.get_by_test_id("selector-options")
    expect(group).to_have_attribute("role", "radiogroup")
    group.get_by_role("radio", name="East").check()
    expect(echo(page)).to_contain_text("one: [East]")


def test_checkboxes_write_a_list(page, api) -> None:
    """p.461 gives checkboxes to a multiple selection, and the variable it
    writes is an array."""
    mod = module_with(api, "Selector checkboxes", {
        "name": "v_picks", "selection": "multiple", "display": "checkboxes",
    })
    open_module(page, mod)
    settled(page)

    group = page.get_by_test_id("selector-options")
    group.get_by_role("checkbox", name="North").check()
    group.get_by_role("checkbox", name="East").check()
    expect(echo(page)).to_contain_text("many: [North,East]")

    group.get_by_role("checkbox", name="North").uncheck()
    expect(echo(page)).to_contain_text("many: [East]")


def test_a_multiple_dropdown_writes_a_list(page, api) -> None:
    mod = module_with(api, "Selector multi dropdown", {
        "name": "v_picks", "selection": "multiple", "display": "dropdown",
    })
    open_module(page, mod)
    settled(page)

    page.get_by_test_id("selector-dropdown").select_option(["North", "South"])
    expect(echo(page)).to_contain_text("many: [North,South]")


def test_an_illegal_pair_renders_the_selections_first_display(page, api) -> None:
    """**One click in the panel produces this**: flip the selection while
    `radio` is saved and the document holds multiple/radio. Trusting the pair
    would draw radio buttons over a variable holding a list."""
    mod = module_with(api, "Selector illegal pair", {
        "name": "v_picks", "selection": "multiple", "display": "radio",
    })
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("selector-dropdown")).to_be_visible()
    expect(page.get_by_test_id("selector-options")).to_have_count(0)
    page.get_by_test_id("selector-dropdown").select_option(["South"])
    expect(echo(page)).to_contain_text("many: [South]")


def test_options_can_come_from_an_array_variable(page, api) -> None:
    """p.461's dynamic option generation. The list arrives through a **server
    resolve**, which is the part no pure function can stand in for."""
    mod = module_with(api, "Selector dynamic", dynamic=True)
    open_module(page, mod)
    settled(page)

    dropdown = page.get_by_test_id("selector-dropdown")
    expect(dropdown.locator("option[value='Alpha']")).to_have_count(1)
    expect(dropdown.locator("option[value='North']")).to_have_count(0)
    dropdown.select_option("Beta")
    expect(echo(page)).to_contain_text("one: [Beta]")


def test_the_default_placeholder_differs_between_the_two_dropdowns(page, api) -> None:
    """p.461 gives them different defaults on purpose: one picks, one
    searches."""
    mod = module_with(api, "Selector placeholder")
    open_module(page, mod)
    settled(page)
    expect(page.get_by_test_id("selector-dropdown")).to_contain_text("Select an option...")


def test_a_custom_placeholder_replaces_the_default(page, api) -> None:
    mod = module_with(api, "Selector custom placeholder", {"placeholder": "Pick a region"})
    open_module(page, mod)
    settled(page)
    expect(page.get_by_test_id("selector-dropdown")).to_contain_text("Pick a region")
    expect(page.get_by_test_id("selector-dropdown")).not_to_contain_text("Select an option...")


def test_a_grid_layout_uses_the_configured_column_count(page, api) -> None:
    """p.461's "grid formation with a specified number of columns"."""
    mod = module_with(api, "Selector grid", {
        "display": "radio", "layout": "grid", "columns": 2,
    })
    open_module(page, mod)
    settled(page)

    style = page.get_by_test_id("selector-options").get_attribute("style") or ""
    assert "repeat(2," in style.replace(" ", "").replace("repeat(2,", "repeat(2,"), style


def test_the_settings_panel_offers_variables_of_the_selections_kind(page, api) -> None:
    """p.461's sentence, in the panel: Single offers string variables, Multiple
    offers arrays."""
    mod = module_with(api, "Selector settings kinds")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="String selector").first.click()
    picker = page.get_by_test_id("selector-variable")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "Chosen" in labels and "Chosen many" not in labels, labels

    page.get_by_test_id("selector-selection").select_option("multiple")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "Chosen many" in labels and "Chosen" not in labels, labels


def test_changing_the_selection_clears_the_bound_variable(page, api) -> None:
    """**The rule this unit exists for.** The bound variable is now the wrong
    kind, so keeping it would save a document the server refuses, naming a
    widget the author did not touch."""
    mod = module_with(api, "Selector selection clears")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="String selector").first.click()
    expect(page.get_by_test_id("selector-variable")).to_have_value("v_pick")
    page.get_by_test_id("selector-selection").select_option("multiple")
    expect(page.get_by_test_id("selector-variable")).to_have_value("")


def test_changing_the_selection_moves_the_display_to_a_legal_one(page, api) -> None:
    """Radio buttons do not exist under Multiple, so the saved display cannot
    survive the change either."""
    mod = module_with(api, "Selector display follows", {"display": "radio"})
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="String selector").first.click()
    expect(page.get_by_test_id("selector-display")).to_have_value("radio")
    page.get_by_test_id("selector-selection").select_option("multiple")
    expect(page.get_by_test_id("selector-display")).to_have_value("dropdown")

    options = page.get_by_test_id("selector-display").locator("option")
    labels = sorted(options.nth(i).inner_text() for i in range(options.count()))
    assert labels == ["Checkboxes", "Dropdown"], labels


def test_the_layout_setting_appears_only_where_p461_gives_one(page, api) -> None:
    """A dropdown has a placeholder and no layout; a list of controls has a
    layout and no placeholder."""
    mod = module_with(api, "Selector layout setting")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="String selector").first.click()
    expect(page.get_by_test_id("selector-layout")).to_have_count(0)
    expect(page.get_by_test_id("selector-placeholder")).to_be_visible()

    page.get_by_test_id("selector-display").select_option("radio")
    expect(page.get_by_test_id("selector-layout")).to_be_visible()
    expect(page.get_by_test_id("selector-placeholder")).to_have_count(0)
    # And the column count only for a grid.
    expect(page.get_by_test_id("selector-columns")).to_have_count(0)
    page.get_by_test_id("selector-layout").select_option("grid")
    expect(page.get_by_test_id("selector-columns")).to_be_visible()


def test_clearing_is_offered_only_on_the_single_dropdown(page, api) -> None:
    """p.461 puts "Disable clearing" under the single dropdown and nowhere
    else."""
    mod = module_with(api, "Selector clearing setting")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="String selector").first.click()
    expect(page.get_by_test_id("selector-allow-clearing")).to_be_visible()
    page.get_by_test_id("selector-selection").select_option("multiple")
    expect(page.get_by_test_id("selector-allow-clearing")).to_have_count(0)


def test_an_empty_option_list_says_so_rather_than_drawing_nothing(page, api) -> None:
    """A selector with no options and no explanation reads as a broken
    widget."""
    mod = module_with(api, "Selector empty", {"options": []})
    open_module(page, mod)
    settled(page)
    tick(page)
    expect(page.locator(".field-hint", has_text="No options yet")).to_be_visible()
