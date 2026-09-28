"""p.32's usage metrics for a link type (§620; `ontology-manager` p.32-34).

> "Usage metrics — reads, writes, interactions over 30 days" … "any object
> type or link type usage happening in Ontology Manager is not included."
> (p.32)

Counting is `apps/api/tests/test_object_type_usage.py`. What needs a browser
is that the Explorer says it is the Explorer when it follows an object's
links - the label is the caller's to pass - and that the link's row in the
Ontology Manager shows the numbers.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import WEB_BASE, open_module


@pytest.fixture(scope="module")
def linked(api):
    mod = Module(api, "Link usage")
    mod.object_type(columns=["id", "name"], rows=[{"id": "A1", "name": "Ada"}],
                    key="id", title="name")
    tag = uuid.uuid4().hex[:6]
    link = api.call("POST", f"/workspaces/{mod.workspace_id}/link-types", {
        "api_name": f"knows_{tag}", "display_name": f"Knows {tag}",
        "from_type_id": mod.object_type_id, "to_type_id": mod.object_type_id,
        "cardinality": "one_to_many", "from_property": "name", "to_property": "name"})
    mod.link = link
    page = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/"
                           f"{mod.object_type_id}/instances")
    mod.instance_id = page["items"][0]["id"]
    return mod


def usage_cell(page, mod):
    return page.get_by_test_id(f"link-usage-{mod.link['api_name']}")


def test_following_links_in_the_explorer_is_its_usage(page, linked) -> None:
    objects = f"{WEB_BASE}/{linked.workspace_slug}/{linked.project_slug}/objects"
    page.goto(objects)
    expect(usage_cell(page, linked)).to_have_text(
        "No usage in the last 30 days.", timeout=30000)

    page.goto(f"{WEB_BASE}/{linked.workspace_slug}/explore"
              f"?object={linked.object_type_id}:{linked.instance_id}")
    expect(page.get_by_text(linked.link["display_name"]).first).to_be_visible(timeout=30000)

    page.goto(objects)
    expect(usage_cell(page, linked)).to_have_text(
        "1 person and 1 interaction in the last 30 days. Most in Object Explorer.",
        timeout=30000)


def test_a_links_widget_reads_it_as_workshop(page, api, linked) -> None:
    """The Links widget is Workshop's reader of the same route, and says so."""
    mod = Module(api, "Link usage widget", beside=linked)
    mod.define({
        "format": 2,
        "layout": layout({"lw": {"resolvedName": "CanvasLinksWidget", "props": {
            "objectSetVariable": "v_set", "linkMode": "all", "links": [],
            "defaultExpand": 0}}}),
        "variables": {"v_set": {"id": "v_set", "kind": "object_set", "label": "Ada",
                                "object_set": object_set(linked.object_type_id)}},
        "events": {},
    })
    open_module(page, mod)
    expect(page.get_by_text(linked.link["display_name"]).first).to_be_visible(timeout=30000)
    usage = api.call("GET", f"/workspaces/{linked.workspace_id}/link-types/"
                            f"{linked.link['id']}/usage")
    assert "workshop" in [a["application"] for a in usage["applications"]], usage
