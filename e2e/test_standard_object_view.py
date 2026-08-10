"""The standard Object View (parity `ontology.md` §4.1; Foundry `object-views` p.10–11).

    "The standard Object View matches the object type's configuration by
     spotlighting prominent properties in either a dedicated table or in other
     visual formats if the property's base type is a time series, media
     reference, or geospatial property. Normal properties are displayed in a
     regular table, and hidden properties are not visible." (p.10)

**Generated, never configured** — the view *is* the object type's
configuration, read back. So the whole of this file is one question asked three
ways: does changing a property's visibility change what an object looks like?

`ontology.md` §8 asks for exactly that: "a hidden property is absent from the
standard Object View… Mutation: mark it normal, and both change."

**Two of Foundry's four renderings are not testable here and it is not this
view's fault**: time series and media reference are property types we do not
have (`ontology.md` §1.1). Geopoint → Map is, and is asserted.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually, no_console_errors

ROWS = [
    {"id": "S1", "name": "Alpha site", "region": "north",
     "where": "51.5,-0.12", "internal_note": "DO NOT SHOW"},
    {"id": "S2", "name": "Beta site", "region": "south",
     "where": "53.4,-2.98", "internal_note": "DO NOT SHOW"},
]


@pytest.fixture(scope="module")
def module(api):
    """One object type with one property of each visibility, plus a prominent
    geopoint — so every branch of the view has something to draw."""
    mod = Module(api, "Standard object view")
    mod.object_type(
        columns=["id", "name", "region", "where", "internal_note"],
        rows=ROWS,
        key="id",
        title="name",
        types={"where": "geopoint"},
        visibility={
            "name": "prominent",
            "where": "prominent",
            "internal_note": "hidden",
            # `region` is left at the default, which is the third case.
        },
    )
    return mod


def open_first_object(page, module):
    """Open the Explorer **filtered to this fixture's own type**, and click in.

    The Explorer is workspace-wide and this dev database carries every object
    every previous test run ever created — over two thousand of them. Clicking
    "the first row" without a filter opens somebody else's object, and the
    failure reads as "the view did not render" rather than "the test opened the
    wrong thing". `?type=` is the same parameter the Explorer writes itself.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    # **Not `conftest.settled`**, which waits for a canvas widget — the Explorer
    # has none, so it timed out before any of this ran and every assertion below
    # reported "the view is not here" about code that had never executed. The
    # same trap `test_resource_filter.py` documents for the resource browser.
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(ROWS),
               what="this type's objects, and only this type's")
    # The row's own "Explore" button, not the row: the row is not a click
    # target, and clicking it silently does nothing.
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()


def test_the_view_is_generated_for_an_object_type_nobody_configured(page, module):
    """There is no builder and no saved document — the object type is the whole
    input, so a type that exists has a view."""
    open_first_object(page, module)
    view = page.get_by_test_id("standard-object-view")
    expect(view).to_contain_text("Alpha site")  # the title property's value
    assert not no_console_errors(page)


def test_prominent_properties_are_surfaced_above_the_table(page, module):
    """p.10: "Foundry surfaces prominent properties at the top of the standard
    Object View to provide immediate context"."""
    open_first_object(page, module)
    cards = page.get_by_test_id("sov-prominent")
    expect(cards).to_be_visible()
    expect(cards.locator("[data-property='name']")).to_be_visible()
    expect(cards.locator("[data-property='where']")).to_be_visible()

    # Above, not merely present — the ordering is the point of "surfaced".
    top = cards.bounding_box()
    table = page.get_by_test_id("sov-normal").bounding_box()
    assert top["y"] < table["y"], (top, table)


def test_a_normal_property_is_in_the_table_not_a_card(page, module):
    open_first_object(page, module)
    expect(page.get_by_test_id("sov-normal").locator("[data-property='region']")).to_be_visible()
    expect(page.get_by_test_id("sov-prominent").locator("[data-property='region']")).to_have_count(0)


def test_a_hidden_property_is_nowhere_in_the_view(page, module):
    """p.10: "hidden properties are not visible". Asserted on the *value*
    rather than the property name, because the value is what would leak."""
    open_first_object(page, module)
    view = page.get_by_test_id("standard-object-view")
    # Presence before absence: the view has drawn, so "no DO NOT SHOW" is about
    # the rule rather than about an empty panel.
    expect(view).to_contain_text("Alpha site")
    expect(view).not_to_contain_text("DO NOT SHOW")
    expect(view.locator("[data-property='internal_note']")).to_have_count(0)


def test_a_prominent_geopoint_renders_a_map(page, module):
    """p.11: "Objects with prominent geohash, geoshape, or geotemporal series
    reference properties will render on a Map."

    Ours is geopoint. Asserting the map *drew* rather than that its container
    exists — an empty box with the right test id would pass the weaker check.
    """
    open_first_object(page, module)
    holder = page.get_by_test_id("sov-map-where")
    expect(holder).to_be_visible()
    eventually(lambda: holder.locator("svg").count(), lambda n: n >= 1,
               what="the map drawn for the prominent geopoint")


def test_the_linked_objects_section_sits_under_the_view(page, module):
    """p.11 makes the Linked objects component part of the standard view rather
    than a separate screen, which is why the dialog now leads with the object."""
    open_first_object(page, module)
    view = page.get_by_test_id("standard-object-view").bounding_box()
    links = page.get_by_text("Linked objects", exact=True).bounding_box()
    assert view["y"] < links["y"], (view, links)
