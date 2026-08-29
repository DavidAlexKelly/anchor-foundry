"""p.314-319's Markdown widget (parity `workshop.md` §11).

> "Input data: Text/Variable… **Text**: If the text option is chosen, a builder
> can directly enter the input Markdown text they'd like to display into the
> configuration panel. **Variable**: If the variable option is chosen, a string
> variable can be chosen as the input Markdown text to be displayed." (p.316)

The parsing is all in `apps/web/src/components/canvas/markdown.test.ts`, where
p.318's syntax table is a table-driven test and a mutation harness has been over
every branch. None of that needs a browser.

**What needs one is the claim the whole design rests on**: that this widget
renders a *tree of elements* rather than a string of markup. A parser can be
tested for what it returns; only a browser can be asked whether an author's
`<script>` became a script. Everything else here is wiring — that the variable
source arrives through a server resolve, that p.317's toggles reach the DOM, and
that a refused URL is still visible to the person who typed it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module, settled


def module_with(api, name: str, props: dict | None = None):
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown",
                   "props": {"source": "text", "text": "", "textVariable": "",
                             "monospace": False, "scrolling": False,
                             "wordWrap": True, "breaks": True, "alignment": "left",
                             **(props or {})}},
        }),
        "variables": {
            "v_doc": {"id": "v_doc", "kind": "string", "label": "Doc",
                      "default": "# From a variable\n\nwith **bold** in it"},
            "v_name": {"id": "v_name", "kind": "string", "label": "Name",
                       "default": "Ada"},
        },
        "events": {},
    })
    return mod


def body(page):
    return page.get_by_test_id("markdown")


def test_typed_markdown_becomes_elements(page, api) -> None:
    """The baseline: a heading is an `<h1>`, not a line beginning with a hash."""
    mod = module_with(api, "Markdown basics", {
        "text": "# Title\n\nA paragraph with **bold** and `code`.",
    })
    open_module(page, mod)
    settled(page)

    expect(body(page).locator("h1")).to_have_text("Title")
    expect(body(page).locator("strong")).to_have_text("bold")
    expect(body(page).locator("code")).to_have_text("code")


def test_raw_html_in_the_source_is_shown_as_text(page, api) -> None:
    """**The claim the hand-rolled parser exists to make.**

    An app's Markdown is written by one person and read by the whole workspace,
    so an author is not automatically trusted by their readers. A renderer that
    emitted an HTML string would need a sanitiser here and would be one
    misconfiguration from executing this. There is no string: the parser
    produces objects, React renders them as text children, and the characters
    below arrive as characters.
    """
    mod = module_with(api, "Markdown html", {
        "text": "<script>window.__pwned = 1</script>\n\n<b>not bold</b>",
    })
    open_module(page, mod)
    settled(page)

    expect(body(page)).to_contain_text("<script>")
    expect(body(page)).to_contain_text("<b>not bold</b>")
    assert body(page).locator("script").count() == 0
    assert body(page).locator("b").count() == 0
    # And nothing ran.
    assert page.evaluate("window.__pwned === undefined") is True


def test_a_link_is_a_link_and_a_refused_one_is_not(page, api) -> None:
    """p.318's Link row, and the rule `safeHref` shares with the server's
    `open_url`: an author may not hand a reader a scheme this platform will not
    navigate to. A refused URL stays **visible as its own source text**, so the
    author can see what was rejected rather than watching it disappear."""
    mod = module_with(api, "Markdown links", {
        "text": "[good](https://example.test/page) and [bad](javascript:alert(1))",
    })
    open_module(page, mod)
    settled(page)

    link = body(page).locator("a")
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("href", "https://example.test/page")
    expect(body(page)).to_contain_text("javascript:alert(1)")


def test_the_text_can_come_from_a_variable(page, api) -> None:
    """p.316's "Variable" input, and the part no pure function can stand in for:
    the value arrives through a **server resolve**."""
    mod = module_with(api, "Markdown from variable", {
        "source": "variable", "textVariable": "v_doc",
    })
    open_module(page, mod)
    settled(page)

    expect(body(page).locator("h1")).to_have_text("From a variable")
    expect(body(page).locator("strong")).to_have_text("bold")


def test_typed_text_expands_a_variable_reference(page, api) -> None:
    """`{{v_id}}`, as `CanvasText` has always done — an author moving to this
    widget should not lose it."""
    mod = module_with(api, "Markdown interpolation", {
        "text": "Hello **{{v_name}}**",
    })
    open_module(page, mod)
    settled(page)

    expect(body(page).locator("strong")).to_have_text("Ada")


def test_text_from_a_variable_is_not_scanned_for_references(page, api) -> None:
    """**Data that can name variables is data that reads them.** A string
    variable holds whatever a derivation or an action put there, which may be
    a row out of a dataset; expanding `{{…}}` inside it would let a value
    reach a variable the author never pointed it at."""
    mod = Module(api, "Markdown variable no interpolation")
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown",
                   "props": {"source": "variable", "textVariable": "v_doc",
                             "text": "", "alignment": "left", "breaks": True}},
        }),
        "variables": {
            "v_doc": {"id": "v_doc", "kind": "string", "label": "Doc",
                      "default": "value is {{v_secret}}"},
            "v_secret": {"id": "v_secret", "kind": "string", "label": "Secret",
                         "default": "leaked"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    expect(body(page)).to_contain_text("{{v_secret}}")
    expect(body(page)).not_to_contain_text("leaked")


def test_a_table_renders_with_its_own_column_alignment(page, api) -> None:
    """p.317: explicit per-column alignment "takes precedence over the
    widget-level text alignment setting". The widget says right; the middle
    column says centre and keeps it, and the unmarked column takes the
    widget's."""
    mod = module_with(api, "Markdown table", {
        "alignment": "right",
        "text": "| a | b | c |\n| --- | :---: | --- |\n| 1 | 2 | 3 |",
    })
    open_module(page, mod)
    settled(page)

    cells = body(page).locator("tbody td")
    expect(cells).to_have_count(3)
    assert cells.nth(0).evaluate("e => getComputedStyle(e).textAlign") == "right"
    assert cells.nth(1).evaluate("e => getComputedStyle(e).textAlign") == "center"
    assert cells.nth(2).evaluate("e => getComputedStyle(e).textAlign") == "right"


def test_a_code_block_stays_left_whatever_the_widget_says(page, api) -> None:
    """p.317: "Code blocks remain left-aligned and full-width regardless of the
    selected alignment." Centred code is unreadable, which is why the page says
    so — and why this is asserted against the *computed* style rather than
    against the prop that was set."""
    mod = module_with(api, "Markdown code align", {
        "alignment": "center",
        "text": "centred prose\n\n```\nx = 1\n```",
    })
    open_module(page, mod)
    settled(page)

    prose = body(page).locator("p").first
    assert prose.evaluate("e => getComputedStyle(e).textAlign") == "center"
    code = body(page).locator("pre")
    assert code.evaluate("e => getComputedStyle(e).textAlign") == "left"


def test_break_on_newlines_changes_the_rendered_output(page, api) -> None:
    """p.317's toggle, "the default for new widgets" being on. Off is standard
    Markdown, where a single newline is a space."""
    on = module_with(api, "Markdown breaks on", {"text": "one\ntwo"})
    open_module(page, on)
    settled(page)
    expect(body(page).locator("br")).to_have_count(1)

    off = module_with(api, "Markdown breaks off", {"text": "one\ntwo", "breaks": False})
    open_module(page, off)
    settled(page)
    expect(body(page).locator("br")).to_have_count(0)
    expect(body(page).locator("p")).to_have_text("one two")


def test_a_task_list_shows_its_ticks_and_cannot_be_edited(page, api) -> None:
    """p.318's task list, "supported despite not being standard". The tick is
    what the author *wrote*, so it is shown and disabled: a checkbox a viewer
    could clear would be a control with nowhere to put the answer."""
    mod = module_with(api, "Markdown tasks", {
        "text": "- [ ] todo\n- [x] done\n- plain",
    })
    open_module(page, mod)
    settled(page)

    boxes = body(page).locator("input[type=checkbox]")
    expect(boxes).to_have_count(2)
    expect(boxes.nth(0)).not_to_be_checked()
    expect(boxes.nth(1)).to_be_checked()
    expect(boxes.nth(1)).to_be_disabled()


def test_the_display_toggles_reach_the_widget(page, api) -> None:
    """p.316's monospace and p.317's scrolling and word wrap. Asserted on the
    computed style, because a class name that no rule matches is a toggle that
    does nothing."""
    plain = module_with(api, "Markdown plain", {"text": "words"})
    open_module(page, plain)
    settled(page)
    assert "mono" not in body(page).evaluate("e => getComputedStyle(e).fontFamily").lower()
    assert body(page).evaluate("e => getComputedStyle(e).overflowY") != "auto"

    fancy = module_with(api, "Markdown styled", {
        "text": "words", "monospace": True, "scrolling": True, "wordWrap": False,
    })
    open_module(page, fancy)
    settled(page)
    assert "mono" in body(page).evaluate("e => getComputedStyle(e).fontFamily").lower()
    assert body(page).evaluate("e => getComputedStyle(e).overflowY") == "auto"
    assert body(page).evaluate("e => getComputedStyle(e).overflowWrap") != "anywhere"


def test_the_settings_panel_swaps_the_input_control_with_the_source(page, api) -> None:
    """p.316's two sources ask different questions, and a control that does
    nothing under the selected source is a control that lies about it."""
    mod = module_with(api, "Markdown settings", {"text": "words"})
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Markdown").first.click()
    expect(page.get_by_test_id("markdown-text")).to_be_visible()
    expect(page.get_by_test_id("markdown-variable")).to_have_count(0)

    page.get_by_test_id("markdown-source").select_option("variable")
    expect(page.get_by_test_id("markdown-text")).to_have_count(0)
    expect(page.get_by_test_id("markdown-variable")).to_be_visible()


def test_the_settings_panel_offers_only_string_variables(page, api) -> None:
    """The same rule as every other widget's picker: a Markdown source is a
    string, and offering a timestamp would be offering a binding the server
    would then have to refuse."""
    mod = Module(api, "Markdown settings kinds")
    mod.define({
        "format": 2,
        "layout": layout({
            "md": {"resolvedName": "CanvasMarkdown",
                   "props": {"source": "variable", "text": "", "textVariable": ""}},
        }),
        "variables": {
            "v_doc": {"id": "v_doc", "kind": "string", "label": "Doc"},
            "v_when": {"id": "v_when", "kind": "timestamp", "label": "When"},
        },
        "events": {},
    })
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Markdown").first.click()
    picker = page.get_by_test_id("markdown-variable")
    labels = [picker.locator("option").nth(i).inner_text()
              for i in range(picker.locator("option").count())]
    assert "Doc" in labels and "When" not in labels, labels


def test_the_variable_backing_the_text_counts_as_a_usage(page, api) -> None:
    """§191's drift guard in its other direction: `textVariable` is in the
    server's `REFERENCE_PROPS`, so a variable feeding a Markdown widget cannot
    be deleted out from under it."""
    mod = module_with(api, "Markdown usage", {
        "source": "variable", "textVariable": "v_doc",
    })
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Variables", exact=False).first.click()
    row = page.locator(".vars-row", has_text="Doc").first
    expect(row.locator(".vars-usage")).to_have_text("used 1\u00d7")
