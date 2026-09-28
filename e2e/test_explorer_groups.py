"""Object type groups on the Object Explorer (§618; `object-link-types` p.262).

> "Groups are searchable in Ontology Manager's Search bar and Search bar
> dialog. The table of object types in Ontology Manager supports displaying
> and filtering by group. Groups are also displayed on the Object Explorer
> home page." (p.262)

Which group the selection *is* is `object-type-groups.test.ts`. What needs a
browser is that opening a group ticks exactly its types and searches them,
that the row stays lit only while the ticks are its members, and that an
empty group is listed and cannot be opened.

**Groups are workspace-wide and `api.cleanup` does not sweep them**, so the
fixture deletes its own - a group left behind is in every later Explorer.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def grouped(api):
    ports = Module(api, "Explorer groups")
    ports.object_type(columns=["id", "name"], rows=[{"id": "P1", "name": "Dover"}],
                      key="id", title="name")
    ships = Module(api, "Explorer groups ships", beside=ports)
    ships.object_type(columns=["id", "name"], rows=[{"id": "V1", "name": "Endeavour"}],
                      key="id", title="name", slug=f"ship_{ports.tag}")
    ws = f"/workspaces/{ports.workspace_id}"
    tag = uuid.uuid4().hex[:6]
    made = []
    for key, members in (("harbour", [ports.object_type_id]), ("empty", [])):
        group = api.call("POST", f"{ws}/object-type-groups", {
            "api_name": f"{key}_{tag}", "display_name": f"{key.title()} {tag}",
            "description": ""})
        made.append(group)
        if members:
            api.call("PUT", f"{ws}/object-type-groups/{group['id']}/members",
                     {"object_type_ids": members})
    ports.ships = ships
    ports.harbour, ports.empty = made
    yield ports
    for group in made:
        try:
            api.call("DELETE", f"{ws}/object-type-groups/{group['id']}")
        except Exception:
            pass


def type_box(page, name: str):
    return page.locator(".ox-type", has_text=name).get_by_role("checkbox")


def test_opening_a_group_ticks_its_types_and_nothing_else(page, grouped) -> None:
    page.goto(f"{WEB_BASE}/{grouped.workspace_slug}/explore"
              f"?type={grouped.ships.object_type_id}")
    harbour = page.get_by_test_id(f"group-open-{grouped.harbour['api_name']}")
    expect(harbour).to_be_visible(timeout=30000)
    expect(harbour).to_contain_text("1 object type")
    expect(harbour).to_have_attribute("aria-pressed", "false")

    harbour.click()
    # Its one member, and the ship type ticked before is let go.
    expect(page).to_have_url(f"{WEB_BASE}/{grouped.workspace_slug}/explore"
                             f"?type={grouped.object_type_id}")
    expect(harbour).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_text("Dover").first).to_be_visible()

    # One more tick and the question is no longer "this group".
    page.goto(f"{WEB_BASE}/{grouped.workspace_slug}/explore")
    harbour.click()
    expect(harbour).to_have_attribute("aria-pressed", "true")
    # Clicked rather than `check()`ed: the box is drawn from the address bar,
    # so it turns on a render after the click rather than during it.
    ship = type_box(page, f"Ship {grouped.tag}").first
    ship.click()
    expect(ship).to_be_checked()
    expect(harbour).to_have_attribute("aria-pressed", "false")


def test_an_empty_group_is_listed_and_cannot_be_opened(page, grouped) -> None:
    page.goto(f"{WEB_BASE}/{grouped.workspace_slug}/explore")
    empty = page.get_by_test_id(f"group-open-{grouped.empty['api_name']}")
    expect(empty).to_be_visible(timeout=30000)
    expect(empty).to_contain_text("0 object types")
    expect(empty).to_be_disabled()
