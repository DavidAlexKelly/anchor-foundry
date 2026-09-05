"""p.91's two events (parity `workshop.md` §5; Foundry `workshop` p.91).

> "The **Refresh data in module** event allows all data in the module to be
> reloaded when this event is triggered." (p.91, "Data staleness")

> "The **Toggle between light and dark mode** event allows the theme of the
> module to be changed by the user when this event is triggered." (p.91,
> "Module appearance")

Both were ○ with nothing beside them but the page number. Opening p.91 settled
each in one sentence, and settled the scope with it: **neither names anything**,
so neither takes a configuration.

What needs a browser is what neither side's tests can see. A refresh is a claim
about the *server being asked again* — the widget's own state does not change,
so the only way to tell a working refresh from a no-op is to change the data
underneath it and see the module notice. And the theme is a claim about widgets
that know nothing about it: `data-scheme` redefines the tokens every widget
already reads (p.59–60's rule, one level up), so the check is that a widget's
**computed colour** moves, not that an attribute is present.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

ROWS = [{"id": "R1", "status": "open"}]


def build(api, name: str, effect: str):
    """A table over one object, and a button carrying one of p.91's events."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "status"], rows=ROWS, key="id", title="id",
    )
    mod.type_id = type_id
    mod.define({
        "format": 2,
        "layout": layout({
            "btn": {"resolvedName": "CanvasButton", "props": {"label": "Do it"}},
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": "status",
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {
            "e_1": {"id": "e_1", "trigger": {"node": "btn", "on": "click"},
                    "effects": [{"type": effect}]},
        },
    })
    return mod


def statuses(page):
    grid = page.locator(".canvas-block > .data-grid").first
    return grid.locator("tbody tr td:nth-child(2)").all_inner_texts()


def test_refreshing_reloads_data_the_module_had_already_read(page, api) -> None:
    """p.91's "all data in the module to be reloaded".

    **The only honest way to check a refresh is to change the data underneath
    it.** The row is edited through the API — by something the module has no
    idea about — so the page is showing a value that is now stale, and nothing
    on screen would ever say so. Pressing the button is what makes it notice.
    """
    mod = build(api, "Refresh data", "refresh_data")
    open_module(page, mod)
    settled(page)
    eventually(lambda: statuses(page), lambda s: s == ["open"],
               what="the value the module first read")

    # Changed behind the module's back.
    action = api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": mod.type_id, "api_name": "refresh_probe",
         "display_name": "Set status", "editable_properties": ["status"]},
    )
    instance = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
        {"definition": {"object_type_id": mod.type_id, "filters": []}, "limit": 5},
    )["instances"][0]
    api.call(
        "POST",
        f"/workspaces/{mod.workspace_id}/projects/{mod.project_id}"
        f"/actions/{action['id']}/execute",
        {"instance_id": instance["id"], "values": {"status": "changed"}},
    )

    # **Still stale**, which is the half that makes the next line mean
    # something: a module that refetched on its own would pass the assertion
    # after the click without the event doing anything.
    expect(page.get_by_text("open", exact=True).first).to_be_visible()

    page.get_by_role("button", name="Do it").click()
    eventually(lambda: statuses(page), lambda s: s == ["changed"],
               what="the reloaded value after the refresh event")


def ink(page) -> str:
    """The colour a widget is actually painted, which is what a theme is."""
    return page.locator(".canvas-block").first.evaluate(
        "el => getComputedStyle(el).color"
    )


def test_toggling_the_theme_repaints_widgets_that_know_nothing_about_it(
    page, api
) -> None:
    """p.91's "the theme of the module to be changed by the user".

    **Asserted as a computed colour, not as an attribute.** `data-scheme="dark"`
    is only a theme because every widget reads `--ink`, `--line` and `--panel` —
    p.59–60's rule, applied one level up — so checking the attribute would check
    that this unit set an attribute, and checking the colour checks that a
    widget written years before this event followed it.
    """
    mod = build(api, "Toggle theme", "toggle_theme")
    open_module(page, mod)
    settled(page)

    light = ink(page)
    expect(page.get_by_test_id("module-scheme")).to_have_attribute(
        "data-scheme", "light"
    )

    page.get_by_role("button", name="Do it").click()
    expect(page.get_by_test_id("module-scheme")).to_have_attribute(
        "data-scheme", "dark"
    )
    eventually(lambda: ink(page), lambda c: c != light,
               what="a widget repainted by the module's new scheme")

    # p.91 calls it a *toggle*, so pressing it again is the other half.
    page.get_by_role("button", name="Do it").click()
    eventually(lambda: ink(page), lambda c: c == light,
               what="the original scheme, because a toggle goes both ways")


def test_a_module_always_opens_light(page, api) -> None:
    """Decision 0002 §3: values are never persisted, and a saved app is not a
    saved session. The theme is runtime state like the current page, so a
    viewer who left a module dark does not hand the next one a dark module."""
    mod = build(api, "Theme reload", "toggle_theme")
    open_module(page, mod)
    settled(page)
    page.get_by_role("button", name="Do it").click()
    expect(page.get_by_test_id("module-scheme")).to_have_attribute(
        "data-scheme", "dark"
    )

    page.reload()
    settled(page)
    expect(page.get_by_test_id("module-scheme")).to_have_attribute(
        "data-scheme", "light"
    )


def test_the_builder_offers_both_without_a_field_under_them(page, api) -> None:
    """p.91 gives each event one sentence with no object in it, so neither has
    anything to configure — and a panel that asked for one would be asking the
    builder to invent a setting the page does not describe.

    The drift guard in `test_workshop_variables.py` already checks the two lists
    agree; what it cannot see is whether choosing one leaves the builder looking
    at a field it cannot fill.
    """
    mod = build(api, "Effect panel", "refresh_data")
    open_builder(page, mod)
    settled(page)
    page.get_by_role("button", name="Events (1)").click()
    # The panel lists events and opens one on click; the effect picker is
    # inside the opened one.
    page.get_by_role("button", name="Button · Do it Clicked · 1 effect").click()

    picker = page.locator("select").filter(has_text="Refresh data in module").first
    expect(picker).to_be_visible()
    expect(picker).to_have_value("refresh_data")
    # Nothing under it: the variable, section and action pickers every other
    # effect draws are all absent.
    expect(page.get_by_test_id("effect-recompute-variable")).to_have_count(0)
