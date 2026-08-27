"""p.465's Text Input widget (parity `workshop.md` §10; decision 0011).

> "**Placeholder**: Define placeholder text… **Format**: Set the format of the
> input field to a single line, a multi-line text area, or a Markdown editor.
> **Single line** — *Event on enter*: set event(s) to be triggered when the enter
> key is pressed. **Text area** — *Initial height*: set the initial height of the
> text input area." (p.465)

Which settings each format has, the row clamping and the stored value are checked
in `apps/web/src/components/canvas/text-input.test.ts` without a browser.

What needs one is what a pure function cannot see: that typing writes the
variable, that a variable changed elsewhere reaches the field, that the format
actually changes the element rendered — and, the one this unit exists for, that
**pressing enter fires p.465's events on a single line and does not in a text
area**, where the same keypress has to insert a newline instead.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict | None = None, *, submit_events: bool = False):
    """One text input over one string variable, a mirror showing what was
    stored, and optionally a Submitted event that stamps a marker.

    The marker doubles as §202's clock: asserting that enter did *not* fire
    needs a point after which it definitely would have.
    """
    events = {}
    if submit_events:
        events["e_1"] = {
            "id": "e_1", "trigger": {"node": "txt", "on": "submit"},
            "effects": [{"type": "set_variable",
                         "config": {"variable": "v_mark", "value": "fired"}}],
        }
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_note", "label": "Note", "placeholder": "",
                              "format": "line", "rows": 4, **(props or {})}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "stored: [{{v_note}}] mark: {{v_mark}}"}},
        }),
        "variables": {
            "v_note": {"id": "v_note", "kind": "string", "label": "Note"},
            "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
            "v_count": {"id": "v_count", "kind": "number", "label": "Count"},
        },
        "events": {
            **events,
            "e_go": {"id": "e_go", "trigger": {"node": "btn", "on": "click"},
                     "effects": [{"type": "set_variable",
                                  "config": {"variable": "v_mark", "value": "clicked"}}]},
        },
    })
    return mod


def field(page):
    return page.get_by_test_id("text-input")


def echo(page):
    return page.locator(".canvas-block", has_text="stored:").first


def test_typing_writes_the_variable(page, api) -> None:
    """The plainest thing the widget does, and the one a pure function cannot
    assert: that the field is wired to the variable at all."""
    mod = module_with(api, "Text basics")
    open_module(page, mod)
    settled(page)

    field(page).fill("hello")
    expect(echo(page)).to_contain_text("stored: [hello]")


def test_clearing_the_field_stores_nothing_rather_than_an_empty_string(page, api) -> None:
    """Matching p.468's Numeric Input. A variable holding `""` has been *set to
    the empty string*; one holding nothing has no value, and the difference
    shows the moment somebody reads it in a `concat`."""
    mod = module_with(api, "Text clear")
    open_module(page, mod)
    settled(page)

    field(page).fill("hello")
    expect(echo(page)).to_contain_text("stored: [hello]")
    field(page).fill("")
    expect(echo(page)).to_contain_text("stored: []")


def test_the_field_follows_a_variable_changed_from_elsewhere(page, api) -> None:
    """The half of the binding typing can never exercise — §202's gap, not
    repeated here by accident."""
    mod = Module(api, "Text external")
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasTextInput",
                    "props": {"name": "v_note", "label": "Note", "placeholder": "",
                              "format": "line", "rows": 4}},
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Go"}},
            "echo": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "stored: [{{v_note}}] mark: {{v_mark}}"}},
        }),
        "variables": {
            "v_note": {"id": "v_note", "kind": "string", "label": "Note"},
            "v_mark": {"id": "v_mark", "kind": "string", "label": "Mark", "default": "no"},
        },
        "events": {
            "e_go": {"id": "e_go", "trigger": {"node": "btn", "on": "click"},
                     "effects": [
                         {"type": "set_variable",
                          "config": {"variable": "v_note", "value": "from elsewhere"}},
                         {"type": "set_variable",
                          "config": {"variable": "v_mark", "value": "clicked"}},
                     ]},
        },
    })
    open_module(page, mod)
    settled(page)

    field(page).fill("typed")
    expect(echo(page)).to_contain_text("stored: [typed]")
    page.get_by_role("button", name="Go", exact=True).click()
    expect(echo(page)).to_contain_text("mark: clicked")
    expect(field(page)).to_have_value("from elsewhere")


def test_a_placeholder_is_shown(page, api) -> None:
    """p.465's placeholder, "displayed in the input field when no text has been
    inputted by the user"."""
    mod = module_with(api, "Text placeholder", {"placeholder": "Say something"})
    open_module(page, mod)
    settled(page)

    expect(field(page)).to_have_attribute("placeholder", "Say something")


def test_the_single_line_format_renders_an_input(page, api) -> None:
    mod = module_with(api, "Text line")
    open_module(page, mod)
    settled(page)

    expect(page.locator("input[data-testid='text-input']")).to_be_visible()
    expect(page.locator("textarea[data-testid='text-input']")).to_have_count(0)


def test_the_text_area_format_renders_a_textarea_at_the_configured_height(page, api) -> None:
    """p.465's "Initial height", in rows — a divergence stated in
    `text-input.ts`: p.465 does not name a unit, and a pixel height set by an
    author is wrong the moment a viewer's font size differs."""
    mod = module_with(api, "Text area", {"format": "area", "rows": 7})
    open_module(page, mod)
    settled(page)

    area = page.locator("textarea[data-testid='text-input']")
    expect(area).to_be_visible()
    expect(area).to_have_attribute("rows", "7")
    expect(page.locator("input[data-testid='text-input']")).to_have_count(0)


def test_an_unknown_format_still_renders_a_field(page, api) -> None:
    """**A saved document can name a format this build does not have** — an app
    authored against a later version, or one whose Markdown format arrives
    before its editor. A field the viewer can type into is the failure worth
    having; a widget that draws nothing leaves a hole where a field was."""
    mod = module_with(api, "Text unknown format", {"format": "markdown"})
    open_module(page, mod)
    settled(page)

    expect(page.locator("input[data-testid='text-input']")).to_be_visible()
    field(page).fill("still works")
    expect(echo(page)).to_contain_text("stored: [still works]")


def test_enter_fires_the_submitted_events_on_a_single_line(page, api) -> None:
    """**p.465's "Event on enter", end to end** — through the `submit` trigger
    this unit added to the server's vocabulary."""
    mod = module_with(api, "Text submit", submit_events=True)
    open_module(page, mod)
    settled(page)

    field(page).fill("done")
    expect(echo(page)).to_contain_text("stored: [done]")
    field(page).press("Enter")
    expect(echo(page)).to_contain_text("mark: fired")


def test_enter_does_not_fire_in_a_text_area(page, api) -> None:
    """**The rule behind p.465's asymmetry.** In a text area the enter key
    inserts a newline, so a widget that also fired an event on it would be
    fighting the person typing.

    Asserted against a clock rather than a moment: the Go button's own effect
    gives a point after which a `submit` firing would demonstrably have landed.
    """
    mod = module_with(api, "Text area no submit", {"format": "area"}, submit_events=True)
    open_module(page, mod)
    settled(page)

    field(page).fill("line one")
    field(page).press("Enter")
    page.get_by_role("button", name="Go", exact=True).click()
    expect(echo(page)).to_contain_text("mark: clicked")
    # `fired` would have overwritten `clicked` only if enter had triggered it
    # before the click; the click is what proves a full cycle completed.
    expect(echo(page)).not_to_contain_text("mark: fired")


def test_the_settings_panel_offers_only_string_variables(page, api) -> None:
    """The widget writes a string. `v_count` is a number and must not be
    offered — the same rule as every other widget's picker."""
    mod = module_with(api, "Text settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Text input").first.click()
    picker = page.get_by_test_id("text-variable")
    expect(picker).to_be_visible()
    options = picker.locator("option")
    labels = [options.nth(i).inner_text() for i in range(options.count())]
    assert "Note" in labels
    assert "Count" not in labels, labels


def test_the_height_setting_appears_only_for_a_text_area(page, api) -> None:
    """p.465 puts "initial height" under Text area, and a control that does
    nothing on the selected format is a control that lies about the format."""
    mod = module_with(api, "Text height setting")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Text input").first.click()
    expect(page.get_by_test_id("text-rows")).to_have_count(0)
    page.get_by_test_id("text-format").select_option("area")
    expect(page.get_by_test_id("text-rows")).to_be_visible()
    page.get_by_test_id("text-format").select_option("line")
    expect(page.get_by_test_id("text-rows")).to_have_count(0)


def test_the_format_dropdown_offers_only_formats_that_are_built(page, api) -> None:
    """Markdown is p.466's editor and is not built. Offering it as an option
    that drew a plain textarea is what these catalogues exist to prevent."""
    mod = module_with(api, "Text formats")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Text input").first.click()
    options = page.get_by_test_id("text-format").locator("option")
    labels = sorted(options.nth(i).inner_text() for i in range(options.count()))
    assert labels == ["Single line", "Text area"], labels


def test_the_events_panel_offers_submitted_on_a_text_input(page, api) -> None:
    """**The offer and the firing are two halves and each is invisible from
    inside the other** (§194, and §202's `change` gap found the same way). The
    widget firing `submit` is checked above; this is that an author can reach
    it."""
    mod = module_with(api, "Text events panel")
    open_builder(page, mod)
    settled(page)

    page.get_by_role("button", name="Events", exact=False).first.click()
    page.get_by_role("button", name="New event", exact=False).first.click()

    # A new event starts on the first trigger-capable widget, which is the
    # Button - and a Button only has "Clicked". Point it at the text input
    # first, which is also the assertion that the widget is offered at all.
    # Located by position inside the open event rather than by label: the two
    # trigger selects are wrapped in their `<label>`, so the accessible name
    # includes the selected option's text and moves when the selection does.
    body = page.locator(".canvas-event-body")
    body.locator("select").first.select_option(label="Text input · Note")

    options = body.locator("select").nth(1).locator("option")
    labels = sorted(options.nth(i).inner_text() for i in range(options.count()))
    # Both halves p.465 gives a text input: per-keystroke and once-on-enter.
    assert labels == ["Changed", "Submitted"], labels
