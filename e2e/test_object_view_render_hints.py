"""p.249-250's render hints that are about Object Views (§725;
`object-link-types` p.249-250).

> "Keywords - Enable to highlight this property in its own section when
> displaying properties in Object Views."
> "Long text - … Object Views will display this property's values in a more
> readable format."
> "Identifier - … Object Views won't format the property values as numbers"

Which section each property lands in is `object-properties.test.ts`. What
needs a browser is the standard Object View drawing them: a section of its
own, a block at a reading width with its line breaks kept, and a number shown
as stored rather than through its formatter.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from test_standard_object_view import open_first_object

ROWS = [
    {"id": "W1", "name": "Pump station", "tags": "pumps", "notes": "Line one.\nLine two.",
     "code": "1234567", "flow": "1234567", "region": "north"},
    {"id": "W2", "name": "Valve house", "tags": "valves", "notes": "Short.",
     "code": "7654321", "flow": "7654321", "region": "south"},
]
GROUPED = {"kind": "number", "grouping": True}


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Object view hints")
    mod.object_type_id = mod.object_type(
        columns=["id", "name", "tags", "notes", "code", "flow", "region"], rows=ROWS,
        key="id", title="name", types={"code": "integer", "flow": "integer"},
        visibility={"name": "prominent"},
        formats={"code": GROUPED, "flow": GROUPED},
        hints={"tags": ["keywords", "searchable"], "notes": ["long_text", "searchable"],
               "code": ["identifier", "searchable"]},
    )
    return mod


def test_keywords_get_a_section_of_their_own(page, module) -> None:
    open_first_object(page, module)
    section = page.get_by_test_id("sov-keywords")
    expect(section.get_by_role("heading", name="Keywords")).to_be_visible()
    expect(section.locator("[data-property='tags']")).to_contain_text("pumps")
    # Out of the table, not in both.
    table = page.get_by_test_id("sov-normal")
    expect(table.locator("[data-property='tags']")).to_have_count(0)
    expect(table.locator("[data-property='region']")).to_be_visible()


def test_long_text_is_a_block_that_keeps_its_line_breaks(page, module) -> None:
    open_first_object(page, module)
    block = page.locator("[data-testid='sov-long'][data-property='notes']")
    expect(block.get_by_role("heading", name="notes")).to_be_visible()
    text = block.locator(".sov-long-text")
    expect(text).to_have_css("white-space", "pre-wrap")
    # Two lines on screen, which is what pre-wrap is for.
    assert text.evaluate("el => el.getBoundingClientRect().height") > 30
    expect(page.get_by_test_id("sov-normal").locator("[data-property='notes']")).to_have_count(0)


def test_an_identifier_is_shown_as_stored_and_its_neighbour_is_formatted(page, module) -> None:
    """The same formatter on two integers: the one marked Identifier shows its
    digits, and the one not marked shows p.98's grouping - so the difference is
    the hint and not the formatter."""
    open_first_object(page, module)
    table = page.get_by_test_id("sov-normal")
    expect(table.locator("[data-property='code'] td")).to_have_text("1234567")
    expect(table.locator("[data-property='flow'] td")).to_have_text("1,234,567")
