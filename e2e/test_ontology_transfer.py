"""p.66's Export and Import, on the screen (§327; `ontology-manager` p.65-67).

    "You can export your Ontology working state by selecting the Advanced
     settings page from the application's home page and then selecting
     Export." (p.66)

    "You will be prompted to choose an Ontology file from your local drive.
     Next, select Import… **You will see the number of changes made in the file
     that need to be saved** in the application header." (p.66)

The document and the plan are tested in `apps/api/tests/test_ontology_export.py`
and `test_ontology_import.py`, and the wording in
`apps/web/src/lib/ontology-transfer.test.ts`. What needs a browser is the loop
p.66 describes and neither can reach: **a file chosen from a disk turns into a
count, and the count turns into an ontology**.

That is the only place the file actually leaves and re-enters the product — a
JSON round trip through a file input, which every layer below stubs out.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture
def workspace(api):
    """A workspace with one object type worth exporting.

    Its own type per test, because these tests import files *into* the shared
    workspace and a type left behind by one changes what the next one's plan
    says.
    """
    mod = Module(api, "Transfer")
    tag = uuid.uuid4().hex[:8]
    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {"api_name": f"tr_{tag}", "display_name": f"Transfer {tag}",
         "description": "Something to export",
         "properties": [{"api_name": "name", "display_name": "Name",
                         "data_type": "string"}]},
    )
    mod.object_type_id = declared["id"]
    mod.tag = tag
    return mod


def open_advanced(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/advanced")
    expect(page.get_by_test_id("ontology-transfer")).to_be_visible(timeout=30000)


def choose(page, document: dict, name: str = "ontology.json") -> None:
    """Hand the file input a file, as a person choosing one from their drive."""
    page.get_by_test_id("ontology-import-file").set_input_files(files=[{
        "name": name,
        "mimeType": "application/json",
        "buffer": json.dumps(document).encode(),
    }])


def test_the_page_offers_both_halves(page, workspace) -> None:
    """p.66 puts Export and Import on one Advanced settings page."""
    open_advanced(page, workspace)
    expect(page.get_by_test_id("ontology-export")).to_be_visible()
    expect(page.get_by_test_id("ontology-import-file")).to_have_count(1)
    # Nothing is planned until a file is chosen: a count over no file would be
    # a number about nothing.
    expect(page.get_by_test_id("ontology-plan")).to_have_count(0)


def test_exporting_downloads_the_ontology(page, workspace) -> None:
    """**The half that leaves the product.**

    Checked as a real download rather than as a request, because the export
    goes through a blob the page builds itself — an assertion on the network
    call would pass for a page that fetched the JSON and dropped it.
    """
    open_advanced(page, workspace)
    with page.expect_download(timeout=30000) as caught:
        page.get_by_test_id("ontology-export").click()
    download = caught.value

    # Named for the workspace and the day, so a folder of exports can be told
    # apart without opening them.
    assert workspace.workspace_slug in download.suggested_filename
    assert download.suggested_filename.endswith(".json")

    path = download.path()
    document = json.loads(open(path, encoding="utf-8").read())
    assert document["format_version"] >= 1
    assert any(t["api_name"] == f"tr_{workspace.tag}"
               for t in document["object_types"]), (
        "the file carries the type this workspace actually has"
    )


def test_a_file_that_is_not_json_is_refused_without_a_round_trip(
    page, workspace
) -> None:
    """Said by the page rather than sent to the server: a file that is not JSON
    at all is not an ontology question, and posting it would turn a typo into a
    round trip that comes back saying the same thing."""
    open_advanced(page, workspace)
    page.get_by_test_id("ontology-import-file").set_input_files(files=[{
        "name": "notes.json",
        "mimeType": "application/json",
        "buffer": b"this is not json",
    }])
    expect(page.get_by_test_id("ontology-import-unreadable")).to_be_visible(
        timeout=30000
    )
    expect(page.get_by_test_id("ontology-plan")).to_have_count(0)


def test_a_file_the_server_refuses_says_which_name_is_wrong(
    page, api, workspace
) -> None:
    """§326's refusals name the thing that is wrong, and p.65's whole premise is
    somebody editing the JSON in a text editor — "invalid file" is not something
    they can act on."""
    open_advanced(page, workspace)
    document = api.call("GET", f"/workspaces/{workspace.workspace_id}/ontology-export")
    mine = next(t for t in document["object_types"]
                if t["api_name"] == f"tr_{workspace.tag}")
    mine["title_property"] = "no_such_property"
    choose(page, document)

    refused = page.get_by_test_id("ontology-import-refused")
    expect(refused).to_be_visible(timeout=30000)
    expect(refused).to_contain_text("no_such_property")


def test_an_untouched_export_plans_nothing_and_offers_no_apply(
    page, api, workspace
) -> None:
    """**p.66's count, at the value that matters most.**

    A file nobody edited must show no changes — and the Apply button must be
    unpressable, because a button that applies nothing is one somebody presses
    and then wonders what happened.
    """
    open_advanced(page, workspace)
    choose(page, api.call(
        "GET", f"/workspaces/{workspace.workspace_id}/ontology-export"))

    headline = page.get_by_test_id("plan-headline")
    expect(headline).to_be_visible(timeout=30000)
    expect(headline).to_contain_text("Nothing to apply")
    expect(page.get_by_test_id("ontology-import-apply")).to_be_disabled()
    # And the page says this file came from here, because "nothing changed"
    # reads differently for a copy than for a round trip (p.65's two workflows).
    expect(page.get_by_test_id("plan-origin")).to_contain_text("from this workspace")


def test_an_edited_file_is_counted_and_then_applied(page, api, workspace) -> None:
    """**p.66's loop, end to end through the screen**: choose a file, read the
    count, apply it, and find the ontology changed.

    Checked against the ontology rather than the page afterwards, because the
    page is the thing that just told you it worked.
    """
    open_advanced(page, workspace)
    document = api.call(
        "GET", f"/workspaces/{workspace.workspace_id}/ontology-export")
    added = f"new_{uuid.uuid4().hex[:8]}"
    template = next(t for t in document["object_types"]
                    if t["api_name"] == f"tr_{workspace.tag}")
    document["object_types"].append({**template, "api_name": added,
                                     "display_name": "Added by file"})
    choose(page, document)

    expect(page.get_by_test_id("plan-headline")).to_contain_text(
        "1 change", timeout=30000
    )
    expect(page.get_by_test_id("plan-object_types")).to_contain_text("1 new")

    apply = page.get_by_test_id("ontology-import-apply")
    expect(apply).to_be_enabled()
    apply.click()
    expect(page.get_by_test_id("ontology-applied")).to_be_visible(timeout=30000)

    def declared() -> list[str]:
        page_of = api.call(
            "GET",
            f"/workspaces/{workspace.workspace_id}/object-types?q={added}",
        )
        items = page_of["items"] if isinstance(page_of, dict) else page_of
        return [t["api_name"] for t in items]

    eventually(declared, lambda names: added in names,
               what="the imported object type to reach the ontology")


def test_a_file_that_leaves_a_type_out_says_it_is_left_alone(
    page, api, workspace
) -> None:
    """**The one thing p.66's reader must not believe.**

    The page they came from says import "will recreate the entire working
    state", and this one declines to delete — an object type's removal takes
    its objects with it, immediately and with no review. So a file missing a
    type says so, and points at the tool that does remove them (§325).
    """
    open_advanced(page, workspace)
    document = api.call(
        "GET", f"/workspaces/{workspace.workspace_id}/ontology-export")
    # Leave this workspace's own type out, and add one so there is a change to
    # apply — a plan with nothing to do would not be read at all.
    template = next(t for t in document["object_types"]
                    if t["api_name"] == f"tr_{workspace.tag}")
    document["object_types"] = [
        t for t in document["object_types"] if t["api_name"] != f"tr_{workspace.tag}"
    ] + [{**template, "api_name": f"kept_{uuid.uuid4().hex[:8]}",
          "display_name": "Kept"}]
    choose(page, document)

    warning = page.get_by_test_id("plan-left-alone")
    expect(warning).to_be_visible(timeout=30000)
    expect(warning).to_contain_text("left alone")
    expect(warning).to_contain_text("Ontology cleanup")
