"""The Ontology Manager's header search (parity `ontology.md` §6; Foundry
`ontology-manager` p.28).

    "Use the search bar in the header … to search across object types,
     properties, link types, action types … The search results highlight the
     specific field that matched your query."

The API tests cover what the search *finds*. What needs a browser is the half
p.28 spends its sentence on: that a reader can see **which field matched**, and
where in it - and that `Cmd+K` reaches the box without having to find it first.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def ontology(api):
    """One object type whose description - and nothing else - carries the word.

    Two things become checkable at once: that a description match is found at
    all, and that the result says `description` rather than a name. A fixture
    matching on its own name could not tell those apart.
    """
    mod = Module(api, "Ontology search")
    word = f"zarquon{uuid.uuid4().hex[:6]}"
    mod.object_type(columns=["id", "status"], rows=[{"id": "1", "status": "open"}], key="id")
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"described_{word}",
            "display_name": f"Described {word}",
            "properties": [
                {"api_name": "notes", "data_type": "string",
                 "description": f"mentions {word} only here"},
            ],
        },
    )
    mod.word = word
    return mod


def open_manager(page, module):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    expect(page.get_by_test_id("ontology-search")).to_be_visible(timeout=30000)


def test_searching_finds_a_type_and_says_which_field_matched(page, ontology):
    """p.28's requirement, on the surface it is a requirement about."""
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").fill(ontology.word)

    results = page.get_by_test_id("ontology-search-results")
    eventually(lambda: results.locator("li").count(), lambda n: n >= 2,
               what="the object type and the property that mention this word")
    # The type's **api_name** is what matched: `api_name` is searched before
    # `display_name`, and both contain the word, so the first one is the
    # reported one. Asserted as api_name rather than loosened to "some field",
    # because the ordering rule is the thing that decides what a reader sees
    # highlighted - and the first version of this test asserted display_name
    # and failed for exactly that reason.
    expect(results.locator("[data-kind='object_type'][data-matched-field='api_name']")
           ).to_be_visible()
    expect(results.locator("[data-kind='property'][data-matched-field='description']")
           ).to_be_visible()


def test_the_match_is_marked_inside_the_matched_value(page, ontology):
    """"Highlight the specific field" - the mark lands on the characters the
    server found, inside the value it found them in."""
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").fill(ontology.word)
    results = page.get_by_test_id("ontology-search-results")
    marks = results.locator("mark")
    eventually(lambda: marks.count(), lambda n: n >= 1, what="the highlighted match")
    assert marks.first.inner_text().lower() == ontology.word.lower()


def test_a_property_hit_says_which_object_type_it_is_on(page, ontology):
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").fill(ontology.word)
    hit = page.get_by_test_id("ontology-search-results").locator("[data-kind='property']")
    # **Wait for the panel the way the two tests above it do.** They give the
    # debounced search 20s to come back; this one relied on `expect`'s 5s
    # default, and was the only assertion in the file with less patience than
    # its siblings for the same precondition. It timed out once, in a full-suite
    # run, and has not reproduced in isolation. The claim below is unchanged -
    # only the window it is allowed to become true in.
    eventually(lambda: hit.count(), lambda n: n >= 1, what="the property hit")
    expect(hit).to_contain_text(f"on Described {ontology.word}")


def test_cmd_k_focuses_the_search(page, ontology):
    """p.28's shortcut. The point of it is that you do not have to find the box
    first, which is why it is bound on the window."""
    open_manager(page, ontology)
    page.locator("body").click()
    page.keyboard.press("Control+k")
    expect(page.get_by_label("Search the ontology")).to_be_focused()


def test_an_empty_box_shows_no_results_panel(page, ontology):
    """A search box whose empty state is the whole ontology is a list, and this
    page already has one below it."""
    open_manager(page, ontology)
    expect(page.get_by_test_id("ontology-search-results")).to_have_count(0)
    box = page.get_by_label("Search the ontology")
    box.fill(ontology.word)
    expect(page.get_by_test_id("ontology-search-results")).to_be_visible()
    box.fill("")
    expect(page.get_by_test_id("ontology-search-results")).to_have_count(0)


def test_a_query_matching_nothing_says_so(page, ontology):
    """Rather than an empty panel, which reads as still loading."""
    open_manager(page, ontology)
    page.get_by_label("Search the ontology").fill(f"nothing{uuid.uuid4().hex}")
    expect(page.get_by_test_id("ontology-search-results")).to_contain_text(
        "Nothing in this workspace's ontology matches that"
    )


# --- the third ownerless kind (§316) ------------------------------------------


def test_an_interface_hit_opens_the_interface(page, api):
    """**Sixty-four units of a hit that opened nothing** (§252 to §316).

    An interface belongs to no object type — it is implemented *by* types
    rather than owned by one (`object-link-types` p.4) — so it has no type's
    screen to borrow. §252 made interfaces searchable without giving them one,
    and the click fell through the group check into the shared property
    handler: an editor opened for an id from another table, found nothing, and
    said nothing.

    **Nothing errored, which is why it lasted.** That is also why this test has
    to assert what *did* open rather than that something did: a dialog that
    never resolves and a dialog showing the wrong thing both look like a click
    that worked.
    """
    from api import Module

    mod = Module(api, "Interface search")
    word = f"zarquon{uuid.uuid4().hex[:6]}"
    api.call(
        "POST", f"/workspaces/{mod.workspace_id}/interfaces",
        {"api_name": f"if_{word}", "display_name": f"Shape {word}",
         "properties": [{"api_name": "code", "display_name": "Code",
                         "data_type": "string", "required": True}]},
    )

    open_manager(page, mod)
    page.get_by_label("Search the ontology").fill(word)
    hit = page.get_by_test_id("ontology-search-results").locator(
        "[data-kind='interface']"
    )
    eventually(lambda: hit.count(), lambda n: n == 1, what="the interface hit")
    # The label the six-kind map had no entry for. A blank chip is not
    # something anybody reports, so it is asserted rather than left to the eye.
    expect(hit).to_contain_text("Interface")
    # And the count that says whether changing this shape is cheap — the fact
    # somebody looking at an interface is deciding on.
    expect(hit).to_contain_text("implemented by 0 object types")

    hit.click()
    # The interface's own screen, named after the interface. Before §316 this
    # was a shared property editor over an interface id.
    expect(page.get_by_role("dialog")).to_contain_text(
        f"if_{word} objects", timeout=30000
    )
