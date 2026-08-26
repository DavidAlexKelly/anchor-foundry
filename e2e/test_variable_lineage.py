"""p.77–78's variable lineage graph (parity `workshop.md` §3.3).

> "Use the Variable lineage graph option found in the header of the Variables
> panel, to visualize how variables and widgets in your module depend on one
> another. Use it to debug recompute behavior, trace which widgets read or write
> a variable…" (p.77)

> "Each node on the graph represents a variable or widget. Nodes with
> dependencies have chevron arrows… Select an arrow to expand a node's parents
> (upstream dependencies) or children (downstream consumers)… Use the Show all
> action in the graph header to expand to the full application graph or Clear to
> remove all nodes. Undo and redo options in the graph header step backward and
> forward through expand, collapse, and selection actions." (p.78)

The graph, the expansion rules, the history and the layering are all in
`apps/web/src/components/canvas/variable-lineage.ts` and are checked there
without a browser. What needs a browser is what a set of ids cannot show: that
the header button exists where p.77 says it does, that the graph it opens is
built from the module actually on screen, that a chevron is wired to the
expansion it claims, and — the one that matters — that **a writing widget is
drawn upstream of its variable and a reading widget downstream of it**. A
`PROP_DIRECTION` entry can be right in the module and still reach the wrong
side of the picture.

The module under test is one chain end to end:

    Filter (writes) → Region → Label (derived) → Text (reads)

with a fifth variable attached to nothing, so that "Show all" has something to
add that no chevron would ever have reached.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, settled


def module_with(api, name: str):
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            # p.69's "output variables": a Filter's parameter name is the
            # variable it produces, so the widget is upstream of it.
            "ctl": {"resolvedName": "CanvasParameterControl",
                    "props": {"name": "v_region", "label": "Region picker",
                              "control": "text", "datasetId": None, "column": None}},
            # p.69's "input variables": a Text that hides itself on a variable
            # consumes it, so the widget is downstream of it.
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Regional", "visibleWhen": "v_label"}},
        }),
        "variables": {
            "v_region": {"id": "v_region", "kind": "string", "label": "Region"},
            "v_label": {"id": "v_label", "kind": "string", "label": "Label",
                        "derivation": {"transform": "concat", "inputs": ["v_region"]}},
            "v_lonely": {"id": "v_lonely", "kind": "string", "label": "Lonely"},
            "v_pad_one": {"id": "v_pad_one", "kind": "string", "label": "Pad one"},
            "v_pad_two": {"id": "v_pad_two", "kind": "string", "label": "Pad two"},
        },
        "events": {},
    })
    return mod


def open_variables(page):
    page.get_by_role("button", name="Variables", exact=False).first.click()


def open_lineage(page):
    page.get_by_test_id("open-lineage").click()
    expect(page.get_by_test_id("lineage")).to_be_visible()


def nodes(page):
    return page.locator(".lineage-node")


def labels(page) -> list[str]:
    """What each drawn node says. The label is a `<title>` on the rect and a
    truncated `<text>` beside it; the `<text>` is what a person reads."""
    texts = page.locator(".lineage-label")
    # `text_content`, not `inner_text`: an SVG `<text>` has no `innerText`.
    return sorted((texts.nth(i).text_content() or "") for i in range(texts.count()))


def open_variable(page, label: str):
    page.locator(".vars-row").filter(has_text=label).first.click()


def test_the_option_is_in_the_variables_panel_header(page, api) -> None:
    """p.77 places it exactly there, and a graph nobody can find is not a
    feature. With no variable open there is nothing to start from, which the
    panel says rather than drawing an empty box."""
    mod = module_with(api, "Lineage header")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_lineage(page)

    expect(page.get_by_test_id("lineage-empty")).to_be_visible()
    expect(nodes(page)).to_have_count(0)


def test_show_all_expands_to_the_full_application_graph(page, api) -> None:
    """p.78's "Show all action… to expand to the full application graph".

    Five variables and two referencing widgets. `Lonely` is in it because Show
    all means all; the two widgets are in it because p.78 says a node is "a
    variable **or widget**".
    """
    mod = module_with(api, "Lineage show all")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_lineage(page)

    page.get_by_test_id("lineage-show-all").click()
    expect(page.get_by_test_id("lineage-node-variable")).to_have_count(5)
    expect(page.get_by_test_id("lineage-node-widget")).to_have_count(2)
    assert labels(page) == [
        "Label", "Lonely", "Pad one", "Pad two", "Region", "Region picker", "Regional",
    ]


def test_a_widget_that_writes_is_upstream_and_one_that_reads_is_downstream(
    page, api,
) -> None:
    """**p.77's "trace which widgets read or write a variable", and the reason
    this unit has a direction table at all.**

    The Filter sets `Region`, so expanding `Region`'s *parents* must reveal it.
    The Text obeys `Label`, so expanding `Label`'s *children* must reveal it.
    Swap either and the graph points an arrow the wrong way — in a view whose
    only purpose is being trusted while debugging.
    """
    mod = module_with(api, "Lineage direction")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_variable(page, "Region")
    open_lineage(page)

    # Just the focused variable to begin with.
    expect(nodes(page)).to_have_count(1)

    # Upstream of Region is the widget that writes it.
    page.get_by_test_id("lineage-parents-v_region").click()
    expect(page.get_by_test_id("lineage-node-widget")).to_have_count(1)
    assert "Region picker" in labels(page)

    # Downstream of Region is the variable derived from it; downstream of that
    # is the widget that reads it.
    page.get_by_test_id("lineage-children-v_region").click()
    assert "Label" in labels(page)
    page.get_by_test_id("lineage-children-v_label").click()
    assert "Regional" in labels(page)
    expect(page.get_by_test_id("lineage-node-widget")).to_have_count(2)

    # And nothing dragged the unrelated variables in with them: a lineage graph
    # that grows to the whole module on one click is the thing Show all is for.
    assert "Lonely" not in labels(page)


def test_a_node_with_nothing_behind_a_chevron_draws_none(page, api) -> None:
    """p.78: "Nodes **with dependencies** have chevron arrows". The Filter is
    the head of the chain — it has no parents ever — and once its child is on
    screen it has nothing left downstream either."""
    mod = module_with(api, "Lineage chevrons")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_variable(page, "Region")
    open_lineage(page)

    page.get_by_test_id("lineage-parents-v_region").click()
    expect(page.get_by_test_id("lineage-parents-ctl")).to_have_count(0)
    expect(page.get_by_test_id("lineage-children-ctl")).to_have_count(0)


def test_collapsing_removes_what_expanding_added(page, api) -> None:
    """The inverse of p.78's chevron. Offered only where it would do something,
    which is why this asserts on the collapse control's existence as well as on
    its effect."""
    mod = module_with(api, "Lineage collapse")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_variable(page, "Region")
    open_lineage(page)

    page.get_by_test_id("lineage-parents-v_region").click()
    expect(nodes(page)).to_have_count(2)
    page.get_by_test_id("lineage-collapse-parents-v_region").click()
    expect(nodes(page)).to_have_count(1)
    assert labels(page) == ["Region"]


def test_undo_and_redo_step_through_expand_and_collapse(page, api) -> None:
    """p.78: "Undo and redo options in the graph header step backward and
    forward through expand, collapse, and selection actions"."""
    mod = module_with(api, "Lineage history")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_variable(page, "Region")
    open_lineage(page)

    # Nothing has happened yet, so neither steps anywhere.
    expect(page.get_by_test_id("lineage-undo")).to_be_disabled()
    expect(page.get_by_test_id("lineage-redo")).to_be_disabled()

    page.get_by_test_id("lineage-children-v_region").click()
    expect(nodes(page)).to_have_count(2)

    page.get_by_test_id("lineage-undo").click()
    expect(nodes(page)).to_have_count(1)
    page.get_by_test_id("lineage-redo").click()
    expect(nodes(page)).to_have_count(2)
    expect(page.get_by_test_id("lineage-redo")).to_be_disabled()


def test_clear_removes_all_nodes_and_is_undoable(page, api) -> None:
    """p.78's "Clear to remove all nodes" — and Clear is one of the actions
    undo steps back through, so an accidental one is not the end of a session's
    worth of expanding."""
    mod = module_with(api, "Lineage clear")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_lineage(page)

    page.get_by_test_id("lineage-show-all").click()
    expect(nodes(page)).to_have_count(7)

    page.get_by_test_id("lineage-clear").click()
    expect(nodes(page)).to_have_count(0)
    expect(page.get_by_test_id("lineage-empty")).to_be_visible()

    page.get_by_test_id("lineage-undo").click()
    expect(nodes(page)).to_have_count(7)


def test_the_graph_closes_and_leaves_the_panel_behind(page, api) -> None:
    """It is a way of looking at the module, not a place in it: closing returns
    to the Variables panel with the variable still open."""
    mod = module_with(api, "Lineage close")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    open_variable(page, "Region")
    open_lineage(page)

    page.get_by_test_id("lineage-close").click()
    expect(page.get_by_test_id("lineage")).to_have_count(0)
    expect(page.locator(".vars-item.on")).to_have_count(1)
