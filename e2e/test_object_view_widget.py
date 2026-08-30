"""p.259-263's Object View widget (parity `workshop.md` §10).

> "The Object View widget provides detailed information about a single object by
> displaying an embedded object view within a Workshop module. … **Object View
> Mode**: Controls which viewing option is displayed (either standard or
> configured), with an option to toggle between them. … **Hide header**: If
> toggled on, the object view header will be hidden. **Empty state**: Configures
> the appearance when the widget's input variable is empty." (p.259-262)

Which view opens and whether the reader is offered the switch is
`apps/web/src/components/canvas/object-view-widget.test.ts`, mutation-tested
without a browser.

**What needs one is that the widget renders the platform's object view rather
than a Workshop copy of it.** A configured view is a published module rendered
inside a module — two Craft editors, one nested in the other, with the object
arriving through a variable the outer one has never heard of. Nothing short of
a browser can say that happened.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

ROWS = [
    {"id": "C1", "name": "Alpha customer", "region": "north"},
    {"id": "C2", "name": "Beta customer", "region": "south"},
]


@pytest.fixture(scope="module")
def configured(api):
    """An object type with a **configured** view: a published module that reads
    the object through `object_property`.

    A derived read rather than literal text, for `test_configured_object_view`'s
    reason: a paragraph with the answer typed into it would satisfy every
    assertion below without the object ever arriving.
    """
    mod = Module(api, "Object view widget")
    type_id = mod.object_type(
        columns=["id", "name", "region"], rows=ROWS, key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Region: {{v_region}}"}},
        }),
        "variables": {
            "v_obj": {"id": "v_obj", "kind": "single_object", "label": "The customer"},
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                               "config": {"property": "region"}},
            },
        },
        "events": {},
    })
    api.call("PUT", f"{mod.base}/canvas-apps/{mod.app_id}/publish", {"scope": "workspace"})
    api.call(
        "PUT", f"/workspaces/{mod.workspace_id}/object-types/{type_id}/view",
        {"canvas_app_id": mod.app_id, "subject_variable": "v_obj"},
    )
    mod.view_type_id = type_id
    return mod


@pytest.fixture(scope="module")
def plain(api, configured):
    """A second object type with **no** configured view, in the same project.

    The contrast the mode setting needs: without it, "opened the standard view
    because you asked" and "opened it because there was nothing else" are the
    same observation (§205).
    """
    mod = Module(api, "Object view widget plain", beside=configured)
    mod.plain_type_id = mod.object_type(
        columns=["id", "name"], rows=[{"id": "P1", "name": "Plain object"}],
        key="id", title="name",
    )
    return mod


def build(api, host, type_id: str, name: str, props: dict | None = None,
          *, who: str = "C1"):
    mod = Module(api, name, beside=host)
    mod.define({
        "format": 2,
        "layout": layout({
            "ov": {
                "resolvedName": "CanvasObjectViewWidget",
                "props": {"objectSetVariable": "v_set", "viewMode": "configured",
                          "allowToggle": True, "hideHeader": False,
                          "emptyMessage": "", **(props or {})},
            },
        }),
        "variables": {
            "v_set": {
                "id": "v_set", "kind": "object_set", "label": "The object",
                "object_set": object_set(
                    type_id, [{"property": "id", "op": "eq", "value": who}] if who else [],
                ),
            },
        },
        "events": {},
    })
    return mod


def test_it_embeds_the_configured_view_with_the_object_in_it(page, api, configured) -> None:
    """**The whole claim of the widget**: a module rendered inside a module,
    with the object reaching the inner one through a variable the outer module
    never declared. "Region: north" can only appear if that happened."""
    mod = build(api, configured, configured.view_type_id, "Object view configured")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("object-view-widget")).to_be_visible()
    expect(page.get_by_test_id("configured-object-view")).to_be_visible()
    expect(page.get_by_test_id("configured-object-view")).to_contain_text("Region: north")


def test_only_the_first_object_of_a_larger_set_is_shown(page, api, configured) -> None:
    """p.261: "only the first object will be shown if the object set contains
    multiple objects"."""
    mod = build(api, configured, configured.view_type_id,
                "Object view first only", who="")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("configured-object-view")).to_contain_text("Region: north")
    expect(page.get_by_test_id("configured-object-view")).not_to_contain_text("south")


def test_the_standard_mode_opens_the_generated_view(page, api, configured) -> None:
    """p.261's Object View Mode, asserted **on a type that has both** — on a
    type with only the generated view, "you asked for standard" and "there was
    nothing else" produce the same screen."""
    mod = build(api, configured, configured.view_type_id,
                "Object view standard mode", {"viewMode": "standard"})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    expect(page.get_by_test_id("configured-object-view")).to_have_count(0)
    # And it is the real generated view, not a placeholder.
    expect(page.get_by_test_id("standard-object-view")).to_contain_text("Alpha customer")


def test_the_reader_can_switch_between_the_two(page, api, configured) -> None:
    """p.261's "with an option to toggle between them", and `object-views`
    p.2's guarantee inside a module."""
    mod = build(api, configured, configured.view_type_id, "Object view toggle")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("configured-object-view")).to_be_visible()
    page.get_by_role("button", name="Standard view").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    page.get_by_role("button", name=f"App {configured.tag}").click()
    expect(page.get_by_test_id("configured-object-view")).to_be_visible()


def test_the_switch_can_be_withheld(page, api, configured) -> None:
    """p.261 makes the toggle a builder's choice. Turning it off has to remove
    the control rather than merely hide the other view — a button that no
    longer works would be worse than one that is not there."""
    mod = build(api, configured, configured.view_type_id,
                "Object view no toggle", {"allowToggle": False})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("configured-object-view")).to_be_visible()
    expect(page.get_by_role("button", name="Standard view")).to_have_count(0)
    expect(page.get_by_role("button", name=f"App {configured.tag}")).to_have_count(0)


def test_a_type_with_no_configured_view_shows_the_standard_one_and_no_switch(
    page, api, plain
) -> None:
    """A configured view can be unpublished long after a module was saved. The
    widget still asks for `configured` here, and the object stays viewable —
    which is the failure `object-view.tsx` refuses one level down."""
    mod = build(api, plain, plain.plain_type_id, "Object view plain type",
                {"viewMode": "configured"}, who="P1")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    expect(page.get_by_test_id("standard-object-view")).to_contain_text("Plain object")
    expect(page.get_by_role("button", name="Standard view")).to_have_count(0)


def test_the_header_can_be_hidden(page, api, plain) -> None:
    """p.262's Hide header. Asserted both ways round on the same object, so the
    absence is about the setting rather than about a view that never had one."""
    shown = build(api, plain, plain.plain_type_id, "Object view header shown",
                  {"viewMode": "standard"}, who="P1")
    open_module(page, shown)
    settled(page)
    expect(page.locator(".sov-head")).to_be_visible()
    expect(page.locator(".sov-title")).to_have_text("Plain object")

    hidden = build(api, plain, plain.plain_type_id, "Object view header hidden",
                   {"viewMode": "standard", "hideHeader": True}, who="P1")
    open_module(page, hidden)
    settled(page)
    expect(page.get_by_test_id("standard-object-view")).to_be_visible()
    expect(page.locator(".sov-head")).to_have_count(0)


def test_an_empty_set_shows_the_configured_message(page, api, configured) -> None:
    """p.262's Empty state. The default and a custom message are both asserted,
    because a widget that ignored the setting would still look correct against
    only one of them."""
    default = build(api, configured, configured.view_type_id,
                    "Object view empty default", who="nobody")
    open_module(page, default)
    settled(page)
    expect(page.get_by_test_id("object-view-empty")).to_have_text("No object to show")

    custom = build(api, configured, configured.view_type_id, "Object view empty custom",
                   {"emptyMessage": "Pick a customer first"}, who="nobody")
    open_module(page, custom)
    settled(page)
    expect(page.get_by_test_id("object-view-empty")).to_have_text("Pick a customer first")
    expect(page.get_by_test_id("object-view-widget")).to_have_count(0)


def test_the_panel_says_whether_the_mode_will_mean_anything(page, api, plain) -> None:
    """The mode setting is only a choice on a type that has both views, and
    which of those a type is cannot be seen from the panel's own select. The
    hint is the only thing that tells a builder their "Configured view" is
    going to render the standard one."""
    mod = build(api, plain, plain.plain_type_id, "Object view panel plain", who="P1")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object view").first.click()
    expect(page.get_by_test_id("object-view-configured-hint")).to_contain_text(
        "no configured view")


def test_the_panel_names_the_configured_view_when_there_is_one(page, api, configured) -> None:
    mod = build(api, configured, configured.view_type_id, "Object view panel configured")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object view").first.click()
    expect(page.get_by_test_id("object-view-configured-hint")).to_contain_text(
        f"App {configured.tag}")
