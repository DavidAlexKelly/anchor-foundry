"""Bulk status editing in the Ontology Manager (parity
`docs/parity/ontology.md` §1.3; Foundry `object-link-types` p.258).

> "Statuses across object types can also be edited in bulk from the home page
> object view page by selecting the checkboxes of the object types to edit and
> selecting the `Edit status` button." (p.258)

**The claim that needs a browser is that the option is an option.** p.258's
"also apply the `active` status to all properties" is a checkbox, and §170's
whole propagation asymmetry rests on it being unticked by default - a version
that always raised would look identical in every test that ticks it.

The rest is what a bulk control has to do to be usable: appear only when
something is selected, say how many, and go away once it has acted.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = [{"id": "R1", "name": "Ada"}, {"id": "R2", "name": "Grace"}]


@pytest.fixture(scope="module")
def module(api):
    things = Module(api, "BulkStatus")
    things.object_type(columns=["id", "name"], rows=ROWS, key="id", title="name")
    return things


@pytest.fixture
def second_type(api, module):
    """A second type, so "bulk" means more than one."""
    tag = uuid.uuid4().hex[:6]
    return api.call(
        "POST", f"/workspaces/{module.workspace_id}/object-types",
        {
            "api_name": f"other_{tag}", "display_name": f"Other {tag}",
            "properties": [
                {"api_name": "name", "data_type": "string"},
                {"api_name": "code", "data_type": "string"},
            ],
            "title_property": "name",
        },
    )


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_role("heading", name="Groups")).to_be_visible(timeout=30000)


def select(page, api_name: str) -> None:
    page.get_by_test_id(f"select-{api_name}").check()


def read_type(api, module, type_id: str) -> dict:
    return api.call(
        "GET", f"/workspaces/{module.workspace_id}/object-types/{type_id}"
    )


def test_the_bar_appears_only_once_something_is_selected(
    page, module, second_type
) -> None:
    """A control that can act on nothing is a control that does nothing."""
    open_objects(page, module)
    expect(page.get_by_test_id("bulk-status-bar")).to_have_count(0)

    select(page, f"seed_{module.tag}")
    expect(page.get_by_test_id("bulk-status-bar")).to_be_visible()
    expect(page.get_by_test_id("bulk-selected-count")).to_contain_text("1 selected")

    select(page, second_type["api_name"])
    expect(page.get_by_test_id("bulk-selected-count")).to_contain_text("2 selected")


def test_two_types_change_together(page, module, second_type, api) -> None:
    """p.258's Edit status button, over the checkboxes somebody ticked."""
    open_objects(page, module)
    select(page, f"seed_{module.tag}")
    select(page, second_type["api_name"])
    page.get_by_test_id("bulk-status-select").select_option("example")
    with page.expect_response(
        lambda r: "bulk-status" in r.url and r.request.method == "POST"
    ) as saved:
        page.get_by_test_id("bulk-status-apply").click()
    assert saved.value.ok, saved.value.text()

    assert read_type(api, module, module.object_type_id)["status"] == "example"
    assert read_type(api, module, second_type["id"])["status"] == "example"

    # And the bar goes away with the selection it was about.
    expect(page.get_by_test_id("bulk-status-bar")).to_have_count(0, timeout=15000)


def test_the_option_is_off_until_it_is_ticked(page, module, second_type, api) -> None:
    """**The claim §170's asymmetry rests on.**

    p.258 offers applying the type's status to all its properties as an
    *option*. A version that always raised would pass every test that ticks
    the box, so this one deliberately does not tick it.
    """
    open_objects(page, module)
    select(page, second_type["api_name"])
    page.get_by_test_id("bulk-status-select").select_option("active")
    expect(page.get_by_test_id("bulk-apply-to-properties")).not_to_be_checked()
    with page.expect_response(
        lambda r: "bulk-status" in r.url and r.request.method == "POST"
    ) as saved:
        page.get_by_test_id("bulk-status-apply").click()
    assert saved.value.ok, saved.value.text()

    detail = read_type(api, module, second_type["id"])
    assert detail["status"] == "active"
    assert {p["status"] for p in detail["properties"]} == {"experimental"}, detail


def test_ticking_the_option_raises_every_property(
    page, module, second_type, api
) -> None:
    """And the other half: p.258's option, taken."""
    open_objects(page, module)
    select(page, second_type["api_name"])
    page.get_by_test_id("bulk-status-select").select_option("active")
    page.get_by_test_id("bulk-apply-to-properties").check()
    with page.expect_response(
        lambda r: "bulk-status" in r.url and r.request.method == "POST"
    ) as saved:
        page.get_by_test_id("bulk-status-apply").click()
    assert saved.value.ok, saved.value.text()

    detail = read_type(api, module, second_type["id"])
    assert {p["status"] for p in detail["properties"]} == {"active"}, detail


def test_clear_drops_the_selection_without_changing_anything(
    page, module, second_type, api
) -> None:
    """The way out of a selection somebody made by accident."""
    before = read_type(api, module, second_type["id"])["status"]
    open_objects(page, module)
    select(page, second_type["api_name"])
    page.get_by_test_id("bulk-status-clear").click()

    expect(page.get_by_test_id("bulk-status-bar")).to_have_count(0)
    assert read_type(api, module, second_type["id"])["status"] == before
