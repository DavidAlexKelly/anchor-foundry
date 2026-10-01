"""p.95's lookup formatters (§624; `object-link-types` p.95).

> "Foundry ID formatting: Display a Foundry ID as a user's first and last name
> or group name. Resource RID formatting: Display a Foundry resource ID (RID)
> as an icon and resource name, with a clickable link that routes to that
> resource." (p.95)

Which name an id is, is `value-format.test.ts`; which formats the server takes
is `apps/api/tests/test_value_format.py`. What needs a browser is that an
object's id-holding strings are shown as who and what they name, that the id
stays in the tooltip, that the resource links to where it opens, and that an
id nothing names is shown as itself rather than as a blank.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE


@pytest.fixture(scope="module")
def looked_up(api):
    mod = Module(api, "Lookup formats")
    # A module to point at: its resource id is what the `doc` column holds.
    mod.define({"format": 2, "layout": layout({}), "variables": {}, "events": {}})
    me = api.call("GET", "/auth/me")
    stranger = str(uuid.uuid4())
    mod.object_type(
        columns=["id", "name", "owner", "doc", "other", "note"],
        rows=[{"id": "L1", "name": "Ledger", "owner": me["user_id"],
               "doc": mod.resource_id, "other": stranger, "note": "quarterly report"}],
        key="id", title="name",
        formats={"owner": {"kind": "user"}, "doc": {"kind": "resource"},
                 "other": {"kind": "user"}, "note": {"kind": "resource"}})
    page = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/"
                           f"{mod.object_type_id}/instances")
    mod.instance_id = page["items"][0]["id"]
    mod.me, mod.stranger = me, stranger
    return mod


def test_ids_are_shown_as_who_and_what_they_name(page, looked_up) -> None:
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/resources/" in r.url else None)
    page.goto(f"{WEB_BASE}/{looked_up.workspace_slug}/explore"
              f"?object={looked_up.object_type_id}:{looked_up.instance_id}")
    person = page.get_by_title(looked_up.me["user_id"]).first
    expect(person).to_have_text(looked_up.me["display_name"] or looked_up.me["email"],
                                timeout=30000)
    expect(person).to_have_attribute("data-testid", "lookup-person")

    resource = page.get_by_test_id("lookup-resource").first
    expect(resource).to_contain_text(f"App {looked_up.tag}")
    expect(resource).to_have_attribute("href", f"/r/{looked_up.resource_id}")
    expect(resource).to_have_attribute("title", looked_up.resource_id)

    # Nobody by that id: the id itself, not an empty cell.
    expect(page.get_by_title(looked_up.stranger).first).to_have_text(looked_up.stranger)

    # Free text under a resource format is shown as itself, and is not a
    # question put to the server: a column of it would be a request per cell.
    expect(page.get_by_title("quarterly report").first).to_have_text("quarterly report")
    assert [u for u in asked if "quarterly" in u] == [], asked
    assert any(looked_up.resource_id in u for u in asked), asked
