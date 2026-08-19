"""Statuses in the Ontology Manager (parity `docs/parity/ontology.md` §1.3;
Foundry `object-link-types` p.253-259).

§170 built the values, the refusals and the propagation through the API. This
is somebody using them: setting a status on p.256's dropdown, seeing p.253's
badge in the listing, and — the part that needed a browser rather than a test
client — being **told what a demotion is about to do** before doing it.

p.256's propagation is invisible until it has already run: demoting an object
type demotes every property on it. A form that does not say so is a form where
somebody discovers the change by re-reading a page they thought they
understood.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = [
    {"id": "R1", "name": "Ada", "code": "A"},
    {"id": "R2", "name": "Grace", "code": "B"},
]


@pytest.fixture(scope="module")
def module(api):
    things = Module(api, "Statuses")
    things.object_type(
        columns=["id", "name", "code"], rows=ROWS, key="id", title="name",
    )
    return things


def open_objects(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_role("heading", name="Value types")).to_be_visible(timeout=30000)


def type_row(page, module):
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    return row


def open_type_editor(page, module) -> None:
    type_row(page, module).get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("status-select")).to_be_visible(timeout=15000)


def set_status(page, module, status: str) -> None:
    open_type_editor(page, module)
    page.get_by_test_id("status-select").select_option(status)
    page.get_by_role("button", name="Save", exact=True).click()


def test_a_status_can_be_set_and_shows_in_the_listing(page, module) -> None:
    """p.256's dropdown, and p.253's "these statuses are viewable in Object
    Explorer, Object Views, and Workshop to provide more information about
    which object types are intended for use"."""
    open_objects(page, module)
    set_status(page, module, "active")

    open_objects(page, module)
    expect(type_row(page, module).get_by_test_id("status-badge-active")).to_be_visible()


def test_experimental_draws_no_badge(page, module) -> None:
    """It is p.256's default, so badging it would put a label on every row of
    a new ontology and say nothing by being everywhere."""
    open_objects(page, module)
    set_status(page, module, "experimental")
    open_objects(page, module)
    row = type_row(page, module)
    expect(row.get_by_test_id("status-badge-experimental")).to_have_count(0)
    expect(row).to_contain_text(f"seed_{module.tag}")


def test_delete_says_why_it_is_unavailable(page, module) -> None:
    """p.256 refuses this on the server. Saying so here turns a rejected
    request into a button that explains itself - and the words are the
    server's, so somebody who reaches the refusal is not told two different
    things."""
    open_objects(page, module)
    set_status(page, module, "active")
    open_objects(page, module)

    delete = type_row(page, module).get_by_role("button", name="Delete")
    expect(delete).to_be_disabled()
    assert "mark it deprecated" in (delete.get_attribute("title") or "")

    # And it comes back when the status allows it.
    set_status(page, module, "experimental")
    open_objects(page, module)
    expect(type_row(page, module).get_by_role("button", name="Delete")).to_be_enabled()


def test_a_demotion_warns_about_the_properties_it_will_take(page, module) -> None:
    """**The claim that needs a browser.** p.256: "if an object type is changed
    from `active` to `experimental`, all of its properties will be marked
    `experimental` as well" - and nothing on screen says so unless something
    says so.

    The warning appears while the choice is still a choice, which is the whole
    point of it being in the form rather than in the response.
    """
    open_objects(page, module)
    # Get the type and its properties to `active` first, so a demotion has
    # something to take with it.
    open_type_editor(page, module)
    page.get_by_test_id("status-select").select_option("active")
    # No warning going up: p.258 makes promoting properties an option, not a
    # consequence, so there is nothing to warn about.
    expect(page.get_by_test_id("status-propagation")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()

    open_objects(page, module)
    open_type_editor(page, module)
    page.get_by_test_id("status-select").select_option("example")
    warning = page.get_by_test_id("status-propagation")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("will also become example")


def test_a_deprecation_asks_why_and_by_when(page, module) -> None:
    """p.254's note, offered exactly where the server allows it - which is
    only on a deprecated resource."""
    open_objects(page, module)
    open_type_editor(page, module)

    expect(page.get_by_test_id("deprecation-reason")).to_have_count(0)
    page.get_by_test_id("status-select").select_option("deprecated")
    page.get_by_test_id("deprecation-reason").fill("Replaced by Contact")
    page.get_by_test_id("deprecation-deadline").fill("2026-12-31")
    page.get_by_role("button", name="Save", exact=True).click()

    open_objects(page, module)
    open_type_editor(page, module)
    expect(page.get_by_test_id("deprecation-reason")).to_have_value("Replaced by Contact")

    # And moving away clears it, rather than leaving a resource explaining why
    # it was going to be deleted.
    #
    # **The save has to be checked, not just the disappearance.** Hiding the
    # fields while keeping the values would look identical here and then be
    # refused by the server, which forbids a deprecation note on anything not
    # deprecated - a 422 nobody would see, because the dialog closes either
    # way. §160's lesson, in a new place.
    page.get_by_test_id("status-select").select_option("experimental")
    expect(page.get_by_test_id("deprecation-reason")).to_have_count(0)
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()


def test_an_unrelated_edit_does_not_reset_a_propertys_status(page, module, api) -> None:
    """**The carry-through failure, for the seventh time** (§157, §160, §163,
    §164, §165, §169, and here). The edit dialog rebuilds every property from
    the type, so any setting it forgets to carry is silently reset by somebody
    changing a display name.

    There is no per-property status control on this screen, so the setting is
    made through the API and the *browser* does the unrelated edit - which is
    exactly the shape of the bug: a value nothing on the page can see, quietly
    dropped by a page that rewrites everything.
    """
    base = f"/workspaces/{module.workspace_id}"
    detail = api.call("GET", f"{base}/object-types/{module.object_type_id}")
    properties = [
        {k: v for k, v in p.items()
         if k in ("api_name", "data_type", "required", "description",
                  "visibility", "status")}
        for p in detail["properties"]
    ]
    next(p for p in properties if p["api_name"] == "code")["status"] = "deprecated"
    api.call(
        "PATCH", f"{base}/object-types/{module.object_type_id}",
        {"display_name": detail["display_name"], "properties": properties,
         "title_property": "name", "status": "active"},
    )

    open_objects(page, module)
    open_type_editor(page, module)
    page.get_by_role("textbox", name="Description", exact=False).fill("Edited")
    with page.expect_response(
        lambda r: "/object-types/" in r.url and r.request.method == "PATCH"
    ) as saved:
        page.get_by_role("button", name="Save", exact=True).click()
    assert saved.value.ok, saved.value.text()

    after = api.call("GET", f"{base}/object-types/{module.object_type_id}")
    statuses = {p["api_name"]: p["status"] for p in after["properties"]}
    assert statuses["code"] == "deprecated", statuses


def test_a_property_is_not_offered_promoted(page, module) -> None:
    """p.255: `promoted` "applies only to object types". The object type's own
    dropdown has five options; anything else has four."""
    open_objects(page, module)
    open_type_editor(page, module)
    options = page.get_by_test_id("status-select").locator("option")
    expect(options).to_have_count(5)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Promoted" in labels, labels
