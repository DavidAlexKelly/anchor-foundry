"""A many-to-many link backed by a join table dataset, defined in the dialog
and followed from an object (§552; `object-link-types` p.200, p.197).

    "Join table dataset: For "many-to-many" cardinality link types. This option
     allows you to use a join table dataset to back the link." (p.197)

p.200's own example: flight F2 was flown by two aircraft, which no foreign key
can say. The API's half - the checks, both directions, set hops and filters -
is `apps/api/tests/test_link_join_tables.py`. What needs a browser is the
dialog offering the join table only where p.197 does, reading its columns off
the dataset, and the object's linked objects arriving through it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import pick_type

AIRCRAFT = [{"id": "A1", "tail": "G-AAAA"}, {"id": "A2", "tail": "G-BBBB"},
            {"id": "A3", "tail": "G-CCCC"}]
FLIGHTS = [{"id": "F1", "route": "LHR-JFK"}, {"id": "F2", "route": "JFK-SFO"},
           {"id": "F3", "route": "SFO-LHR"}]
PAIRS = b"flight,aircraft\nF1,A1\nF2,A1\nF2,A2\nF3,A2\n"


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Join tables")
    mod.aircraft = mod.object_type(columns=["id", "tail"], rows=AIRCRAFT, key="id",
                                   title="tail", slug=f"aircraft_{mod.tag}")
    mod.flights = mod.object_type(columns=["id", "route"], rows=FLIGHTS, key="id",
                                  title="route", slug=f"flight_{mod.tag}")
    mod.pairs = api.upload_csv(f"{mod.base}/datasets/upload", f"flown_{mod.tag}", PAIRS)
    return mod


def open_objects(page, world) -> None:
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_test_id("type-search")).to_be_visible(timeout=30000)


def test_the_dialog_backs_a_many_to_many_link_with_a_join_table(page, api, world) -> None:
    open_objects(page, world)
    page.get_by_role("button", name="New link type").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill(f"Flown by {world.tag}")
    pick_type(page, "link-from-type", {"id": world.flights, "api_name": f"flight_{world.tag}"})
    pick_type(page, "link-to-type", {"id": world.aircraft, "api_name": f"aircraft_{world.tag}"})
    # p.197: a join table is a many-to-many link's, so it is offered for no other.
    expect(page.get_by_test_id("link-joined-by")).to_have_count(0)
    dialog.get_by_label("Cardinality").select_option("many_to_many")
    page.get_by_test_id("link-joined-by").select_option("join_table")
    page.get_by_test_id("link-join-dataset").select_option(world.pairs["id"])
    # The columns are the dataset's own, read off its schema.
    from_column = page.get_by_test_id("link-join-from-column")
    expect(from_column.locator("option[value='aircraft']")).to_be_attached()
    from_column.select_option("flight")
    # p.200: "A column can only be mapped to one primary key."
    page.get_by_test_id("link-join-to-column").select_option("flight")
    expect(dialog.get_by_text("Each end needs its own column.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Create link type")).to_be_disabled()
    page.get_by_test_id("link-join-to-column").select_option("aircraft")
    dialog.get_by_role("button", name="Create link type").click()
    expect(dialog).to_have_count(0, timeout=15000)

    made = next(lt for lt in api.call("GET", f"/workspaces/{world.workspace_id}/link-types")
                if lt["display_name"] == f"Flown by {world.tag}")
    assert (made["cardinality"], made["join_dataset_id"], made["join_from_column"],
            made["join_to_column"]) == ("many_to_many", world.pairs["id"], "flight", "aircraft")
    row = page.locator("tr", has_text=f"Flown by {world.tag}")
    expect(row).to_contain_text("join table: flight ↔ aircraft")


def open_object(page, world, type_id: str, title: str, count: int) -> None:
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/explore?type={type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == count, what="this type's objects")
    rows.filter(has_text=title).first.get_by_role("button", name="Explore").click()
    expect(page.get_by_text("Linked objects", exact=True)).to_be_visible()


def test_an_object_lists_what_the_join_table_pairs_it_with(page, api, world) -> None:
    """From the flight two aircraft flew, both of them; and no Explorer link,
    which could only say a property match - the wrong objects here."""
    api.call("POST", f"/workspaces/{world.workspace_id}/link-types", {
        "api_name": f"crewed_{world.tag}", "display_name": "Crewed",
        "from_type_id": world.flights, "to_type_id": world.aircraft,
        "cardinality": "many_to_many", "join_dataset_id": world.pairs["id"],
        "join_from_column": "flight", "join_to_column": "aircraft",
        "from_side_name": "Flights", "to_side_name": "Aircraft"})
    open_object(page, world, world.flights, "JFK-SFO", len(FLIGHTS))
    group = page.locator("section", has_text="through a join table").filter(has_text="Aircraft")
    expect(group.first).to_contain_text("2 objects")
    expect(group.first).to_contain_text("G-AAAA")
    expect(group.first).to_contain_text("G-BBBB")
    expect(group.first.locator("[data-testid^='link-subset-']")).to_have_count(0)
