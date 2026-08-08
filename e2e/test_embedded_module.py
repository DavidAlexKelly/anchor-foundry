"""One Workshop module inside another (roadmap 1.5, priority 4).

**The thing that could only be settled in a browser**: every widget calls
Craft.js's `useNode()`, which needs an `<Editor>` above it, so an embedded
module renders inside a *nested* editor. Whether Craft.js tolerates that at all
is not answerable by reading its source with any confidence — two editors on
one page share a document, a selection and a set of drag handlers. This suite
is the answer.

What the server already refuses is tested in `apps/api/tests/test_canvas.py`:
self-embedding, cycles, a module outside the project, and depth past three.
Those are decided when the author saves, so they never reach here.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_module

COUNTS = {"north": 4, "south": 2}
TOTAL = sum(COUNTS.values())


@pytest.fixture(scope="module")
def modules(api):
    """An inner module with a table and its own variable, and an outer module
    that embeds it beside a table of its own.

    Both read the same object type, and the **inner one is filtered to north**
    — so "the inner module ran its own variables" and "the inner module
    inherited the outer's" produce visibly different row counts rather than
    needing to be told apart by inspection.
    """
    rows = [
        {"id": f"{region[0].upper()}{i}", "region": region, "name": f"Site {region} {i}"}
        for region, count in COUNTS.items()
        for i in range(1, count + 1)
    ]
    inner = Module(api, "Inner")
    type_id = inner.object_type(
        columns=["id", "region", "name"], rows=rows, key="id", title="name"
    )
    inner.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "INNER MODULE"}},
            "tbl": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_north", "columns": "id,region",
                              "pageSize": 25}},
        }),
        "variables": {
            "v_north": {
                "id": "v_north", "kind": "object_set", "label": "North only",
                "object_set": object_set(
                    type_id, [{"property": "region", "op": "eq", "value": "north"}]
                ),
            }
        },
        "events": {},
    })

    # **In the inner module's project.** The server refuses an embed across
    # projects, correctly — and the first version of this fixture put them in
    # separate ones, so the widget was asked to load a module the viewer's
    # project does not contain and reported exactly that.
    outer = Module(api, "Outer", beside=inner)
    outer.object_type_id = type_id
    outer.define({
        "format": 2,
        "layout": layout({
            "own": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_all", "columns": "id,region",
                              "pageSize": 25}},
            "emb": {"resolvedName": "CanvasEmbeddedModule",
                    "props": {"moduleId": inner.app_id, "title": "Embedded"}},
        }),
        "variables": {
            "v_all": {"id": "v_all", "kind": "object_set", "label": "All sites",
                      "object_set": object_set(type_id)},
        },
        "events": {},
    })
    return outer, inner


def tables(page):
    return page.locator(".canvas-block table tbody")


def test_an_embedded_module_renders_inside_its_host(page, modules):
    """The nested-`<Editor>` question, answered. If Craft.js refused a nested
    editor this is where it would show — as an error boundary, an empty box, or
    a console error, all of which this catches."""
    outer, _ = modules
    open_module(page, outer)

    embedded = page.locator(".canvas-embedded")
    expect(embedded).to_have_count(1)
    # **Visible, not merely present.** `to_contain_text` reads `textContent`,
    # which a `display: none` element still has — a mutation hiding the embed
    # sailed through a version of this that only asserted the text. Rendered
    # and invisible is a distinction a viewer very much notices.
    expect(embedded).to_be_visible()
    expect(embedded.get_by_text("INNER MODULE")).to_be_visible()
    assert not no_console_errors(page)


def test_the_inner_module_runs_its_own_variables(page, modules):
    """**The boundary is a wall, not a leak.** The inner module's set is
    filtered to north and the outer's is not, so an inner table showing every
    row would mean it had resolved against the host's variables — a collision
    that would be silent and would look like it was working."""
    outer, _ = modules
    open_module(page, outer)

    inner_rows = page.locator(".canvas-embedded table tbody tr")
    expect(inner_rows).to_have_count(COUNTS["north"])

    # And the host's own table is unfiltered, so the two are visibly different
    # pictures of one object type rather than two copies of one picture.
    all_rows = page.locator(".canvas-block table tbody tr")
    eventually(lambda: all_rows.count(), lambda n: n == TOTAL + COUNTS["north"],
               what="host rows plus embedded rows")


def test_an_embedded_module_is_not_editable_in_place(page, modules):
    """Editing a module means opening it. A nested *editable* canvas would put
    two documents' selections and drag targets on one screen with no way to say
    which a gesture meant."""
    outer, _ = modules
    open_module(page, outer)
    embedded = page.locator(".canvas-embedded")
    expect(embedded).to_contain_text("INNER MODULE")

    # Presence before absence: the inner content is there, so "no drag handles"
    # is about the inner editor being disabled rather than about an empty box.
    assert embedded.locator("[draggable='true']").count() == 0


def test_the_host_still_works_around_the_embed(page, modules):
    """A nested editor that broke the outer one would be a poor trade. The
    host's own widgets are asserted *after* the embed has rendered, so this is
    about coexistence rather than about load order."""
    outer, _ = modules
    open_module(page, outer)
    expect(page.locator(".canvas-embedded")).to_contain_text("INNER MODULE")
    expect(tables(page).first.locator("tr")).to_have_count(TOTAL)
