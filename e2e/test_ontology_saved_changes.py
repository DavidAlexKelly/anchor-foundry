"""p.8's Ontology history on the ontology page (§683; `ontology-manager` p.8).

> "Select the History tab in the homepage sidebar to view a list of all saved
> Ontology changes with details on when the changes were made and the user who
> applied them. By default, the list of changes are collapsed. You can select
> the (down arrow) on any change to view details."
> "You also have the option to consolidate the view by merging changes that
> have been made by the same author into a single entry." (p.8)

What each change is called is `ontology-history.test.ts`; which writes are
recorded is `test_ontology_saved_changes.py`. What needs a browser is the
reading: the newest change first, collapsed until opened, merged by author on
request, and the footer on a type's own editor saying who touched it last.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from test_value_types import open_objects, open_type_editor


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Value types")
    mod.object_type(columns=["id", "name"], rows=[{"id": "1", "name": "Ada"}],
                    key="id", title="name")
    tag = uuid.uuid4().hex[:6]
    face = api.call("POST", f"/workspaces/{mod.workspace_id}/interfaces", {
        "api_name": f"Named{tag}", "display_name": f"Named {tag}", "properties": []})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/interfaces/{face['id']}", {
        "display_name": f"Titled {tag}", "description": "", "properties": []})
    mod.interface_name = f"Titled {tag}"
    return mod


def entries(page):
    return page.get_by_test_id("ontology-history").get_by_test_id("history-entry")


def test_the_newest_change_is_first_and_opens_to_its_details(page, module) -> None:
    open_objects(page, module)
    newest = entries(page).first
    expect(newest).to_contain_text(f"Edited interface {module.interface_name}")
    expect(newest).to_have_attribute("data-action", "interface.update")
    expect(entries(page).nth(1)).to_contain_text(f"Created interface {module.interface_name}")
    # Collapsed by default, as p.8 has it.
    expect(newest.get_by_test_id("history-details")).to_have_count(0)
    newest.get_by_role("button").click()
    expect(newest.get_by_test_id("history-details")).to_contain_text("properties: 0")
    newest.get_by_role("button").click()
    expect(newest.get_by_test_id("history-details")).to_have_count(0)


def test_one_author_s_run_is_merged_into_one_entry(page, module) -> None:
    open_objects(page, module)
    expect(entries(page).first).to_be_visible(timeout=30000)
    page.get_by_test_id("history-merge").check()
    run = page.get_by_test_id("history-run").first
    # Everything this suite saved was saved by one person, so the first run
    # holds at least the interface's two changes, each still its own line.
    expect(run.get_by_test_id("history-entry").nth(1)).to_be_visible()
    count = run.get_by_test_id("history-entry").count()
    expect(run).to_contain_text(f"{count} changes")


def test_a_type_s_editor_says_who_edited_it_last(page, module) -> None:
    open_objects(page, module)
    open_type_editor(page, module)
    expect(page.get_by_test_id("last-edited")).to_contain_text("Last edited by")
