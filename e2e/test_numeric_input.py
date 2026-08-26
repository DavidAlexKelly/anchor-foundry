"""p.468's Numeric Input widget (parity `workshop.md` §10; decision 0011).

> "**Show grouping**: If toggled on, formats the numeric input with a comma
> style thousands separator… **Unit suffix**: … The suffix can be text, an icon
> of choice, or a percent sign. **If the percent sign is selected, the output
> variable of the widget will be the user-entered value divided by 100.**"
> (p.468)

The arithmetic — parsing, grouping, the percent conversion, the round trip — is
checked in `apps/web/src/components/canvas/number-input.test.ts` without a
browser.

What needs one is everything a pure function cannot see: that typing into the
field actually writes the variable, that a variable changed from *elsewhere*
reaches the field, that the field does not fight the person typing into it while
the text is being reformatted, and that the settings panel offers only variables
the widget can legally write to.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict | None = None):
    """One numeric input over one number variable, plus a Text widget showing
    the variable's value so what the widget *stored* is visible on screen.

    The mirror matters: reading the input back only ever confirms the input, and
    p.468's percent case is precisely where the field and the variable hold
    different numbers.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "num": {"resolvedName": "CanvasNumericInput",
                    "props": {"name": "v_amount", "label": "Amount",
                              "grouping": False, "allowReset": False,
                              "prefix": "", "suffix": "none", "suffixText": "",
                              **(props or {})}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "stored: {{v_amount}}"}},
        }),
        "variables": {
            "v_amount": {"id": "v_amount", "kind": "number", "label": "Amount"},
            "v_note": {"id": "v_note", "kind": "string", "label": "Note"},
        },
        "events": {},
    })
    return mod


def field(page):
    return page.get_by_test_id("numeric-input")


def echo(page):
    return page.locator(".canvas-block", has_text="stored:").first


def test_typing_a_number_writes_the_variable(page, api) -> None:
    """The plainest thing the widget exists to do, and the one the unit tests
    cannot assert: that the field is wired to the variable at all."""
    mod = module_with(api, "Numeric basics")
    open_module(page, mod)
    settled(page)

    field(page).fill("42")
    expect(echo(page)).to_contain_text("stored: 42")


def test_clearing_the_field_clears_the_variable_rather_than_zeroing_it(page, api) -> None:
    """**Empty and zero are different answers**, and this is where the
    difference becomes visible: a filter reading a variable somebody cleared
    must not behave like one reading zero."""
    mod = module_with(api, "Numeric clear")
    open_module(page, mod)
    settled(page)

    field(page).fill("7")
    expect(echo(page)).to_contain_text("stored: 7")
    field(page).fill("")
    expect(echo(page)).not_to_contain_text("stored: 0")


def test_a_percent_suffix_stores_the_entered_value_divided_by_a_hundred(page, api) -> None:
    """**p.468's sentence, end to end.** "If the percent sign is selected, the
    output variable of the widget will be the user-entered value divided by
    100."

    The field shows 25 and the variable holds 0.25 — two different numbers on
    one screen, which is the whole reason this widget could not stay a mode of
    the generic parameter control (decision 0011).
    """
    mod = module_with(api, "Numeric percent", {"suffix": "percent"})
    open_module(page, mod)
    settled(page)

    field(page).fill("25")
    expect(echo(page)).to_contain_text("stored: 0.25")
    expect(field(page)).to_have_value("25")
    # And the sign is on the field, so the 25 is not read as twenty-five.
    expect(page.locator(".canvas-number-affix")).to_contain_text("%")


def test_a_percent_value_survives_the_round_trip_through_a_float(page, api) -> None:
    """8.2 ÷ 100 is 0.08199999999999999 in binary, and multiplied back it is
    8.199999999999999. Somebody typing a percentage and looking at the field a
    moment later must see what they typed."""
    mod = module_with(api, "Numeric percent float", {"suffix": "percent"})
    open_module(page, mod)
    settled(page)

    field(page).fill("8.2")
    expect(echo(page)).to_contain_text("stored: 0.082")
    expect(field(page)).to_have_value("8.2")


def test_grouping_formats_the_field_without_rejecting_what_it_typed(page, api) -> None:
    """p.468's "comma style thousands separator".

    The trap is the second half: once the field shows `1,234`, the field has to
    accept `1,234` back — a widget that rejects the text it just rendered is
    unusable the moment somebody edits an existing value.
    """
    mod = module_with(api, "Numeric grouping", {"grouping": True})
    open_module(page, mod)
    settled(page)

    field(page).fill("1234567")
    expect(echo(page)).to_contain_text("stored: 1234567")

    # Edit the grouped text as a person would, commas and all.
    field(page).fill("7,654,321")
    expect(echo(page)).to_contain_text("stored: 7654321")


def test_the_field_does_not_fight_a_half_typed_number(page, api) -> None:
    """`-` and `1.` are states of typing, not values. A field that committed
    them would clear the variable or commit a different number on the keystroke
    between `1` and `1.5`."""
    mod = module_with(api, "Numeric partial")
    open_module(page, mod)
    settled(page)

    field(page).fill("5")
    expect(echo(page)).to_contain_text("stored: 5")
    # Mid-entry: the text stays as typed and the variable keeps its last value.
    field(page).fill("1.")
    expect(field(page)).to_have_value("1.")
    expect(echo(page)).to_contain_text("stored: 5")
    field(page).fill("1.5")
    expect(echo(page)).to_contain_text("stored: 1.5")


def test_a_unit_prefix_and_suffix_are_shown(page, api) -> None:
    """p.468's read-only affixes, on the left and right of the input field."""
    mod = module_with(api, "Numeric units", {
        "prefix": "$", "suffix": "text", "suffixText": "kg",
    })
    open_module(page, mod)
    settled(page)

    affixes = page.locator(".canvas-number-affix")
    expect(affixes).to_have_count(2)
    expect(affixes.first).to_have_text("$")
    expect(affixes.nth(1)).to_have_text("kg")


def test_the_reset_button_appears_only_when_there_is_something_to_clear(page, api) -> None:
    """p.468's "Include option to reset to default value". Over an empty field
    it is a control that does nothing, which reads as a broken one."""
    mod = module_with(api, "Numeric reset", {"allowReset": True})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("numeric-reset")).to_have_count(0)
    field(page).fill("12")
    expect(page.get_by_test_id("numeric-reset")).to_be_visible()
    page.get_by_test_id("numeric-reset").click()
    expect(field(page)).to_have_value("")


def test_the_reset_button_is_absent_unless_it_is_configured(page, api) -> None:
    """The toggle is off by default, so the button is not there at all."""
    mod = module_with(api, "Numeric no reset")
    open_module(page, mod)
    settled(page)

    field(page).fill("12")
    expect(page.get_by_test_id("numeric-reset")).to_have_count(0)


def test_the_settings_panel_offers_only_number_variables(page, api) -> None:
    """The widget writes a number. Offering a string variable would produce a
    document the server accepts and a value nothing downstream can use — the
    same reason every other widget's picker is filtered by kind."""
    mod = module_with(api, "Numeric settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Numeric input").first.click()
    picker = page.get_by_test_id("numeric-variable")
    expect(picker).to_be_visible()
    options = picker.locator("option")
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Amount" in labels
    assert "Note" not in labels, labels


def test_the_percent_setting_says_what_it_does_to_the_variable(page, api) -> None:
    """p.468 is explicit that the percent suffix is not a display option. Said
    in the panel rather than discovered by an author whose numbers are all a
    hundred times too small."""
    mod = module_with(api, "Numeric percent hint")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Numeric input").first.click()
    page.get_by_test_id("numeric-suffix").select_option("percent")
    expect(page.locator(".field-hint", has_text="divided by 100")).to_be_visible()
