"""p.268-272's Links widget (parity `workshop.md` §10).

> "The links widget displays the links relationship between objects and provide
> exploration into those paths. … **Link types to display**: By default, all
> links are shown in the links widget. By choosing "Specify link types",
> granular controls and features such as link level sorting can be configured.
> … **Default link expand**: Specify the number of links that will be
> auto-expanded by default in the first level. … **Link type label override**:
> The link type's label can be overridden with a new label for the link type."
> (p.268-272)

Which rows are drawn, what they are called and which of them open on load is
`apps/web/src/components/canvas/links-widget.test.ts`, mutation-tested without
a browser.

**What needs one is that a link is a pair, not an id.** A self-link comes back
from the server twice - once per end - and every configuration here is keyed on
the type *and the direction*. A widget that keyed on the id alone would draw
both rows, label them identically, and configure both when the author meant
one; each of those looks entirely reasonable on screen, and this fixture has a
self-link precisely so that none of them can pass.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, open_module, settled

# Ada manages everybody and reports to nobody, so her two ends of the self-link
# have *different counts* - 0 one way, eleven the other. A widget that drew one
# row for the link type would have to pick one of those two numbers.
#
# **Eleven, not two.** The traversal returns a first page of ten with a count,
# so a fixture with fewer reports than that page holds cannot tell the count
# apart from the number of rows drawn - and the header's job is to report the
# link, not the page (the harness had to say so).
PREVIEW_LIMIT = 10
REPORTS = 11
PEOPLE = [{"id": "P1", "name": "Ada", "dept": "ENG", "manager_id": ""}] + [
    {"id": f"P{n}", "name": f"Report {n}",
     "dept": "RES" if n % 2 else "ENG", "manager_id": "P1"}
    for n in range(2, 2 + REPORTS)
]
DEPARTMENTS = [
    {"code": "ENG", "label": "Engineering"},
    {"code": "RES", "label": "Research"},
]

# The server orders link types by display name and returns each one outbound
# end first, so "Reports to" comes before "Works in" and Ada's rows arrive as:
SERVER_ORDER = ["Manager", "Direct reports", "Department"]


@pytest.fixture(scope="module")
def seed(api):
    people = Module(api, "Links widget")
    person_type = people.object_type(
        columns=["id", "name", "dept", "manager_id"], rows=PEOPLE, key="id", title="name",
    )
    depts = Module(api, "Links widget departments", beside=people)
    dept_type = depts.object_type(
        columns=["code", "label"], rows=DEPARTMENTS, key="code", title="label",
    )
    works_in = api.call(
        "POST", f"/workspaces/{people.workspace_id}/link-types",
        {
            "api_name": f"works_in_{people.tag}",
            "display_name": "Works in",
            "from_type_id": person_type,
            "to_type_id": dept_type,
            "cardinality": "one_to_many",
            "from_property": "dept",
            "to_property": "$primary_key",
            "from_side_name": "Employees",
            "to_side_name": "Department",
        },
    )
    reports_to = api.call(
        "POST", f"/workspaces/{people.workspace_id}/link-types",
        {
            "api_name": f"reports_to_{people.tag}",
            "display_name": "Reports to",
            "from_type_id": person_type,
            "to_type_id": person_type,
            "cardinality": "one_to_many",
            "from_property": "manager_id",
            "to_property": "$primary_key",
            "from_side_name": "Direct reports",
            "to_side_name": "Manager",
        },
    )
    return SimpleNamespace(
        module=people, person_type=person_type, dept_type=dept_type,
        works_in=works_in["id"], reports_to=reports_to["id"],
    )


def build(api, seed, name: str, props: dict | None = None, *, who: str = "P1"):
    """A module whose Links widget is pointed at one person."""
    mod = Module(api, name, beside=seed.module)
    mod.define({
        "format": 2,
        "layout": layout({
            "lw": {
                "resolvedName": "CanvasLinksWidget",
                "props": {"objectSetVariable": "v_set", "linkMode": "all",
                          "links": [], "defaultExpand": 0, **(props or {})},
            },
        }),
        "variables": {
            "v_set": {
                "id": "v_set", "kind": "object_set", "label": "The person",
                "object_set": object_set(
                    seed.person_type,
                    [{"property": "id", "op": "eq", "value": who}] if who else [],
                ),
            },
        },
        "events": {},
    })
    return mod


def label_locator(page):
    return page.get_by_test_id("link-label")


def labels(page) -> list[str]:
    return [(label_locator(page).nth(i).text_content() or "").strip()
            for i in range(label_locator(page).count())]


def expect_labels(page, expected: list[str]) -> None:
    """Assert the labels **through a wait**.

    `count()` and `text_content()` do not retry, so reading them straight after
    `settled()` asks the page a question before the traversal has answered -
    and gets `[]`, which compares unequal for a reason that has nothing to do
    with the labels (§202).
    """
    expect(label_locator(page)).to_have_count(len(expected))
    assert labels(page) == expected, labels(page)


def section(page, label: str):
    return page.get_by_test_id("link-group").filter(has_text=label).first


def header(page, label: str):
    return section(page, label).get_by_role("button")


def test_it_lists_every_link_of_the_object(page, api, seed) -> None:
    mod = build(api, seed, "Links basic")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("links")).to_be_visible()
    expect_labels(page, SERVER_ORDER)
    # The side names, not the link type's own name: "Reports to" appears on
    # neither row, because neither end of it reads that way.
    expect(page.get_by_test_id("links")).not_to_contain_text("Reports to")


def test_a_self_links_two_ends_are_separate_rows(page, api, seed) -> None:
    """**The reason everything here is keyed on the pair.**

    Both rows carry the same `link_type_id`. Only the direction tells "my
    manager" apart from "my direct reports", and Ada has none of the first and
    two of the second - so a widget that collapsed them into one row would have
    to show one of those two counts for both questions.
    """
    mod = build(api, seed, "Links self")
    open_module(page, mod)
    settled(page)

    expect(section(page, "Manager")).to_contain_text("0 ")
    expect(section(page, "Direct reports")).to_contain_text(f"{REPORTS} ")


def test_a_section_opens_and_closes(page, api, seed) -> None:
    mod = build(api, seed, "Links expand")
    open_module(page, mod)
    settled(page)

    # Closed on load, because `defaultExpand` is 0.
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_test_id("link-object")).to_have_count(0)

    header(page, "Direct reports").click()
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_test_id("link-object")).to_have_count(PREVIEW_LIMIT)
    expect(section(page, "Direct reports")).to_contain_text("P2")
    expect(section(page, "Direct reports")).to_contain_text("P3")

    header(page, "Direct reports").click()
    expect(page.get_by_test_id("link-object")).to_have_count(0)


def test_the_header_counts_the_link_not_the_page(page, api, seed) -> None:
    """**The count is the link's `total`, not the rows drawn.**

    The traversal returns a first page of ten and says how many there are; Ada
    has eleven reports. A header that counted its own list would say ten, be
    wrong by one, and look completely reasonable — which is why the fixture
    keeps more reports than a page holds.
    """
    mod = build(api, seed, "Links count")
    open_module(page, mod)
    settled(page)

    header(page, "Direct reports").click()
    expect(page.get_by_test_id("link-object")).to_have_count(PREVIEW_LIMIT)
    expect(section(page, "Direct reports")).to_contain_text(f"{REPORTS} ")
    expect(section(page, "Direct reports")).to_contain_text(
        f"Showing {PREVIEW_LIMIT} of {REPORTS}")


def test_the_whole_header_row_is_the_control(page, api, seed) -> None:
    """A section that only opens from a 12px triangle is a section most people
    never discover opens.

    Asserted as a measurement, because a button that has shrunk to fit its text
    is still perfectly clickable — just not where the reader aims.
    """
    mod = build(api, seed, "Links header width")
    open_module(page, mod)
    settled(page)

    row, control = section(page, "Direct reports").evaluate(
        "e => [e.getBoundingClientRect().width,"
        " e.querySelector('button').getBoundingClientRect().width]"
    )
    assert control > row - 4, (control, row)


def test_opening_one_section_leaves_the_others_alone(page, api, seed) -> None:
    """Two linked groups are routinely compared; a section that closed the last
    one would make that impossible without clicking twice for every look."""
    mod = build(api, seed, "Links two open")
    open_module(page, mod)
    settled(page)

    header(page, "Direct reports").click()
    header(page, "Department").click()
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "true")
    expect(header(page, "Department")).to_have_attribute("aria-expanded", "true")
    # A page of reports plus Ada's one department.
    expect(page.get_by_test_id("link-object")).to_have_count(PREVIEW_LIMIT + 1)


def test_a_link_pointing_at_nothing_says_so_when_opened(page, api, seed) -> None:
    """Ada has no manager. An empty section and a section that failed to load
    look identical, and only one of them is a fact about the data."""
    mod = build(api, seed, "Links empty side")
    open_module(page, mod)
    settled(page)

    header(page, "Manager").click()
    expect(page.get_by_test_id("link-empty")).to_be_visible()


def test_default_expand_opens_that_many_sections_on_load(page, api, seed) -> None:
    """p.271: "the number of links that will be auto-expanded by default"."""
    none = build(api, seed, "Links expand none", {"defaultExpand": 0})
    open_module(page, none)
    settled(page)
    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "false")

    two = build(api, seed, "Links expand two", {"defaultExpand": 2})
    open_module(page, two)
    settled(page)
    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "true")
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "true")
    # The third is not opened, which is what makes the number a number.
    expect(header(page, "Department")).to_have_attribute("aria-expanded", "false")


def test_a_negative_expand_count_opens_nothing(page, api, seed) -> None:
    """**A document can hold a number the panel would not offer** — an older
    module, the raw JSON editor — and `-1` is the one that separates reading the
    prop from reading it *through the model*: clamped it opens nothing, taken
    raw it slices from the front and opens all but the last section. Both are
    plausible-looking widgets, and only one of them was asked for.
    """
    mod = build(api, seed, "Links expand negative", {"defaultExpand": -1})
    open_module(page, mod)
    settled(page)

    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "false")
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "false")
    expect(header(page, "Department")).to_have_attribute("aria-expanded", "false")


def test_a_section_the_reader_closed_stays_closed(page, api, seed) -> None:
    """p.271's expansion is a *starting* state.

    Re-deriving it every render would reopen a section the moment anything else
    on the page refetched - and the reader would be left clicking the same
    triangle repeatedly with no idea why.
    """
    mod = build(api, seed, "Links expand sticky", {"defaultExpand": 1})
    open_module(page, mod)
    settled(page)

    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "true")
    header(page, "Manager").click()
    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "false")
    # Nothing reopens it: the section is still closed after the widget has had
    # every chance to re-render.
    header(page, "Department").click()
    expect(header(page, "Department")).to_have_attribute("aria-expanded", "true")
    expect(header(page, "Manager")).to_have_attribute("aria-expanded", "false")


def test_specify_draws_only_the_chosen_links_in_the_chosen_order(page, api, seed) -> None:
    """p.270's "Specify link types". The order is the author's, not the
    server's - which is why the fixture's chosen order is its reverse."""
    mod = build(api, seed, "Links specify", {
        "linkMode": "specify",
        "links": [{"key": f"{seed.works_in}:outbound"},
                  {"key": f"{seed.reports_to}:inbound"}],
    })
    open_module(page, mod)
    settled(page)

    expect_labels(page, ["Department", "Direct reports"])


def test_one_end_of_a_self_link_can_be_chosen_without_the_other(page, api, seed) -> None:
    """**The case the pair-keying exists for**, at the widget layer: both rows
    carry `seed.reports_to`, and only the outbound one was asked for."""
    mod = build(api, seed, "Links specify one end", {
        "linkMode": "specify",
        "links": [{"key": f"{seed.reports_to}:outbound"}],
    })
    open_module(page, mod)
    settled(page)

    expect_labels(page, ["Manager"])


def test_the_label_of_one_end_can_be_overridden(page, api, seed) -> None:
    """p.272's "Link type label override", and the same trap once more: an
    override recorded against the link type would rename both ends."""
    mod = build(api, seed, "Links override", {
        "linkMode": "specify",
        "links": [{"key": f"{seed.reports_to}:inbound", "label": "Team"},
                  {"key": f"{seed.reports_to}:outbound"}],
    })
    open_module(page, mod)
    settled(page)

    expect_labels(page, ["Team", "Manager"])


def test_a_chosen_link_the_type_no_longer_has_is_dropped(page, api, seed) -> None:
    """A link type can be deleted long after a widget was pointed at it, and an
    empty row labelled with a link nobody recognises is worse than no row."""
    gone = f"{uuid.uuid4()}:outbound"
    mod = build(api, seed, "Links stale", {
        "linkMode": "specify",
        "links": [{"key": gone}, {"key": f"{seed.works_in}:outbound"}],
    })
    open_module(page, mod)
    settled(page)
    expect_labels(page, ["Department"])

    only_gone = build(api, seed, "Links all stale", {
        "linkMode": "specify", "links": [{"key": gone}],
    })
    open_module(page, only_gone)
    settled(page)
    expect(page.get_by_test_id("links-none")).to_be_visible()
    expect(page.get_by_test_id("links")).to_have_count(0)


def test_default_expand_opens_what_is_shown_not_what_the_server_sent(page, api, seed) -> None:
    """p.271 auto-expands the first sections **of the widget**.

    The server's first row for Ada is "Manager"; this widget does not draw it.
    Expanding "the first one" against the server's list would open a section
    nobody can see, and the widget would load with everything folded for no
    visible reason.
    """
    mod = build(api, seed, "Links expand visible", {
        "linkMode": "specify",
        "links": [{"key": f"{seed.works_in}:outbound"},
                  {"key": f"{seed.reports_to}:inbound"}],
        "defaultExpand": 1,
    })
    open_module(page, mod)
    settled(page)

    expect(header(page, "Department")).to_have_attribute("aria-expanded", "true")
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "false")


def test_an_empty_set_says_so_rather_than_drawing_links(page, api, seed) -> None:
    mod = build(api, seed, "Links no object", who="nobody")
    open_module(page, mod)
    settled(page)

    expect(page.get_by_test_id("links-no-object")).to_be_visible()
    expect(page.get_by_test_id("links")).to_have_count(0)


def test_the_panel_offers_the_types_links_including_both_ends(page, api, seed) -> None:
    """p.272: "Once a starting object set has been selected, choose the link
    type from a dropdown".

    The choices come from the **object type**, not from traversing the bound
    object - otherwise which links could be configured would depend on whether
    today's set happened to be empty, and a widget would become configurable
    and unconfigurable as the data changed underneath it.
    """
    mod = build(api, seed, "Links panel")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Links").first.click()
    # p.270: the granular controls belong to "Specify link types". Offering the
    # picker under "All link types" would let an author tick links that change
    # nothing — the control would be lying about what it does.
    expect(page.get_by_test_id("links-mode")).to_be_visible()
    expect(page.get_by_test_id("links-picker")).to_have_count(0)

    page.get_by_test_id("links-mode").select_option("specify")
    picker = page.get_by_test_id("links-picker")
    expect(picker).to_be_visible()
    expect(picker.locator("input[type=checkbox]")).to_have_count(3)
    # Both ends of the self-link are offered separately, named for their sides.
    expect(page.get_by_test_id(f"links-pick-{seed.reports_to}:outbound")).to_be_visible()
    expect(page.get_by_test_id(f"links-pick-{seed.reports_to}:inbound")).to_be_visible()
    expect(picker).to_contain_text("Manager")
    expect(picker).to_contain_text("Direct reports")


def test_ticking_a_link_records_the_end_and_saves_an_override(page, api, seed) -> None:
    """What the panel writes is what the document has to hold: the pair, and
    p.272's override beside it."""
    mod = build(api, seed, "Links panel write", {"linkMode": "specify"})
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Links").first.click()
    page.get_by_test_id(f"links-pick-{seed.reports_to}:inbound").check()
    page.get_by_test_id(f"links-label-{seed.reports_to}:inbound").fill("Team")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_text("Saved", exact=False).first).to_be_visible()

    saved = mod.definition()["layout"]["lw"]["props"]["links"]
    assert saved == [{"key": f"{seed.reports_to}:inbound", "label": "Team"}], saved


def test_changing_the_selection_re_expands_what_is_now_shown(page, api, seed) -> None:
    """p.271's expansion is seeded, and the seed has to follow the configuration.

    An author with Default link expand set to 1 who swaps which link the widget
    draws should see the new section open. Seeded on the *object* alone, the
    expansion would still name the link that is no longer there — so the widget
    would sit fully folded and the setting would look broken until a reload.

    Driven entirely from the panel: nothing here clicks the widget, because in
    the builder a click on a widget is a selection rather than an interaction.
    """
    mod = build(api, seed, "Links reseed", {
        "linkMode": "specify",
        "links": [{"key": f"{seed.works_in}:outbound"}],
        "defaultExpand": 1,
    })
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Links").first.click()
    expect(header(page, "Department")).to_have_attribute("aria-expanded", "true")

    page.get_by_test_id(f"links-pick-{seed.works_in}:outbound").uncheck()
    page.get_by_test_id(f"links-pick-{seed.reports_to}:inbound").check()

    expect_labels(page, ["Direct reports"])
    expect(header(page, "Direct reports")).to_have_attribute("aria-expanded", "true")
