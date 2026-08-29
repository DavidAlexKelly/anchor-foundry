"""p.274's Object Set Title widget (parity `workshop.md` §10).

> "The Object Set Title widget displays a summary of a given object set as a
> title… **Contains single object**: If toggled on, the widget will display the
> title of the single object from the inputted object set. If toggled off, the
> widget will display the title of the object type and the total count of
> objects… **Render widget when the object set is empty** — No: Default option.
> Widget will not render in the module view if the inputted object set is
> empty." (p.274)

The string and the render decision are in
`apps/web/src/components/canvas/object-set-title.test.ts`, mutation-tested
without a browser.

**What needs one is everything the string is made of**: the count comes from a
server-side evaluation of the set, the single object's title comes from the
object type's *title property* (a second fetch, joined to an instance), and
p.274's empty rule is a widget that has to be absent — which is the one claim
that cannot be checked by looking at what a function returned.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "S1", "region": "north", "name": "Alpha site"},
    {"id": "S2", "region": "north", "name": "Bravo site"},
    {"id": "S3", "region": "south", "name": "Charlie site"},
]


def build(api, name: str, props: dict | None = None, *, filters=None):
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "region", "name"], rows=ROWS, key="id", title="name"
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "title": {
                "resolvedName": "CanvasObjectSetTitle",
                "props": {"objectSetVariable": "v_set", "single": False,
                          "showIcon": False, "titleOverride": "",
                          "renderWhenEmpty": False, "placeholderTypeId": None,
                          **(props or {})},
            },
            # A neighbour, so "the title widget did not render" is
            # distinguishable from "the module did not render".
            "mark": {"resolvedName": "CanvasText",
                     "props": {"tag": "p", "text": "MODULE RENDERED"}},
        }),
        "variables": {
            "v_set": {"id": "v_set", "kind": "object_set", "label": "The set",
                      "object_set": object_set(type_id, filters)},
        },
        "events": {},
    })
    mod.type_id = type_id
    return mod


def title(page):
    return page.get_by_test_id("set-title")


def test_a_set_reads_as_its_type_and_a_count(page, api) -> None:
    """p.274's default: "the title of the object type and the total count"."""
    mod = build(api, "Set title count")
    open_module(page, mod)
    settled(page)

    expect(title(page)).to_contain_text("3")
    expect(title(page)).to_contain_text("Seed")


def test_a_narrowed_set_counts_what_it_holds(page, api) -> None:
    """The count is the *set's*, not the type's — which is the difference
    between summarising an object set and naming an object type."""
    mod = build(api, "Set title narrowed",
                filters=[{"property": "region", "op": "eq", "value": "north"}])
    open_module(page, mod)
    settled(page)

    expect(title(page)).to_contain_text("2")


def test_a_single_object_set_reads_as_that_object(page, api) -> None:
    """p.274's Contains single object: "the title of the single object".

    **The title comes from the object type's title property**, which is a
    second fetch joined to an instance — the widget has an object and a type
    and has to put them together to get one string.
    """
    mod = build(api, "Set title single", {"single": True},
                filters=[{"property": "id", "op": "eq", "value": "S3"}])
    open_module(page, mod)
    settled(page)

    expect(title(page)).to_have_text("Charlie site")


def test_an_override_replaces_the_type_and_count(page, api) -> None:
    mod = build(api, "Set title override", {"titleOverride": "Open alerts"})
    open_module(page, mod)
    settled(page)

    expect(title(page)).to_have_text("Open alerts")


def test_an_override_does_not_rename_a_single_object(page, api) -> None:
    """p.274 says the override is "only available when Contains single object is
    disabled". A document can hold both — one click in the panel leaves the
    override behind — and the *value* has to honour the rule, not just the
    panel that stopped offering it."""
    mod = build(api, "Set title override ignored",
                {"single": True, "titleOverride": "Open alerts"},
                filters=[{"property": "id", "op": "eq", "value": "S1"}])
    open_module(page, mod)
    settled(page)

    expect(title(page)).to_have_text("Alpha site")


def test_an_empty_set_removes_the_widget(page, api) -> None:
    """p.274: "Widget will not render in the module view if the inputted object
    set is empty."

    **Absence is the assertion**, and it needs the neighbour: a module that
    failed to load also shows no title, and the two look identical without
    something else on the page that did render.
    """
    mod = build(api, "Set title empty",
                filters=[{"property": "region", "op": "eq", "value": "nowhere"}])
    open_module(page, mod)
    settled(page)

    expect(page.get_by_text("MODULE RENDERED")).to_be_visible()
    expect(title(page)).to_have_count(0)


def other_type(api, mod, label: str) -> str:
    """A second object type, named differently from the module's own.

    **The placeholder tests are worthless without it.** The first version used
    the module's own type as the placeholder, so "used the placeholder" and
    "ignored it" produced the same string — the harness killed nothing, which
    is §205's shape: the control value coincided with what it was contrasted
    against. It needs no dataset; a placeholder is only ever a name.
    """
    declared = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-types",
        {
            "api_name": f"{label}_{mod.tag}",
            "display_name": f"{label.title()} {mod.tag}",
            "properties": [{"api_name": "id", "display_name": "Id",
                            "data_type": "string"}],
            "title_property": "id",
        },
    )
    return declared["id"]


def test_an_empty_set_can_be_kept_with_a_placeholder(page, api) -> None:
    """p.274's Yes: "Allows selection of an object type to display as a
    placeholder if the inputted object set is empty"."""
    mod = build(api, "Set title placeholder",
                filters=[{"property": "region", "op": "eq", "value": "nowhere"}])
    stand_in = other_type(api, mod, "placeholder")
    definition = mod.definition()
    definition["layout"]["title"]["props"]["renderWhenEmpty"] = True
    definition["layout"]["title"]["props"]["placeholderTypeId"] = stand_in
    mod.define(definition)

    open_module(page, mod)
    settled(page)

    expect(title(page)).to_be_visible()
    expect(title(page)).to_contain_text("0")
    # **The placeholder type's name, not the set's** — which is the whole point
    # of naming one, and is invisible unless the two differ.
    expect(title(page)).to_contain_text("Placeholder")
    expect(title(page)).not_to_contain_text("Seed")


def test_a_placeholder_does_not_stand_in_for_a_set_that_has_objects(page, api) -> None:
    """p.274 offers the placeholder "if the inputted object set is empty".

    A placeholder that applied always would rename every non-empty set to
    whatever type an author once picked as the stand-in — and it would look
    entirely deliberate.
    """
    mod = build(api, "Set title placeholder unused")
    stand_in = other_type(api, mod, "placeholder")
    definition = mod.definition()
    definition["layout"]["title"]["props"]["renderWhenEmpty"] = True
    definition["layout"]["title"]["props"]["placeholderTypeId"] = stand_in
    mod.define(definition)

    open_module(page, mod)
    settled(page)

    expect(title(page)).to_contain_text("Seed")
    expect(title(page)).not_to_contain_text("Placeholder")
    expect(title(page)).to_contain_text("3")


def test_the_builder_says_why_a_hidden_widget_is_missing(page, api) -> None:
    """**A builder who cannot see the widget cannot select it to change the
    setting back.** p.274's rule is about the module *view*; on the canvas the
    widget says why it would be absent instead of going blank."""
    mod = build(api, "Set title hidden note",
                filters=[{"property": "region", "op": "eq", "value": "nowhere"}])
    open_builder(page, mod)
    settled(page)

    expect(page.get_by_test_id("set-title-hidden")).to_be_visible()


def test_the_icon_is_drawn_only_when_asked_for(page, api) -> None:
    """p.274's Show icon. **A divergence, stated**: the `icon` field holds a
    name like `cube` and this platform has no icon set, so what is drawn is a
    mark in the object type's colour carrying the name as its label."""
    off = build(api, "Set title no icon")
    open_module(page, off)
    settled(page)
    expect(title(page)).to_be_visible()
    expect(page.get_by_test_id("set-title-icon")).to_have_count(0)

    on = build(api, "Set title icon", {"showIcon": True})
    open_module(page, on)
    settled(page)
    expect(page.get_by_test_id("set-title-icon")).to_be_visible()


def test_the_override_field_appears_only_when_it_applies(page, api) -> None:
    """A control that does nothing under the current setting is a control that
    lies about it — p.274 words this one as "only available"."""
    mod = build(api, "Set title settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object set title").first.click()
    expect(page.get_by_test_id("set-title-override")).to_be_visible()

    page.get_by_test_id("set-title-single").check()
    expect(page.get_by_test_id("set-title-override")).to_have_count(0)


def test_the_placeholder_picker_appears_only_when_empty_rendering_is_on(page, api) -> None:
    mod = build(api, "Set title placeholder settings")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object set title").first.click()
    expect(page.get_by_test_id("set-title-placeholder")).to_have_count(0)

    page.get_by_test_id("set-title-render-empty").check()
    expect(page.get_by_test_id("set-title-placeholder")).to_be_visible()
