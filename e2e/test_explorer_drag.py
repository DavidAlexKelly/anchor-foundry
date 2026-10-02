"""The Object Explorer as a drag source for Workshop's drop zones (§673;
`workshop` p.564-570).

> "Use drag and drop and the App Pairing widget to integrate your Workshop
> module with and connect it to other Palantir applications." (p.562)
>
> "This drop zone accepts the Foundry object RID and the Foundry object set
> media type." (p.568)

An object's key in the Explorer's results, and the icon of the object open
there, carry the object media type a Workshop table cell does (§457), so a
module's drop zone takes them without knowing where they came from.

**Two pages, so two halves.** A drag cannot be carried by the mouse from
one tab to another in this harness, so the handoff is tested as its
contract: a real `dragstart` on the Explorer fills a `DataTransfer`, and that
data, put on a `drop` at the module's zone, narrows the zone's table to the
object dragged. `test_drag_and_drop.py` carries a drag by the mouse within a
module; this is the same drop, arriving from outside it.
"""
from __future__ import annotations

from playwright.sync_api import expect

from conftest import WEB_BASE, eventually
from test_drag_and_drop import dnd, open_settled, picked_rows, zone  # noqa: F401

MEDIA = "application/x-anchor-object"

#: A real `dragstart` on the element, and what it put on the transfer.
CAPTURE = """(el) => {
  const dt = new DataTransfer();
  el.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
  return Object.fromEntries(dt.types.map((t) => [t, dt.getData(t)]));
}"""

#: The captured data dropped on the zone, as a browser delivers a drop.
DROP = """([el, data]) => {
  const dt = new DataTransfer();
  for (const [type, value] of Object.entries(data)) dt.setData(type, value);
  for (const kind of ["dragenter", "dragover", "drop"]) {
    el.dispatchEvent(new DragEvent(kind, { bubbles: true, cancelable: true, dataTransfer: dt }));
  }
}"""


def sites_type(dnd) -> str:
    return dnd.definition()["variables"]["v_sites"]["object_set"]["object_type_id"]


def open_explorer(page, dnd) -> None:
    page.goto(f"{WEB_BASE}/{dnd.workspace_slug}/explore?type={sites_type(dnd)}")
    rows = page.locator("tbody tr")
    eventually(lambda: rows.count(), lambda n: n == 3, what="the sites in the Explorer")


def test_an_explorer_row_dropped_on_a_module_s_zone(page, dnd) -> None:
    open_explorer(page, dnd)
    row = page.locator("tbody tr").filter(has_text="Charlie site").first
    handle = row.get_by_test_id("explorer-drag")
    expect(handle).to_have_attribute("draggable", "true")
    carried = handle.evaluate(CAPTURE)
    assert carried["text/plain"] == "S3"
    assert '"primary_keys": ["S3"]'.replace(" ", "") in carried[MEDIA].replace(" ", "")

    open_settled(page, dnd)
    page.evaluate(DROP, [zone(page).element_handle(), carried])
    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(1, timeout=15000)
    expect(picked_rows(page).first).to_contain_text("Charlie site")


def test_the_object_open_in_the_explorer_drags_by_its_icon(page, dnd) -> None:
    open_explorer(page, dnd)
    page.locator("tbody tr").filter(has_text="Bravo site").first.get_by_role(
        "button", name="Explore").click()
    mark = page.get_by_test_id("sov-type-mark")
    expect(mark).to_have_attribute("draggable", "true")
    carried = mark.evaluate(CAPTURE)
    assert MEDIA in carried

    open_settled(page, dnd)
    page.evaluate(DROP, [zone(page).element_handle(), carried])
    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(1, timeout=15000)
    expect(picked_rows(page).first).to_contain_text("Bravo site")


def test_a_linked_object_in_the_side_panel_drags_as_its_own_type(page, api, dnd) -> None:
    """p.11's side panel holds a linked object - here the staff member S1
    beside Alpha site - and its icon carries *that* object: dropped on the
    sites' zone it is another type's S1, which narrows the sites to none."""
    variables = dnd.definition()["variables"]
    tag = dnd.tag
    api.call("POST", f"/workspaces/{dnd.workspace_id}/link-types", {
        "api_name": f"staffed_{tag}", "display_name": "Staffed by",
        "from_type_id": variables["v_sites"]["object_set"]["object_type_id"],
        "to_type_id": variables["v_staff"]["object_set"]["object_type_id"],
        "cardinality": "one_to_one", "from_property": "id", "to_property": "sid",
        "from_side_name": "Site", "to_side_name": "Staff"})
    open_explorer(page, dnd)
    page.locator("tbody tr").filter(has_text="Alpha site").first.get_by_role(
        "button", name="Explore").click()
    page.get_by_role("button", name="Show S1 in the side panel").click()
    mark = page.get_by_role("complementary", name="Linked object panel").get_by_test_id("sov-type-mark")
    expect(mark).to_have_attribute("draggable", "true")
    carried = mark.evaluate(CAPTURE)

    open_settled(page, dnd)
    page.evaluate(DROP, [zone(page).element_handle(), carried])
    expect(page.get_by_text("NOTE=dropped 1")).to_be_visible(timeout=15000)
    expect(picked_rows(page)).to_have_count(0, timeout=15000)
