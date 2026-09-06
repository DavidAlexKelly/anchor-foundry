"""Finding one object type on the Ontology Manager's table.

**Written because §256 bounded that table.** It had no `LIMIT`, so every test
in this suite found its seeded type by scanning `tbody tr` for the tag — which
worked for exactly as long as the page was the whole ontology. On the
development workspace that is 791 object types; a page of fifty does not
contain a type created a moment ago with a name starting `seed_`.

Ten tests across five files failed the first time the bound landed, and all ten
failed the same way. That is the tell that this belonged in one place: each
file had grown its own `open_type_editor`, all of them four lines, all of them
scanning. The duplication was invisible while the assumption held.

**It searches rather than pages.** Paging to find a known type would be the
same scan with more requests; the search box beside the table is the control a
person would use, so it is the control the suite uses.
"""
from __future__ import annotations

from playwright.sync_api import expect


def find_type_row(page, needle: str):
    """The listing row for the object type whose name contains `needle`.

    Types into the table's search first, so the row is on the page whatever the
    workspace holds. Returns the row locator, already waited for.
    """
    search = page.get_by_test_id("type-search")
    expect(search).to_be_visible(timeout=30000)
    # `fill` rather than `type`: the query is state, and a leftover value from
    # a previous call in the same test would narrow this one to nothing.
    #
    # **And checked, then re-filled.** The box is a controlled input, so a
    # render that lands between the keystroke and React's state update writes
    # the old value straight back over it — and the page then searches for
    # nothing while the test waits for a row. It is not hypothetical: a save
    # elsewhere on the page invalidates the types query, and
    # `test_shared_properties` fills this box a few milliseconds after one.
    for _ in range(4):
        search.fill(needle)
        try:
            expect(search).to_have_value(needle, timeout=2000)
            break
        except AssertionError:
            continue
    expect(search).to_have_value(needle, timeout=5000)
    # **Scoped to the types table**, which is the whole reason this is a
    # function. The objects page draws eight tables and several of them mention
    # an object type by name - shared properties, value types, interfaces,
    # groups, link types, action types, dataset sources. An unscoped
    # `tbody tr` was right only because the types table was long enough to
    # contain the match first; a page of fifty narrowed by a search is one row,
    # and `.first` then lands wherever the DOM happens to put it.
    row = types_table(page).locator("tbody tr").filter(has_text=needle).first
    expect(row).to_be_visible(timeout=30000)
    return row


def types_table(page):
    """The object types table, told apart from the seven others on the page by
    the one column heading only it has."""
    return page.locator("table").filter(
        has=page.get_by_role("columnheader", name="Object type")
    ).first


def open_type_editor(page, needle: str) -> None:
    """Open the Edit dialog for the object type named by `needle`."""
    find_type_row(page, needle).get_by_role("button", name="Edit").click()


def pick_type(page, test_id: str, kind: dict) -> None:
    """Choose one object type in a `TypePicker` (§256).

    Searches first **when the picker offers a search**, which it does only on a
    workspace whose ontology outgrew a page. So this is the same two lines on a
    small workspace and the working ones on the development workspace, and a
    test written with it does not encode which of those it is running against.
    """
    picker = page.get_by_test_id(test_id)
    # **The select first, before anything is typed.** A picker in a dialog
    # mounts and then fetches, and `search.count()` on a dialog that has not
    # rendered yet returns zero - which reads as "this workspace is small
    # enough not to need a search" and skips straight to a select with nothing
    # in it. Found as an intermittent failure in `test_type_paging`.
    expect(picker).to_be_visible(timeout=20000)
    search = page.get_by_test_id(f"{test_id}-search")
    if search.count():
        search.fill(str(kind["api_name"]))
    # Waited for by *option*, not by the select: the select is on screen from
    # the first render and the option arrives with the search's response.
    expect(
        picker.locator(f'option[value="{kind["id"]}"]')
    ).to_be_attached(timeout=20000)
    picker.select_option(str(kind["id"]))
