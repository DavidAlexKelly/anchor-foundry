"""p.72's search, filter and partitions in the Variables panel (parity
`workshop.md` §3.3; Foundry p.72–73).

> "…an input to search variables by their name or unique ID… and a filter to
> display variables based on their definition type or what settings are enabled.
> The variable list includes partitions to help you quickly find relevant
> variables: when a widget is selected, a partition displays variables used by
> that widget; when no widget is selected, a partition displays variables used
> in the active page." (p.72)

The narrowing arithmetic is checked in
`apps/web/src/components/canvas/variable-finder.test.ts`. What needs a browser
is what the pure module cannot see: that the controls are wired to the list at
all, that the partition follows the **live Craft selection** rather than the
saved document, and that the three compose rather than clobbering each other.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout
from conftest import open_builder, settled


def module_with(api, name: str):
    """Five variables of different definition types and settings, on two pages.

    Five because the panel only draws the controls past a handful - three
    controls over a list of two is chrome - and because a partition needs
    something on each side of it to be worth asserting.
    """
    mod = Module(api, name)
    mod.define({
        "format": 2,
        "layout": layout({
            "p1": {"resolvedName": "CanvasPage", "isCanvas": True,
                   "props": {"title": "First"}, "nodes": ["s1"]},
            "s1": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "p1",
                   "props": {"direction": "columns"}, "nodes": ["w_one"]},
            "w_one": {"resolvedName": "CanvasText", "parent": "s1",
                      "props": {"tag": "p", "text": "one", "visibleWhen": "v_alpha"}},
            "p2": {"resolvedName": "CanvasPage", "isCanvas": True,
                   "props": {"title": "Second"}, "nodes": ["s2"]},
            "s2": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "p2",
                   "props": {"direction": "columns"}, "nodes": ["w_two"]},
            "w_two": {"resolvedName": "CanvasText", "parent": "s2",
                      "props": {"tag": "p", "text": "two", "visibleWhen": "v_beta"}},
        }),
        "variables": {
            "v_alpha": {"id": "v_alpha", "kind": "string", "label": "Alpha"},
            "v_beta": {"id": "v_beta", "kind": "string", "label": "Beta"},
            "v_gamma": {"id": "v_gamma", "kind": "string", "label": "Gamma",
                        "external_id": "gamma", "interface": {"required": False}},
            "v_delta": {"id": "v_delta", "kind": "string", "label": "Delta",
                        "derivation": {"transform": "concat", "inputs": ["v_alpha"]}},
            "v_eps": {"id": "v_eps", "kind": "string", "label": "Epsilon"},
        },
        "events": {},
    })
    return mod


def open_variables(page):
    page.get_by_role("button", name="Variables", exact=False).first.click()


def rows(page):
    return page.locator(".vars-row")


def labels(page) -> list[str]:
    return [rows(page).nth(i).inner_text().split("\n")[0] for i in range(rows(page).count())]


def test_search_narrows_the_list_by_name(page, api) -> None:
    """p.72's "search variables by their name"."""
    mod = module_with(api, "Finder search")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    expect(rows(page)).to_have_count(5)

    page.get_by_test_id("variable-search").fill("gam")
    expect(rows(page)).to_have_count(1)
    assert labels(page) == ["Gamma"]


def test_search_finds_a_variable_by_its_id(page, api) -> None:
    """p.72 says "or unique ID", and this system has two things that could be
    called one — the generated id and the author's external ID. Both find it,
    because picking one would be right half the time."""
    mod = module_with(api, "Finder search id")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    page.get_by_test_id("variable-search").fill("v_delta")
    expect(rows(page)).to_have_count(1)
    assert labels(page) == ["Delta"]

    page.get_by_test_id("variable-search").fill("gamma")
    expect(rows(page)).to_have_count(1)
    assert labels(page) == ["Gamma"]


def test_a_search_that_matches_nothing_says_how_many_there_are(page, api) -> None:
    """Rather than an empty panel, which looks identical to a module with no
    variables — the one state an author cannot tell apart from a broken panel."""
    mod = module_with(api, "Finder search empty")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    page.get_by_test_id("variable-search").fill("zzzz")
    expect(rows(page)).to_have_count(0)
    expect(page.get_by_test_id("variable-none-found")).to_contain_text("5 in this module")


def test_the_type_filter_narrows_by_definition_type(page, api) -> None:
    """p.73's definition types. Only `v_delta` is derived."""
    mod = module_with(api, "Finder type")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    page.get_by_test_id("variable-type-filter").select_option("variable_transformation")
    expect(rows(page)).to_have_count(1)
    assert labels(page) == ["Delta"]

    page.get_by_test_id("variable-type-filter").select_option("static")
    expect(rows(page)).to_have_count(4)


def test_the_settings_filter_narrows_by_what_is_enabled(page, api) -> None:
    """p.73's "which of the below features should be enabled". Only `v_gamma`
    is on the module interface."""
    mod = module_with(api, "Finder setting")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    page.get_by_test_id("variable-setting-filter").select_option("interface")
    expect(rows(page)).to_have_count(1)
    assert labels(page) == ["Gamma"]

    page.get_by_test_id("variable-setting-filter").select_option("routing")
    expect(rows(page)).to_have_count(0)


def test_search_and_filter_compose(page, api) -> None:
    """**The normal case, not an edge one.** A search inside a filter is how
    somebody actually finds a variable, and two controls that each work alone
    can still clobber each other."""
    mod = module_with(api, "Finder compose")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    page.get_by_test_id("variable-type-filter").select_option("static")
    page.get_by_test_id("variable-search").fill("a")
    # Alpha, Beta, Gamma and Delta all contain "a"; Delta is not static.
    assert sorted(labels(page)) == ["Alpha", "Beta", "Gamma"]


def test_selecting_a_widget_partitions_by_that_widget(page, api) -> None:
    """p.72: "when a widget is selected, a partition displays variables used by
    that widget".

    **The partition follows the live Craft selection**, which is the thing the
    pure module cannot check — it is handed a node id and has no opinion about
    where it came from.
    """
    mod = module_with(api, "Finder widget partition")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="one").first.click()
    open_variables(page)

    headings = page.get_by_test_id("variable-partition")
    expect(headings.first).to_contain_text("Used by the selected widget · 1")
    expect(headings.nth(1)).to_contain_text("Everything else · 4")
    # And the relevant one comes first, which is what a partition is for.
    assert labels(page)[0] == "Alpha"


def test_selecting_a_page_partitions_by_that_page(page, api) -> None:
    """p.72's other half, adapted.

    **Divergence, and it is deliberate**: our builder draws every page at once,
    so "the active page" has no answer the way p.72 assumes. The page an author
    is working in is the one holding their selection, so selecting a *page*
    partitions by it — and the second page's variable lands in the other half,
    which is what makes this an assertion rather than a count.
    """
    mod = module_with(api, "Finder page partition")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="First").first.click()
    open_variables(page)

    expect(page.get_by_test_id("variable-partition").first).to_contain_text(
        "Used on this page · 1",
    )
    assert labels(page)[0] == "Alpha"


def test_nothing_selected_draws_no_partition(page, api) -> None:
    """A partition of everything is not a partition, and a heading over the
    whole list says nothing."""
    mod = module_with(api, "Finder no partition")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    expect(page.get_by_test_id("variable-partition")).to_have_count(0)
    expect(rows(page)).to_have_count(5)
