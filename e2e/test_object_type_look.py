"""An object type's icon and colour (§449; `object-link-types` p.15).

    "Icon: Select the default icon to customize the icon and color of the
     object type; this icon and color will be displayed in user applications
     when a user views an object of this type." (p.15)

Both halves had been on the wire since the schema was written and on no screen
at all: nothing set them, and nothing drew them. The editor sent neither, so
**every edit of a type wrote the route's defaults over whatever was there** —
the defect `apps/api/tests/test_objects.py` now pins, and the reason the
fields exist here.

What the glyph rule is, and what a stored Foundry icon name falls back to, is
`apps/web/src/lib/object-type-icon.test.ts`'s. What needs a browser is the
seam and p.15's own sentence: that the control writes what the server keeps,
and that the mark is there **where a user views an object of this type**.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually
from ontology_page import find_type_row

ROWS = [{"code": "A1", "town": "Ely"}, {"code": "B2", "town": "Wells"}]


@pytest.fixture(scope="module")
def module(api):
    mod = Module(api, "Type look")
    mod.object_type(columns=["code", "town"], rows=ROWS, key="code", title="town")
    return mod


def stored(api, module) -> dict:
    return api.call(
        "GET",
        f"/workspaces/{module.workspace_id}/object-types/{module.object_type_id}",
    )


def open_type_editor(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/objects")
    find_type_row(page, f"seed_{module.tag}").get_by_role("button", name="Edit").click()
    expect(page.get_by_role("textbox", name="Property 1 name")).to_be_visible(
        timeout=30000)


def save(page) -> None:
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0, timeout=30000)


def test_a_type_starts_with_the_stored_foundry_name_and_draws_its_initial(
    page, api, module
) -> None:
    """**The corpus, and why a name is not a glyph.** Every type here was
    created with `icon = "cube"`, which is a name from a set this platform
    does not have — drawing two letters of it would put "cu" on every card."""
    assert stored(api, module)["icon"] == "cube"
    open_type_editor(page, module)
    preview = page.get_by_test_id("type-mark-preview")
    expect(preview).to_be_visible(timeout=30000)
    expect(preview).to_have_text("S")  # "Seed <tag>"


def test_the_field_says_why_the_mark_is_a_letter(page, api, module) -> None:
    """A stored name is not a problem — the type predates the control — but a
    reader looking at an initial needs to know where it came from (§337)."""
    open_type_editor(page, module)
    field = page.get_by_test_id("type-icon").locator("xpath=ancestor::*[contains(@class,'field')][1]")
    expect(field).to_contain_text("cube", timeout=30000)
    expect(field).to_contain_text("first letter")


def test_an_icon_and_colour_chosen_here_are_what_the_server_keeps(
    page, api, module
) -> None:
    """**The seam.** A control that filled in and stored nothing looks exactly
    like one that worked — so this is asked of the server."""
    open_type_editor(page, module)
    page.get_by_test_id("type-icon").fill("🚢")
    # `fill`, not a scripted `value =`: a controlled input only hears React's
    # own setter, so assigning the property and dispatching `input` moved the
    # swatch and told the component nothing — the icon saved and the colour
    # did not, which is how this was found.
    page.get_by_test_id("type-colour").fill("#b3261e")
    preview = page.get_by_test_id("type-mark-preview")
    expect(preview).to_have_text("🚢")
    # **And the preview takes the colour**, which the sweep had to ask for: a
    # swatch that ignored it would be a colour picked blind, and picking a
    # colour without seeing what it is behind is picking it twice.
    eventually(lambda: preview.evaluate("el => getComputedStyle(el).backgroundColor"),
               lambda c: c == "rgb(179, 38, 30)",
               what="the preview to show the colour that was chosen")
    save(page)

    eventually(lambda: stored(api, module)["icon"], lambda i: i == "🚢",
               what="the icon the editor sent")
    assert stored(api, module)["colour"] == "#b3261e", stored(api, module)


def test_an_edit_that_touches_something_else_keeps_the_look(
    page, api, module
) -> None:
    """**The defect this unit exists for, from the screen.**

    `icon` and `colour` were on the wire and on no screen, so the dialog sent
    neither and the route defaulted them — every edit, for any reason, wrote
    `cube` and the platform green over whatever somebody had chosen. Asserted
    against the server, because a dialog that still showed the old mark while
    having sent the default would look correct and be the same bug.
    """
    open_type_editor(page, module)
    page.get_by_role("textbox", name="Display name").fill(f"Seed {module.tag} renamed")
    save(page)

    eventually(lambda: stored(api, module)["display_name"],
               lambda n: n.endswith("renamed"),
               what="the rename to have landed")
    after = stored(api, module)
    assert after["icon"] == "🚢", after
    assert after["colour"] == "#b3261e", after


def test_the_field_refuses_a_third_character_rather_than_cutting_it(
    page, api, module
) -> None:
    """**The difference between a limit and a surprise.**

    An icon longer than two characters is read as a name from Foundry's set
    and drawn as an initial, so a field that accepted one would store a value
    the reader never sees and show a letter they did not choose. The limit is
    on the control, where the typing stops.
    """
    open_type_editor(page, module)
    field = page.get_by_test_id("type-icon")
    assert field.get_attribute("maxlength") == "2"

    field.fill("")
    field.type("ABC")
    assert field.input_value() == "AB"


def test_the_mark_is_on_the_object_view_where_p15_says_it_is(
    page, api, module
) -> None:
    """p.15: the icon and colour "will be displayed in user applications
    **when a user views an object of this type**"."""
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("standard-object-view")).to_be_visible(timeout=30000)

    mark = page.get_by_test_id("sov-type-mark")
    expect(mark).to_be_visible()
    expect(mark).to_have_text("🚢")
    assert mark.evaluate("el => getComputedStyle(el).backgroundColor") == "rgb(179, 38, 30)"


def test_the_mark_is_in_the_explorers_type_list(page, api, module) -> None:
    """The other screen a reader tells one type from thirty on."""
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    mark = page.get_by_test_id(f"type-mark-{module.object_type_id}")
    expect(mark).to_be_visible(timeout=30000)
    expect(mark).to_have_text("🚢")


def test_clearing_the_icon_falls_back_to_the_initial_rather_than_to_nothing(
    page, api, module
) -> None:
    """A blank mark beside a name is a rendering fault to look at; the type's
    own initial is at least true."""
    open_type_editor(page, module)
    page.get_by_test_id("type-icon").fill("")
    expect(page.get_by_test_id("type-mark-preview")).to_have_text("S")
    save(page)

    eventually(lambda: stored(api, module)["icon"], lambda i: i == "",
               what="the cleared icon to have been stored as cleared")
    page.goto(
        f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    expect(page.get_by_test_id(f"type-mark-{module.object_type_id}")).to_have_text(
        "S", timeout=30000)
