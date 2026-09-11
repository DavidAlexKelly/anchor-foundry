"""p.30's quick links, on the screen (§317; `ontology-manager` p.30).

    "Hovering over the Back home button will also bring up quick links to
     recently edited object types, link types, and action types, as well as
     all resources that are related to the one you are currently viewing."
     (p.30)

The ordering and the three kinds are in `apps/api/tests/test_ontology_recent.py`.
What needs a browser is the half that is only a claim about an interface:
**they are quick links** — they appear where somebody is already going when
they want to get somewhere, and clicking one arrives.

**Focus rather than hover**, and the reason is on the component: a hover is a
gesture a keyboard and a touchscreen do not have, and `Cmd+K` already lands in
this box from anywhere on the page. There is also no Back home button here to
hang one on — this ontology is one page with sections rather than Foundry's
separate home, which the `ontology.md` row for p.29 explains.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def ontology(api):
    """A type to edit, and a link type so a second kind can reach the list."""
    mod = Module(api, "Recently edited")
    mod.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ely"}],
                    key="id", title="town")
    tag = uuid.uuid4().hex[:8]
    far = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {"api_name": f"far_{tag}", "display_name": f"Far {tag}",
         "properties": [{"api_name": "code", "display_name": "Code",
                         "data_type": "string", "required": True}]},
    )
    link = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/link-types",
        {"api_name": f"lk_{tag}", "display_name": f"Link {tag}",
         "from_type_id": mod.object_type_id, "to_type_id": far["id"],
         "cardinality": "one_to_many",
         "from_property": "id", "to_property": "code"},
    )
    mod.far_id = far["id"]
    mod.far_api_name = f"far_{tag}"
    mod.link_id = link["id"]
    mod.link_api_name = f"lk_{tag}"
    return mod


def touch_type(api, module, type_id: str) -> None:
    """Edit a type through the API, so the browser is only asked about the
    list rather than about the editing."""
    detail = api.call(
        "GET", f"/workspaces/{module.workspace_id}/object-types/{type_id}"
    )
    api.call(
        "PATCH", f"/workspaces/{module.workspace_id}/object-types/{type_id}",
        {"display_name": f"{detail['display_name'].split(' · ')[0]} · "
                         f"{uuid.uuid4().hex[:6]}",
         "description": detail.get("description", ""),
         "icon": detail.get("icon", "cube"),
         "colour": detail.get("colour", "#4f46e5"),
         "properties": [
             {"api_name": p["api_name"], "display_name": p["display_name"],
              "data_type": p["data_type"], "required": p.get("required", False)}
             for p in detail["properties"]
         ],
         "title_property": detail.get("title_property")},
    )


def open_manager(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_test_id("ontology-search")).to_be_visible(timeout=30000)


def test_focusing_the_empty_box_offers_what_was_edited_last(page, api, ontology):
    """**p.30's quick links**, reached the way this product has a way of
    reaching them."""
    touch_type(api, ontology, ontology.object_type_id)
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").focus()

    panel = page.get_by_test_id("ontology-recent")
    expect(panel).to_be_visible(timeout=30000)
    expect(panel).to_contain_text("Recently edited")
    row = page.get_by_test_id(f"recent-seed_{ontology.tag}")
    expect(row).to_be_visible()
    # **And when.** The order says which is most recent and nothing about
    # whether the top row is four minutes old or four months, which are
    # different lists — one is "what I was doing", the other is "this ontology
    # is finished".
    expect(row).to_contain_text("just now")


def test_the_links_are_not_the_search_results(page, api, ontology):
    """The distinction the component's two comments are about.

    "Blank means blank" still holds for *search*: an empty query searches for
    nothing, because a box whose empty state is the whole ontology is a list.
    Eight things somebody edited is not the ontology — so both panels must not
    be on screen at once, and each must be the one that is.
    """
    touch_type(api, ontology, ontology.object_type_id)
    open_manager(page, ontology)
    box = page.get_by_label("Search the ontology")
    box.focus()
    expect(page.get_by_test_id("ontology-recent")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("ontology-search-results")).to_have_count(0)

    box.fill(f"seed_{ontology.tag}")
    expect(page.get_by_test_id("ontology-search-results")).to_be_visible()
    expect(page.get_by_test_id("ontology-recent")).to_have_count(0)

    box.fill("")
    expect(page.get_by_test_id("ontology-recent")).to_be_visible()


def test_an_edited_link_type_appears_and_says_what_it_is_on(page, api, ontology):
    """p.30's second kind, and **the one that had no column to read** until db
    0075: `link_types` gained six editable columns over fifty migrations and
    never an `updated_at`.

    It also says which type it hangs off, because a link listed under no type
    is a quick link to nowhere.
    """
    api.call(
        "PATCH", f"/workspaces/{ontology.workspace_id}/link-types/{ontology.link_id}",
        {"from_side_name": f"side{uuid.uuid4().hex[:6]}"},
    )
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").focus()
    row = page.get_by_test_id(f"recent-{ontology.link_api_name}")
    expect(row).to_be_visible(timeout=30000)
    expect(row).to_contain_text("Link type")
    expect(row).to_contain_text("on ")


def test_clicking_a_quick_link_arrives(page, api, ontology):
    """**The word "link" is the claim**, and the only one a browser can check.

    Two ways to get this wrong are both silent: the blur that closes the panel
    fires before a `click` handler on a button inside it, so the button
    unmounts mid-click and nothing happens — and a destination decided by
    assumption rather than by the shared one would send a link type somewhere
    that has nothing to do with it. §316 spent sixty-four units being the
    first of those.
    """
    touch_type(api, ontology, ontology.object_type_id)
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").focus()
    row = page.get_by_test_id(f"recent-seed_{ontology.tag}")
    expect(row).to_be_visible(timeout=30000)
    row.click()

    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible(timeout=30000)
    expect(dialog).to_contain_text("seed_" + ontology.tag)


def test_the_list_is_short_enough_to_be_a_hover(page, api, ontology):
    """p.30 calls these "quick links", and the page below already has a search
    and a paged table of every type. A third way of looking at the same rows,
    long enough to scroll, would be the worst of the three."""
    touch_type(api, ontology, ontology.object_type_id)
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").focus()
    panel = page.get_by_test_id("ontology-recent")
    expect(panel).to_be_visible(timeout=30000)
    eventually(lambda: panel.locator("li").count(),
               lambda n: 0 < n <= 8, what="a list short enough to read at once")
