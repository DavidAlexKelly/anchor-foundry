"""Loop layouts, Flow and Toolbar sections (parity `workshop.md` §1.3; p.54, p.129–136).

A loop layout renders a whole *module* per object, which is what separates it
from an Object Table or a Card List:

    "While other object set display widgets come with a fixed set of features,
     the loop layout allows any feature combination available in Workshop to be
     used for the display of each object in the object set." (p.129)

**The claim this file exists to check is per-instance scoping.** p.129: each
embedded module in a loop "functions independently from other embedded module
instances, and has its own variable scope and layout state". A single shared
scope is the failure that would look like it was working — every card would
render, and they would all show the same object. So the child derives its text
from the object it was handed, and three cards must show three different names.

What the server refuses is in `apps/api/tests/test_canvas.py`: an item variable
the child does not publish, one that is not a single object, a cycle through a
loop, and the ordinary interface refusals. Those are settled when the author
saves.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_builder, open_module

NAMES = ["Alpha", "Beta", "Gamma"]

# p.132's property sorts (§231). The ranks are 100, 10, 25 rather than 1, 2, 3
# so that a *numeric* ordering and a *text* one disagree: as text they read 10,
# 100, 25 and as numbers 10, 25, 100. Sorting ascending therefore proves the
# declared type reached the store, not merely that some ordering was applied —
# which is the entire subject of decision 0006.
RANKS = {"Alpha": "100", "Beta": "10", "Gamma": "25"}
BY_RANK = ["Beta", "Gamma", "Alpha"]


@pytest.fixture(scope="module")
def modules(api):
    """A card module that renders the one object it is given, and a host that
    loops a three-object set through it."""
    card = Module(api, "Loop card")
    type_id = card.object_type(
        columns=["id", "name", "rank"],
        rows=[{"id": f"S{i}", "name": name, "rank": RANKS[name]}
              for i, name in enumerate(NAMES, start=1)],
        key="id", title="name", types={"rank": "integer"},
    )
    card.define({
        "format": 2,
        "layout": layout({
            # Interpolated from a variable derived off the handed-in object, so
            # the text is evidence about *which* object this copy received.
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "CARD {{v_name}}"}},
        }),
        "variables": {
            "v_obj": {
                "id": "v_obj", "kind": "single_object", "label": "The object",
                "external_id": "obj",
                "interface": {"display_name": "Object", "required": True},
            },
            "v_name": {
                "id": "v_name", "kind": "string", "label": "Name",
                "derivation": {"transform": "object_property", "inputs": ["v_obj"],
                               "config": {"property": "name"}},
            },
        },
        "events": {},
    })

    host = Module(api, "Loop host", beside=card)
    host.object_type_id = type_id
    host.define({
        "format": 2,
        "layout": layout({
            "loop": {"resolvedName": "CanvasLoopSection",
                     "props": {"objectSetVariable": "v_all", "moduleId": card.app_id,
                               "itemVariable": "obj", "paging": "limit", "maxItems": 12,
                               "display": "list"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return host, card


def cards(page):
    return page.locator(".canvas-loop-item")


def test_a_loop_renders_one_module_per_object(page, modules):
    host, _ = modules
    open_module(page, host)
    eventually(lambda: cards(page).count(), lambda n: n == len(NAMES),
               what="one card per object in the set")
    assert not no_console_errors(page)


def test_each_copy_gets_its_own_object(page, modules):
    """**The assertion the whole feature rests on** (p.129). One shared variable
    scope would render three cards all showing the same name — which looks
    convincingly like a working loop until you read them."""
    host, _ = modules
    open_module(page, host)
    texts = eventually(
        lambda: sorted(t.strip() for t in cards(page).all_inner_texts()),
        lambda got: len(got) == len(NAMES) and all(t.startswith("CARD ") for t in got),
        what="three cards, each naming its own object",
    )
    assert texts == sorted(f"CARD {name}" for name in NAMES), texts


def test_a_loop_with_no_sort_keeps_the_order_it_always_had(page, modules):
    """**The compatibility half of §231.** p.132's sort is new; every loop saved
    before it holds no `sort` at all, and adding a default here would silently
    reorder them. The fallback is the empty string, which sends no `sort` key —
    so the set's own order is what a blank setting means, exactly as before.
    """
    host, _ = modules
    open_module(page, host)
    texts = eventually(
        lambda: [t.strip() for t in cards(page).all_inner_texts()],
        lambda got: len(got) == len(NAMES),
        what="three cards in the set's own order",
    )
    assert texts == [f"CARD {name}" for name in NAMES], texts


def test_a_loop_can_be_ordered_by_a_declared_property(page, modules):
    """p.132: "Property sorts may be applied to the object set being looped
    through to determine the order in which the objects will be displayed in the
    looped layout."

    Set through the panel rather than the document, because the panel is where
    the refusal used to be — this widget carried "sorting by a property is not
    available yet" for ten units after §221 built it.
    """
    host, _ = modules
    open_builder(page, host)
    page.locator(".canvas-tree-row").first.click()
    expect(page.get_by_test_id("loop-sort")).to_be_visible()
    page.get_by_test_id("loop-sort").select_option("rank")

    texts = eventually(
        lambda: [t.strip() for t in cards(page).all_inner_texts()],
        lambda got: len(got) == len(NAMES) and got[0] == f"CARD {BY_RANK[0]}",
        what="the cards reordered by rank, ascending",
    )
    assert texts == [f"CARD {name}" for name in BY_RANK], texts

    page.get_by_test_id("loop-sort").select_option("-rank")
    texts = eventually(
        lambda: [t.strip() for t in cards(page).all_inner_texts()],
        lambda got: len(got) == len(NAMES) and got[0] == f"CARD {BY_RANK[-1]}",
        what="the cards reordered by rank, descending",
    )
    assert texts == [f"CARD {name}" for name in reversed(BY_RANK)], texts


def test_the_loop_sort_offers_only_properties_the_stores_agree_on(page, modules):
    """The picker's list is `property-sort.ts`'s, so `name` — text, refused
    permanently — must not be in it. A widened list breaks nothing until
    somebody picks from it, which is why this asserts the options rather than
    the result of choosing one."""
    host, _ = modules
    open_builder(page, host)
    page.locator(".canvas-tree-row").first.click()
    picker = page.get_by_test_id("loop-sort")
    expect(picker).to_be_visible()
    values = picker.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
    assert values == ["key", "-key", "recent", "oldest", "rank", "-rank"], values


def test_the_limit_paging_style_caps_what_is_drawn(page, modules):
    """p.134: Limit "will display only a single page which displays up to the
    first X objects", where X is Max items to display."""
    host, _ = modules
    open_builder(page, host)
    page.locator(".canvas-tree-row").first.click()
    expect(page.get_by_test_id("loop-max")).to_be_visible()
    page.get_by_test_id("loop-max").fill("2")

    eventually(lambda: cards(page).count(), lambda n: n == 2,
               what="two cards after the limit was lowered")


def test_the_grid_display_lays_the_copies_out_in_columns(page, modules):
    """p.134's Grid option. Asserting a computed layout rather than a class
    name: a class that no rule matched would pass a class assertion and lay out
    as a single column."""
    host, _ = modules
    open_builder(page, host)
    page.locator(".canvas-tree-row").first.click()
    page.get_by_test_id("loop-display").select_option("grid")

    loop = page.locator(".canvas-loop")
    eventually(lambda: loop.evaluate("el => getComputedStyle(el).display"),
               lambda d: d == "grid", what="a grid container")
    columns = loop.evaluate("el => getComputedStyle(el).gridTemplateColumns")
    assert len(columns.split()) > 1, f"more than one column: {columns}"


# ---- Flow and Toolbar sections (p.54) ---------------------------------------
@pytest.fixture(scope="module")
def sections(api):
    """One module with a Flow section and a Toolbar section, each holding three
    widgets, so the two layouts can be told apart by where the widgets land."""
    mod = Module(api, "Flow and toolbar")
    mod.define({
        "format": 2,
        "layout": layout({
            "flow": {"resolvedName": "CanvasSection",
                     "props": {"direction": "flow", "minHeight": 120, "gap": 8},
                     "isCanvas": True,
                     "nodes": ["f1", "f2", "f3"]},
            "f1": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FLOW ONE"},
                   "parent": "flow"},
            "f2": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FLOW TWO"},
                   "parent": "flow"},
            "f3": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "FLOW THREE"},
                   "parent": "flow"},
            "bar": {"resolvedName": "CanvasSection",
                    "props": {"direction": "toolbar", "gap": 8},
                    "isCanvas": True,
                    "nodes": ["b1", "b2", "b3"]},
            "b1": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "BAR ONE"},
                   "parent": "bar"},
            "b2": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "BAR TWO"},
                   "parent": "bar"},
            "b3": {"resolvedName": "CanvasText", "props": {"tag": "p", "text": "BAR THREE"},
                   "parent": "bar"},
        }),
        "variables": {},
        "events": {},
    })
    return mod


def parts_of(page, which: str):
    return page.locator(f".canvas-section--{which} > .canvas-section-parts > .canvas-section-part")


def test_a_flow_section_stacks_and_scrolls(page, sections):
    """p.54: Flow "turns the current section in a vertically scrolling container
    to allow module building to configure widgets that stretch beyond the
    displayed interface"."""
    open_module(page, sections)
    parts = parts_of(page, "flow")
    expect(parts).to_have_count(3)

    boxes = [parts.nth(i).bounding_box() for i in range(3)]
    assert boxes[0]["y"] < boxes[1]["y"] < boxes[2]["y"], "stacked vertically"

    container = page.locator(".canvas-section--flow > .canvas-section-parts")
    assert container.evaluate("el => getComputedStyle(el).overflowY") == "auto"


def test_a_toolbar_lays_out_horizontally_and_keeps_its_widgets_narrow(page, sections):
    """p.54: a Toolbar is "optimized for smaller widgets like Button Groups or
    Metric Cards".

    Two assertions, and the second is the one that matters: three widgets each
    taking a third of the page is a Columns section, not a toolbar. So they must
    be side by side *and* together take much less than the full width.
    """
    open_module(page, sections)
    parts = parts_of(page, "toolbar")
    expect(parts).to_have_count(3)

    boxes = [parts.nth(i).bounding_box() for i in range(3)]
    assert boxes[0]["y"] == pytest.approx(boxes[1]["y"], abs=2), "on one line"
    assert boxes[0]["x"] < boxes[1]["x"] < boxes[2]["x"], "left to right"

    container = page.locator(".canvas-section--toolbar > .canvas-section-parts")
    full = container.bounding_box()["width"]
    used = sum(b["width"] for b in boxes)
    assert used < full * 0.7, f"widgets keep their own width: {used} of {full}"
