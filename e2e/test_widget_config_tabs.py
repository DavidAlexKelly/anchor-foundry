"""The three widget-configuration tabs (parity `workshop.md` §2; Foundry p.65–68).

Foundry splits a widget's configuration three ways, and the split says what kind
of statement each control is: **Widget setup** for input and output variables and
the widget's own options, **Metadata** for the name and the raw JSON, **Display**
for sizing.

Two of the three are worth a browser and one is not. The Widget setup tab is the
panel that already existed, moved behind a tab; a test that it still renders is
covered by every other suite here that opens a settings panel. What could only be
settled by driving the real thing:

**Does Craft.js persist `custom` through serialize and reload?** Both the rename
and the sizing config live in a node's `custom`, not its props, and if
`query.serialize()` dropped it the symptom would be a control that works
perfectly until you reload — which is exactly the class of silent failure this
repo keeps finding. Reading the library's source would not settle it as well as
saving and reloading does.

**Does a Display change actually alter a rendered height?** §12's wording is
"a Display sizing change alters computed height", and the point of the phrasing
is that a stored number nothing reads is not a feature.
"""
from __future__ import annotations

import json

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_builder, settled

ROWS = 30


@pytest.fixture
def module(api):
    """One tall table, so a max-height has something to clip.

    Thirty rows rather than three: an "Auto (max)" of 120px has to be visibly
    smaller than the natural height or the assertion would pass against a
    widget that ignored it entirely.

    **Per test, not per module**, and that is not a preference. Four of the
    tests below *save* onto this module - an edited column list, a removed
    prop, a rename, a stored height - so a shared one hands each test whatever
    the last one left behind. The symptom was the suite passing in isolation
    and failing in company, with a different subset failing each run: the
    sizing test's `natural > 240` guard depends on a column list an earlier
    test had rewritten. This repo has now paid for the same shared-mutating-
    fixture bug three times (§118, the versions dialog, and here); a test that
    saves gets its own module.
    """
    mod = Module(api, "Config tabs")
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": f"R{i}", "name": f"Row {i}"} for i in range(1, ROWS + 1)],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "id,name",
                              "pageSize": 50}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


@pytest.fixture(scope="module")
def plain_module(api):
    """A module nothing in this file configures, for the default-state check."""
    mod = Module(api, "Config tabs (untouched)")
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "PLAIN"}},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def select_widget(page):
    """Select the table so the settings panel is showing.

    Through the Layout panel rather than by clicking the widget: a click on the
    canvas lands on whatever is under the pointer - a table cell, a header - and
    Craft selects from the connected element, so it is a coin toss which node
    ends up selected. The tree row names the node it selects.
    """
    page.locator(".canvas-tree-row").first.click()
    expect(page.get_by_role("tab", name="Widget setup")).to_be_visible()


def header_count(page) -> int:
    """The table's column count.

    Read rather than assumed: the widget draws a title column of its own
    alongside the configured ones, so "two columns configured" is not "two
    `<th>`". Every assertion below is relative to this for that reason.
    """
    return page.locator(".canvas-block table thead th").count()


def tab(page, name: str):
    page.get_by_role("tab", name=name).click()


def save(page):
    """Click Save **and wait for it to land**.

    Every caller reloads straight afterwards, and a reload that beats the PUT
    throws the edit away - the page comes back showing what the server still
    has, which reads exactly like a feature that does not persist. In isolation
    the write is fast enough to hide it; under a full-file run it is not, which
    is why this file failed in company and passed alone with a different subset
    each time.

    The builder already says when the write has landed - the version line gains
    "· saved" on success - so this waits for the application's own statement
    rather than for a sleep.
    """
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")


def test_the_panel_offers_foundrys_three_tabs(page, module):
    """Named exactly as p.65–68 names them. An earlier roadmap draft guessed
    'Widget setup / Display / Actions' and was wrong on two of three, which is
    why the names are asserted rather than the count."""
    open_builder(page, module)
    select_widget(page)
    for name in ("Widget setup", "Metadata", "Display"):
        expect(page.get_by_role("tab", name=name)).to_be_visible()


def test_the_raw_json_shows_the_widgets_stored_configuration(page, module):
    """p.68: it "displays how the current widget's setup is stored in JSON".

    Asserting on a parsed prop rather than on the text, so the test is about the
    configuration being *there* and not about how it is formatted.
    """
    open_builder(page, module)
    select_widget(page)
    tab(page, "Metadata")
    raw = page.get_by_test_id("widget-raw-json")
    expect(raw).to_be_visible()
    props = json.loads(raw.input_value())
    assert props["objectSetVariable"] == "v_all", props
    assert props["columns"] == "id,name", props


def test_editing_the_raw_json_changes_the_widget_and_survives_a_reload(page, module):
    """The round trip §12 asks for, and the reason this needs a browser: the
    edit has to reach the rendered widget *and* come back after a save."""
    open_builder(page, module)
    select_widget(page)
    tab(page, "Metadata")

    raw = page.get_by_test_id("widget-raw-json")
    props = json.loads(raw.input_value())
    props["columns"] = "id"
    before = header_count(page)
    raw.fill(json.dumps(props, indent=2))
    page.get_by_role("button", name="Apply", exact=True).click()

    # One column fewer than before. The widget read the edit.
    eventually(lambda: header_count(page), lambda n: n == before - 1,
               what="one column fewer after the raw edit")

    save(page)
    page.reload()
    settled(page)
    eventually(lambda: header_count(page), lambda n: n == before - 1,
               what="one column fewer still, after a reload")
    assert not no_console_errors(page)


def test_removing_a_prop_in_the_raw_json_actually_removes_it(page, module):
    """**Replace, not merge**, and this is the only assertion that can tell the
    difference. Every other raw-JSON test changes a value, which a merge applies
    just as happily — so a merging implementation passed all of them. What a
    merge cannot do is *delete*: the key would come back, and the editor would
    be showing a configuration that is not the widget's.
    """
    open_builder(page, module)
    select_widget(page)
    tab(page, "Metadata")

    raw = page.get_by_test_id("widget-raw-json")
    props = json.loads(raw.input_value())
    assert "pageSize" in props, props
    del props["pageSize"]
    raw.fill(json.dumps(props, indent=2))
    page.get_by_role("button", name="Apply", exact=True).click()

    # Re-read from the editor, which renders the node's *current* props.
    eventually(lambda: json.loads(page.get_by_test_id("widget-raw-json").input_value()),
               lambda p: "pageSize" not in p, what="the removed prop staying removed")


def test_malformed_json_is_refused_and_says_so(page, module):
    """Reported rather than swallowed. A raw editor that silently discarded a
    bad edit would lose work with no sign it had."""
    open_builder(page, module)
    select_widget(page)
    tab(page, "Metadata")

    raw = page.get_by_test_id("widget-raw-json")
    before = raw.input_value()
    columns = header_count(page)
    raw.fill("{ not json")
    page.get_by_role("button", name="Apply", exact=True).click()

    # Not `get_by_role("alert")`: Next.js renders its own route announcer with
    # that role, so the bare query is ambiguous and fails on strict mode
    # rather than on the thing under test.
    expect(page.locator(".canvas-raw-json-error")).to_be_visible()
    # And the widget is untouched: still drawing, same columns.
    assert header_count(page) == columns

    page.get_by_role("button", name="Revert", exact=True).click()
    assert json.loads(raw.input_value()) == json.loads(before)


def test_renaming_a_widget_renames_it_in_the_layout_panel(page, module):
    """p.68: a rename "will affect how the current widget is referenced through
    Workshop, most notably as a component in the Layout panel"."""
    open_builder(page, module)
    select_widget(page)
    tab(page, "Metadata")
    page.get_by_test_id("widget-name").fill("Site register")

    layout_panel = page.locator(".canvas-layout-tree")
    eventually(lambda: layout_panel.inner_text(), lambda t: "Site register" in t,
               what="the renamed widget in the Layout panel")

    save(page)
    page.reload()
    settled(page)
    eventually(lambda: layout_panel.inner_text(), lambda t: "Site register" in t,
               what="the rename surviving a reload")


def test_absolute_sizing_changes_the_rendered_height(page, module):
    """§12's assertion, and the one that makes Display a feature rather than a
    stored number: a widget told to be 120px tall is 120px tall."""
    open_builder(page, module)
    select_widget(page)

    natural = page.locator(".canvas-block").first.bounding_box()["height"]
    assert natural > 240, f"the fixture needs a tall widget to clip: {natural}"

    tab(page, "Display")
    page.get_by_test_id("display-mode").select_option("absolute")
    page.get_by_test_id("display-height").fill("120")

    sized = page.locator(".canvas-sized")
    expect(sized).to_have_attribute("data-sizing", "absolute")
    eventually(lambda: sized.bounding_box()["height"], lambda h: abs(h - 120) < 2,
               what="the widget at its absolute height")

    # And it is the *stored* configuration, not a transient style.
    save(page)
    page.reload()
    settled(page)
    eventually(lambda: page.locator(".canvas-sized").bounding_box()["height"],
               lambda h: abs(h - 120) < 2, what="the height after a reload")


def test_auto_max_clips_a_tall_widget_and_scrolls(page, module):
    """p.68: Auto (max) scales "based on its contents while setting a max
    height". So the height is the maximum and the content is still all there —
    a version that truncated the rows would pass a height check and be wrong."""
    open_builder(page, module)
    select_widget(page)
    tab(page, "Display")
    page.get_by_test_id("display-mode").select_option("auto")
    page.get_by_test_id("display-max").fill("150")

    sized = page.locator(".canvas-sized")
    eventually(lambda: sized.bounding_box()["height"], lambda h: h <= 152,
               what="the clipped height")
    # Every row is still rendered; it scrolls rather than dropping them.
    expect(page.locator(".canvas-block table tbody tr")).to_have_count(ROWS)
    assert sized.evaluate("el => el.scrollHeight > el.clientHeight"), "it should scroll"


def test_the_default_adds_no_wrapper_at_all(page, plain_module):
    """The passthrough that keeps this free for every module that configures no
    sizing. An inert `<div>` around every widget is not nothing: it is an extra
    element in every flex chain in the document.

    **Its own module**, because the tests above save sizing onto the shared one
    - and a claim about the default cannot be checked against a module that has
    since been configured. The first version of this shared the fixture and
    failed for exactly that reason.
    """
    open_builder(page, plain_module)
    # Presence before absence — the widget is drawn, *then* there is no wrapper.
    expect(page.locator(".canvas-block").first).to_be_visible()
    expect(page.locator(".canvas-sized")).to_have_count(0)
