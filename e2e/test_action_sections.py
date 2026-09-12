"""Sections on an action form, on the screen (§328; `action-types` p.122-124).

    "The action form can be customized with sections. These sections provide a
     logical grouping of parameters to organize an action form. Sections also
     support columns, descriptions, and conditional overrides." (p.122)

    "Sections are also collapsible, can be hidden entirely… A section can be
     hidden at first and only shown based on a prior parameter." (p.123)

The document is tested in `apps/api/tests/test_action_sections.py` and the
arrangement in `apps/web/src/lib/action-sections.test.ts`. What needs a browser
is the claim neither can reach and every one of these tests is about:

**a section changes what a form looks like and nothing else.**

A form with a section hidden must submit exactly what the same form submits
without it — same parameters, same values, same rules. That is a fact about a
real form being filled in and posted, and the only place to observe it is here.

**Each test that writes gets its own module and its own ticket**, for the reason
`test_action_form.py` gives: a form test is a write test by definition.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module


def when(parameter: str, value: str) -> dict:
    return {"left": {"kind": "parameter", "parameter": parameter},
            "operator": "is", "right": {"kind": "value", "value": value}}


def build(api, name: str, *, sections: list[dict] | None = None) -> Module:
    """One action over one ticket, with p.122's sections around its form."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status", "note", "reason"],
        rows=[{"ticket_id": "1", "status": "open", "note": "keep me",
               "reason": "because"}],
        key="ticket_id",
        title="ticket_id",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": type_id, "api_name": f"close_{uuid.uuid4().hex[:8]}",
         "display_name": "Close ticket",
         "editable_properties": ["status", "note", "reason"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {
            "parameters": [
                {"api_name": "status", "display_name": "New status",
                 "data_type": "string", "required": True},
                {"api_name": "reason", "display_name": "Reason",
                 "data_type": "string"},
                {"api_name": "note", "display_name": "Note", "data_type": "string"},
            ],
            "rules": [
                {"kind": "modify_object",
                 "config": {"property": "status", "parameter": "status"}},
                {"kind": "modify_object",
                 "config": {"property": "reason", "parameter": "reason"}},
                {"kind": "modify_object",
                 "config": {"property": "note", "parameter": "note"}},
            ],
            # **The criterion that makes "still submitted" observable at all.**
            # A parameter merely written back unchanged produces the same stored
            # row whether the form sent it or dropped it, so a check built on
            # that could not fail. This one refuses when `note` never arrives —
            # and `note` is the parameter the hidden section holds.
            "criteria": [
                {"message": "A ticket with no note cannot be updated.",
                 "config": {"left": {"kind": "parameter", "parameter": "note"},
                            "operator": "is_not", "right": {"kind": "none"}}},
            ],
        },
    )
    if sections is not None:
        api.call(
            "PUT",
            f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/sections",
            {"sections": sections},
        )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "SECTIONED FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = type_id
    mod.action = action
    return mod


ARRANGED = [
    {"title": "Details", "description": "What this closes.", "columns": 2,
     "parameters": ["status"]},
    {"title": "Why", "visible_when": when("status", "closed"),
     "parameters": ["reason"]},
    {"title": "Bookkeeping", "hidden": True, "parameters": ["note"]},
]


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def in_section(page, title: str, name: str):
    return page.locator(f"[data-section='{title}'] [data-parameter='{name}'] input")


def choose_the_ticket(page) -> None:
    page.locator("form select").first.select_option(index=1)
    expect(field(page, "status")).not_to_have_value("")


def stored(api, mod: Module) -> dict:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return items[0]["properties"]


@pytest.fixture(scope="module")
def readonly(api):
    """Shared by the tests that never submit."""
    return build(api, "Sectioned form", sections=ARRANGED)


# ---- p.122's grouping ---------------------------------------------------------
def test_a_section_holds_its_parameter_and_the_body_does_not(page, readonly):
    """p.122's "logical grouping".

    Both halves: the field is *inside* the section, and it is no longer loose in
    the form. Only asserting the first would pass for a form that drew every
    parameter twice.
    """
    open_module(page, readonly)
    choose_the_ticket(page)
    expect(in_section(page, "Details", "status")).to_be_visible()
    expect(field(page, "status")).to_have_count(1)


def test_a_two_column_section_puts_two_fields_side_by_side(page, api):
    """p.123: "A section can be divided into one or two columns."

    **Measured rather than announced.** The first version of this read
    `data-columns="2"` off the section — an attribute the component writes
    about itself — and a mutant that kept the attribute while dropping the
    grid drew a single column and survived. That is STATUS.md's standing
    lesson about structural checks: what must be *visible* has to be asserted
    as a fact about the rendered page.

    Both layouts in one test, because "side by side" alone would pass for a
    form that ignored the setting and always used two.
    """
    wide = build(api, "Two columns", sections=[
        {"title": "Details", "columns": 2, "parameters": ["status", "reason"]},
    ])
    narrow = build(api, "One column", sections=[
        {"title": "Details", "columns": 1, "parameters": ["status", "reason"]},
    ])

    def boxes(module):
        open_module(page, module)
        choose_the_ticket(page)
        first = page.locator("[data-section='Details'] [data-parameter='status']")
        second = page.locator("[data-section='Details'] [data-parameter='reason']")
        expect(second).to_be_visible(timeout=30000)
        return first.bounding_box(), second.bounding_box()

    a, b = boxes(wide)
    assert abs(a["y"] - b["y"]) < a["height"] / 2, (
        f"two columns should put them on one row: {a} {b}"
    )
    assert b["x"] > a["x"] + a["width"] / 2, (
        f"the second field should sit to the right of the first: {a} {b}"
    )

    a, b = boxes(narrow)
    assert b["y"] > a["y"] + a["height"] / 2, (
        f"one column should stack them: {a} {b}"
    )


def test_the_description_is_shown_in_the_section_rather_than_in_a_tooltip(
    page, readonly
):
    """p.123 says so in as many words, and contrasts it with a parameter's
    description: "The description is not stylized and, unlike parameter
    descriptions, will always be shown in the section itself, not in a
    tooltip." A `title` attribute would be the tooltip p.123 rules out."""
    open_module(page, readonly)
    choose_the_ticket(page)
    shown = page.locator("[data-section='Details']").get_by_test_id(
        "action-form-section-description")
    expect(shown).to_be_visible()
    expect(shown).to_have_text("What this closes.")


# ---- p.123's hiding -----------------------------------------------------------
def test_a_hidden_sections_parameter_is_not_drawn_and_is_still_submitted(
    page, api
):
    """**The claim this whole unit rests on.**

    p.123's "hidden entirely" is about a form. The parameter is still declared,
    still seeded and still sent — so the criterion over `note` passes and the
    rule writes it. A form that dropped a hidden section's values would mean the
    same action did different things depending on which boxes were on screen,
    and the refusal below is what that would look like.
    """
    mod = build(api, "Hidden section", sections=ARRANGED)
    open_module(page, mod)
    choose_the_ticket(page)

    # Not drawn, anywhere: not in its section and not fallen back into the body.
    expect(field(page, "note")).to_have_count(0)
    expect(page.locator("[data-section='Bookkeeping']")).to_have_count(0)

    field(page, "status").fill("closed")
    page.get_by_role("button", name="Submit").click()
    # No refusal — which is the positive form of "the hidden value arrived",
    # because the criterion refuses a submission `note` is missing from.
    expect(page.get_by_test_id("action-form-refused")).to_have_count(0)
    expect(page.locator("form")).to_contain_text("Saved.")
    assert stored(api, mod)["note"] == "keep me"
    assert stored(api, mod)["status"] == "closed"


def test_a_conditional_section_arrives_when_the_prior_parameter_says_so(
    page, readonly
):
    """p.123: "A section can be hidden at first and only shown based on a prior
    parameter."

    **Both directions in one observation**, which is §318's rule: the section is
    absent at first, appears when the value matches, and goes away again. A test
    that only asserted the appearance would pass for a form that drew every
    section always.
    """
    open_module(page, readonly)
    choose_the_ticket(page)
    reason = page.locator("[data-section='Why']")
    expect(reason).to_have_count(0)

    field(page, "status").fill("closed")
    expect(reason).to_be_visible(timeout=30000)
    expect(in_section(page, "Why", "reason")).to_have_value("because")

    field(page, "status").fill("open")
    expect(reason).to_have_count(0, timeout=30000)


def test_a_section_shown_to_one_person_is_drawn_for_that_person(page, api):
    """p.50's **other** condition template, which reads nothing out of the form.

    "Simple submission criteria can require a specific user ID or group ID"
    (p.140), and p.123's conditional override is the same grammar — so a
    section can be shown to the person it names. **This is the check the unit
    was missing**: the form decided whether to ask the server from which
    parameters the conditions *mention*, and a condition about the current user
    mentions none, so the question was never asked and the section could never
    be drawn for anybody. A mutation sweep found it; nothing here did.

    Both halves in one test, because "drawn" alone would pass for a form that
    drew every conditional section and "not drawn" alone for one that drew
    none.
    """
    me = api.call("GET", "/auth/me")["user_id"]
    mod = build(api, "Current-user section", sections=[
        {"title": "Mine", "parameters": ["reason"],
         "visible_when": {"left": {"kind": "current_user", "attribute": "id"},
                          "operator": "is",
                          "right": {"kind": "value", "value": me}}},
        {"title": "Theirs", "parameters": ["note"],
         "visible_when": {"left": {"kind": "current_user", "attribute": "id"},
                          "operator": "is",
                          "right": {"kind": "value",
                                    "value": "00000000-0000-0000-0000-000000000000"}}},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Mine']")).to_be_visible(timeout=30000)
    expect(page.locator("[data-section='Theirs']")).to_have_count(0)
    # And the browser is the same person the API call was, which is what makes
    # the first assertion mean anything.
    expect(in_section(page, "Mine", "reason")).to_have_value("because")


def test_a_conditional_sections_parameter_is_submitted_even_while_it_is_hidden(
    page, api
):
    """The same promise as the hidden section, for the other kind of hiding —
    and the one a builder is likelier to reach, because a conditional section
    spends most of its life off screen."""
    mod = build(api, "Conditional section", sections=[
        {"title": "Why", "visible_when": when("status", "closed"),
         "parameters": ["reason", "note"]},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Why']")).to_have_count(0)

    page.get_by_role("button", name="Submit").click()
    expect(page.get_by_test_id("action-form-refused")).to_have_count(0)
    expect(page.locator("form")).to_contain_text("Saved.")
    assert stored(api, mod)["reason"] == "because"


def test_a_form_with_nothing_conditional_never_asks_the_server(page, api):
    """**A claim about the network, which no assertion about the screen can
    reach.**

    p.123's conditional override is the server's to evaluate, so the form asks
    — but a form whose sections carry no condition has nothing to ask about,
    and asking anyway would put a round trip on every action form in the
    product for an answer it does not read. A mutant that asked always drew an
    identical page and survived every check here, which is §327's finding one
    unit later: "was not sent" is about the request, so the request is the
    observable.

    **The conditional module afterwards is not decoration.** Without it,
    "nothing was asked" would pass just as well for a listener attached to the
    wrong thing, or a url that never matches — which is how two earlier
    versions of §327's equivalent could not fail.
    """
    plain = build(api, "Plain sections",
                  sections=[{"title": "Details", "parameters": ["status"]}])
    conditional = build(api, "Conditional sections", sections=[
        {"title": "Why", "visible_when": when("status", "closed"),
         "parameters": ["reason"]},
    ])

    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url)
            if "visible-sections" in r.url else None)

    open_module(page, plain)
    choose_the_ticket(page)
    expect(in_section(page, "Details", "status")).to_be_visible()
    # And typing does not provoke one either: there is no condition to re-read.
    field(page, "status").fill("closed")
    expect(field(page, "status")).to_have_value("closed")
    assert asked == [], asked

    open_module(page, conditional)
    choose_the_ticket(page)
    field(page, "status").fill("closed")
    expect(page.locator("[data-section='Why']")).to_be_visible(timeout=30000)
    assert asked, "the listener never fired, so the assertion above said nothing"


def test_a_form_with_no_sections_is_the_form_it_always_was(page, api):
    """The shape every action in this platform already has, and the one p.122's
    customisation is optional on top of. **The check that a unit added for
    sections did not quietly change the forms nobody sectioned.**"""
    mod = build(api, "Unsectioned form", sections=[])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.get_by_test_id("action-form-section")).to_have_count(0)
    for name in ("status", "reason", "note"):
        expect(field(page, name)).to_be_visible()

    field(page, "status").fill("closed")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")
    assert stored(api, mod)["status"] == "closed"


# ---- p.123's collapsing -------------------------------------------------------
def test_a_collapsible_section_folds_and_unfolds(page, api):
    """p.123's "Sections are also collapsible".

    Folding is a fact about a reader in a moment, which is why the database
    stores only whether a section *may* fold and whether it *starts* folded —
    one person collapsing a section does not collapse it for everybody.
    """
    mod = build(api, "Folding section", sections=[
        {"title": "Details", "collapsible": True, "collapsed": True,
         "parameters": ["status"]},
    ])
    open_module(page, mod)
    page.locator("form select").first.select_option(index=1)

    toggle = page.get_by_test_id("action-form-section-toggle")
    expect(toggle).to_be_visible(timeout=30000)
    # It starts folded, which is the half a click alone would not show.
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(field(page, "status")).to_have_count(0)

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(field(page, "status")).to_be_visible()

    toggle.click()
    expect(field(page, "status")).to_have_count(0)


def test_a_section_that_cannot_fold_has_no_control_that_says_it_can(page, readonly):
    """§214: a control that looks like it works is worse than one that is
    absent. A section nobody made collapsible draws a heading, not a button."""
    open_module(page, readonly)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Details']")).to_be_visible()
    expect(page.get_by_test_id("action-form-section-toggle")).to_have_count(0)


# ---- the case p.123 does not discuss ------------------------------------------
def test_a_required_parameter_nobody_can_reach_says_so_and_blocks(page, api):
    """A required parameter inside a hidden section.

    The server still requires it, so the submission would be refused. A form
    that said "New status is required" beside no New status box would be §214's
    shape all over again — so it stays disabled, which is true, and says
    something the person who *can* fix it could act on.
    """
    mod = build(api, "Unreachable required", sections=[
        {"title": "Bookkeeping", "hidden": True, "parameters": ["status"]},
    ])
    open_module(page, mod)
    page.locator("form select").first.select_option(index=1)

    note = page.get_by_test_id("action-form-unreachable")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("New status")
    expect(note).to_contain_text("arranged the form")
    expect(page.get_by_role("button", name="Submit")).to_be_disabled()


# ---- p.124's Form tab ---------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    """The dialog for *this* action.

    By api_name, never by display name: the Actions table is workspace-wide and
    the dev database has carried "Close ticket" since August.
    """
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def saved_sections(api, mod: Module) -> list[dict]:
    return api.call(
        "GET",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/sections",
    )


def test_the_form_tab_arranges_a_form_and_the_form_draws_it(page, api):
    """**p.124's loop, end to end**: add a section in the Form tab, put a
    parameter in it, save, and find the form arranged that way.

    The two ends are two documents saved by two requests — the definition, then
    the form — and a section naming a parameter can only be written once the
    parameter exists. Checked through the screen at both ends because that
    ordering is the thing a unit test cannot see.
    """
    mod = build(api, "Form tab", sections=[])
    open_editor(page, mod)

    page.get_by_test_id("add-section").click()
    page.get_by_label("Section 1 title").fill("Details")
    page.get_by_label("Section 1 description").fill("What this closes.")
    page.get_by_label("Section 1 columns").select_option("2")
    page.get_by_label("Add a parameter to section 1").select_option("status")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    written = saved_sections(api, mod)
    assert [s["title"] for s in written] == ["Details"]
    assert written[0]["parameters"] == ["status"]
    assert written[0]["columns"] == 2
    assert written[0]["description"] == "What this closes."

    open_module(page, mod)
    choose_the_ticket(page)
    expect(in_section(page, "Details", "status")).to_be_visible()


def test_the_form_tab_hides_a_section_on_a_prior_parameter(page, api):
    """p.123's conditional override, written through the panel rather than
    posted as JSON — the shape it stores is decision 0007's, which is the whole
    reason the form does not evaluate it itself."""
    mod = build(api, "Form tab condition", sections=[])
    open_editor(page, mod)

    page.get_by_test_id("add-section").click()
    page.get_by_label("Section 1 title").fill("Why")
    page.get_by_label("Section 1 condition parameter").select_option("status")
    page.get_by_label("Section 1 condition value").fill("closed")
    page.get_by_label("Add a parameter to section 1").select_option("reason")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    assert saved_sections(api, mod)[0]["visible_when"] == when("status", "closed")

    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.locator("[data-section='Why']")).to_have_count(0)
    field(page, "status").fill("closed")
    expect(page.locator("[data-section='Why']")).to_be_visible(timeout=30000)


def test_a_rename_carries_through_the_form_rather_than_being_refused(page, api):
    """The one edit in this dialog with consequences in the other document.

    Without it every rename of a sectioned parameter is refused, and for the
    wrong reason: the section still points at the old name, so the server
    answers "'status' is not a parameter of this action" — true, unhelpful, and
    about a row the person did not touch. The same argument `patchParameter`
    already makes about rules and criteria.
    """
    mod = build(api, "Form tab rename",
                sections=[{"title": "Details", "parameters": ["status"]}])
    open_editor(page, mod)

    page.get_by_label("Parameter 1 name").fill("state")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    # No refusal reached the dialog, and the section followed the rename.
    assert saved_sections(api, mod)[0]["parameters"] == ["state"]


def test_a_parameter_removed_from_the_action_leaves_its_section(page, api):
    """The other edit with consequences. A section holding a parameter the
    action no longer declares is refused by the server, about a section the
    person was not looking at."""
    mod = build(api, "Form tab removal",
                sections=[{"title": "Details", "parameters": ["status", "reason"]}])
    open_editor(page, mod)

    # The rule that writes it goes first, because the server refuses a
    # definition whose rule reads a parameter that is not declared — a refusal
    # about the *rules*, which would hide the one this test is about.
    page.get_by_test_id("rule-rows").locator(".card").nth(1).get_by_role(
        "button", name="Remove").click()
    # `reason` is the second parameter, and removing it must take it out of the
    # section too.
    page.locator("[data-parameter-row='reason'] button", has_text="Remove").click()
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)
    assert saved_sections(api, mod)[0]["parameters"] == ["status"]


def test_starting_folded_is_unreachable_until_a_section_can_fold(page, api):
    """A section folded with no way to open it would be p.123's "hidden
    entirely" wearing the wrong name — so the second box means nothing without
    the first, and the panel says so by being unusable rather than by
    explaining."""
    mod = build(api, "Form tab folding", sections=[])
    open_editor(page, mod)
    page.get_by_test_id("add-section").click()

    folded = page.get_by_label("Section 1 starts folded")
    expect(folded).to_be_disabled()
    page.get_by_label("Section 1 collapsible").check()
    expect(folded).to_be_enabled()
