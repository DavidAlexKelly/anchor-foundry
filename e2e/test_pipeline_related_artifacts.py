"""The Related artifacts helper on the lineage graph (§614; `data-lineage`
p.10, p.30).

> "The related artifacts helper displays artifacts directly linked to the
> nodes selected on the graph." (p.10)

> "The Related items icon will show a badge with the number of artifacts
> related to the selected dataset… Click on the node icon next to a resource
> to zoom in on the related dataset, or click the resource to open it in the
> corresponding application in a new tab. You can filter the list of related
> artifacts to include different item types and sort the list by oldest,
> newest, name, path, or last modified." (p.30)

Which modules and repositories are found, and who may see them, is
`apps/api/tests/test_related_artifacts.py`; the orders are
`related-artifacts.test.ts`. What needs a browser is the helper answering for
the selection as it changes, and its links and node buttons going somewhere.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from api import Module, object_set
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def related(api):
    board = Module(api, "Related artifacts")
    board.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ely"}],
                      key="id", title="town")
    document = {"format": 2, "layout": {}, "events": {}, "variables": {
        "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                  "object_set": object_set(board.object_type_id)}}}
    board.define(document)
    # A second module on the same type, made later, for p.30's orders.
    board.later = Module(api, "Related artifacts later", beside=board)
    board.later.define(document)
    # And one in a project of its own, which says so.
    board.elsewhere = Module(api, "Related elsewhere")
    board.elsewhere.define(document)
    return board




def card(page, kind: str, tag: str):
    return page.locator("button").filter(has_text=kind).filter(has_text=f"seed_{tag}").first


def test_the_selection_lists_the_modules_that_name_it(page, related) -> None:
    page.goto(f"{WEB_BASE}/{related.workspace_slug}/{related.project_slug}/pipeline")
    helper = page.get_by_test_id("related-artifacts")
    expect(card(page, "object type", related.tag)).to_be_visible(timeout=30000)
    expect(helper).to_have_count(0)

    # The dataset backs the type, but the module names the type, not it.
    card(page, "dataset", related.tag).click()
    expect(helper.get_by_test_id("related-empty")).to_have_text(
        "Nothing off the graph links to the selection.")
    expect(helper.get_by_test_id("related-count")).to_have_text("0")
    expect(helper.get_by_test_id("related-exclusions")).to_contain_text("no artifact is left out")

    card(page, "object type", related.tag).click()
    entry = helper.get_by_test_id(f"related-entry-workshop_module:{related.app_id}")
    expect(entry).to_be_visible()
    expect(helper.get_by_test_id("related-count")).to_have_text("3")
    expect(entry).not_to_contain_text(" in ")
    elsewhere = helper.get_by_test_id(f"related-entry-workshop_module:{related.elsewhere.app_id}")
    expect(elsewhere).to_contain_text(f"in Related elsewhere {related.elsewhere.tag}")
    link = entry.get_by_role("link", name=f"App {related.tag}")
    expect(link).to_have_attribute("href", f"/r/{related.resource_id}")
    expect(link).to_have_attribute("target", "_blank")

    # Filtered away by its item type, then back.
    helper.get_by_test_id("related-kind-workshop_module").click()
    expect(entry).to_have_count(0)
    expect(helper.get_by_test_id("related-empty")).to_have_text("Every item type is filtered out.")
    # The badge is how many are related, which a filter does not change.
    expect(helper.get_by_test_id("related-count")).to_have_text("3")
    helper.get_by_test_id("related-kind-workshop_module").click()
    expect(entry).to_be_visible()

    # p.30's orders: oldest and newest are the two modules either way round.
    made = [f"App {m.tag}" for m in (related, related.later, related.elsewhere)]
    links = helper.get_by_test_id("related-list").get_by_role("link")
    helper.get_by_test_id("related-sort").select_option("oldest")
    expect(links).to_have_text(made)
    helper.get_by_test_id("related-sort").select_option("newest")
    expect(links).to_have_text(made[::-1])


def test_a_node_button_zooms_to_the_node_it_links_to(page, related) -> None:
    page.goto(f"{WEB_BASE}/{related.workspace_slug}/{related.project_slug}/pipeline")
    type_card = card(page, "object type", related.tag)
    expect(type_card).to_be_visible(timeout=30000)
    # Select the dataset as well: Ctrl adds to a selection.
    type_card.click()
    card(page, "dataset", related.tag).click(modifiers=["Control"])
    # Zoomed in first, so "zoom in on" has a scale to put back.
    page.get_by_role("button", name="+", exact=True).click()
    expect(page.get_by_role("button", name="115%")).to_be_visible()
    zoom = page.get_by_test_id(f"related-entry-workshop_module:{related.app_id}").get_by_test_id(
        f"related-zoom-object_type:{related.object_type_id}")
    expect(zoom).to_be_visible()
    zoom.click()
    # Selected alone - the dataset let go - at full size, in the corner.
    expect(type_card).to_have_attribute("data-selected", "true")
    expect(card(page, "dataset", related.tag)).not_to_have_attribute("data-selected", "true")
    expect(page).to_have_url(re.compile(r"sel=object_type"))
    expect(page.get_by_role("button", name="100%")).to_be_visible()
    view = page.get_by_test_id("graph-viewport").bounding_box()
    at = type_card.bounding_box()
    assert abs(at["x"] - view["x"] - 40) <= 2, (at, view)
    assert abs(at["y"] - view["y"] - 40) <= 2, (at, view)
