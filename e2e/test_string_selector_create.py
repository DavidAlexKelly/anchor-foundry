"""p.461's user-created options, and the dropdowns' `change` event (§579).

> "Allow creating new options: Can be toggled on to allow users to create
> new options to be added to the dropdown. Any user-created options will be
> italicized." (p.461)

**Where a created option lives is the selection itself**: an option the
listed options do not hold, in the array the widget writes. So a created
option is kept exactly as long as it is chosen, and anything that writes the
variable writes it too.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled
from test_string_selector import save


def build(api, name: str, events: bool = True, **props) -> Module:
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "sel": {"resolvedName": "CanvasStringSelector",
                    "props": {"name": "v_picks", "label": "Tags", "selection": "multiple",
                              "display": "dropdown", "optionSource": "static",
                              "options": ["North", "South"], "allowCreating": True, **props}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "many: [{{v_picks}}] said: [{{v_said}}]"}},
        }),
        "variables": {
            "v_picks": {"id": "v_picks", "kind": "array", "label": "Chosen", "element": "string"},
            "v_said": {"id": "v_said", "kind": "string", "label": "Said"},
        },
        "events": {
            "e_changed": {"id": "e_changed", "trigger": {"node": "sel", "on": "change"},
                          "effects": [{"type": "set_variable",
                                       "config": {"variable": "v_said", "value": "{{value}}"}}]},
        } if events else {},
    })
    return mod


def echo(page):
    return page.locator(".canvas-block", has_text="many:").first


def test_a_typed_option_is_chosen_and_italicised(page, api) -> None:
    open_module(page, build(api, "Selector create"))
    typed = page.get_by_test_id("selector-create-input")
    expect(typed).to_have_attribute("placeholder", "Search options...")
    typed.fill("  Up north ")
    typed.press("Enter")
    expect(echo(page)).to_contain_text("many: [Up north]")
    created = page.locator("[data-testid='selector-dropdown'] option[data-created='true']")
    expect(created).to_have_text(["Up north"])
    expect(created).to_have_css("font-style", "italic")
    # A listed option typed is that option, not a copy of it.
    typed.fill("South")
    page.get_by_test_id("selector-create").click()
    expect(echo(page)).to_contain_text("many: [Up north,South]")
    expect(created).to_have_count(1)
    # And the dropdown's own change fires the event, as a click on a box does.
    expect(echo(page)).to_contain_text("said: [Up north, South]")


def test_a_created_option_goes_when_it_is_unchosen(page, api) -> None:
    open_module(page, build(api, "Selector uncreate"))
    typed = page.get_by_test_id("selector-create-input")
    typed.fill("Up north")
    typed.press("Enter")
    expect(echo(page)).to_contain_text("many: [Up north]")
    page.get_by_test_id("selector-dropdown").select_option(["North"])
    expect(echo(page)).to_contain_text("many: [North]")
    expect(page.locator("option[data-created='true']")).to_have_count(0)
    expect(echo(page)).to_contain_text("said: [North]")
    expect(page.get_by_test_id("selector-create")).to_be_disabled()


def test_no_field_to_create_unless_allowed(page, api) -> None:
    open_module(page, build(api, "Selector no create", allowCreating=False))
    expect(page.get_by_test_id("selector-dropdown")).to_be_visible()
    expect(page.get_by_test_id("selector-create-input")).to_have_count(0)


def test_a_single_dropdown_fires_change_too(page, api) -> None:
    mod = Module(api, "Selector single change")
    mod.define({
        "format": 2,
        "layout": layout({
            "sel": {"resolvedName": "CanvasStringSelector",
                    "props": {"name": "v_pick", "label": "Region", "selection": "single",
                              "display": "dropdown", "optionSource": "static",
                              "options": ["North", "South"]}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "said: [{{v_said}}]"}},
        }),
        "variables": {
            "v_pick": {"id": "v_pick", "kind": "string", "label": "Chosen"},
            "v_said": {"id": "v_said", "kind": "string", "label": "Said"},
        },
        "events": {
            "e_changed": {"id": "e_changed", "trigger": {"node": "sel", "on": "change"},
                          "effects": [{"type": "set_variable",
                                       "config": {"variable": "v_said", "value": "{{value}}"}}]},
        },
    })
    open_module(page, mod)
    page.get_by_test_id("selector-dropdown").select_option("South")
    expect(page.locator(".canvas-block", has_text="said:").first).to_contain_text("said: [South]")


def test_the_panel_offers_it_for_a_multiple_dropdown_only(page, api) -> None:
    mod = build(api, "Selector create panel", events=False, allowCreating=False)
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="String selector").first.click()
    toggle = page.get_by_test_id("selector-allow-creating")
    toggle.check()
    save(page)
    assert mod.definition()["layout"]["sel"]["props"]["allowCreating"] is True
