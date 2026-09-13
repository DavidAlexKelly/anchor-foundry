"""A multiple-choice parameter's allowed values, on the screen (§335;
`action-types` p.33).

    "…select the property that includes all allowed values for the parameter
     dropdown. **If only one linked object is available in the resulting object
     set and the parameter is required, the parameter dropdown will
     automatically prefill with the corresponding property value.**" (p.33)

The distinct values and the refusals are tested in
`apps/api/tests/test_action_options.py`, and the wording in
`apps/web/src/lib/action-options.test.ts`. What needs a browser is the control
itself:

**a parameter that was a text box is a list of the values that exist** — and
p.33's prefill, which is a thing that happens to a form while somebody looks
at it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module
from ontology_page import pick_type

#: Four offices, three regions. **The repeat is the point**: a control that
#: listed one option per object would show EU twice, and with three distinct
#: objects nothing could tell "distinct" from "all of them".
OFFICES = [
    {"code": "o1", "region": "US"},
    {"code": "o2", "region": "US"},
    {"code": "o3", "region": "US"},
    {"code": "o4", "region": "EU"},
    {"code": "o5", "region": "UK"},
]


def build(api, name: str, *, offices=None, required=False, options=True):
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    office_type = mod.object_type(
        columns=["code", "region"], rows=offices if offices is not None else OFFICES,
        key="code", title="code", slug=f"opoffice_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"], rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id", title="ticket_id", slug=f"opticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"opassign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "region", "display_name": "Region",
              "data_type": "string", "required": required,
              **({"options_from": {"object_type_id": office_type,
                                   "property": "region"}} if options else {})},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "region"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "OPTIONS FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.office_type = office_type
    mod.office_api_name = f"opoffice_{tag}"
    mod.ticket_api_name = f"opticket_{tag}"
    mod.action = action
    return mod


def picker(page, name: str):
    return page.locator(f"[data-parameter='{name}'] select")


def options_of(page, name: str) -> list[str]:
    return [t.strip() for t in picker(page, name).locator("option").all_inner_texts()]


def choose_the_ticket(page, *, listed: bool = True) -> None:
    """Pick the subject, then wait for the Region control to be on screen.

    **Which control depends on what is being tested**: a parameter with no
    options document draws a text box, so waiting for a `select` there waits
    forever — which is how the panel test failed for a reason that had nothing
    to do with the panel.
    """
    page.locator("form > label select").first.select_option(index=1)
    if listed:
        expect(picker(page, "region")).to_have_count(1)
    else:
        expect(page.locator("[data-parameter='region'] input")).to_have_count(1)


def test_the_parameter_is_a_list_of_the_values_that_exist(page, api):
    """**p.33's sentence, on a screen.** Four offices, three regions — a
    control listing one option per object would show EU twice."""
    mod = build(api, "Options list")
    open_module(page, mod)
    choose_the_ticket(page)
    shown = [o for o in options_of(page, "region") if o != "Choose…"]
    assert shown == ["EU", "UK", "US"], shown


def test_a_parameter_with_no_options_is_still_a_text_box(page, api):
    """Every action written before §335. The control is the *document's* doing,
    so a form that drew a list for every string would be drawing one over
    nothing."""
    mod = build(api, "Options absent", options=False)
    open_module(page, mod)
    expect(page.locator("[data-parameter='region'] input")).to_have_count(1)
    expect(page.get_by_test_id("values-select")).to_have_count(0)


def test_one_value_on_a_required_parameter_fills_itself_in(page, api):
    """p.33: "the parameter dropdown will **automatically prefill** with the
    corresponding property value".

    Two objects sharing one region, which is p.33's condition read for its
    purpose: there is one answer, so there is nothing to choose.
    """
    mod = build(api, "Options prefill", required=True, offices=[
        {"code": "o1", "region": "SOLE"}, {"code": "o2", "region": "SOLE"},
    ])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(picker(page, "region")).to_have_value("SOLE", timeout=30000)


def test_several_values_are_left_for_somebody_to_choose(page, api):
    """The other half: prefilling when there *is* a decision would be making it
    for somebody. Without this the test above passes for a control that always
    picks the first option."""
    mod = build(api, "Options no prefill", required=True)
    open_module(page, mod)
    choose_the_ticket(page)
    expect(picker(page, "region")).to_have_count(1)
    expect(picker(page, "region")).to_have_value("")


def test_the_values_are_shown_alphabetically_rather_than_by_frequency(page, api):
    """**Two orderings, on purpose, and the fixture has to tell them apart.**

    The store returns the most common value first so that a cap keeps the ones
    somebody is most likely to want; what survives is sorted so the control does
    not reshuffle as the data moves. `US` is the most common region here and the
    last alphabetically — a fixture where the two orders agreed could not see
    which one the control used, and a sweep said so.
    """
    mod = build(api, "Options order")
    open_module(page, mod)
    choose_the_ticket(page)
    shown = [o for o in options_of(page, "region") if o != "Choose…"]
    assert shown == ["EU", "UK", "US"], shown


def test_clearing_a_prefilled_box_survives_the_offers_arriving_again(page, api):
    """**What the prefill must not argue with, and the only way to ask it.**

    p.33 fills a blank; it does not undo a person. But the effect runs on the
    offers and on re-seeding, and `refetchOnWindowFocus` is off — so clearing
    the box alone never consults the guard, and a sweep deleting it stayed
    green. What *does* bring the offers back while a form is open is p.36: a
    filter on another parameter re-keys the choices query on every keystroke in
    the box it reads.

    So this form has both, and the keystroke is the point: the region box was
    cleared on purpose and must still be clear after the response lands.
    """
    mod = Module(api, "Options cleared")
    tag = uuid.uuid4().hex[:8]
    office_type = mod.object_type(
        columns=["code", "region"],
        rows=[{"code": "o1", "region": "SOLE"}, {"code": "o2", "region": "SOLE"}],
        key="code", title="code", slug=f"clroffice_{tag}",
    )
    team_type = mod.object_type(
        columns=["code", "where"],
        rows=[{"code": "alpha", "where": "eu"}, {"code": "beta", "where": "uk"}],
        key="code", title="code", slug=f"clrteam_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"], rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id", title="ticket_id", slug=f"clrticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"clrassign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "where", "display_name": "Where", "data_type": "string"},
             # The filtered dropdown, whose watched box is what makes the
             # choices query re-run while the form is open.
             {"api_name": "team", "display_name": "Team", "data_type": "object",
              "object_type_id": team_type,
              "dropdown_filters": [{"property": "where", "values": [
                  {"kind": "parameter", "parameter": "where"}]}]},
             {"api_name": "region", "display_name": "Region",
              "data_type": "string", "required": True,
              "options_from": {"object_type_id": office_type,
                               "property": "region"}},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "region"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "CLEARED FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.action = action

    open_module(page, mod)
    page.locator("form > label select").first.select_option(index=1)
    expect(picker(page, "region")).to_have_value("SOLE", timeout=30000)
    picker(page, "region").select_option("")
    expect(picker(page, "region")).to_have_value("")

    # The keystroke that brings the offers back.
    page.locator("[data-parameter='where'] input").fill("uk")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "beta"], timeout=30000
    )
    expect(picker(page, "region")).to_have_value("")


def test_a_chosen_value_is_what_the_submission_carries(page, api):
    """The control and the rule agreeing while somebody submits. A form that
    offered three regions and sent something else would be §214 from the other
    side."""
    mod = build(api, "Options submit")
    open_module(page, mod)
    choose_the_ticket(page)
    picker(page, "region").select_option("UK")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")

    tickets = api.call(
        "GET",
        f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances",
    )["items"]
    assert tickets[0]["properties"]["note"] == "UK"


def test_a_property_no_object_has_a_value_for_says_so(page, api):
    """§214: an empty dropdown is a control that looks like it works — somebody
    opens it, finds nothing, and cannot tell whether the list failed to load.
    The truth is one an editor can act on."""
    mod = build(api, "Options empty", offices=[{"code": "o1", "region": ""}])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.get_by_test_id("values-empty")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("values-empty")).to_contain_text("property")


# ---- the editor's panel ---------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_the_panel_says_where_the_options_come_from(page, api):
    """The sentence rather than the shape."""
    mod = build(api, "Options panel says")
    open_editor(page, mod)
    panel = page.locator("[data-parameter-options='region']")
    expect(panel.get_by_test_id("options-summary")).to_contain_text("region of every")


def test_opening_and_saving_the_dialog_keeps_the_options_it_did_not_touch(page, api):
    """**The pattern `STATUS.md` names, and the seventh unit to need it.**

    The dialog saves the parameters whole, so a document it does not read is
    one it overwrites with nothing the moment somebody opens it to fix a label.
    """
    mod = build(api, "Options kept")
    open_editor(page, mod)
    page.get_by_label("Parameter 1 label").fill("Region now")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    region = next(p for p in saved["parameters"] if p["api_name"] == "region")
    assert region["display_name"] == "Region now"
    assert region["options_from"] == {
        "object_type_id": mod.office_type, "property": "region",
    }


def test_a_list_written_in_the_panel_narrows_the_form(page, api):
    """**The panel and the form, in one test.** A panel that saved something
    the form does not honour, or a form drawing a list no panel can write,
    would each pass every other test here."""
    mod = build(api, "Options panel writes", options=False)
    open_module(page, mod)
    choose_the_ticket(page, listed=False)

    open_editor(page, mod)
    panel = page.locator("[data-parameter-options='region']")
    panel.get_by_role("checkbox").check()
    # The problem note names what is still missing, in the order the panel asks.
    expect(panel.get_by_test_id("options-problem")).to_contain_text("object type")
    # **`pick_type`, not `fill`.** A `TypePicker` is a search control whose
    # options arrive with a response (§256), so typing an id into it chooses
    # nothing — the first version of this test did that and the save wrote no
    # document at all.
    pick_type(page, "parameter-1-options-type",
              {"id": mod.office_type, "api_name": mod.office_api_name})
    page.get_by_label("Options for region property").select_option("region")
    expect(panel.get_by_test_id("options-problem")).to_have_count(0)
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    # What the panel wrote, before asking what the form does with it: the two
    # halves fail differently and "the dropdown is missing" does not say which.
    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    region = next(p for p in saved["parameters"] if p["api_name"] == "region")
    assert region["options_from"] == {
        "object_type_id": mod.office_type, "property": "region",
    }, region

    open_module(page, mod)
    choose_the_ticket(page)
    shown = [o for o in options_of(page, "region") if o != "Choose…"]
    assert shown == ["EU", "UK", "US"], shown


def test_unchecking_the_box_clears_the_document(page, api):
    """The checkbox is the only way back to "whatever is typed in", and a
    parameter left holding a half-written document would be refused on the next
    save of something else entirely."""
    mod = build(api, "Options unchecked")
    open_editor(page, mod)
    panel = page.locator("[data-parameter-options='region']")
    panel.get_by_role("checkbox").uncheck()
    expect(panel.get_by_test_id("options-summary")).to_contain_text(
        "Whatever is typed in"
    )
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    region = next(p for p in saved["parameters"] if p["api_name"] == "region")
    assert region["options_from"] is None


def test_changing_the_type_drops_a_property_of_the_old_one(page, api):
    """A property chosen against one type is not a property of the next, and
    the server refuses that pair by name — so the panel clears it rather than
    letting Save produce a 422 about a field somebody did not touch."""
    mod = build(api, "Options retype")
    open_editor(page, mod)
    panel = page.locator("[data-parameter-options='region']")
    expect(panel.get_by_test_id("options-summary")).to_contain_text("region of every")
    # The ticket type has no `region`, so keeping the old property here would
    # be exactly the pair the server refuses.
    pick_type(page, "parameter-1-options-type",
              {"id": mod.type_id, "api_name": mod.ticket_api_name})
    expect(panel.get_by_test_id("options-problem")).to_contain_text("property")


def test_the_panel_offers_no_list_for_a_parameter_that_cannot_have_one(page, api):
    """p.33's multiple choice is for parameters that are *not* objects; that
    shape has had its own dropdown since §330. Offering the setting would be a
    control whose only outcome is a refusal."""
    mod = build(api, "Options not offered", options=False)
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition",
        {"parameters": [
             {"api_name": "region", "display_name": "Region",
              "data_type": "object", "object_type_id": mod.office_type},
             {"api_name": "note", "display_name": "Note", "data_type": "string"},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "note"}}],
         "criteria": []},
    )
    open_editor(page, mod)
    # **The section itself is on screen** — `note` is a string and can have a
    # list — so this is the *row* being absent rather than the whole block.
    # With only an object parameter the outer gate hides everything and the
    # assertion passes for the wrong reason; a sweep found that fixture.
    expect(page.get_by_test_id("parameter-options")).to_be_visible()
    expect(page.locator("[data-parameter-options='note']")).to_have_count(1)
    expect(page.locator("[data-parameter-options='region']")).to_have_count(0)


# ---- p.33's filters over the options set (§336) ---------------------------------
def build_filtered(api, name: str):
    """An action whose Region list is narrowed by the Tier chosen above it.

    Offices are US/gold, US/gold, US/silver, EU/gold, UK/silver — so gold
    leaves EU and US, silver leaves UK and US, and the whole set leaves all
    three. No two of those lists are the same, which is what makes "narrowed by
    *this* value" visible rather than merely "narrowed".
    """
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    office_type = mod.object_type(
        columns=["code", "region", "tier"],
        rows=[{"code": "o1", "region": "US", "tier": "gold"},
              {"code": "o2", "region": "US", "tier": "gold"},
              {"code": "o3", "region": "US", "tier": "silver"},
              {"code": "o4", "region": "EU", "tier": "gold"},
              {"code": "o5", "region": "UK", "tier": "silver"}],
        key="code", title="code", slug=f"fltoffice_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"], rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id", title="ticket_id", slug=f"fltticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"fltassign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "tier", "display_name": "Tier", "data_type": "string"},
             {"api_name": "region", "display_name": "Region",
              "data_type": "string",
              "options_from": {"object_type_id": office_type,
                               "property": "region"},
              "dropdown_filters": [{"property": "tier", "values": [
                  {"kind": "parameter", "parameter": "tier"}]}]},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "region"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "FILTERED OPTIONS FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.office_type = office_type
    mod.office_api_name = f"fltoffice_{tag}"
    mod.action = action
    return mod


def test_typing_a_value_narrows_the_list_of_values(page, api):
    """**p.33's first sentence, on a screen**, and the loop no layer below can
    see: a value typed in one box changes what the next box offers, and the two
    lists differ from each other as well as from the whole set."""
    mod = build_filtered(api, "Filtered options")
    open_module(page, mod)
    page.locator("form > label select").first.select_option(index=1)
    # Nothing typed: the list says which box comes first rather than offering
    # every region and refusing the submission later.
    expect(page.get_by_test_id("values-waiting")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("values-waiting")).to_contain_text("Tier")

    page.locator("[data-parameter='tier'] input").fill("silver")
    expect(picker(page, "region").locator("option")).to_contain_text(
        ["Choose", "UK", "US"], timeout=30000
    )
    assert not any("EU" in o for o in options_of(page, "region"))

    # And again, to a different answer — one value could be a list that
    # narrowed once and then stopped listening.
    page.locator("[data-parameter='tier'] input").fill("gold")
    expect(picker(page, "region").locator("option")).to_contain_text(
        ["Choose", "EU", "US"], timeout=30000
    )
    assert not any("UK" in o for o in options_of(page, "region"))


def test_a_filter_written_in_the_panel_narrows_the_values(page, api):
    """**The panel and the form, in one test.** The filter panel used to live
    inside the object-parameter block, so this shape could not have one at all
    (§336) — a panel that saved something the form does not honour, or a form
    narrowed by something no panel can write, would each pass every other test
    here.
    """
    mod = build(api, "Filtered options panel")
    open_module(page, mod)
    choose_the_ticket(page)
    shown = [o for o in options_of(page, "region") if o != "Choose…"]
    assert shown == ["EU", "UK", "US"], shown

    open_editor(page, mod)
    panel = page.locator("[data-parameter-filters='region']")
    expect(panel).to_have_count(1)
    page.get_by_label("Add a filter to region").click()
    page.get_by_label("Filter 1 on region property").select_option("region")
    page.get_by_label("Filter 1 on region value").fill("UK")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    open_module(page, mod)
    choose_the_ticket(page)
    shown = [o for o in options_of(page, "region") if o != "Choose…"]
    assert shown == ["UK"], shown


def test_the_filter_panel_is_not_offered_before_there_is_a_set_to_narrow(page, api):
    """A filter is written against the properties of the type the options name,
    so until one is chosen there is nothing to write it against — and the
    server refuses a filter on a parameter with no options at all."""
    mod = build(api, "Filtered options unset", options=False)
    open_editor(page, mod)
    expect(page.locator("[data-parameter-filters='region']")).to_have_count(0)
    # The options row itself is there, so this is the filter panel waiting
    # rather than the section being absent.
    expect(page.locator("[data-parameter-options='region']")).to_have_count(1)
