"""Workshop's drag and drop: a Section drop zone and the three drag zones
(parity `workshop.md` §2 and §11; `foundry_workshop` p.55, p.274, p.564–570).

> "To turn the section component into a drop zone, select the relevant section
> and toggle Drop Handling… The Drop label and Drop icon settings determine the
> text and icon that will appear on the drop zone… Select the object set
> variable that the dropped data should be written to. This can be used to
> populate an object table, for example. An event can also be configured to
> fire after the drop." (p.564–568)

What a drag carries and what a drop writes are pure, and are in
`apps/web/src/components/canvas/drag-payload.test.ts`; what the server makes of
the written clauses is in `test_workshop_variables.py`. **What needs a browser
is the handoff**: a real `dragstart` on one widget setting data that a real
`drop` on another reads, through the page's own `DataTransfer`, and a table
downstream of the variable changing because of it.

One module holds everything, because the claim is that the zones and the drop
zone agree on a contract without knowing each other exist: a table of sites
(p.570's cells), an Object Set Title over the northern sites (p.569), an Object
View of one site (p.570's icon), and a table of **staff whose keys collide
with the sites'** - so a drop that forgot its type would visibly pick the
wrong object instead of none.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_module, select_node, open_builder, settled

SITES = [
    {"id": "S1", "region": "north", "name": "Alpha site"},
    {"id": "S2", "region": "north", "name": "Bravo site"},
    {"id": "S3", "region": "south", "name": "Charlie site"},
]
# **The same keys as two of the sites**, on purpose. See the module docstring.
STAFF = [
    {"sid": "S1", "name": "Staff one"},
    {"sid": "S9", "name": "Staff nine"},
]


@pytest.fixture(scope="module")
def dnd(api):
    mod = Module(api, "Drag and drop")
    tag = uuid.uuid4().hex[:8]
    sites = mod.object_type(
        columns=["id", "region", "name"], rows=SITES, key="id", title="name",
        slug=f"site_{tag}",
    )
    staff = mod.object_type(
        columns=["sid", "name"], rows=STAFF, key="sid", title="name",
        slug=f"staff_{tag}",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "src": {"resolvedName": "CanvasObjectTable",
                    "props": {"objectSetVariable": "v_sites", "columns": "name",
                              "pageSize": 25}},
            "staff": {"resolvedName": "CanvasObjectTable",
                      "props": {"objectSetVariable": "v_staff", "columns": "name",
                                "pageSize": 25}},
            "title": {"resolvedName": "CanvasObjectSetTitle",
                      "props": {"objectSetVariable": "v_north", "enableDrag": True}},
            "view": {"resolvedName": "CanvasObjectViewWidget",
                     "props": {"objectSetVariable": "v_bravo"}},
            # A drop zone around the drop zone, so "the innermost zone takes
            # it" is a claim something can check.
            "outer": {"resolvedName": "CanvasSection", "isCanvas": True,
                      "nodes": ["outer_note", "zone"],
                      "props": {"direction": "rows", "dropHandling": True}},
            "outer_note": {"resolvedName": "CanvasText", "parent": "outer",
                           "props": {"tag": "p", "text": "OUTER={{v_outer}}"}},
            "zone": {"resolvedName": "CanvasSection", "isCanvas": True, "parent": "outer",
                     "nodes": ["picked", "note"],
                     "props": {"direction": "rows", "dropHandling": True,
                               "dropLabel": "Drop sites here", "dropIcon": "+",
                               "dropVariable": "v_dropped"}},
            "picked": {"resolvedName": "CanvasObjectTable", "parent": "zone",
                       "props": {"objectSetVariable": "v_picked", "columns": "name",
                                 "pageSize": 25}},
            "note": {"resolvedName": "CanvasText", "parent": "zone",
                     "props": {"tag": "p", "text": "NOTE={{v_note}}"}},
        }),
        "variables": {
            "v_sites": {"id": "v_sites", "kind": "object_set", "label": "Sites",
                        "object_set": object_set(sites)},
            "v_staff": {"id": "v_staff", "kind": "object_set", "label": "Staff",
                        "object_set": object_set(staff)},
            "v_north": {"id": "v_north", "kind": "object_set", "label": "North",
                        "object_set": object_set(sites, [
                            {"property": "region", "op": "eq", "value": "north"}])},
            "v_bravo": {"id": "v_bravo", "kind": "object_set", "label": "Bravo",
                        "object_set": object_set(sites, [
                            {"property": "$primary_key", "op": "in", "value": ["S2"]}])},
            "v_dropped": {"id": "v_dropped", "kind": "array", "label": "Dropped"},
            "v_picked": {"id": "v_picked", "kind": "object_set", "label": "Picked",
                         "derivation": {"transform": "narrow_set",
                                        "inputs": ["v_sites", "v_dropped"]}},
            "v_note": {"id": "v_note", "kind": "string", "label": "Note",
                       "default": "none"},
            "v_outer": {"id": "v_outer", "kind": "string", "label": "Outer",
                        "default": "none"},
        },
        "events": {
            "e_drop": {"id": "e_drop", "trigger": {"node": "zone", "on": "drop"},
                       "effects": [{"type": "set_variable",
                                    "config": {"variable": "v_note",
                                               "value": "dropped {{count}}"}}]},
            "e_outer": {"id": "e_outer", "trigger": {"node": "outer", "on": "drop"},
                        "effects": [{"type": "set_variable",
                                     "config": {"variable": "v_outer",
                                                "value": "outer {{count}}"}}]},
        },
    })
    return mod


def open_settled(page, module) -> None:
    """Open the module and wait until nothing on it will move.

    **A drag is aimed at coordinates**, measured once, before the press. The
    zone is the last widget on the page, so the Object View above it finishing
    its load mid-drag pushed the zone down and the drop landed where it used
    to be - no refusal, no event, just a drop on something else. So every
    widget that loads is waited for, and the viewport is tall enough for the
    source and the zone to be on screen together.
    """
    page.set_viewport_size({"width": 1280, "height": 1800})
    open_module(page, module)
    expect(picked_rows(page)).to_have_count(3, timeout=30000)
    expect(page.get_by_text("Staff nine")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("set-title")).to_have_attribute("data-drag", "ready", timeout=30000)
    expect(page.get_by_test_id("standard-object-view")).to_have_attribute(
        "data-state", "ready", timeout=30000)
    expect(page.get_by_text("NOTE=none")).to_be_visible()


def picked_rows(page):
    return zone(page).locator("table tbody tr")


def zone(page):
    return page.get_by_test_id("drop-zone-zone")


def drag(page, source, target) -> None:
    """A real HTML5 drag, pressed, nudged and carried in steps.

    **Not Playwright's `drag_to`**, which moves in one jump: about one run in
    eight it released before the browser had begun the drag, the drop never
    arrived, and the test read a working zone as a broken one. A first small
    move is what starts a drag at all; the steps give the browser a
    `dragenter` on the way in, which is what a person's pointer gives it too.
    """
    expect(source).to_be_visible(timeout=30000)
    start = source.bounding_box()
    end = target.bounding_box()
    assert start is not None and end is not None
    x, y = start["x"] + min(20, start["width"] / 2), start["y"] + start["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 10, y)
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=5)
    page.mouse.up()


def source_row(page, name: str):
    return page.locator("table tbody tr").filter(has_text=name).first


def test_a_table_cell_dropped_on_the_section_narrows_what_it_shows(page, dnd) -> None:
    """p.570's cell drag, p.568's Output object set, and p.568's event - the
    whole chain in one drop."""
    open_settled(page, dnd)
    # Before anything is dropped the zone's table shows the whole set: an
    # empty clause list is no filter, the rule every narrow_set follows.
    expect(picked_rows(page)).to_have_count(3, timeout=30000)
    expect(page.get_by_text("NOTE=none")).to_be_visible()

    drag(page, source_row(page, "Charlie site"), zone(page))

    # The event first: it says the drop arrived, so a wrong count after it is
    # about the write rather than about the drag.
    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(1, timeout=15000)
    expect(picked_rows(page).first).to_contain_text("Charlie site")
    # The innermost zone took it; the one around it did not also fire.
    expect(page.get_by_text("OUTER=none")).to_be_visible()


def test_an_object_of_another_type_narrows_to_nothing(page, dnd) -> None:
    """**The collision the fixture was built for.** Staff "S1" shares its key
    with Alpha site. A drop that carried only the key would show Alpha site -
    a real object nobody dragged - and nothing on screen would say it was
    wrong."""
    open_settled(page, dnd)
    expect(picked_rows(page)).to_have_count(3, timeout=30000)

    drag(page, source_row(page, "Staff one"), zone(page))

    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(0, timeout=15000)


def test_an_object_set_title_drags_every_object_in_its_set(page, dnd) -> None:
    """p.274's Enable drag, and p.569: the title carries the set - here the
    two northern sites, not the one row the title happened to fetch."""
    open_settled(page, dnd)
    title = page.get_by_test_id("set-title")
    expect(title).to_have_attribute("data-drag", "ready", timeout=30000)

    drag(page, title, zone(page))

    expect(page.get_by_text("NOTE=dropped 2")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(2, timeout=15000)
    expect(zone(page)).to_contain_text("Alpha site")
    expect(zone(page)).to_contain_text("Bravo site")


def test_an_object_views_icon_drags_its_object(page, dnd) -> None:
    """p.570: "The icon in the object view widget header can be dragged onto
    compatible drop zones." """
    open_settled(page, dnd)
    mark = page.get_by_test_id("sov-type-mark")
    expect(mark).to_have_attribute("draggable", "true", timeout=30000)

    drag(page, mark, zone(page))

    expect(picked_rows(page)).to_have_count(1, timeout=15000)
    expect(picked_rows(page).first).to_contain_text("Bravo site")


def test_the_zone_shows_its_label_and_icon_while_something_is_over_it(page, dnd) -> None:
    """p.566: "the text and icon that will appear on the drop zone" - and only
    while a payload is over it, so it is asserted absent on both sides."""
    open_settled(page, dnd)
    overlay = page.get_by_test_id("drop-overlay-zone")
    row = source_row(page, "Alpha site")
    expect(row).to_be_visible(timeout=30000)
    expect(overlay).to_have_count(0)

    start = row.bounding_box()
    box = zone(page).bounding_box()
    assert start is not None and box is not None
    page.mouse.move(start["x"] + 20, start["y"] + start["height"] / 2)
    page.mouse.down()
    # `drag`, without its release, so the pointer is still over the zone.
    page.mouse.move(start["x"] + 30, start["y"] + start["height"] / 2)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=5)
    expect(overlay).to_be_visible()
    expect(overlay).to_contain_text("+")
    expect(overlay).to_contain_text("Drop sites here")

    # **Across the zone's own children, it stays lit.** Every child boundary
    # the pointer crosses sends a `dragleave`, and one that counted as leaving
    # the zone would flicker the overlay off until the next `dragover` - a
    # flash the eye catches and a single `expect` does not. So every value the
    # zone's state takes is recorded while the pointer walks from its note
    # down through its table.
    page.evaluate("""() => {
        const zone = document.querySelector('[data-testid=drop-zone-zone]');
        window.__zoneStates = [];
        new MutationObserver(() => window.__zoneStates.push(zone.dataset.dropZone))
            .observe(zone, { attributes: true, attributeFilter: ['data-drop-zone'] });
    }""")
    note = page.get_by_text("NOTE=none").bounding_box()
    last = picked_rows(page).last.bounding_box()
    assert note is not None and last is not None
    page.mouse.move(note["x"] + 5, note["y"] + note["height"] / 2, steps=8)
    page.mouse.move(last["x"] + 30, last["y"] + last["height"] / 2, steps=12)
    expect(overlay).to_be_visible()
    assert "ready" not in page.evaluate("() => window.__zoneStates"), (
        "the overlay went out while the pointer was still inside the zone"
    )
    page.mouse.up()

    expect(overlay).to_have_count(0)
    expect(picked_rows(page)).to_have_count(1, timeout=15000)


def test_the_outer_zone_takes_a_drop_on_itself(page, dnd) -> None:
    """The counterweight to the line above: the outer zone is a live zone, so
    its silence there means the inner one kept the drop, not that the outer
    one could never have fired."""
    open_settled(page, dnd)
    drag(page, source_row(page, "Alpha site"), page.get_by_text("OUTER=none"))
    expect(page.get_by_text("OUTER=outer 1")).to_be_visible(timeout=15000)
    expect(page.get_by_text("NOTE=none")).to_be_visible()


def test_a_drag_carrying_nothing_of_ours_is_not_taken(page, dnd) -> None:
    """The zone accepts p.568's two media types and nothing else. Text dragged
    onto it is ignored - the variable is untouched and no event fires - rather
    than being read as an empty drop that clears the table."""
    open_settled(page, dnd)
    expect(picked_rows(page)).to_have_count(3, timeout=30000)
    page.evaluate(
        """() => {
            const zone = document.querySelector('[data-testid=drop-zone-zone]');
            const data = new DataTransfer();
            data.setData('text/plain', 'S1');
            for (const type of ['dragenter', 'dragover', 'drop']) {
                zone.dispatchEvent(new DragEvent(type, {
                    bubbles: true, cancelable: true, dataTransfer: data,
                }));
            }
        }"""
    )
    # Passed over, not refused: a refusal is for a drag that claimed our type.
    expect(page.get_by_test_id("drop-refused-zone")).to_have_count(0)
    # The negative after a positive (§318): a real drop afterwards lands, so
    # the one before it had its chance to.
    drag(page, source_row(page, "Bravo site"), zone(page))
    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(1)
    expect(picked_rows(page).first).to_contain_text("Bravo site")


def test_a_forged_payload_is_refused_and_says_so(page, dnd) -> None:
    """A drag can come from anywhere on the page. One that claims our type and
    carries nonsense is refused out loud - a drop that silently did nothing
    looks exactly like a broken drop zone."""
    open_settled(page, dnd)
    expect(picked_rows(page)).to_have_count(3, timeout=30000)
    page.evaluate(
        """() => {
            const zone = document.querySelector('[data-testid=drop-zone-zone]');
            const data = new DataTransfer();
            data.setData('application/x-anchor-object', '{"primary_keys": ["S1"]}');
            for (const type of ['dragenter', 'dragover', 'drop']) {
                zone.dispatchEvent(new DragEvent(type, {
                    bubbles: true, cancelable: true, dataTransfer: data,
                }));
            }
        }"""
    )
    expect(page.get_by_test_id("drop-refused-zone")).to_be_visible()
    expect(page.get_by_text("NOTE=none")).to_be_visible()
    expect(picked_rows(page)).to_have_count(3)


def test_the_builder_offers_drop_handling_and_does_not_drop(page, dnd) -> None:
    """p.564-565's toggle and the fields it reveals, in the builder - where a
    drag is the builder moving widgets, so the zone is not live."""
    open_builder(page, dnd)
    settled(page)
    expect(page.locator("[data-drop-zone]")).to_have_count(0)
    # The inner zone is the second Section in the Layout tree; the first is
    # the zone around it.
    select_node(page, "Section")
    page.locator(".canvas-tree-row", has_text="Section").nth(1).click()
    expect(page.get_by_test_id("section-drop-handling")).to_be_checked()
    expect(page.get_by_test_id("section-drop-label")).to_have_value("Drop sites here")
    expect(page.get_by_test_id("section-drop-icon")).to_have_value("+")
    expect(page.get_by_test_id("section-drop-variable")).to_have_value("v_dropped")
