"""p.223's **Default sort(s)** on the Object Table (parity `workshop.md` §10, item 4).

> "Default sort(s): This setting allows one or more default sorts to be applied
> to the table. Module builders can sort on both visible property types shown
> within the table or hidden property types not displayed. If no sort is
> applied, the data is not sorted." (p.223)

The rules are in two mutation-tested places without a browser:
`apps/web/src/components/canvas/table-sorts.test.ts` for what a document may
hold and what gets sent, and `apps/api/tests/test_object_sets.py` for what the
two stores do with it.

**What needs a browser is that the rows on screen are in that order.** A sort
travels from a settings panel, into a document, into a request, through two
possible stores and back into a table body - and every step of that can be
right while the table renders the page it always did, because a table with the
wrong order still looks like a table. So the assertions here read the rendered
cells.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set

from conftest import open_builder, open_module, settled

# `priority` ties three ways on purpose, and `stamp` breaks the tie in an order
# that is **not** the primary key's - which is the whole point of a second sort.
# By priority alone the tie group comes back S1, S3, S5 (key order); by stamp it
# comes back S5, S3, S1. A fixture whose second sort agreed with the tie-break
# would pass whether or not the second sort did anything.
ROWS = [
    {"id": "S1", "name": "Alpha", "priority": 40, "stamp": "2026-05-05"},
    {"id": "S2", "name": "Bravo", "priority": 7, "stamp": "2026-01-01"},
    {"id": "S3", "name": "Charlie", "priority": 40, "stamp": "2026-03-03"},
    {"id": "S4", "name": "Delta", "priority": 250, "stamp": "2026-02-02"},
    {"id": "S5", "name": "Echo", "priority": 40, "stamp": "2026-01-05"},
]
TYPES = {"priority": "integer", "stamp": "date"}


def build(api, name: str, sort, *, columns: str = "name,priority"):
    """One table over the fixture, with p.223's setting as `sort`."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "name", "priority", "stamp"], rows=ROWS, key="id",
        title="name", types=TYPES,
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {
                "resolvedName": "CanvasObjectTable",
                "props": {
                    "objectSetVariable": "v_all", "columns": columns,
                    "pageSize": 25, "activeVariable": None, "autoSelect": False,
                    "sort": sort,
                },
            },
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return mod


def save(page):
    """Click Save and wait for **this** save, not for a moment (§201).

    Waiting for "· saved" is not enough once a test saves twice: the header
    renders it from `save.isSuccess`, which stays true, so the second wait
    matches the *first* save's text and the assertion after it reads a document
    the click never reached. The version number is what actually changes, so
    the wait is for the header to stop saying what it said.
    """
    before = page.locator(".ws-actions .sub").text_content()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).not_to_have_text(before)
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")


def sort_prop(mod):
    """The `sort` prop **as the server holds it** - which is the only place the
    string-versus-list shape is observable. Both read back the same on screen,
    so a test that looked at the panel could not tell them apart."""
    return mod.definition()["layout"]["tbl"]["props"]["sort"]


def column(page, header: str = "Name") -> list[str]:
    """The rendered values of one column, top to bottom, **found by its header**.

    Not `nth-child(1)`: the table renders a Key column of its own before the
    configured ones, so a positional locator reads the primary key and every
    assertion about ordering passes or fails for the wrong reason. §207's
    lesson, in the same widget.
    """
    headers = page.locator(".data-grid thead th").all_text_contents()
    index = [h.strip() for h in headers].index(header)
    return [
        c.strip() for c in
        page.locator(f".data-grid tbody tr td:nth-child({index + 1})").all_text_contents()
    ]


# ---- p.223's "one or more" ---------------------------------------------------
def test_one_sort_orders_the_rows_on_screen(page, api) -> None:
    """The single sort, still working - it is what every module stored before
    p.223 holds, and the document shape did not change under it."""
    mod = build(api, "Table sort one", "priority")
    open_module(page, mod)
    settled(page)

    assert column(page) == ["Bravo", "Alpha", "Charlie", "Echo", "Delta"]


def test_a_second_sort_breaks_the_first_one_s_ties(page, api) -> None:
    """**The assertion this unit exists for.**

    Three rows share `priority` 40. Sorted by priority alone they come back in
    key order; the second sort has to override that, or it is configured and
    does nothing. `stamp` ascending puts the tie group Echo, Charlie, Alpha -
    which is neither key order nor its reverse, so no accident produces it.
    """
    mod = build(api, "Table sort two", ["priority", "stamp"])
    open_module(page, mod)
    settled(page)

    assert column(page) == ["Bravo", "Echo", "Charlie", "Alpha", "Delta"]


def test_the_order_of_the_sorts_is_the_setting(page, api) -> None:
    """"By priority then date" and "by date then priority" are different
    tables, so the list's order has to survive the round trip rather than being
    normalised on the way through."""
    mod = build(api, "Table sort order", ["stamp", "priority"])
    open_module(page, mod)
    settled(page)

    assert column(page) == ["Bravo", "Echo", "Delta", "Charlie", "Alpha"]


def test_a_descending_sort_still_puts_the_tie_group_together(page, api) -> None:
    mod = build(api, "Table sort desc", ["-priority", "stamp"])
    open_module(page, mod)
    settled(page)

    assert column(page) == ["Delta", "Echo", "Charlie", "Alpha", "Bravo"]


def test_a_hidden_property_can_be_sorted_on(page, api) -> None:
    """p.223 in its own words: "module builders can sort on both visible
    property types shown within the table **or hidden property types not
    displayed**". `stamp` is not among the columns here, and it still orders the
    page - which is why the panel's property field is not a column picker."""
    mod = build(api, "Table sort hidden", ["priority", "stamp"], columns="name")
    open_module(page, mod)
    settled(page)

    # Key plus the one configured column - `stamp` is nowhere on screen.
    assert "Stamp" not in page.locator(".data-grid thead th").all_text_contents()
    assert column(page) == ["Bravo", "Echo", "Charlie", "Alpha", "Delta"]


def test_no_sort_still_renders_a_table(page, api) -> None:
    """p.223's "if no sort is applied, the data is not sorted" - which here
    means the server's default ordering rather than none at all, because a page
    with no stated order cannot be paged consistently. What matters on screen is
    that the table renders and every row is present."""
    mod = build(api, "Table sort none", "")
    open_module(page, mod)
    settled(page)

    assert sorted(column(page)) == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]


def test_a_document_holding_a_repeat_still_renders(page, api) -> None:
    """**The widget reads the document before it sends it**, and this is where
    that is observable.

    The server *refuses* a repeated sort - the second entry can never break a
    tie the first did not - so a document holding one would 422 and the table
    would show its load error. A document can hold one easily: a hand-edit, a
    paste, or the raw JSON tab. So the widget drops it on the way out, and the
    table renders in the order the first entry asks for.

    Every other test here passes a sort the server would have accepted as
    written, which is why they cannot see the difference between sending the
    prop and sending what was read from it.
    """
    mod = build(api, "Table sort repeat", ["priority", "priority"])
    open_module(page, mod)
    settled(page)

    expect(page.get_by_text("Couldn't load these objects")).to_have_count(0)
    assert column(page) == ["Bravo", "Alpha", "Charlie", "Echo", "Delta"]


def test_a_document_holding_more_sorts_than_the_server_takes_still_renders(
    page, api
) -> None:
    """The same rule at the other limit: seven orderings are refused outright,
    and the widget sends the six it kept."""
    mod = build(api, "Table sort overflow",
                ["priority", "stamp", "key", "recent", "oldest", "-key", "-stamp"])
    open_module(page, mod)
    settled(page)

    expect(page.get_by_text("Couldn't load these objects")).to_have_count(0)
    assert column(page) == ["Bravo", "Echo", "Charlie", "Alpha", "Delta"]


def test_a_sort_the_server_refuses_does_not_empty_the_table(page, api) -> None:
    """`name` is a string property, and decision 0006 refuses string ordering
    permanently - Postgres orders by the database collation and OpenSearch by
    byte order. The request 422s, and what a viewer must not see is a table that
    silently became empty: an error belongs on screen."""
    mod = build(api, "Table sort refused", ["name"])
    open_module(page, mod)
    settled(page)

    # The table says it could not load rather than drawing an empty one - which
    # is the distinction that matters: "no rows match" and "this request was
    # refused" are different answers, and only one of them is a data question.
    expect(page.get_by_text("Couldn't load these objects")).to_be_visible()
    expect(page.locator(".data-grid tbody tr")).to_have_count(0)


# ---- the settings panel ------------------------------------------------------
def test_the_panel_reads_a_stored_string_as_one_row(page, api) -> None:
    """decision 0002: a document does not change when you open it. A module
    saved before p.223 holds `"recent"`, and opening its panel must show that
    one sort rather than migrating the document."""
    mod = build(api, "Table sort panel string", "recent")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-sort-kind-0")).to_have_value("recent")
    expect(page.get_by_test_id("table-sort-kind-1")).to_have_count(0)


def test_a_sort_can_be_added_and_removed_in_the_panel(page, api) -> None:
    mod = build(api, "Table sort panel add", "priority")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    page.get_by_test_id("table-sort-add").click()
    page.get_by_test_id("table-sort-property-1").select_option("stamp")
    # Two rows, and the summary says what the order means in words.
    expect(page.get_by_test_id("table-sorts-summary")).to_contain_text("then")

    # **The first of the two, not the last.** Removing the last row is what
    # `slice(0, -1)` also does, so a test that removed it could not tell the
    # two apart - and what survives is the assertion that matters.
    page.get_by_test_id("table-sort-remove-0").click()
    expect(page.get_by_test_id("table-sort-property-1")).to_have_count(0)
    expect(page.get_by_test_id("table-sort-property-0")).to_have_value("stamp")


def test_a_fixed_sort_offers_no_direction_of_its_own(page, api) -> None:
    """`-key` *is* the descending one, so a direction control beside "Key, Z-A"
    would put two answers to one question on the panel."""
    mod = build(api, "Table sort panel fixed", "-key")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    expect(page.get_by_test_id("table-sort-direction-0")).to_have_count(0)
    expect(page.get_by_test_id("table-sort-property-0")).to_have_count(0)

    # Switched to a property, both appear.
    page.get_by_test_id("table-sort-kind-0").select_option("")
    expect(page.get_by_test_id("table-sort-property-0")).to_be_visible()
    expect(page.get_by_test_id("table-sort-direction-0")).to_be_visible()


def test_one_sort_is_saved_as_a_string_and_several_as_a_list(page, api) -> None:
    """**Asserted on the saved document, not on the panel.**

    `["priority"]` and `"priority"` read back identically everywhere on screen,
    so nothing a viewer or a builder can see distinguishes them. What they
    change is the document - and decision 0002's whole point is that the
    document is the thing that outlives the code, so a table with one ordering
    must keep the shape every module before p.223 already had.
    """
    mod = build(api, "Table sort saved shape", "priority")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    # Touch the row so the panel writes the prop rather than leaving the
    # fixture's value in place - otherwise this asserts what `build` wrote.
    page.get_by_test_id("table-sort-property-0").select_option("stamp")
    save(page)
    assert sort_prop(mod) == "stamp"

    page.get_by_test_id("table-sort-add").click()
    page.get_by_test_id("table-sort-property-1").select_option("priority")
    save(page)
    assert sort_prop(mod) == ["stamp", "priority"]

    # And back down to one: the shape returns rather than staying a list, so a
    # table does not carry the scar of having briefly had two orderings.
    page.get_by_test_id("table-sort-remove-1").click()
    # Wait for the row to be gone before saving. Clicking Save and then waiting
    # for "saved" is not enough on its own: the header already said "saved" from
    # the write above, so the wait matches the *previous* save and the assertion
    # reads a document the click never reached. §201's rule, one level in.
    expect(page.get_by_test_id("table-sort-property-1")).to_have_count(0)
    save(page)
    assert sort_prop(mod) == "stamp"


def test_the_property_control_is_a_picker_over_the_orderable_properties(
    page, api
) -> None:
    """§225 left this a text box because the panel had no property list; §231
    gave it one (`property-sort.ts`), and a picker cannot name a property the
    type does not declare.

    **`name` must not be in it.** It is a column on this table and it is text,
    so it is exactly the property somebody would reach for — and the server
    refuses a text sort permanently, so the picker offering one would be a
    setting that can only produce an empty table. p.223's "hidden property
    types not displayed" still holds: `stamp` is not a configured column here
    and is offered anyway, because the list is the type's and not the table's.
    """
    mod = build(api, "Table sort picker", "priority", columns="name,priority")
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    picker = page.get_by_test_id("table-sort-property-0")
    values = picker.locator("option").evaluate_all("nodes => nodes.map(n => n.value)")
    assert values == ["", "priority", "stamp"], values


def test_the_panel_stops_at_the_cap_the_server_enforces(page, api) -> None:
    """A seventh row would be a control offering something the request refuses,
    which is the shape §214 called a setting that looks like it works."""
    mod = build(api, "Table sort panel cap", ["priority", "stamp"])
    open_builder(page, mod)
    settled(page)

    page.locator(".canvas-tree-row").filter(has_text="Object table").first.click()
    for _ in range(4):
        page.get_by_test_id("table-sort-add").click()
    expect(page.get_by_test_id("table-sort-kind-5")).to_be_visible()
    expect(page.get_by_test_id("table-sort-add")).to_have_count(0)
