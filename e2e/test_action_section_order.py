"""p.124's one Form Content order (§589; `action-types` p.124).

> "Parameters and sections display in the form based on their order in this
>  Form Content section." (p.124)

A section placed at the top is drawn above the parameters no section holds,
where before §589 every section came after all of them.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import open_module
from test_action_definition_editor import open_editor
from test_action_sections import build, choose_the_ticket

BEFORE = """([first, second]) => {
  const a = document.querySelector(first);
  const b = document.querySelector(second);
  return !!(a && b && (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
}"""


def comes_before(page, first: str, second: str) -> bool:
    return page.evaluate(BEFORE, [first, second])


def test_a_section_placed_at_the_top_is_drawn_first(page, api) -> None:
    mod = build(api, "Section at the top", sections=[
        {"title": "Why", "parameters": ["reason"], "loose_before": 0},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Why'] [data-parameter='reason']")).to_be_visible()
    assert comes_before(page, "[data-section='Why']", "[data-parameter='status']")
    assert comes_before(page, "[data-parameter='status']", "[data-parameter='note']")


def test_a_section_placed_after_one_parameter_sits_between_them(page, api) -> None:
    mod = build(api, "Section in the middle", sections=[
        {"title": "Why", "parameters": ["reason"], "loose_before": 1},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Why'] [data-parameter='reason']")).to_be_visible()
    assert comes_before(page, "[data-parameter='status']", "[data-section='Why']")
    assert comes_before(page, "[data-section='Why']", "[data-parameter='note']")


def test_the_editor_places_a_section(page, api) -> None:
    mod = build(api, "Section placed in the editor", sections=[
        {"title": "Why", "parameters": ["reason"]},
    ])
    open_editor(page, mod)
    place = page.get_by_label("Section 1 place")
    expect(place).to_have_value("")
    expect(place.locator("option")).to_have_text(
        ["At the top", "After New status", "After the other parameters"])
    place.select_option(label="At the top")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    sections = api.call("GET", f"/workspaces/{mod.workspace_id}/action-types/"
                               f"{mod.action['id']}/sections")
    assert sections[0]["loose_before"] == 0
