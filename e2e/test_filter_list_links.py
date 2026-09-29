"""p.451's filters on linked objects in a Filter List (§545).

> "To filter on linked object properties, select a link within the Filter on a
> link section of the Add filter... dropdown. … The Has Link filter is unique
> to linked object filters and filters on the presence of a link. For example:
> "Filter for all Tasks that have a link to Person."" (p.451)

The set is employees, and the link is the issues each has raised. Linus has
raised none, so Has link has someone to leave out; Ada and Grace have two
each, and a filter on the issues' titles picks between them.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, save, settled

EMPLOYEES = [{"id": "E1", "name": "Ada"}, {"id": "E2", "name": "Grace"},
             {"id": "E3", "name": "Linus"}]
ISSUES = [
    {"id": "I1", "employee_id": "E1", "title": "Printer jam"},
    {"id": "I2", "employee_id": "E1", "title": "VPN down"},
    {"id": "I3", "employee_id": "E2", "title": "Printer toner"},
    {"id": "I4", "employee_id": "E2", "title": "Laptop fan"},
]


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Filter list links")
    tag = uuid.uuid4().hex[:8]
    mod.employee_type = mod.object_type(
        columns=["id", "name"], rows=EMPLOYEES, key="id", title="name", slug=f"emp_{tag}")
    mod.issue_type = mod.object_type(
        columns=["id", "employee_id", "title"], rows=ISSUES, key="id", title="title",
        slug=f"iss_{tag}")
    mod.link = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/link-types",
        {"api_name": f"raised_by_{tag}", "display_name": "Raised by",
         "from_type_id": mod.issue_type, "to_type_id": mod.employee_type,
         "cardinality": "one_to_many",
         "from_property": "employee_id", "to_property": "$primary_key"},
    )["id"]
    return mod


def build(api, world, name: str, filters: list[dict]) -> Module:
    mod = Module(api, name, beside=world)
    mod.define({
        "format": 2,
        "layout": layout({
            "fl": {"resolvedName": "CanvasFilterList", "props": {
                "objectSetVariable": "v_all", "variable": "v_clauses", "title": "People",
                "filters": filters}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_picked", "columns": "id,name", "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Everyone",
                      "object_set": object_set(world.employee_type)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Filters"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Narrowed",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_all", "v_clauses"]}},
        },
        "events": {},
    })
    return mod


def linked(world, property: str = "", component: str = "histogram", fid: str = "f_1") -> dict:
    return {"id": fid, "property": property, "component": component,
            "link": world.link, "linkTo": world.issue_type}


def rows_are(page, ids: list[str], what: str) -> None:
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == sorted(ids), what=what)


def test_has_link_keeps_the_people_who_have_raised_an_issue(page, api, world) -> None:
    mod = build(api, world, "Links has link", [linked(world)])
    open_module(page, mod)
    rows_are(page, ["E1", "E2", "E3"], "everyone first")
    box = page.get_by_test_id("filter-has-link-f_1")
    box.check()
    rows_are(page, ["E1", "E2"], "the people with an issue")
    box.uncheck()
    rows_are(page, ["E1", "E2", "E3"], "everyone again")


def test_a_linked_property_filters_by_the_linked_objects(page, api, world) -> None:
    mod = build(api, world, "Links values", [linked(world, "title", "keyword")])
    open_module(page, mod)
    rows_are(page, ["E1", "E2", "E3"], "everyone first")
    page.get_by_role("searchbox").fill("VPN")
    rows_are(page, ["E1"], "the person whose issue is the VPN")
    page.get_by_role("searchbox").fill("Printer")
    rows_are(page, ["E1", "E2"], "both printer people")
    page.get_by_role("searchbox").fill("")
    rows_are(page, ["E1", "E2", "E3"], "everyone once it is cleared")


def test_a_linked_histogram_counts_the_linked_objects(page, api, world) -> None:
    mod = build(api, world, "Links histogram", [linked(world, "title", "histogram")])
    open_module(page, mod)
    # The issues' titles, from the linked type's own objects.
    bars = page.locator(".canvas-filter-bar")
    expect(bars).to_have_count(4)
    bars.filter(has_text="Laptop fan").get_by_role("checkbox").check()
    rows_are(page, ["E2"], "Grace, whose laptop fan it is")


def test_has_link_and_a_value_hold_together(page, api, world) -> None:
    mod = build(api, world, "Links both", [
        linked(world), linked(world, "title", "keyword", fid="f_2")])
    open_module(page, mod)
    page.get_by_test_id("filter-has-link-f_1").check()
    page.get_by_role("searchbox").fill("Laptop")
    rows_are(page, ["E2"], "Grace")
    # Clearing the value leaves the Has link somebody ticked.
    page.get_by_role("searchbox").fill("")
    rows_are(page, ["E1", "E2"], "the people with an issue, still")
    expect(page.get_by_test_id("filter-has-link-f_1")).to_be_checked()


def test_the_panel_adds_a_filter_on_a_link(page, api, world) -> None:
    mod = build(api, world, "Links panel", [])
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="People").first.click()
    add = page.get_by_test_id("filter-add")
    # p.451's "Filter on a link section of the Add filter... dropdown".
    expect(add.locator("optgroup[label='Filter on a link'] option")).to_have_count(1)
    add.select_option(label=add.locator("optgroup option").first.inner_text())
    page.get_by_test_id("filter-linked-property-f_1").select_option("title")
    page.get_by_test_id("filter-component-f_1").select_option("keyword")
    save(page)
    filters = mod.definition()["layout"]["fl"]["props"]["filters"]
    assert filters == [linked(world, "title", "keyword")], filters


# ---- p.451's display options (§546) -----------------------------------------

def build_shown(api, world, name: str, filters: list[dict], **props) -> Module:
    mod = build(api, world, name, filters)
    definition = mod.definition()
    definition["layout"]["fl"]["props"].update(props)
    mod.define(definition)
    return mod


def test_grouped_linked_filters_sit_in_a_section_with_their_count(page, api, world) -> None:
    mod = build_shown(api, world, "Links grouped",
                      [linked(world), linked(world, "title", "keyword", fid="f_2")],
                      linkDisplay="grouped")
    open_module(page, mod)
    group = page.get_by_test_id("filter-link-group")
    expect(group).to_have_count(1)
    # Both of the link's filters in it, and the linked issues counted: four,
    # every issue being linked to somebody in the set.
    expect(group.get_by_test_id("filter-has-link-f_1")).to_be_visible()
    expect(group.get_by_role("searchbox")).to_be_visible()
    expect(group.get_by_test_id("filter-link-count")).to_have_text("4")
    group.get_by_test_id("filter-has-link-f_1").check()
    rows_are(page, ["E1", "E2"], "the people with an issue")


def test_the_count_is_of_the_objects_linked_to_the_set(page, api, world) -> None:
    """Over Ada alone, her two issues - not the four the linked type holds."""
    mod = build_shown(api, world, "Links grouped Ada", [linked(world)], linkDisplay="grouped")
    definition = mod.definition()
    definition["variables"]["v_all"]["object_set"]["filters"] = [
        {"property": "name", "op": "eq", "value": "Ada"}]
    mod.define(definition)
    open_module(page, mod)
    expect(page.get_by_test_id("filter-link-count")).to_have_text("2")


def test_a_collapsed_group_starts_closed(page, api, world) -> None:
    mod = build_shown(api, world, "Links collapsed", [linked(world)],
                      linkDisplay="grouped", collapseLinked=True)
    open_module(page, mod)
    group = page.get_by_test_id("filter-link-group")
    expect(group).not_to_have_attribute("open", "")
    expect(page.get_by_test_id("filter-has-link-f_1")).not_to_be_visible()
    group.locator("summary").click()
    expect(page.get_by_test_id("filter-has-link-f_1")).to_be_visible()


def test_inline_linked_filters_have_no_section(page, api, world) -> None:
    mod = build_shown(api, world, "Links inline", [linked(world)])
    open_module(page, mod)
    expect(page.get_by_test_id("filter-has-link-f_1")).to_be_visible()
    expect(page.get_by_test_id("filter-link-group")).to_have_count(0)


def test_the_panel_groups_and_collapses_linked_filters(page, api, world) -> None:
    mod = build(api, world, "Links display panel", [linked(world)])
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row", has_text="People").first.click()
    expect(page.get_by_test_id("filter-collapse-linked")).to_have_count(0)
    page.get_by_test_id("filter-link-display").select_option("grouped")
    page.get_by_test_id("filter-collapse-linked").check()
    save(page)
    props = mod.definition()["layout"]["fl"]["props"]
    assert (props["linkDisplay"], props["collapseLinked"]) == ("grouped", True), props
