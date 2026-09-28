"""p.330's Interactive metric (§527; parity `workshop.md` Metric Card row).

> "Interactive metric: An optional configuration to trigger a command,
> action, or event upon card selection. Defaults to No interaction." (p.330)

An event wired to a card's `click` in the Events panel, where it reads "Card
selected". What needs a browser: the wired card is a control a click and a
key both press, an unwired one is not a control at all (p.330's default), and
the builder offers the trigger by that name.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, save, settled


def card(label: str) -> dict:
    return {"resolvedName": "CanvasMetricCard", "props": {"label": label}}


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Interactive metric")
    mod.define({
        "format": 2,
        "layout": layout({
            "live": card("Open cases"),
            "still": card("Closed cases"),
            "note": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {
            "v_note": {"id": "v_note", "kind": "string", "label": "Note", "default": "none"},
        },
        "events": {
            "e_live": {"id": "e_live", "trigger": {"node": "live", "on": "click"},
                       "effects": [{"type": "set_variable",
                                    "config": {"variable": "v_note", "value": "open"}}]},
        },
    })
    return mod


def test_a_wired_card_fires_its_event_when_selected(page, module) -> None:
    open_module(page, module)
    expect(page.get_by_text("NOTE=none")).to_be_visible()
    page.get_by_role("button", name="Open cases").click()
    expect(page.get_by_text("NOTE=open")).to_be_visible()


def test_a_wired_card_is_pressed_from_the_keyboard_too(page, module) -> None:
    open_module(page, module)
    live = page.get_by_role("button", name="Open cases")
    live.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_text("NOTE=open")).to_be_visible()


def test_a_card_with_nothing_wired_is_not_a_control(page, module) -> None:
    """p.330: "Defaults to No interaction"."""
    open_module(page, module)
    expect(page.get_by_role("button", name="Closed cases")).to_have_count(0)
    page.get_by_text("Closed cases").click()
    expect(page.get_by_text("NOTE=none")).to_be_visible()


def test_the_builder_offers_card_selected(page, api) -> None:
    mod = Module(api, "Interactive metric panel")
    mod.define({
        "format": 2,
        "layout": layout({"live": card("Open cases")}),
        "variables": {}, "events": {},
    })
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="Metric card").first.click()
    page.get_by_role("button", name="Events (0)").click()
    page.get_by_role("button", name="New event").click()
    expect(page.get_by_text("Card selected").first).to_be_visible()
    save(page)
    assert [e["trigger"] for e in mod.definition()["events"].values()] == [
        {"node": "live", "on": "click"}]
