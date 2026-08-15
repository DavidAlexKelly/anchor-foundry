"""Required properties, where a person meets them (`object-link-types` p.116).

    "Required properties are object type properties that must have a value. …
    This validation applies to data from the backing datasource and edits via
    actions." (p.116)

The rules are arithmetic and are tested in `apps/api/tests`. What needs a
browser is that both halves **reach somebody**: a sync that quietly counted
non-compliant rows and showed nothing would be the same as not counting them,
and an action refusal nobody can read is an action that appears to be broken.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import ApiError, Module
from conftest import WEB_BASE, eventually

# One row complies, two do not - so a count of 2 cannot come from an off-by-one
# and cannot come from "all of them".
SITES = (
    b"id,name,region\n"
    b"S1,North site,north\n"
    b"S2,,south\n"
    b"S3,,east\n"
)


@pytest.fixture(scope="module")
def module(api):
    """A type whose `name` is required, over a dataset where two rows lack it.

    Built directly rather than through `Module.object_type`, because the thing
    under test is the one flag that helper does not set.
    """
    mod = Module(api, "Required")
    dataset = api.upload_csv(f"{mod.base}/datasets/upload", f"sites_{mod.tag}", SITES)
    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"site_{mod.tag}",
            "display_name": f"Site {mod.tag}",
            "properties": [
                {"api_name": "name", "display_name": "Name", "data_type": "string",
                 "required": True},
                {"api_name": "region", "display_name": "Region", "data_type": "string"},
            ],
            "title_property": "name",
        },
    )
    mod.object_type_id = declared["id"]
    source = api.call(
        "POST", f"{mod.base}/object-type-sources",
        {
            "object_type_id": mod.object_type_id,
            "dataset_id": dataset["id"],
            "primary_key_column": "id",
            "column_mappings": {"name": "name", "region": "region"},
        },
    )
    mod.source_id = source["id"]

    # An action that can empty the required property, which is the write p.116
    # says must fail.
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {
            "api_name": f"rename_{mod.tag}",
            "display_name": f"Rename {mod.tag}",
            "object_type_id": mod.object_type_id,
            "editable_properties": ["name"],
        },
    )
    api.call(
        "PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "name", "display_name": "Name", "data_type": "string",
                 "required": False},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "name", "parameter": "name"}},
            ],
            "criteria": [],
        },
    )
    mod.action_id = action["id"]
    return mod


def test_a_sync_indexes_the_bad_rows_and_says_how_many(page, module):
    """p.116: the check "happens as backing datasources are indexed" and "the
    ontology modification itself will succeed". Both halves matter - the rows
    are there *and* the shortfall is on screen. A count nobody sees is the same
    as no count."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    # The one mapped source in this project - the type table above it has no
    # Sync button, which is what made a row filter the wrong tool here.
    sync = page.get_by_role("button", name="Sync")
    expect(sync).to_have_count(1, timeout=30000)
    sync.click()

    warning = page.get_by_test_id("missing-required")
    expect(warning).to_be_visible(timeout=30000)
    expect(warning).to_contain_text("2 rows with no name")
    # Indexed anyway, which is the half a refusal would have lost.
    expect(warning).to_contain_text("indexed anyway")


def test_every_row_is_there_despite_the_shortfall(page, module, api):
    """The sentence the warning above is making. If the sync had refused, the
    object type would be empty and unopenable, and the person who could fix the
    dataset would have nothing to look at."""
    synced = api.call(
        "POST", f"{module.base}/object-type-sources/{module.source_id}/sync", {}
    )
    assert synced["upserted"] == 3, synced
    assert synced["missing_required"] == {"name": 2}, synced


def test_an_action_that_would_empty_it_is_refused_where_somebody_can_read_it(
    page, module, api
):
    """p.116: "If you attempt to write a null or empty value to a property via
    an action, the action will fail to execute." The refusal has to name the
    property - one that named neither would leave somebody checking every field
    on the form."""
    api.call("POST", f"{module.base}/object-type-sources/{module.source_id}/sync", {})
    instances = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}/instances",
    )
    rows_ = instances["items"] if isinstance(instances, dict) and "items" in instances \
        else instances if isinstance(instances, list) else instances.get("results", [])
    complying = next(i for i in rows_ if i["properties"].get("name"))

    # **Refused as a 422 with its message**, the same shape a submission
    # criterion uses (`CriteriaRefusal`) - "this may not be applied, and here
    # is why" is one kind of answer, and a second shape for it would be a
    # second thing every caller has to handle.
    with pytest.raises(ApiError) as refusal:
        api.call(
            "POST", f"{module.base}/actions/{module.action_id}/execute",
            {"instance_id": complying["id"], "values": {"name": ""}},
        )
    assert "422" in str(refusal.value), refusal.value
    assert "'name' is required" in str(refusal.value), refusal.value

    # And the same action with a value goes through, so the refusal is about
    # the emptiness rather than about the action being broken.
    ok = api.call(
        "POST", f"{module.base}/actions/{module.action_id}/execute",
        {"instance_id": complying["id"], "values": {"name": "Renamed site"}},
    )
    assert ok["ok"] is True, ok


def test_the_ontology_manager_can_turn_it_on(page, module):
    """The flag has been displayed since the Ontology Manager was built and was
    not settable. A rule nobody can configure is a rule nobody has."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"site_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()
    checkbox = page.get_by_label("Property 1 required", exact=True)
    expect(checkbox).to_be_visible()
    expect(checkbox).to_be_checked()
