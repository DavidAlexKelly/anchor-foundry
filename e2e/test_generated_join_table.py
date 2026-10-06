"""Generate join table in the link dialog (§562; `object-link-types` p.200).

    "The Generate join table option will create a dataset with the correct
     schema based on the primary keys of the two object types you have
     selected." (p.200)

The dialog asks for the two types first, since the columns are named for
them; the button then makes the dataset and fills in the dataset and both
columns. The API's half, including a pair written into it by an action, is
`apps/api/tests/test_generated_join_tables.py`.
"""
from __future__ import annotations

from playwright.sync_api import expect

from ontology_page import pick_type
from test_link_join_tables import open_objects, world  # noqa: F401


def test_generating_a_join_table_fills_the_link_in(page, api, world) -> None:
    tag = world.tag
    open_objects(page, world)
    page.get_by_role("button", name="New link type").click()
    dialog = page.get_by_role("dialog")
    page.get_by_test_id("link-name").fill(f"Serviced {tag}")
    dialog.get_by_label("Cardinality").select_option("many_to_many")
    page.get_by_test_id("link-joined-by").select_option("join_table")
    generate = page.get_by_test_id("link-generate-join-table")
    expect(generate).to_be_disabled()
    pick_type(page, "link-from-type", {"id": world.flights, "api_name": f"flight_{tag}"})
    pick_type(page, "link-to-type", {"id": world.aircraft, "api_name": f"aircraft_{tag}"})
    generate.click()
    expect(page.get_by_test_id("link-join-from-column")).to_have_value(f"flight_{tag}_key",
                                                                        timeout=15000)
    expect(page.get_by_test_id("link-join-to-column")).to_have_value(f"aircraft_{tag}_key")
    chosen = page.get_by_test_id("link-join-dataset")
    expect(chosen.locator("option:checked")).to_have_text(f"Serviced {tag} join table")
    dialog.get_by_role("button", name="Create link type").click()
    expect(dialog).to_have_count(0, timeout=15000)

    made = next(lt for lt in api.call("GET", f"/workspaces/{world.workspace_id}/link-types")
                if lt["display_name"] == f"Serviced {tag}")
    assert made["join_dataset_id"] == chosen_id(api, world, f"Serviced {tag} join table")
    expect(page.locator("tr", has_text=f"Serviced {tag}")).to_contain_text(
        f"join table: flight_{tag}_key ↔ aircraft_{tag}_key")


def chosen_id(api, world, name: str) -> str:
    return next(d["id"] for d in api.call("GET", f"{world.base}/datasets") if d["name"] == name)


def test_a_link_defined_without_a_join_can_generate_one(page, api, world) -> None:
    """p.200 says "for new link types"; a many-to-many link defined without a
    join has no pairs either, so its Set join dialog offers the same."""
    tag = world.tag
    api.call("POST", f"/workspaces/{world.workspace_id}/link-types", {
        "api_name": f"inspected_{tag}", "display_name": f"Inspected {tag}",
        "from_type_id": world.flights, "to_type_id": world.aircraft,
        "cardinality": "many_to_many"})
    open_objects(page, world)
    row = page.locator("tr", has_text=f"Inspected {tag}")
    row.get_by_role("button", name="Set join").click()
    dialog = page.get_by_role("dialog")
    page.get_by_test_id("link-joined-by").select_option("join_table")
    page.get_by_test_id("link-generate-join-table").click()
    expect(page.get_by_test_id("link-join-to-column")).to_have_value(f"aircraft_{tag}_key",
                                                                      timeout=15000)
    dialog.locator("button[type=submit]").click()
    expect(dialog).to_have_count(0, timeout=15000)
    expect(row).to_contain_text(f"join table: flight_{tag}_key ↔ aircraft_{tag}_key")
