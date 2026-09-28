"""Object-backed link types, defined in the dialog and followed from an object
(§667; `object-link-types` p.197, p.199).

    "Object-backed link types expand on many-to-one cardinality link types,
     providing first class support for object types as a link type storage
     solution." (p.197)

    "Select a link to view the link's backing object properties." (p.199)

p.199's own example: a flight manifest names an aircraft and a flight, and
says who flew it. The API's half is `apps/api/tests/test_link_backing.py`.
What needs a browser is the dialog offering the backing type and p.199's two
prerequisite links, and an object's linked objects arriving with the backing
objects that link them.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import pick_type
from test_link_join_tables import open_object

AIRCRAFT = [{"id": "A1", "tail": "G-AAAA"}, {"id": "A2", "tail": "G-BBBB"}]
FLIGHTS = [{"id": "F1", "route": "LHR-JFK"}, {"id": "F2", "route": "JFK-SFO"}, {"id": "F3", "route": "SFO-LHR"}]
MANIFESTS = [{"id": "M1", "aircraft": "A1", "flight": "F1", "pilot": "Ada"},
             {"id": "M2", "aircraft": "A1", "flight": "F2", "pilot": "Grace"},
             {"id": "M3", "aircraft": "A2", "flight": "F3", "pilot": "Alan"}]


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Backed links")
    mod.aircraft = mod.object_type(columns=["id", "tail"], rows=AIRCRAFT, key="id", title="tail",
                                   slug=f"aircraft_{mod.tag}")
    mod.flights = mod.object_type(columns=["id", "route"], rows=FLIGHTS, key="id", title="route",
                                  slug=f"flight_{mod.tag}")
    mod.manifests = mod.object_type(columns=["id", "aircraft", "flight", "pilot"], rows=MANIFESTS, key="id",
                                    title="pilot", slug=f"manifest_{mod.tag}")
    link = lambda name, to, prop: api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {  # noqa: E731
        "api_name": f"{name}_{mod.tag}", "display_name": f"Manifest {name}", "from_type_id": mod.manifests,
        "to_type_id": to, "cardinality": "one_to_many", "from_property": prop,
        "to_property": "$primary_key"})["id"]
    # p.199's prerequisites: a many-to-one link from the manifest to each end.
    mod.to_aircraft = link("aircraft", mod.aircraft, "aircraft")
    mod.to_flight = link("flight", mod.flights, "flight")
    return mod


def open_objects(page, world) -> None:
    page.goto(f"{WEB_BASE}/{world.workspace_slug}/{world.project_slug}/objects")
    expect(page.get_by_test_id("type-search")).to_be_visible(timeout=30000)


def test_the_dialog_backs_a_link_with_an_object_type(page, api, world) -> None:
    open_objects(page, world)
    page.get_by_role("button", name="New link type").click()
    dialog = page.get_by_role("dialog")
    dialog.get_by_label("Name").fill(f"Flew {world.tag}")
    pick_type(page, "link-from-type", {"id": world.aircraft, "api_name": f"aircraft_{world.tag}"})
    pick_type(page, "link-to-type", {"id": world.flights, "api_name": f"flight_{world.tag}"})
    page.get_by_test_id("link-joined-by").select_option("backing")
    expect(dialog.get_by_text("Choose the backing object type.")).to_be_visible()
    expect(dialog.get_by_role("button", name="Create link type")).to_be_disabled()
    pick_type(page, "link-backing-type", {"id": world.manifests, "api_name": f"manifest_{world.tag}"})
    # Each end is offered the links joining it and the backing type on a pair.
    expect(page.get_by_test_id("link-backing-from").locator("option")).to_have_text(
        ["Choose a link…", "Manifest aircraft"])
    page.get_by_test_id("link-backing-from").select_option(world.to_aircraft)
    page.get_by_test_id("link-backing-to").select_option(world.to_flight)
    dialog.get_by_role("button", name="Create link type").click()
    expect(dialog).to_have_count(0, timeout=15000)
    made = next(lt for lt in api.call("GET", f"/workspaces/{world.workspace_id}/link-types")
                if lt["display_name"] == f"Flew {world.tag}")
    assert (made["backing_type_id"], made["backing_from_link_id"], made["backing_to_link_id"]) == (
        world.manifests, world.to_aircraft, world.to_flight)
    expect(page.locator("tr", has_text=f"Flew {world.tag}")).to_contain_text("backed by")


def test_an_object_lists_what_its_backing_objects_link_it_to(page, api, world) -> None:
    """From aircraft A1, its two flights, each with the manifest that links it
    and who flew it; and no Explorer link, which could only say a match."""
    api.call("POST", f"/workspaces/{world.workspace_id}/link-types", {
        "api_name": f"flown_{world.tag}", "display_name": "Flown", "from_type_id": world.aircraft,
        "to_type_id": world.flights, "cardinality": "many_to_many", "from_side_name": "Aircraft",
        "to_side_name": "Flights", "backing_type_id": world.manifests,
        "backing_from_link_id": world.to_aircraft, "backing_to_link_id": world.to_flight})
    open_object(page, world, world.aircraft, "G-AAAA", len(AIRCRAFT))
    group = page.locator("section", has_text="Flights").filter(has_text="through")
    expect(group.first).to_contain_text("2 objects")
    expect(group.first).to_contain_text("LHR-JFK")
    backing = group.first.get_by_test_id("link-backing")
    expect(backing).to_have_count(2)
    expect(backing.filter(has_text="M1")).to_contain_text("pilot Ada")
    expect(backing.filter(has_text="M2")).to_contain_text("pilot Grace")
    expect(group.first.locator("[data-testid^='link-subset-']")).to_have_count(0)
