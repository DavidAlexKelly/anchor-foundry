"""p.477–478's User Select (parity `workshop.md` §10).

> "Use the User Select widget for selection of user(s) through a single or
> multi-select dropdown menu." (p.477)

**The first widget whose options are people rather than data.** Everything else
in the browser suite builds an object type and reads it back; this reads the
organisation's directory, which `dev-up.sh` seeds with four users — admin,
editor, owner and viewer — and which `GET /org/members` has always exposed to
every member of the org.

**What needs a browser is that the selection reaches a variable in the shape
p.478 specifies**, and that is asserted through a second widget: a Text widget
interpolating the output variable says what the picker actually wrote, where the
picker's own label would only say what it thinks it wrote.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import eventually, open_builder, open_module, settled, stays

# Seeded by `scripts/dev-up.sh`. **The display names, not the email local
# parts** — the widget prefers `display_name`, which is the whole point of
# `labelOf`, and a test written against "editor" would pass only against a
# widget that had got that wrong.
SEEDED = ["Ada Admin", "Ed Editor", "Odette Owner", "Vi Viewer"]
EDITOR, VIEWER = "Ed Editor", "Vi Viewer"


@pytest.fixture(scope="module")
def base(api):
    """A module to hang User Selects off. No object type: this widget has no
    object set, which is itself worth saying — it is the only picker here that
    does not."""
    return Module(api, "User select base")


def build(api, base, name: str, props: dict | None = None, *, multiple: bool = False):
    """The widget, plus a Text widget interpolating what it wrote."""
    mod = Module(api, name, beside=base)
    mod.define({
        "format": 2,
        "layout": layout({
            "pick": {
                "resolvedName": "CanvasUserSelect",
                "props": {
                    "variable": "v_pick", "groupsVariable": None,
                    "mode": "multiple" if multiple else "single",
                    "allowClear": False, "label": "", "placeholder": "",
                    **(props or {}),
                },
            },
            # **A second widget reading the same variable.** A picker showing
            # the right name while writing the wrong value looks perfect from
            # outside; the interpolation is what makes the write observable.
            "echo": {
                "resolvedName": "CanvasText",
                "props": {"tag": "p", "text": "PICKED[{{v_pick}}]"},
            },
        }),
        "variables": {
            "v_pick": {
                "id": "v_pick", "label": "Who",
                # p.478's two shapes: a string for Single, a string array for
                # Multiple. The variable's *kind* is the setting's consequence.
                "kind": "array" if multiple else "string",
            },
        },
        "events": {},
    })
    return mod


def options(page):
    return page.get_by_test_id("user-select-option")


def option_names(page) -> list[str]:
    got = page.locator('[data-testid="user-select-option"] .canvas-dropdown-title')
    return [(got.nth(i).text_content() or "").strip() for i in range(got.count())]


def open_list(page):
    page.get_by_test_id("user-select-toggle").click()
    expect(page.get_by_test_id("user-select-list")).to_be_visible()


def echo(page) -> str:
    return (page.locator("p", has_text="PICKED[").first.text_content() or "").strip()


def test_it_lists_the_organisations_users(page, api, base) -> None:
    """p.477's dropdown. The seeded four are all `active`, so all four show."""
    mod = build(api, base, "Users list")
    open_module(page, mod)
    settled(page)

    open_list(page)
    names = eventually(lambda: option_names(page), lambda n: len(n) >= len(SEEDED),
                       what="the seeded users")
    for who in SEEDED:
        assert who in names, (who, names)


def test_a_single_selection_writes_one_id_into_a_string_variable(
    page, api, base
) -> None:
    """p.478: "the output variable will be a string variable containing the ID
    of the selected user".

    **Asserted through the echo**, because the id is what downstream widgets
    read and the picker's own label is a display name — a widget that showed the
    right person while writing their name instead of their id would look right
    and break every consumer.
    """
    mod = build(api, base, "Users single")
    open_module(page, mod)
    settled(page)

    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()

    expect(page.get_by_test_id("user-select-value")).to_have_text(EDITOR)
    # A uuid, not a name: `PICKED[]` empty or `PICKED[editor]` would both be
    # wrong, and only one of them looks wrong.
    written = eventually(lambda: echo(page), lambda t: t != "PICKED[]",
                         what="the id in the variable")
    assert "-" in written and EDITOR not in written, written


def test_choosing_again_replaces_rather_than_toggling(page, api, base) -> None:
    """p.478 gives clearing its own control, so a click that sometimes selected
    and sometimes cleared would be two behaviours on one gesture."""
    mod = build(api, base, "Users replace")
    open_module(page, mod)
    settled(page)

    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()
    first = eventually(lambda: echo(page), lambda t: t != "PICKED[]", what="a first id")

    open_list(page)
    options(page).filter(has_text=VIEWER).first.click()
    expect(page.get_by_test_id("user-select-value")).to_have_text(VIEWER)
    second = eventually(lambda: echo(page), lambda t: t != first, what="a different id")
    assert second != "PICKED[]", second


def test_multiple_writes_an_array_and_unticking_removes_one(page, api, base) -> None:
    """p.478's Multiple: "a string array variable containing the ID(s)"."""
    mod = build(api, base, "Users multiple", multiple=True)
    open_module(page, mod)
    settled(page)

    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()
    expect(page.get_by_test_id("user-select-value")).to_have_text(EDITOR)

    # The list stays open while ticking, as the Object Selector's does — the
    # point of Multiple is to choose several.
    options(page).filter(has_text=VIEWER).first.click()
    expect(page.get_by_test_id("user-select-value")).to_have_text("2 selected")

    options(page).filter(has_text=EDITOR).first.click()
    expect(page.get_by_test_id("user-select-value")).to_have_text(VIEWER)


def test_allow_clear_appears_only_when_configured_and_only_with_a_selection(
    page, api, base
) -> None:
    """p.478's Allow clear, and both halves of when it is not there."""
    off = build(api, base, "Users no clear")
    open_module(page, off)
    settled(page)
    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()
    expect(page.get_by_test_id("user-select-clear")).to_have_count(0)

    on = build(api, base, "Users clear", {"allowClear": True})
    open_module(page, on)
    settled(page)
    # Nothing selected yet, so there is nothing to clear.
    expect(page.get_by_test_id("user-select-clear")).to_have_count(0)
    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()
    expect(page.get_by_test_id("user-select-clear")).to_be_visible()
    page.get_by_test_id("user-select-clear").click()
    eventually(lambda: echo(page), lambda t: t == "PICKED[]",
               what="the variable emptied")


def test_clearing_is_absent_in_multiple_mode(page, api, base) -> None:
    """Unticking is how a multiple selection goes away, so a second control
    would be a second answer to one question."""
    mod = build(api, base, "Users multi clear", {"allowClear": True}, multiple=True)
    open_module(page, mod)
    settled(page)
    open_list(page)
    options(page).filter(has_text=EDITOR).first.click()
    expect(page.get_by_test_id("user-select-clear")).to_have_count(0)


def test_the_label_and_placeholder_are_drawn_when_there_are_any(
    page, api, base
) -> None:
    """p.477's two optional strings. Blank is *whitespace*, not the empty
    string: `""` is falsy whether or not it went through the model, so a test
    using it asks nothing (§214's lesson at the Object Dropdown)."""
    blank = build(api, base, "Users blank text", {"label": "   ", "placeholder": "  "})
    open_module(page, blank)
    settled(page)
    expect(page.get_by_test_id("user-select-label")).to_have_count(0)
    expect(page.get_by_test_id("user-select-value")).to_have_text("Select a user...")

    named = build(api, base, "Users named",
                  {"label": "  Owner  ", "placeholder": "  Pick somebody  "})
    open_module(page, named)
    settled(page)
    label = page.get_by_test_id("user-select-label")
    assert (label.text_content() or "") == "Owner", repr(label.text_content())
    expect(page.get_by_test_id("user-select-value")).to_have_text("Pick somebody")


def test_the_placeholder_says_users_in_multiple_mode(page, api, base) -> None:
    mod = build(api, base, "Users multi placeholder", multiple=True)
    open_module(page, mod)
    settled(page)
    expect(page.get_by_test_id("user-select-value")).to_have_text("Select users...")


def test_a_group_filter_naming_nobody_asks_for_nobody(page, api, base) -> None:
    """**The rule the server cannot enforce.** A repeated query parameter has no
    empty form, so "no groups" and "no filter" are the same request — and that
    request answers with the whole organisation. A filtered picker must
    therefore not ask at all until its variable names a group, or it would show
    every user in the org and then narrow.

    The variable here is declared and unset, which is the state every app is in
    on load.
    """
    mod = Module(api, "Users group filter", beside=base)
    mod.define({
        "format": 2,
        "layout": layout({
            "pick": {
                "resolvedName": "CanvasUserSelect",
                "props": {"variable": "v_pick", "groupsVariable": "v_groups",
                          "mode": "single"},
            },
        }),
        "variables": {
            "v_pick": {"id": "v_pick", "kind": "string", "label": "Who"},
            "v_groups": {"id": "v_groups", "kind": "array", "label": "Groups"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    open_list(page)
    expect(page.get_by_test_id("user-select-unfiltered")).to_be_visible()
    # **`stays`, not a single read.** "It never showed the directory" is a
    # negative claim about an async page: a one-shot check runs before the
    # request it is ruling out could have returned (§233).
    stays(lambda: options(page).count(), lambda n: n == 0,
          what="no users while the group filter names none")


def test_the_panel_offers_the_variable_kind_the_mode_needs(page, api, base) -> None:
    """p.478 makes Single a string variable and Multiple a string array. The
    panel offers the matching kind rather than both, because a widget writing an
    array into a string variable is refused on save and one writing a string
    into an array variable looks fine and reads wrong."""
    mod = Module(api, "Users panel", beside=base)
    mod.define({
        "format": 2,
        "layout": layout({
            "pick": {"resolvedName": "CanvasUserSelect",
                     "props": {"variable": None, "mode": "single"}},
        }),
        "variables": {
            "v_str": {"id": "v_str", "kind": "string", "label": "A string"},
            "v_arr": {"id": "v_arr", "kind": "array", "label": "An array"},
        },
        "events": {},
    })
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="User select").first.click()

    picker = page.get_by_test_id("user-select-variable")
    expect(picker.locator("option")).to_have_count(2)
    assert picker.locator("option").evaluate_all(
        "nodes => nodes.map(n => n.textContent.trim())"
    ) == ["Choose…", "A string"]

    page.get_by_test_id("user-select-mode").select_option("multiple")
    expect(picker.locator("option")).to_have_count(2)
    assert picker.locator("option").evaluate_all(
        "nodes => nodes.map(n => n.textContent.trim())"
    ) == ["Choose…", "An array"]


def test_changing_the_mode_clears_the_output_binding(page, api, base) -> None:
    """The two modes hold different kinds of variable, so a `string` binding
    left behind by Single is not a legal Multiple output. Cleared here rather
    than refused on the next save, which is where it would otherwise surface."""
    mod = build(api, base, "Users mode change")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="User select").first.click()

    expect(page.get_by_test_id("user-select-variable")).to_have_value("v_pick")
    page.get_by_test_id("user-select-mode").select_option("multiple")
    expect(page.get_by_test_id("user-select-variable")).to_have_value("")


def test_allow_clear_is_offered_only_for_a_single_selection(page, api, base) -> None:
    mod = build(api, base, "Users clear setting")
    open_builder(page, mod)
    settled(page)
    page.locator(".canvas-tree-row").filter(has_text="User select").first.click()

    expect(page.get_by_test_id("user-select-allow-clear")).to_be_visible()
    page.get_by_test_id("user-select-mode").select_option("multiple")
    expect(page.get_by_test_id("user-select-allow-clear")).to_have_count(0)


def test_the_list_is_inert_in_the_builder(page, api, base) -> None:
    """Picking a user in the builder would write a viewer's selection into the
    document being edited."""
    mod = build(api, base, "Users builder")
    open_builder(page, mod)
    settled(page)
    expect(page.get_by_test_id("user-select-toggle")).to_be_disabled()
