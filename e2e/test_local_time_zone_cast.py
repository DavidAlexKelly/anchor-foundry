"""A cast in the viewer's local time zone (§596; `workshop` p.138-139).

> "The timezone used when casting the outputted date value may be defined
>  either using the user's local timezone, set statically via options in a
>  dropdown, or set dynamically using a string reference or variable."
>  (p.139)

The server evaluates variables, so the viewer's zone has to travel with the
resolve. Asserted with two browsers in two zones reading one module: the same
date's start of day is a different instant in each, and only the browser
could have told the server which.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import _signed_in, eventually, open_builder, open_module, settled


@pytest.fixture
def tokyo_page(browser, token: str, request):
    yield from _signed_in(browser, token, request, timezone_id="Asia/Tokyo")


@pytest.fixture
def new_york_page(browser, token: str, request):
    yield from _signed_in(browser, token, request, timezone_id="America/New_York")


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Local zone cast")
    mod.define({
        "format": 2,
        "layout": layout({"txt": {"resolvedName": "CanvasText", "props": {
            "tag": "p", "text": "start: [{{v_start}}]"}}}),
        "variables": {
            "v_day": {"id": "v_day", "kind": "date", "label": "Day", "default": "2024-06-26"},
            "v_start": {"id": "v_start", "kind": "timestamp", "label": "Start", "derivation": {
                "transform": "cast", "inputs": ["v_day"],
                "config": {"to": "timestamp", "timezone": "local"}}},
        },
        "events": {},
    })
    return mod


def test_p139_each_viewer_reads_their_own_zone(tokyo_page, new_york_page, module) -> None:
    open_module(tokyo_page, module)
    expect(tokyo_page.get_by_text("start: [2024-06-25T15:00:00Z]")).to_be_visible()
    open_module(new_york_page, module)
    expect(new_york_page.get_by_text("start: [2024-06-26T04:00:00Z]")).to_be_visible()


def test_the_panel_sets_a_cast_to_the_local_zone(page, api, module) -> None:
    open_builder(page, module)
    settled(page)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    page.locator(".vars-row", has_text="Start").first.click()
    local = page.get_by_test_id("cast-local-zone")
    expect(local).to_be_checked()
    expect(page.get_by_test_id("cast-timezone")).to_have_count(0)
    local.uncheck()
    page.get_by_test_id("cast-timezone").fill("Europe/Paris")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")
    assert module.definition()["variables"]["v_start"]["derivation"]["config"][
        "timezone"] == "Europe/Paris"
    local.check()
    expect(page.get_by_test_id("cast-timezone")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    # The first save's "saved" is still showing, so the document is what is
    # waited on.
    eventually(lambda: (page.title(), module.definition()["variables"]["v_start"]
                        ["derivation"]["config"].get("timezone"))[1],
               lambda zone: zone == "local", what="the cast saved in the local zone")
