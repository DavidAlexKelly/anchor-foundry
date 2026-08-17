"""Conditional formatting (parity `ontology.md` §1.2; Foundry
`object-link-types` p.102-109).

    "Conditional formatting enables the configuration of rules for any property
     and dictates how that property's values will be rendered (e.g. coloring,
     alignment, etc.) in user facing applications." (p.102)

Which rule wins is unit-tested (`apps/web/src/lib/conditional-format.test.ts`)
and which rule is legal is tested on the server. What needs a browser:

* a rule declared on the object type actually reaching a painted cell;
* **the composition with value formatting** - the rule comparing the raw
  number while the reader sees the formatted text, which is the one claim
  neither unit suite can make on its own because it needs both settings on one
  property at once;
* somebody being able to build a rule, in order, with p.105's fallback last.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

GREEN = "rgb(26, 127, 55)"    # #1a7f37
RED = "rgb(185, 28, 28)"      # #b91c1c

# `region` carries nothing at all: it is what the editor test draws a rule on,
# and a property the fixture already configured could not tell "the rule I just
# drew" from "the rule that was already there".
ROWS = [
    {"id": "S1", "name": "Alpha", "value": "100000", "wifi": "true", "region": "north"},
    {"id": "S2", "name": "Beta", "value": "2500", "wifi": "false", "region": "south"},
]


@pytest.fixture(scope="module")
def module(api):
    """p.102's own shape: a flag coloured by its own value, and a number that
    is **both formatted and coloured** - which is the pair this file exists to
    check, because each setting is fine on its own and the interesting question
    is what the rule compares once the other one is on.
    """
    mod = Module(api, "Conditional formatting")
    mod.object_type(
        columns=["id", "name", "value", "wifi", "region"],
        rows=ROWS,
        key="id",
        title="name",
        types={"value": "float", "wifi": "boolean"},
        formats={
            "value": {"kind": "number", "style": "currency", "currency": "USD",
                      "notation": "compact", "maximum_fraction_digits": 0},
        },
        rules={
            # p.103 verbatim: "we assign green if the value of the property
            # is 'true' … and red if it is 'false'."
            "wifi": [
                {"comparison": "boolean", "value": True, "colour": "#1a7f37"},
                {"kind": "always", "colour": "#b91c1c"},
            ],
            # The threshold is 50000, and the *formatted* value is "$100K".
            # A rule handed the formatted text would never be above 50000.
            "value": [
                {"comparison": "numeric_range", "min": 50000, "colour": "#1a7f37"},
                {"kind": "always", "colour": "#b91c1c"},
            ],
        },
    )
    return mod


def open_object(page, module, name: str):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == len(ROWS),
               what="this type's objects, and only this type's")
    rows.filter(has_text=name).first.get_by_role("button", name="Explore").click()
    expect(page.get_by_role("heading", name=name)).to_be_visible()


def colour_of(page, api_name: str) -> str:
    cell = page.locator(f"[data-property='{api_name}'] span").first
    return cell.evaluate("el => getComputedStyle(el).color")


def open_type_editor(page, module):
    """This fixture's own type, filtered by api_name - the objects page lists
    every type in the workspace."""
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    row = page.locator("tbody tr").filter(has_text=f"seed_{module.tag}").first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Edit").click()


def test_a_rule_paints_the_value_it_matches(page, module) -> None:
    """p.103's own pattern: green when the flag is true, and the fallback
    otherwise. Both objects are checked, because "everything is green" would
    pass the first assertion on its own."""
    open_object(page, module, "Alpha")
    assert colour_of(page, "wifi") == GREEN
    open_object(page, module, "Beta")
    assert colour_of(page, "wifi") == RED


def test_a_rule_compares_the_raw_value_while_the_reader_sees_the_formatted_one(
    page, module
) -> None:
    """**The claim neither unit suite can make alone.** `value` carries a
    formatter *and* a rule: the reader sees "$100K", and the rule's threshold
    is 50000. A rule handed the formatted text would compare a string against a
    number and never fire - so the green here is evidence the comparison
    reached the stored 100000."""
    open_object(page, module, "Alpha")
    cell = page.locator("[data-property='value'] span").first
    expect(cell).to_have_text("$100K")
    assert colour_of(page, "value") == GREEN

    # And the object below the threshold takes the fallback, so the rule is
    # discriminating rather than always matching.
    open_object(page, module, "Beta")
    # "$3K", not "$2.5K": the formatter's own `maximum_fraction_digits: 0`
    # rounds it, which is worth pinning here because it is the formatted text
    # and the rule below still read 2500.
    expect(page.locator("[data-property='value'] span").first).to_have_text("$3K")
    assert colour_of(page, "value") == RED


def test_a_rule_can_be_built_and_ordered(page, module) -> None:
    """p.103-105's editor: add a rule, and the fallback has to be last because
    first match wins. The Apply button is what enforces it, which is the same
    refusal the server makes - checked where the answer can still change."""
    open_type_editor(page, module)
    page.get_by_role("button", name="Property 2 rules").click()

    # p.104's "newly created default rule", twice.
    page.get_by_test_id("rule-add").click()
    page.get_by_test_id("rule-add").click()
    page.get_by_test_id("rule-1-kind").select_option("always")

    # An always-true rule that is not last makes rule 2 unreachable, and the
    # editor says so rather than letting it save and be refused.
    expect(page.get_by_test_id("rule-problem")).to_contain_text("can never apply")
    expect(page.get_by_test_id("rule-save")).to_be_disabled()

    page.get_by_role("button", name="Move rule 1 down").click()
    expect(page.get_by_test_id("rule-problem")).to_have_count(0)
    expect(page.get_by_test_id("rule-save")).to_be_enabled()


def test_the_editor_offers_only_the_comparisons_the_property_allows(page, module) -> None:
    """p.105 label C: "Types of comparisons available are based on the type of
    the property." `name` is a string and `value` is a float, and the same
    dropdown has to say different things for each - so the rule reads the
    property it was pointed at rather than the one it paints."""
    open_type_editor(page, module)
    page.get_by_role("button", name="Property 2 rules").click()
    page.get_by_test_id("rule-add").click()

    options = page.get_by_test_id("rule-1-comparison").locator("option")
    expect(options).to_have_count(2)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert labels == ["String comparison", "Is null"], labels

    # Point the same rule at the numeric property, and the choices change.
    page.get_by_test_id("rule-1-property").select_option("value")
    expect(options).to_have_count(3)
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Numeric range" in labels, labels
    assert "String comparison" not in labels, labels
    # And the *selection* moves with them. Leaving the old comparison chosen
    # would be a rule the server refuses, held by a form that looked settled -
    # and the dropdown would be showing a value it no longer offers.
    assert page.get_by_test_id("rule-1-comparison").input_value() == "numeric_range"


def test_a_rule_can_be_drawn_and_it_paints_an_object(page, module) -> None:
    """The whole chain, which the ordering test above stops short of: build a
    rule, apply it, save the type, and look at an object.

    It also carries §157's lesson forward. The edit dialog rebuilds every
    property from the type, so this asserts the *other* properties' rules
    survived a save that was about something else - the failure with no error
    and no trace, now with a third setting able to hit it.
    """
    open_type_editor(page, module)
    # `region` is the fifth property, and the only one nothing else configures.
    page.get_by_role("button", name="Property 5 rules").click()
    page.get_by_test_id("rule-add").click()
    page.get_by_test_id("rule-1-comparison").select_option("string")
    page.get_by_test_id("rule-1-operator").select_option("is_exactly")
    page.get_by_test_id("rule-1-value").fill("north")
    page.get_by_test_id("rule-1-colour").fill("#1a7f37")

    # p.106's preview, against a value somebody types rather than against an
    # object - the same evaluator, so "which rule wins" is answered here.
    page.get_by_test_id("rule-sample").fill("north")
    expect(page.get_by_test_id("rule-preview")).to_have_css("color", GREEN)

    page.get_by_test_id("rule-save").click()
    page.get_by_role("button", name="Save", exact=True).click()

    open_object(page, module, "Alpha")
    assert colour_of(page, "region") == GREEN
    # The rules the fixture declared are still there, on a property this edit
    # never touched.
    assert colour_of(page, "wifi") == GREEN

    open_object(page, module, "Beta")
    # **Not "a different colour" - no element at all.** An unmatched value is
    # rendered as bare text, deliberately: an unstyled wrapper around every
    # cell of every table is a lot of DOM for nothing. So the evidence that no
    # rule fired is the absence of the span, and asserting a colour here would
    # be waiting thirty seconds for something that is never coming.
    expect(page.locator("[data-property='region'] span")).to_have_count(0)
    expect(page.locator("[data-property='region']")).to_contain_text("south")
