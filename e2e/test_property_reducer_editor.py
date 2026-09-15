"""Declaring a property reducer in the Ontology Manager (parity
`ontology.md`; Foundry `object-link-types` p.131-133 **[Beta]**; db 0088).

§348 built the whole read path — the declaration, its refusals, the reduction,
the reduced value beside the array on two reads — and deliberately left it
reachable only through the API, on §346's precedent and §214's rule: there was
no control that could complete the declaration, so there was no control. This
file is the other half arriving.

Three things need a browser, and the first decides whether the rest matters:

* **the round trip** — a reducer declared entirely through the dialog is stored
  as the server holds it, which is the only way to know the dialog and the API
  agree about a shape neither typechecks against the other;
* **which rows get the button at all**, which is this unit's §214 judgement: an
  array of geopoints has no operation p.132 gives it, so a Reduce button on one
  would open a dialog whose only outcome is a refusal;
* **the reduced value on the page**, because a declaration that stores
  perfectly and changes nothing anybody sees is the half §348 could not deliver
  on its own.

The vocabulary and the refusals are unit-tested in
`apps/web/src/lib/property-reducer.test.ts`; the table is guarded against the
server's own in `apps/api/tests/test_property_reducers.py`.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import find_type_row, save_type

#: Out of order on purpose: the latest date is **not** the last element, so a
#: reducer that answered with `value[-1]` — or with nothing — is visible in the
#: assertion rather than only in a comment.
CHECKS = json.dumps(["2024-01-05", "2024-03-09", "2023-11-02"])
WHERE = json.dumps([{"lat": 51.5, "lon": -0.1}])
#: p.140's "Struct Array", which is the shape p.133's tie-breaking is actually
#: about: two inspections on the same day, told apart by their score.
VISITS = json.dumps([
    {"on": "2024-03-09", "score": "3"},
    {"on": "2024-03-09", "score": "7"},
    {"on": "2024-01-05", "score": "9"},
])
VISIT_FIELDS = [
    {"api_name": "on", "display_name": "On", "data_type": "date"},
    {"api_name": "score", "display_name": "Score", "data_type": "integer"},
]


@pytest.fixture(scope="module")
def module(api):
    """One reducible array, one that is not, one already reducing, one struct
    array, and one the dialog-only tests declare nothing on.

    A column each because the tests ask different questions of them, and a test
    that only passes after another one is not a test —
    `test_struct_fields_editor` writes down how that bit it there, and this
    fixture learned it again: `runs` exists because the two tests that only
    open the dialog were reading `checks`, which the round-trip test above
    leaves already reducing, so "add one row" became "add a second".
    """
    mod = Module(api, "Property reducer editor")
    mod.object_type(
        columns=["code", "checks", "seen", "spots", "visits", "runs"],
        rows=[{"code": "A1", "checks": CHECKS, "seen": CHECKS, "spots": WHERE,
               "visits": VISITS, "runs": CHECKS}],
        key="code",
        title="code",
        types={"checks": "array", "seen": "array", "spots": "array",
               "visits": "array", "runs": "array"},
        array_of={"checks": "date", "seen": "date", "spots": "geopoint",
                  "visits": "struct", "runs": "date"},
        struct_fields={"visits": VISIT_FIELDS},
        # `seen` arrives already reducing, so the test that reads a stored
        # declaration back has one to read.
        reducers={"seen": [{"operation": "latest"}]},
    )
    return mod


def properties(api, module) -> dict[str, dict]:
    detail = api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )
    return {p["api_name"]: p for p in detail["properties"]}


def open_type_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = find_type_row(page, f"seed_{module.tag}")
    row.get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible()


def property_row(page, api_name: str) -> int:
    names = page.get_by_role("textbox", name="Property")
    for index in range(names.count()):
        box = page.get_by_role("textbox", name=f"Property {index + 1} name")
        if box.input_value() == api_name:
            return index + 1
    raise AssertionError(f"no property row named {api_name!r}")


def test_a_reducer_is_declared_entirely_through_the_dialog(page, api, module) -> None:
    """p.133's flow end to end: open the array property's Reduce dialog, add a
    reducer, choose what to take, apply, save, and find it stored.

    **Read back from the API rather than from the dialog.** A dialog that
    showed `Most recent` while having sent `earliest` would look right and be
    the bug this test exists to exclude — and the two are one dropdown apart.
    """
    open_type_editor(page, module)
    index = property_row(page, "checks")
    page.get_by_role("button", name=f"Property {index} reducers").click()
    # It opens on **no** rows: p.131 makes reduction optional, so arriving with
    # one already declared would mean Cancel was the only way out that left the
    # property alone.
    expect(page.get_by_test_id("reducer-none")).to_be_visible()

    page.get_by_test_id("reducer-add").click()
    operation = page.get_by_role("combobox", name="Reducer 1 operation")
    # Seeded rather than empty, for the reason the element type is (§347): an
    # unanswered select is a declaration the server refuses.
    expect(operation).to_have_value("latest")
    operation.select_option("earliest")
    page.get_by_test_id("reducer-save").click()
    save_type(page)

    held = properties(api, module)["checks"]
    assert held["reducers"] == [{"operation": "earliest", "field": None}], held
    # And the array itself is untouched, which is p.131's first sentence:
    # "reduction does not change the underlying property type or property data
    # stored".
    assert held["data_type"] == "array" and held["array_of"] == "date", held


def test_only_a_property_p132_can_order_offers_the_button(page, api, module) -> None:
    """**This unit's §214 judgement.** p.132's unsupported table has Geohash
    and Geoshape, so an array of geopoints has no reducer operation at all — a
    Reduce button on that row would open a dialog whose only outcome is the
    server's refusal, which is worse than no button.

    Both directions in one test, because the claim is a *difference*: asserting
    only that the button is missing from `spots` would pass just as well
    against a build where nothing had one.
    """
    open_type_editor(page, module)
    dates = property_row(page, "checks")
    points = property_row(page, "spots")
    expect(page.get_by_role("button", name=f"Property {dates} reducers")).to_be_visible()
    expect(
        page.get_by_role("button", name=f"Property {points} reducers")
    ).to_have_count(0)


def test_a_stored_reducer_is_shown_and_can_be_taken_away(page, api, module) -> None:
    """The other half of the round trip, and the way a property stops reducing:
    p.131 makes reduction optional, so removing every row is the control rather
    than a separate one.

    Stored as NULL either way, and the dialog does **not** try to help: it
    sends the list it has. `property_reducers.parse` turns `[]` into `None`
    before anything is written, so a conditional here was a second answer to a
    question the server already answers — a sweep proved nothing could tell the
    two apart, and it is gone with the reasoning in its place (§213).
    """
    open_type_editor(page, module)
    index = property_row(page, "seen")
    button = page.get_by_role("button", name=f"Property {index} reducers")
    # The count on the button, which is what says a property reduces without
    # anybody opening anything — p.131's whole point is that the stored value
    # does not show it.
    expect(button).to_have_text("Reduce (1)")
    button.click()
    expect(page.get_by_role("combobox", name="Reducer 1 operation")).to_have_value(
        "latest"
    )
    # **`dispatch_event`, not `click`** — `test_struct_fields_editor` wrote
    # down why, one dialog over: a real click carries a *position*, and
    # removing the only row collapses the table, so whatever is below it slides
    # up into the point the pointer is aimed at. There the button underneath
    # was *Add field* and three clicks produced three removals and one add;
    # here it is *Cancel*, and the click closed the dialog it had just emptied.
    # Asking the button directly is the assertion about p.131 rather than about
    # the layout.
    page.get_by_test_id("reducer-rows").get_by_role("button").first.dispatch_event(
        "click"
    )
    expect(page.get_by_test_id("reducer-none")).to_be_visible()
    page.get_by_test_id("reducer-save").click()
    save_type(page)

    held = properties(api, module)["seen"]
    assert held["reducers"] is None, held


def test_a_reduced_property_reads_as_one_value_on_the_page(page, api, module) -> None:
    """p.131's payoff: "applying a reducer to an array with multiple inspection
    dates allows you to display only the most recent date when viewing the
    property in a table".

    Its own module, because the tests above retype the fixture's columns and
    this one is about a workspace where the declaration is still standing.

    **The other dates are the assertion.** An array drawn without its reducer
    shows all three, and one drawn with it shows the one — so asserting only
    that "2024-03-09" is present would pass over exactly the bug this test is
    for.
    """
    mod = Module(api, "Reduced value")
    mod.object_type(
        columns=["code", "checks"],
        rows=[{"code": "B1", "checks": CHECKS}],
        key="code", title="code",
        types={"checks": "array"}, array_of={"checks": "date"},
        reducers={"checks": [{"operation": "latest"}]},
    )
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects/"
        f"{mod.object_type_id}"
    )
    drawn = page.get_by_test_id("reduced-value").first
    expect(drawn).to_be_visible(timeout=30000)
    # **Asserted on the `title`, not on the text**, and that is the feature
    # rather than a workaround: the reduced element renders *typed* (db 0087's
    # `array_of` is what an array's own elements cannot reach), so the cell
    # reads "3/9/2024" in this browser's locale and something else in another.
    # `PropertyValue`'s date branch keeps the ISO value as the title, which is
    # the one spelling that does not depend on where the reader is.
    expect(drawn.locator("span[title='2024-03-09']")).to_have_count(1)
    # The other two are the assertion. An array drawn without its reducer shows
    # all three, so checking only for the latest would pass over the bug.
    expect(drawn.locator("span[title='2023-11-02']")).to_have_count(0)
    expect(drawn.locator("span[title='2024-01-05']")).to_have_count(0)
    # And p.131's other half — "the full array remains accessible", with
    # applications able to "view the complete array on hover". A cell showing
    # one date and nothing else would read as a property holding one date.
    expect(page.get_by_test_id("reduced-count").first).to_have_text("of 3")

    # **And the object's own page, which is p.131's "or application".** The
    # single read fills `reduced` too, so a property that reduces in the table
    # and not here would be the same declaration answering differently
    # depending on which page asked.
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    listed = page.get_by_test_id("sov-normal")
    expect(listed).to_be_visible(timeout=30000)
    expect(listed.get_by_test_id("reduced-value").first).to_be_visible()
    expect(listed.locator("span[title='2024-01-05']")).to_have_count(0)


def test_a_reducer_the_dialog_refuses_cannot_be_applied(page, api, module) -> None:
    """p.133 gives a second reducer exactly one job — breaking the tie the one
    before it left — and a plain array has one basis, the element itself. So a
    second row on a date array cannot break anything, and the server refuses
    it.

    **Answered here rather than at the API**, which is the split
    `lib/property-reducer` exists for: the dialog owns what to offer and the
    server owns what is legal, and a form that turns into a 422 with the dialog
    already closed is a form that wasted the work. Apply being *disabled* is
    the assertion — a dialog that explained the problem and let somebody press
    it anyway would satisfy a test that only looked for the sentence.
    """
    open_type_editor(page, module)
    index = property_row(page, "runs")
    page.get_by_role("button", name=f"Property {index} reducers").click()
    page.get_by_test_id("reducer-add").click()
    expect(page.get_by_test_id("reducer-save")).to_be_enabled()
    page.get_by_test_id("reducer-add").click()

    expect(page.get_by_test_id("reducer-problem")).to_contain_text("tie")
    expect(page.get_by_test_id("reducer-save")).to_be_disabled()


def test_an_operation_reads_as_p132s_words_and_not_as_its_stored_name(
    page, api, module
) -> None:
    """p.132 writes "Most recent (latest)", and `latest` is the API's spelling.
    A dropdown showing the stored name is a control that asks somebody to know
    the schema — and it is what every one of these `select_option` calls would
    still pass against, because they choose by value.
    """
    open_type_editor(page, module)
    index = property_row(page, "runs")
    page.get_by_role("button", name=f"Property {index} reducers").click()
    page.get_by_test_id("reducer-add").click()
    shown = page.get_by_role("combobox", name="Reducer 1 operation").locator("option")
    assert [o.strip() for o in shown.all_inner_texts()] == [
        "Most recent", "Least recent",
    ], shown.all_inner_texts()


def test_a_struct_array_is_reduced_by_a_field_and_carries_the_operation(
    page, api, module
) -> None:
    """p.133's two sentences in one flow: "reducers function on struct arrays
    based on a specific field within the struct, not the struct itself", and
    "you can also configure multiple reducers using different struct fields to
    handle tie-breaking scenarios".

    **The operation moving with the field is the rule a plain
    `{...reducer, field}` gets wrong**, and it gets it wrong the way §347's
    transition did: the operations are the *field's*, so a row moved from a
    date to an integer keeps `latest` naming something an integer cannot do —
    and the server refuses it with a message about a control the dialog is no
    longer showing.
    """
    open_type_editor(page, module)
    index = property_row(page, "visits")
    page.get_by_role("button", name=f"Property {index} reducers").click()
    page.get_by_test_id("reducer-add").click()
    field = page.get_by_role("combobox", name="Reducer 1 field")
    operation = page.get_by_role("combobox", name="Reducer 1 operation")
    # The field control exists at all, which is the first of p.133's sentences.
    expect(field).to_have_value("on")
    expect(operation).to_have_value("latest")

    field.select_option("score")
    # **The assertion.** `latest` is not something an integer can do, and the
    # row has to have stopped saying it before anybody presses Apply.
    expect(operation).to_have_value("highest")

    # p.133's tie-break: the second row opens on the field nothing has claimed.
    page.get_by_test_id("reducer-add").click()
    expect(page.get_by_role("combobox", name="Reducer 2 field")).to_have_value("on")
    page.get_by_test_id("reducer-save").click()
    save_type(page)

    held = properties(api, module)["visits"]
    assert held["reducers"] == [
        {"operation": "highest", "field": "score"},
        {"operation": "latest", "field": "on"},
    ], held
