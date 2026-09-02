"""p.475's Prominent Terms (parity `workshop.md` §10).

> "Use the Prominent Terms widget to define prominently-used terms and phrases
> to match on within an object set. Showcase the number of matched results, and
> use the widget as a way to define a custom set of terms for users to apply as
> filters." (p.475)

The rules are in `apps/web/src/components/canvas/prominent-terms.ts`, mutation
tested without a browser. **What needs one is that the numbers are right and
that the filter reaches somewhere**, which is asserted through a second widget
reading the narrowed set — a term row showing the right count while writing the
wrong clause looks perfect from the outside.

The variable graph:

    v_all      (object_set)   every site
    v_clauses  (array)        what the terms widget writes
    v_picked   (object_set)   narrow_set(v_all, v_clauses)

**`rare` is the fixture's whole argument.** It appears on one row, and there are
more than `object_sets.MAX_GROUPS` distinct values in the column — so a
`/object-sets/group` implementation would not see it at all, and its count would
read as zero. One count per term is what makes it a 1.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_builder, open_module, settled

# 22 distinct `tag` values, which is past `object_sets.MAX_GROUPS` (20). `north`
# and `south` are the two common ones; `rare` sits on a single row and would
# fall off a grouped response ordered by count. `absent` is on no row at all -
# the case a Filter List structurally cannot produce and this widget can.
COMMON = {"north": 6, "south": 4}
FILLER = [f"tag{i}" for i in range(1, 21)]
# `band` exists so a *base set with a filter of its own* is expressible. Two of
# the six northern rows are "old", so a base set narrowed to "new" has four of
# them — which is what separates a term clause **added to** the base set's
# filters from one that replaces them. With an unfiltered base set the two are
# the same request, and a suite built only on one cannot tell them apart.
OLD = {"N1", "N2"}
NEW_NORTH = COMMON["north"] - len(OLD)
ROWS = (
    [{"id": f"N{i}", "tag": "north", "name": f"North {i}",
      "band": "old" if f"N{i}" in OLD else "new"}
     for i in range(1, COMMON["north"] + 1)]
    + [{"id": f"S{i}", "tag": "south", "name": f"South {i}", "band": "new"}
       for i in range(1, COMMON["south"] + 1)]
    + [{"id": "R1", "tag": "rare", "name": "The rare one", "band": "new"}]
    + [{"id": f"F{i}", "tag": tag, "name": f"Filler {i}", "band": "new"}
       for i, tag in enumerate(FILLER, start=1)]
)


@pytest.fixture(scope="module")
def sites(api):
    mod = Module(api, "Prominent terms")
    mod.site_type_id = mod.object_type(
        columns=["id", "tag", "name", "band"], rows=ROWS, key="id", title="name",
    )
    return mod


def build(api, sites, name: str, props: dict | None = None):
    """The widget, plus an Object Set Title reading the narrowed set — so "what
    did the click filter to" is answered by something other than the widget
    that wrote the clause."""
    mod = Module(api, name, beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "terms": {
                "resolvedName": "CanvasProminentTerms",
                "props": {
                    "objectSetVariable": "v_all", "variable": "v_clauses",
                    "property": "tag", "hideEmpty": False, "title": "By tag",
                    "terms": [
                        {"value": "north", "label": "Northern", "icon": "N"},
                        {"value": "south", "label": "Southern", "icon": ""},
                        {"value": "rare", "label": "", "icon": ""},
                        {"value": "absent", "label": "Nowhere", "icon": ""},
                    ],
                    **(props or {}),
                },
            },
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_picked", "columns": "id,tag,name",
                          "pageSize": 50},
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "The terms picked"},
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "The narrowed set",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
            },
        },
        "events": {},
    })
    return mod


def rows(page):
    return page.get_by_test_id("prominent-term")


def term(page, value: str):
    return page.locator(f'[data-testid="prominent-term"][data-value="{value}"]')


def labels(page) -> list[str]:
    got = page.locator(".canvas-term-label")
    return [(got.nth(i).text_content() or "").strip() for i in range(got.count())]


def counts(page) -> dict[str, str]:
    out = {}
    for i in range(rows(page).count()):
        row = rows(page).nth(i)
        out[row.get_attribute("data-value") or ""] = (
            (row.locator(".canvas-term-count").text_content() or "").strip()
        )
    return out


def table_rows(page) -> int:
    return page.locator(".data-grid tbody tr").count()


def test_each_term_shows_its_own_count(page, api, sites) -> None:
    """p.475: the value "determin[es] the total count of results returned to
    display in the term's row"."""
    mod = build(api, sites, "Terms counts")
    open_module(page, mod)
    settled(page)

    got = eventually(
        lambda: counts(page),
        lambda c: len(c) == 4 and all(v != "" for v in c.values()),
        what="a count on every term",
    )
    assert got == {"north": "6", "south": "4", "rare": "1", "absent": "0"}, got


def test_a_rare_term_is_counted_rather_than_lost_to_the_grouping_cap(
    page, api, sites
) -> None:
    """**The reason each count is its own request.**

    The column has 22 distinct values and `object_sets.MAX_GROUPS` is 20, so a
    `/object-sets/group` implementation — which is what the Filter List beside
    this widget uses — would return the twenty most populous and `rare` would
    not be among them. Its count would then read 0, indistinguishable from a
    term nothing matches, and p.475's Hide empty terms would remove the row.

    The fixture is built to make that failure reachable: `rare` is on exactly
    one row, and there are twenty filler tags ahead of it.
    """
    mod = build(api, sites, "Terms rare")
    open_module(page, mod)
    settled(page)

    expect(term(page, "rare").locator(".canvas-term-count")).to_have_text("1")
    # And it is a different answer from the term that genuinely matches nothing,
    # which is the distinction the whole design turns on.
    expect(term(page, "absent").locator(".canvas-term-count")).to_have_text("0")


def test_a_term_names_a_value_no_row_has(page, api, sites) -> None:
    """The case a Filter List structurally cannot produce: its options come from
    the data, so every one of them matches at least one row. An author writes
    the vocabulary they want viewers to think in, and the data says which parts
    of it are populated today."""
    mod = build(api, sites, "Terms absent")
    open_module(page, mod)
    settled(page)

    expect(term(page, "absent")).to_be_visible()
    expect(term(page, "absent").locator(".canvas-term-count")).to_have_text("0")


def test_hide_empty_terms_removes_only_the_ones_that_answered_zero(
    page, api, sites
) -> None:
    """p.475's Hide empty terms.

    **`rare` staying is the assertion**, not `absent` going: hiding a row for
    being unfashionable rather than unused is the failure a grouped
    implementation would produce, and it is invisible on screen.
    """
    mod = build(api, sites, "Terms hide empty", {"hideEmpty": True})
    open_module(page, mod)
    settled(page)

    eventually(lambda: rows(page).count(), lambda n: n == 3,
               what="three rows once the empty one is hidden")
    assert sorted(counts(page)) == ["north", "rare", "south"], counts(page)


def test_a_term_shows_its_display_name_and_falls_back_to_its_value(
    page, api, sites
) -> None:
    """p.475's Display name. `rare` has none, so its row is named by the value
    it matches — a row with no name still has to be pickable."""
    mod = build(api, sites, "Terms labels")
    open_module(page, mod)
    settled(page)

    eventually(lambda: labels(page), lambda got: len(got) == 4, what="four rows")
    assert labels(page) == ["Northern", "Southern", "rare", "Nowhere"], labels(page)


def test_picking_a_term_narrows_a_set_another_widget_reads(page, api, sites) -> None:
    """**p.475's Filter variable, and the claim that needs a browser.** Asserted
    through the table, because a term row showing the right count while writing
    the wrong clause looks perfect from outside."""
    mod = build(api, sites, "Terms narrow")
    open_module(page, mod)
    settled(page)

    eventually(lambda: table_rows(page), lambda n: n == len(ROWS),
               what="every row before anything is picked")

    term(page, "south").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["south"],
               what="the four southern rows")
    expect(term(page, "south")).to_have_attribute("aria-pressed", "true")


def test_two_terms_are_an_in_clause_and_a_third_click_undoes_one(
    page, api, sites
) -> None:
    """One value is `eq` and several are `in` — the Filter List's vocabulary,
    and both mean the same thing on both stores. What a browser has to show is
    that the second pick *widens* rather than replaces, which is what separates
    a term list from a radio group."""
    mod = build(api, sites, "Terms multi")
    open_module(page, mod)
    settled(page)

    term(page, "south").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["south"],
               what="south alone")

    term(page, "north").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["north"] + COMMON["south"],
               what="north and south together")

    term(page, "south").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["north"],
               what="north alone after unticking south")
    expect(term(page, "south")).to_have_attribute("aria-pressed", "false")


def test_the_counts_do_not_move_when_a_term_is_picked(page, api, sites) -> None:
    """The Filter List's rule, and it matters more here: counts are measured
    against the **base** set, so picking one term does not send every other row
    to zero. p.475 calls it the "Base object set" for this reason — a term list
    whose other numbers all read 0 tells a viewer nothing about what picking
    them would do."""
    mod = build(api, sites, "Terms stable counts")
    open_module(page, mod)
    settled(page)

    before = eventually(lambda: counts(page), lambda c: len(c) == 4 and all(c.values()),
                        what="every count")
    term(page, "south").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["south"],
               what="the set to narrow")
    assert counts(page) == before, counts(page)


def test_a_term_narrows_the_base_set_rather_than_replacing_its_filters(
    page, api, sites
) -> None:
    """p.475 calls it the **Base** object set, and the word is load-bearing: a
    term is a filter applied *on top of* what the set already says.

    The base set here is narrowed to the "new" band, which holds four of the six
    northern rows. A term whose clause replaced the set's own filters would
    count six — and every other test in this file uses an unfiltered base set,
    where the two implementations produce the identical request.
    """
    mod = Module(api, "Terms on a filtered set", beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "terms": {
                "resolvedName": "CanvasProminentTerms",
                "props": {
                    "objectSetVariable": "v_new", "variable": "v_clauses",
                    "property": "tag", "hideEmpty": False, "title": "By tag",
                    "terms": [{"value": "north", "label": "", "icon": ""}],
                },
            },
        }),
        "variables": {
            "v_new": {
                "id": "v_new", "kind": "object_set", "label": "New band only",
                "object_set": object_set(
                    sites.site_type_id,
                    filters=[{"property": "band", "op": "eq", "value": "new"}],
                ),
            },
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Picked"},
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    expect(term(page, "north").locator(".canvas-term-count")).to_have_text(str(NEW_NORTH))


def test_two_terms_widgets_sharing_one_variable_do_not_erase_each_other(
    page, api, sites
) -> None:
    """**Several widgets chain through one `narrow_set`**, so a widget rewriting
    the whole variable would silently drop another's filter — the failure
    §101–§103 gave two clause variables to avoid, reachable again the moment two
    widgets are pointed at one.

    Two Prominent Terms widgets on two properties, one variable. Picking in each
    has to leave both clauses standing, which the table is what proves.
    """
    mod = Module(api, "Terms sharing a variable", beside=sites)
    mod.define({
        "format": 2,
        "layout": layout({
            "bytag": {
                "resolvedName": "CanvasProminentTerms",
                "props": {
                    "objectSetVariable": "v_all", "variable": "v_clauses",
                    "property": "tag", "title": "By tag",
                    "terms": [{"value": "north", "label": "", "icon": ""}],
                },
            },
            "byband": {
                "resolvedName": "CanvasProminentTerms",
                "props": {
                    "objectSetVariable": "v_all", "variable": "v_clauses",
                    "property": "band", "title": "By band",
                    "terms": [{"value": "old", "label": "", "icon": ""}],
                },
            },
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {"objectSetVariable": "v_picked", "columns": "id,tag,band",
                          "pageSize": 50},
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "Every site",
                      "object_set": object_set(sites.site_type_id)},
            "v_clauses": {"id": "v_clauses", "kind": "array", "label": "Picked"},
            "v_picked": {
                "id": "v_picked", "kind": "object_set", "label": "Narrowed",
                "derivation": {"transform": "narrow_set", "inputs": ["v_all", "v_clauses"]},
            },
        },
        "events": {},
    })
    open_module(page, mod)
    settled(page)

    term(page, "north").click()
    eventually(lambda: table_rows(page), lambda n: n == COMMON["north"],
               what="the six northern rows")

    # The second widget's clause has to *narrow further*, not replace the first.
    term(page, "old").click()
    eventually(lambda: table_rows(page), lambda n: n == len(OLD),
               what="northern and old together")
    # And both stay lit, because both clauses are still in the variable.
    expect(term(page, "north")).to_have_attribute("aria-pressed", "true")
    expect(term(page, "old")).to_have_attribute("aria-pressed", "true")


def test_the_rows_are_inert_in_the_builder(page, api, sites) -> None:
    """Clicking a term in the builder would write a viewer's filter into the
    document being edited. The rows are shown — an author has to see what they
    configured — and they do not act."""
    mod = build(api, sites, "Terms builder")
    open_builder(page, mod)
    settled(page)

    eventually(lambda: rows(page).count(), lambda n: n == 4, what="four rows")
    expect(term(page, "south")).to_be_disabled()


def test_the_panel_edits_the_terms(page, api, sites) -> None:
    """p.475's Terms as three fields a row, plus Add and Remove."""
    mod = build(api, sites, "Terms panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Prominent terms").first.click()
    expect(page.get_by_test_id("term-value-0")).to_have_value("north")
    expect(page.get_by_test_id("term-label-0")).to_have_value("Northern")
    expect(page.get_by_test_id("term-icon-0")).to_have_value("N")

    page.get_by_test_id("term-add").click()
    expect(page.get_by_test_id("term-value-4")).to_be_visible()
    page.get_by_test_id("term-value-4").fill("tag1")
    eventually(lambda: rows(page).count(), lambda n: n == 5,
               what="the new term rendered by the widget")
    expect(term(page, "tag1").locator(".canvas-term-count")).to_have_text("1")

    page.get_by_test_id("term-remove-4").click()
    eventually(lambda: rows(page).count(), lambda n: n == 4, what="back to four")


def test_the_panel_offers_the_type_s_properties_for_the_one_property(
    page, api, sites
) -> None:
    """p.475's Property: "Select a property on which to filter" — one property
    for the whole widget, unlike the Filter List's several."""
    mod = build(api, sites, "Terms property")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Prominent terms").first.click()
    picker = page.get_by_test_id("terms-property")
    expect(picker).to_have_value("tag")
    # **Wait through a retrying matcher before reading**, per §202 and §231:
    # `evaluate_all` is a one-shot read, and the options arrive when the object
    # type resolves rather than when the select mounts.
    expect(picker.locator("option")).to_have_count(5)
    values = picker.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
    # The primary key is a declared property and is offered like any other: a
    # term list over unique values is a strange thing to build, but nothing here
    # gets to decide that for an author — unlike a *text sort*, which the server
    # actually refuses (§231).
    assert values == ["", "id", "tag", "name", "band"], values


def test_an_unconfigured_widget_says_what_it_is_waiting_for(page, api, sites) -> None:
    """p.66's progressive disclosure, at the widget rather than the panel: a
    blank space is indistinguishable from a widget that failed."""
    mod = build(api, sites, "Terms unset", {"property": "", "terms": []})
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("prominent-terms")).to_have_count(0)
    expect(page.locator(".canvas-widget-empty").first).to_contain_text("Settings")
