"""Value formatting on a property (parity `ontology.md` §1.2; Foundry
`object-link-types` p.94-101).

    "Value formatting refers to applying a special formatter to the value of a
     property, transforming the raw value to a more readable version … the
     weight column [has] a unit ("kg") applied and the value column is
     displayed in a more compact form with a currency sign ("$100K")." (p.94)

The formatter itself is unit-tested (`apps/web/src/lib/value-format.test.ts`) -
that is where "does 100000 become $100K" belongs, and a browser is a bad place
to ask it. What needs a browser is the parts a pure function cannot reach:

* a formatter declared on the object type actually arriving at a rendered cell;
* the **raw value still being reachable**, because p.94's readability is bought
  by hiding the number somebody has to type into a filter;
* somebody being able to *set* one, with p.96's preview;
* and the setting surviving an unrelated edit - the failure the property editor
  already carries a comment about, now with a second setting able to hit it.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import FIRST_RENDER_MS, WEB_BASE, eventually

ROWS = [
    {"id": "S1", "name": "Alpha", "value": "100000", "weight": "72.5"},
    {"id": "S2", "name": "Beta", "value": "2500", "weight": "8"},
]


@pytest.fixture(scope="module")
def module(api):
    """p.94's own example, as an object type: a compact currency, and a second
    numeric property left **unformatted** on purpose.

    Without the second one, "the formatted property is formatted" would pass
    equally on a page that formatted everything and on one that formatted
    nothing in particular.
    """
    mod = Module(api, "Value formatting")
    mod.object_type(
        columns=["id", "name", "value", "weight"],
        rows=ROWS,
        key="id",
        title="name",
        types={"value": "float", "weight": "float"},
        formats={
            "value": {"kind": "number", "style": "currency", "currency": "USD",
                      "notation": "compact", "maximum_fraction_digits": 0},
        },
    )
    return mod


def open_type_editor(page, module):
    """The Ontology Manager's edit dialog for *this fixture's* type.

    Reached by filtering the row on the api_name, not by taking the first one:
    the objects page lists every type in the workspace, and `.first` picked a
    different fixture's type entirely the first time this was written.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()
    # **And wait for the editor to have drawn its rows.** The click was waited
    # for; what comes after it was not, so every assertion in this file about
    # the dialog's contents ran against Playwright's five-second default while
    # the type detail was still being fetched. Under a full-suite run that is
    # not enough, and the failure looks like the feature being wrong rather
    # than like the page being slow - `test_a_string_property_is_not_offered_a
    # _formatter` failed exactly that way, on its *presence* assertion, which
    # is the one its own comment says makes the absence meaningful.
    #
    # `Property 1 name` is the anchor because every property row has one
    # whatever its type - and the questions this file asks are about which
    # *other* controls each type gets.
    expect(page.get_by_label("Property 1 name")).to_be_visible(timeout=FIRST_RENDER_MS)


def open_first_object(page, module):
    """The Explorer filtered to this fixture's type, then into an object.

    Filtered for `test_standard_object_view.py`'s reason: the Explorer is
    workspace-wide and this dev database carries every object every previous
    run created.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(ROWS),
               what="this type's objects, and only this type's")
    rows.first.get_by_role("button", name="Explore").click()
    expect(page.get_by_role("heading", name="Alpha")).to_be_visible()


def test_a_formatted_property_reaches_the_rendered_cell(page, module) -> None:
    """p.94's "$100K", on a real object rather than in a unit test.

    Three assertions, because any one alone would pass for the wrong reason:
    the formatted value is there, the raw one is *not* also on the page, and
    the unformatted property beside it still shows its own raw number.
    """
    open_first_object(page, module)
    view = page.locator(".object-view, dialog").first
    expect(view.get_by_text("$100K", exact=True)).to_be_visible()
    expect(view.get_by_text("100000", exact=True)).to_have_count(0)
    expect(view.get_by_text("72.5", exact=True)).to_be_visible()


def test_the_raw_value_stays_reachable(page, module) -> None:
    """The cost of p.94's readability is that the number a person would type
    into a filter is no longer on screen. It is in the cell's tooltip, which is
    the whole reason the formatted branch renders a `title` at all."""
    open_first_object(page, module)
    expect(page.get_by_title("100000").first).to_have_text("$100K")


def test_a_formatter_can_be_drawn_and_it_changes_what_a_reader_sees(page, module) -> None:
    """The builder half: p.95's editor and p.96's preview, then the change
    landing on an object.

    Driven end to end rather than asserted on the dialog, because a Format
    dialog that writes a formatter nowhere is exactly what this test exists to
    catch.
    """
    open_type_editor(page, module)

    # `weight` is the fourth property row, and it is the unformatted one.
    page.get_by_role("button", name="Property 4 format").click()
    page.get_by_test_id("format-on").select_option("on")
    page.get_by_test_id("format-style").select_option("unit")

    # The editor invents no unit, so Apply is shut until one is named - the
    # same rule the server enforces, checked where the answer can still be
    # changed rather than as a 422 after the dialog has closed.
    expect(page.get_by_test_id("format-save")).to_be_disabled()
    expect(page.get_by_test_id("format-problem")).to_contain_text("needs a unit")
    page.get_by_test_id("format-unit").fill("kilogram")
    expect(page.get_by_test_id("format-save")).to_be_enabled()

    # p.96: "As you select the available formatting options, you will see a
    # preview for how values of the property will be rendered."
    page.get_by_test_id("format-sample").fill("72.5")
    expect(page.get_by_test_id("format-preview")).to_have_text("72.5 kg")

    page.get_by_test_id("format-save").click()
    page.get_by_role("button", name="Save", exact=True).click()

    open_first_object(page, module)
    expect(page.get_by_text("72.5 kg", exact=True).first).to_be_visible()


def test_a_string_property_is_not_offered_a_formatter(page, module) -> None:
    """p.95: the options you see depend on the property's base type. A Format
    button on a string would open a dialog whose every answer the server
    refuses - a Save button that is a trap. `name` is the second row."""
    open_type_editor(page, module)
    # **Presence first, and it is not a style point.** `to_have_count(0)` is
    # satisfied by a dialog that has not rendered yet, so asserting the absence
    # first made this test pass against a build where *every* property offered
    # a Format button - the check could not fail. Waiting for the numeric row's
    # button is what makes the string row's silence mean something.
    expect(page.get_by_role("button", name="Property 3 format")).to_be_visible()
    expect(page.get_by_role("button", name="Property 2 format")).to_have_count(0)


def test_editing_an_object_type_does_not_clear_a_formatter(page, module) -> None:
    """**The failure this editor already carries a comment about**, with a
    second setting able to hit it. The edit dialog rebuilds every property from
    the type, so any setting it forgets to carry is silently reset by somebody
    changing something else - a loss with no error and no trace.

    Runs after the drawing test, so there are two formatters to lose.
    """
    open_type_editor(page, module)
    # Touch something with nothing to do with properties at all, and save.
    page.get_by_role("textbox", name="Description", exact=False).fill("Edited")
    page.get_by_role("button", name="Save", exact=True).click()

    open_first_object(page, module)
    expect(page.get_by_text("$100K", exact=True).first).to_be_visible()
    expect(page.get_by_text("72.5 kg", exact=True).first).to_be_visible()
