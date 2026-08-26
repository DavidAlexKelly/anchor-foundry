"""p.73's Duplicate and New-variable-from-current (parity `workshop.md` §3.3).

> "**New variable from current** (object set variables only): Next to the
> duplicate variable button, the New variable from current button allows you to
> create a new object set variable that automatically takes the current object
> set as its input. This is useful when you want to build upon an existing
> object set's configuration while maintaining a reference to the source
> variable." (p.73)

Which fields survive a copy, what a new label is, and what an external ID takes
with it when it goes are all checked in
`apps/web/src/components/canvas/variable-create.test.ts`, without a browser.

What needs one is everything a pure function cannot see: that the buttons are
where p.73 puts them, that "object set variables only" is enforced by the
*kind of the variable actually open* rather than by whatever the panel last
rendered, that a copy is added to the module rather than replacing anything,
that the note about dropped settings reaches the screen — and, the one that
matters most, that **what the panel produces is something the server accepts**.
A duplicate that carried the external ID would pass every unit test that did
not think to look, and fail on save with a 422 naming a variable the author
never touched.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import open_builder, settled


def module_with(api, name: str):
    """One routed, saved, interface-carrying string variable and one object set.

    The string variable has all three of p.72's settings on, because the
    interesting half of Duplicate is what it *cannot* bring with it. The object
    set exists so the second button has a subject.
    """
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["id", "name"],
        rows=[{"id": "R1", "name": "Ada"}],
        key="id", title="name",
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "hello"}},
        }),
        "variables": {
            "v_region": {
                "id": "v_region", "kind": "string", "label": "Region",
                "external_id": "region",
                "interface": {"required": False},
                "url_behavior": "always",
                "save_state": True,
            },
            "v_all": {
                "id": "v_all", "kind": "object_set", "label": "All orders",
                "object_set": object_set(type_id),
            },
            "v_plain": {"id": "v_plain", "kind": "string", "label": "Plain"},
        },
        "routing": {"enabled": True},
        "state_saving": {"enabled": True},
        "events": {},
    })
    return mod


def open_variables(page):
    page.get_by_role("button", name="Variables", exact=False).first.click()


def rows(page):
    return page.locator(".vars-row")


def labels(page) -> list[str]:
    return [rows(page).nth(i).inner_text().split("\n")[0] for i in range(rows(page).count())]


def open_variable(page, label: str):
    page.locator(".vars-row").filter(has_text=label).first.click()


def save(page):
    """Click Save and **wait for the save**, not for a moment.

    The button fires a mutation; reading the document back the instant after
    the click races it, and the failure reads as "the copy was never made"
    rather than "the read was early" (§189, and §198's baseline-of-zero). The
    header prints "· saved" on success, so that is the thing to wait for.
    """
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.locator(".ws-actions .sub")).to_contain_text("saved")


def test_duplicate_adds_a_copy_and_leaves_the_original(page, api) -> None:
    """The plainest case, and the one that would be embarrassing to get wrong:
    a duplicate is an addition, not a rename."""
    mod = module_with(api, "Duplicate basics")
    open_builder(page, mod)
    settled(page)
    open_variables(page)
    expect(rows(page)).to_have_count(3)

    open_variable(page, "Plain")
    page.get_by_test_id("duplicate-variable").click()

    expect(rows(page)).to_have_count(4)
    assert "Plain" in labels(page)
    assert "Plain copy" in labels(page)


def test_duplicating_twice_numbers_from_two(page, api) -> None:
    """One copy of one thing is "Plain copy". The number appears when it is
    needed rather than on every copy so the second one can have it."""
    mod = module_with(api, "Duplicate twice")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "Plain")
    page.get_by_test_id("duplicate-variable").click()
    # The copy is what the panel opens, so duplicating again copies the copy -
    # which still has to land on a label nothing is using.
    open_variable(page, "Plain")
    page.get_by_test_id("duplicate-variable").click()

    got = labels(page)
    assert "Plain copy" in got
    assert "Plain copy 2" in got


def test_a_copy_says_what_it_could_not_carry(page, api) -> None:
    """**The note is the feature.** An external ID is unique in a module, so a
    copy cannot have one — and p.72's three settings are all keyed by it. Six
    checkboxes' worth of difference between two rows that otherwise look
    identical, with nothing on screen to explain it, is how somebody spends an
    afternoon on a saved state that never appears."""
    mod = module_with(api, "Duplicate notice")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "Region")
    page.get_by_test_id("duplicate-variable").click()

    notice = page.get_by_test_id("variable-notice")
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Module interface")
    expect(notice).to_contain_text("Routing")
    expect(notice).to_contain_text("State saving")


def test_a_copy_of_a_plain_variable_says_nothing(page, api) -> None:
    """A note listing an empty set of losses is noise on the common case."""
    mod = module_with(api, "Duplicate quiet")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "Plain")
    page.get_by_test_id("duplicate-variable").click()
    expect(page.get_by_test_id("variable-notice")).to_have_count(0)


def test_the_copy_is_something_the_server_accepts(page, api) -> None:
    """**The assertion the unit tests cannot make.** A copy that kept the
    external ID passes anything that does not think to look, then fails on save
    with a 422 naming a variable the author never edited. So: duplicate the
    variable that has all three settings on, save the module, and read it
    back."""
    mod = module_with(api, "Duplicate saves")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "Region")
    page.get_by_test_id("duplicate-variable").click()
    save(page)

    saved = mod.definition()
    variables = saved["variables"]
    copies = [v for v in variables.values() if v["label"] == "Region copy"]
    assert len(copies) == 1, f"expected one copy, got {[v['label'] for v in variables.values()]}"
    copy = copies[0]
    assert copy["kind"] == "string"
    assert "external_id" not in copy or copy["external_id"] is None
    assert not copy.get("save_state")
    assert copy.get("url_behavior") in (None, "never")
    # And the original is untouched, which is the other half of "addition".
    assert variables["v_region"]["external_id"] == "region"
    assert variables["v_region"]["save_state"] is True


def test_new_from_current_is_offered_on_object_sets_only(page, api) -> None:
    """p.73's "object set variables only" — and absent rather than disabled,
    because a string variable is not a set that has not loaded yet."""
    mod = module_with(api, "From current gating")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "Plain")
    expect(page.get_by_test_id("duplicate-variable")).to_be_visible()
    expect(page.get_by_test_id("new-from-current")).to_have_count(0)

    open_variable(page, "All orders")
    expect(page.get_by_test_id("new-from-current")).to_be_visible()


def test_new_from_current_references_the_source(page, api) -> None:
    """p.73: "automatically takes the current object set as its input… while
    maintaining a reference to the source variable".

    A reference, not a copy — which is the entire difference between this
    button and the one beside it. The new set is narrowed *from* the source, so
    the source appears in its "Set to narrow" dropdown.
    """
    mod = module_with(api, "From current")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "All orders")
    page.get_by_test_id("new-from-current").click()

    expect(rows(page)).to_have_count(4)
    assert "All orders narrowed" in labels(page)
    # The panel opens the new variable, and its source select already names the
    # variable it came from.
    expect(page.get_by_test_id("set-source")).to_have_value("narrowed")
    expect(page.locator(".vars-editor select").filter(has_text="All orders").first).to_be_visible()


def test_new_from_current_lands_half_configured(page, api) -> None:
    """On purpose. The value to filter on is the author's next decision, and
    guessing a property to make the thing savable immediately would invent a
    filter nobody asked for — so the module refuses to save until it is
    answered, and the message says which variable and what is missing."""
    mod = module_with(api, "From current unsaved")
    open_builder(page, mod)
    settled(page)
    open_variables(page)

    open_variable(page, "All orders")
    page.get_by_test_id("new-from-current").click()
    # Not `save()`: that waits for the save to succeed, and the point here is
    # that it does not. The refusal is the assertion.
    page.get_by_role("button", name="Save", exact=True).click()

    expect(page.locator(".ws-actions .state.error")).to_contain_text("filter_set")
    expect(page.locator(".ws-actions .sub")).not_to_contain_text("saved")
