"""p.133's loop over an array (parity `workshop.md` §1.3; Foundry p.132–134).

> "If the array option is selected, the first configuration is the array to loop
> through variable input. Loop layouts iterate through each entry in the array,
> and each entry is displayed as an instance of the embedded module configured
> in the Module selection step. **Modules are ordered by the entry's position in
> the array.**" (p.133)

The paging arithmetic is checked in
`apps/web/src/components/canvas/loop-array.test.ts`, and the refusals in
`test_workshop_variables.py`. What needs a browser is the thing neither can
see: that a real child module is instantiated **once per entry**, that each copy
receives *its own* entry rather than the array or the first value, and that the
copies come out in the array's order.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, open_module


def child_module(api, name: str):
    """A module whose interface takes one string and shows it.

    `external_id` plus the interface toggle is what publishes a variable
    (p.163), and a loop needs one to hand each entry to.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "t": {"resolvedName": "CanvasText",
                  "props": {"tag": "p", "text": "entry:{{v_each}}"}},
        }),
        "variables": {
            "v_each": {"id": "v_each", "kind": "string", "label": "Each",
                       "external_id": "each", "interface": {"required": False}},
        },
        "events": {},
    })
    return mod


def host_module(api, name: str, child, entries, **loop):
    """`beside=child` puts the host in the *same project*: the server refuses an
    embed whose module is elsewhere, because nothing would be drawn where it
    was placed."""
    props = {
        "source": "array", "arrayVariable": "v_names", "moduleId": child.app_id,
        "itemVariable": "each", "paging": "limit", "maxItems": 12,
        "display": "list",
    }
    props.update(loop)
    mod = Module(api, name, beside=child)
    mod.define({
        "format": 2,
        "layout": layout({
            "loop": {"resolvedName": "CanvasLoopSection", "isCanvas": True, "props": props},
        }),
        "variables": {
            "v_names": {"id": "v_names", "kind": "array", "label": "Names",
                        "element": "string", "default": entries},
        },
        "events": {},
    })
    return mod


def copies(page):
    return page.locator(".canvas-loop-item")


def test_one_copy_per_entry(page, api) -> None:
    """p.133: "Loop layouts iterate through each entry in the array"."""
    child = child_module(api, "Loop array child")
    mod = host_module(api, "Loop array count", child, ["alpha", "beta", "gamma"])
    open_module(page, mod)

    expect(copies(page)).to_have_count(3, timeout=20000)


def test_each_copy_gets_its_own_entry_in_order(page, api) -> None:
    """**The assertion the feature exists for.**

    p.133 orders the copies by position. A loop that handed every copy the
    whole array, or the first entry, would render the right *number* of cards -
    so counting alone would pass against both bugs.
    """
    child = child_module(api, "Loop array child order")
    mod = host_module(api, "Loop array order", child, ["alpha", "beta", "gamma"])
    open_module(page, mod)

    expect(copies(page)).to_have_count(3, timeout=20000)
    expect(copies(page).nth(0)).to_contain_text("entry:alpha")
    expect(copies(page).nth(1)).to_contain_text("entry:beta")
    expect(copies(page).nth(2)).to_contain_text("entry:gamma")


def test_a_repeated_entry_still_gets_its_own_copy(page, api) -> None:
    """**Why position is the key rather than the value.** An array may hold the
    same entry twice, and two copies sharing a React key is a tree that renders
    one of them."""
    child = child_module(api, "Loop array child dupes")
    mod = host_module(api, "Loop array dupes", child, ["same", "same", "other"])
    open_module(page, mod)

    expect(copies(page)).to_have_count(3, timeout=20000)


def test_limit_shows_only_the_first_x(page, api) -> None:
    """p.134: "display only a single page which displays up to the first X…
    array entries"."""
    child = child_module(api, "Loop array child limit")
    mod = host_module(
        api, "Loop array limit", child,
        ["a", "b", "c", "d", "e"], paging="limit", maxItems=2,
    )
    open_module(page, mod)

    expect(copies(page)).to_have_count(2, timeout=20000)
    expect(copies(page).nth(0)).to_contain_text("entry:a")
    # And no pager: p.134's Limit is one page, not the first of several, so
    # entries past the cap are not shown rather than being a click away.
    expect(page.locator(".canvas-loop-pager")).to_have_count(0)


def test_paged_walks_the_entries(page, api) -> None:
    """p.134's other style, and the pager it draws."""
    child = child_module(api, "Loop array child paged")
    mod = host_module(
        api, "Loop array paged", child,
        ["a", "b", "c", "d", "e"], paging="paged", pageSize=2,
    )
    open_module(page, mod)

    expect(copies(page)).to_have_count(2, timeout=20000)
    expect(copies(page).nth(0)).to_contain_text("entry:a")

    page.get_by_role("button", name="Next").first.click()
    expect(copies(page).nth(0)).to_contain_text("entry:c")

    page.get_by_role("button", name="Previous").first.click()
    expect(copies(page).nth(0)).to_contain_text("entry:a")


def test_an_empty_array_says_so(page, api) -> None:
    """Rather than rendering nothing, which looks identical to a loop that is
    broken."""
    child = child_module(api, "Loop array child empty")
    mod = host_module(api, "Loop array empty", child, [])
    open_module(page, mod)

    expect(page.get_by_text("Nothing in that array.")).to_be_visible(timeout=20000)


def test_a_document_with_no_source_prop_still_means_object_set(page, api) -> None:
    """**The regression this whole unit could most easily cause.**

    `source` defaults to the arm that already existed, precisely so that adding
    the setting does not change what a saved module does — and only a document
    written *without* the prop can check that. The builder's own prompt is the
    assertion: a loop that had silently become array-shaped would ask for an
    array instead.
    """
    mod = Module(api, "Loop default source")
    mod.define({
        "format": 2,
        "layout": layout({
            "loop": {"resolvedName": "CanvasLoopSection", "isCanvas": True, "props": {}},
        }),
        "variables": {},
        "events": {},
    })
    open_builder(page, mod)

    expect(page.get_by_text("Loop — choose an object set in Settings")).to_be_visible()
    expect(page.get_by_text("Loop — choose an array in Settings")).to_have_count(0)
