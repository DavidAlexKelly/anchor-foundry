"""p.483's Menu and Two-part buttons (parity `workshop.md` §10's Button Group
row; §462).

> "Inline buttons that provide a single option / Menu buttons that provide
> multiple options / Two-part buttons that contain a primary button alongside
> an additional menu of options." (p.483)

What the server accepts is `test_workshop_variables.py` (an item the button
lacks, a Menu button's own click); the item list is `button-items.test.ts`.
What needs a browser is that each item fires **its own** events and nobody
else's, that a Menu button's own click only opens the menu, and that the
builder can wire an event to an item.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, save, settled


def setting(item: str | None, value: str, node: str = "btn") -> dict:
    trigger = {"node": node, "on": "click", **({"item": item} if item else {})}
    return {"trigger": trigger, "effects": [
        {"type": "set_variable", "config": {"variable": "v_note", "value": value}}]}


@pytest.fixture(scope="module")
def menus(api):
    mod = Module(api, "Button menus")
    items = [{"id": "i_1", "label": "Mark north"}, {"id": "i_2", "label": "Mark south"}]
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton",
                    "props": {"label": "Actions", "buttonType": "menu", "items": items}},
            "two": {"resolvedName": "CanvasButton",
                    "props": {"label": "Save", "buttonType": "twoPart",
                              "items": [{"id": "i_1", "label": "Save as draft"}]}},
            "note": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {
            "v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": "none"},
        },
        "events": {
            "e_n": {"id": "e_n", **setting("i_1", "north")},
            "e_s": {"id": "e_s", **setting("i_2", "south")},
            "e_main": {"id": "e_main", **setting(None, "saved", node="two")},
            "e_draft": {"id": "e_draft", **setting("i_1", "draft", node="two")},
        },
    })
    return mod


def note(page, value: str):
    return page.get_by_text(f"NOTE={value}")


def test_each_menu_item_fires_its_own_events(page, menus) -> None:
    open_module(page, menus)
    expect(note(page, "none")).to_be_visible()
    page.get_by_role("button", name="Actions").click()
    menu = page.get_by_role("menu", name="Actions")
    expect(menu.get_by_role("menuitem")).to_have_text(["Mark north", "Mark south"])
    menu.get_by_role("menuitem", name="Mark south").click()
    expect(note(page, "south")).to_be_visible()
    # Chosen, so it closes.
    expect(page.get_by_role("menu")).to_have_count(0)

    page.get_by_role("button", name="Actions").click()
    page.get_by_role("menuitem", name="Mark north").click()
    expect(note(page, "north")).to_be_visible()


def test_a_menu_buttons_own_click_only_opens_it(page, menus) -> None:
    """p.483: a Menu button "provides multiple options"; pressing it offers
    them. It fires nothing itself, and the server refuses an event that says
    otherwise."""
    open_module(page, menus)
    expect(note(page, "none")).to_be_visible()
    page.get_by_role("button", name="Actions").click()
    expect(page.get_by_role("menu", name="Actions")).to_be_visible()
    expect(note(page, "none")).to_be_visible()


def test_a_menu_closes_on_escape_and_on_a_click_elsewhere(page, menus) -> None:
    open_module(page, menus)
    page.get_by_role("button", name="Actions").click()
    expect(page.get_by_role("menu")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("menu")).to_have_count(0)
    page.get_by_role("button", name="Actions").click()
    expect(page.get_by_role("menu")).to_be_visible()
    note(page, "none").click()
    expect(page.get_by_role("menu")).to_have_count(0)
    # Nothing was chosen, so nothing fired.
    expect(note(page, "none")).to_be_visible()


def test_a_two_part_buttons_main_part_and_menu_are_separate(page, menus) -> None:
    """p.483's "primary button alongside an additional menu of options": the
    main part fires the button's own events, and an item fires its own."""
    open_module(page, menus)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(note(page, "saved")).to_be_visible()
    page.get_by_role("button", name="More options for Save").click()
    page.get_by_role("menuitem", name="Save as draft").click()
    expect(note(page, "draft")).to_be_visible()


def test_the_builder_wires_an_event_to_an_item(page, api) -> None:
    """The panel's Button type makes a menu with an item to rename, Add item
    adds one, and the Events panel's Which aims an event at it."""
    mod = Module(api, "Button menu panel")
    mod.define({
        "format": 2,
        "layout": layout({"btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}}}),
        "variables": {"v_note": {"id": "v_note", "kind": "string", "label": "Note"}},
        "events": {},
    })
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Button").first.click()
    page.get_by_test_id("button-type").select_option("menu")
    expect(page.get_by_test_id("button-item-i_1")).to_have_value("Option 1")
    page.get_by_test_id("button-item-i_1").fill("First")
    page.get_by_test_id("button-add-item").click()
    page.get_by_test_id("button-item-i_2").fill("Second")

    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    which = page.get_by_test_id("event-item")
    # A Menu button's own click is not offered: its items are the choices.
    expect(which.locator("option")).to_have_text(["First", "Second"])
    # And a new event names the first rather than none, which the server
    # would refuse as the Menu button's own click.
    save(page)
    first = [e["trigger"] for e in mod.definition()["events"].values()]
    assert first == [{"node": "btn", "on": "click", "item": "i_1"}], first
    which.select_option("i_2")
    # A second save: "saved" is already on the version line from the first,
    # so `save` returns before this one lands and the document is polled.
    save(page)
    eventually(lambda: [e["trigger"] for e in mod.definition()["events"].values()],
               lambda got: got == [{"node": "btn", "on": "click", "item": "i_2"}],
               what="the event aimed at the second item")
    document = mod.definition()
    assert [i["label"] for i in document["layout"]["btn"]["props"]["items"]] == ["First", "Second"]
