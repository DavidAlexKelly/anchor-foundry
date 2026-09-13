"""Narrowing what an object parameter offers, on the screen (§331;
`action-types` p.33-36, p.40-41).

    "After configuring the filters, the action form will render a dropdown with
     only objects that match the filter. **The value selected is also validated
     before the action is executed.**" (p.34)

The compilation and the refusal are tested in
`apps/api/tests/test_action_filters.py` and the wording in
`apps/web/src/lib/action-filters.test.ts`. What needs a browser is the loop
p.36 describes and neither can reach:

**a value typed in one box changes what the next box offers.**

That is the whole of p.36's "inferred from another parameter", and it is the
only place where the form's narrowing and the server's refusal have to agree
while somebody is actually typing.
"""
from __future__ import annotations

import json
import uuid

from playwright.sync_api import expect

from api import Module, layout
from conftest import WEB_BASE, open_module, settled
from ontology_page import pick_type


def static(prop: str, *values) -> dict:
    return {"property": prop,
            "values": [{"kind": "value", "value": v} for v in values]}


def from_parameter(prop: str, name: str) -> dict:
    return {"property": prop,
            "values": [{"kind": "parameter", "parameter": name}]}


def build(api, name: str, *, dropdown_filters: list[dict]) -> Module:
    """An action whose Team parameter offers teams, narrowed by `region`."""
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    team_type = mod.object_type(
        columns=["code", "name", "region"],
        rows=[{"code": "alpha", "name": "Alpha", "region": "eu"},
              {"code": "beta", "name": "Beta", "region": "uk"},
              {"code": "gamma", "name": "Gamma", "region": "us"}],
        key="code", title="name", slug=f"team_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"],
        rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id", title="ticket_id", slug=f"ticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"assign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "where", "display_name": "Region",
              "data_type": "string"},
             {"api_name": "team", "display_name": "Team", "data_type": "object",
              "object_type_id": team_type,
              "dropdown_filters": dropdown_filters},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "where"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "FILTERED FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.team_type = team_type
    mod.team_api_name = f"team_{tag}"
    mod.action = action
    return mod


def field(page, name: str):
    return page.locator(f"[data-parameter='{name}'] input")


def picker(page, name: str):
    return page.locator(f"[data-parameter='{name}'] select")


def choose_the_ticket(page) -> None:
    page.locator("form > label select").first.select_option(index=1)
    expect(field(page, "where")).to_have_count(1)


def options(page, name: str) -> list[str]:
    return [t.strip() for t in picker(page, name).locator("option").all_inner_texts()]


def test_a_static_filter_narrows_what_the_dropdown_offers(page, api):
    """p.34: "the action form will render a dropdown with only objects that
    match the filter".

    Both halves: the matching object is offered and the others are not — the
    first alone would pass for a dropdown that ignored the filter.
    """
    mod = build(api, "Filter static", dropdown_filters=[static("region", "eu")])
    open_module(page, mod)
    choose_the_ticket(page)
    shown = options(page, "team")
    assert any("Alpha" in o for o in shown), shown
    assert not any("Beta" in o for o in shown), shown
    assert not any("Gamma" in o for o in shown), shown


def test_several_values_are_an_or(page, api):
    """p.36 in as many words. A single-value fixture could not see this: two
    values admit two objects, not zero."""
    mod = build(api, "Filter or", dropdown_filters=[static("region", "eu", "uk")])
    open_module(page, mod)
    choose_the_ticket(page)
    shown = options(page, "team")
    assert any("Alpha" in o for o in shown), shown
    assert any("Beta" in o for o in shown), shown
    assert not any("Gamma" in o for o in shown), shown


def test_typing_in_one_box_changes_what_the_next_one_offers(page, api):
    """**p.36's loop, which is the whole reason this file exists.**

    "The value can be… inferred from another parameter." Nothing below a
    browser can watch a dropdown change while somebody types, and this is the
    only place the form's narrowing and the server's refusal have to agree in
    the middle of a form being filled in.
    """
    mod = build(api, "Filter from parameter",
                dropdown_filters=[from_parameter("region", "where")])
    open_module(page, mod)
    choose_the_ticket(page)

    # Nothing typed yet: the list is empty and says which box comes first,
    # rather than offering every team and refusing the submission later.
    expect(page.get_by_test_id("choices-waiting")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("choices-waiting")).to_contain_text("Region")

    field(page, "where").fill("uk")
    expect(page.get_by_test_id("choices-waiting")).to_have_count(0, timeout=30000)
    shown = options(page, "team")
    assert any("Beta" in o for o in shown), shown
    assert not any("Alpha" in o for o in shown), shown

    # And again, to a different answer — one value could be a dropdown that
    # narrowed once and then stopped listening.
    field(page, "where").fill("us")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Gamma"], timeout=30000
    )
    assert not any("Beta" in o for o in options(page, "team"))


def test_an_empty_dropdown_that_is_waiting_does_not_claim_there_are_none(page, api):
    """§214, and a sentence that is simply false: "there are no Teams" when the
    truth is "you have not said which region"."""
    mod = build(api, "Filter waiting",
                dropdown_filters=[from_parameter("region", "where")])
    open_module(page, mod)
    choose_the_ticket(page)
    expect(page.get_by_test_id("choices-waiting")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("choices-empty")).to_have_count(0)


def test_a_form_with_no_filters_asks_once(page, api):
    """**A claim about the network** (§327's shape). A form whose object
    parameters carry no parameter-reading filters has nothing to re-ask about,
    so typing must not send a request per keystroke.

    The positive control is a filtered module opened on the same page, because
    "nothing was asked" passes just as well for a listener on the wrong thing.
    """
    plain = build(api, "Filter none", dropdown_filters=[static("region", "eu")])
    watched = build(api, "Filter watched",
                    dropdown_filters=[from_parameter("region", "where")])

    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url)
            if "parameter-choices" in r.url else None)

    open_module(page, plain)
    choose_the_ticket(page)
    expect(picker(page, "team")).to_have_count(1)
    before = len(asked)
    field(page, "where").fill("uk")
    field(page, "where").fill("us")
    expect(picker(page, "team")).to_have_count(1)
    assert len(asked) == before, asked[before:]

    open_module(page, watched)
    choose_the_ticket(page)
    field(page, "where").fill("uk")
    expect(page.get_by_test_id("choices-waiting")).to_have_count(0, timeout=30000)
    assert len(asked) > before, "the listener fires for a form that does watch"


def test_a_filtered_submission_carries_the_object_that_was_offered(page, api):
    """The dropdown and the refusal are the same set, so the object a narrowed
    control offers is one the server accepts. Asserted on the request for the
    reason §330's docstring gives about the run log."""
    mod = build(api, "Filter submit", dropdown_filters=[static("region", "eu")])
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.post_data or "")
            if "/execute" in r.url else None)

    open_module(page, mod)
    choose_the_ticket(page)
    field(page, "where").fill("anything")
    picker(page, "team").select_option(label="Alpha")
    page.get_by_role("button", name="Submit").click()
    expect(page.locator("form")).to_contain_text("Saved.")

    teams = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.team_type}/instances"
    )["items"]
    alpha = next(t for t in teams if t["properties"]["name"] == "Alpha")
    assert len(sent) == 1, sent
    assert json.loads(sent[0])["values"]["team"] == alpha["id"]


# ---- p.36's third value kind (§334) ---------------------------------------------
def build_with_office(api, name: str):
    """An action whose Team dropdown matches the region of the Office chosen
    above it — p.36's third kind, on a canvas.

    Two offices in different regions, because with one the filter's value never
    changes and "reads the object" is indistinguishable from "happens to match".
    """
    mod = Module(api, name)
    tag = uuid.uuid4().hex[:8]
    team_type = mod.object_type(
        columns=["code", "name", "region"],
        rows=[{"code": "alpha", "name": "Alpha", "region": "eu"},
              {"code": "beta", "name": "Beta", "region": "uk"},
              {"code": "gamma", "name": "Gamma", "region": "us"}],
        key="code", title="name", slug=f"oteam_{tag}",
    )
    office_type = mod.object_type(
        columns=["code", "name", "region"],
        rows=[{"code": "hq", "name": "HQ", "region": "eu"},
              {"code": "branch", "name": "Branch", "region": "uk"}],
        key="code", title="name", slug=f"office_{tag}",
    )
    ticket_type = mod.object_type(
        columns=["ticket_id", "note"], rows=[{"ticket_id": "1", "note": ""}],
        key="ticket_id", title="ticket_id", slug=f"oticket_{tag}",
    )
    action = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/action-types",
        {"object_type_id": ticket_type, "api_name": f"oassign_{tag}",
         "display_name": "Assign ticket", "editable_properties": ["note"]},
    )
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition",
        {"parameters": [
             {"api_name": "office", "display_name": "Office",
              "data_type": "object", "object_type_id": office_type},
             {"api_name": "team", "display_name": "Team", "data_type": "object",
              "object_type_id": team_type,
              "dropdown_filters": [{"property": "region", "values": [
                  {"kind": "object_property", "parameter": "office",
                   "property": "region"}]}]},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "team"}}],
         "criteria": []},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "OBJECT PROPERTY FORM"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"]}},
        }),
        "variables": {},
        "events": {},
    })
    mod.type_id = ticket_type
    mod.team_type = team_type
    mod.office_type = office_type
    mod.action = action
    return mod


def choose_the_office_ticket(page) -> None:
    """`choose_the_ticket`'s job for the office fixture, which has no `where`
    box to wait on — its first parameter is the Office picker."""
    page.locator("form > label select").first.select_option(index=1)
    expect(picker(page, "office")).to_have_count(1)


def test_choosing_an_object_narrows_by_one_of_its_properties(page, api):
    """**p.36's third kind, end to end, which is the only place it can be
    seen.** Choose HQ and the Teams offered are the EU ones — a value nobody
    typed and no parameter holds."""
    mod = build_with_office(api, "Object property filter")
    open_module(page, mod)
    choose_the_office_ticket(page)
    picker(page, "office").select_option(label="HQ")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Alpha"], timeout=30000
    )
    shown = options(page, "team")
    assert not any("Beta" in o for o in shown), shown
    assert not any("Gamma" in o for o in shown), shown


def test_choosing_a_different_object_narrows_differently(page, api):
    """A filter that read the object once and then stopped listening passes the
    test above and fails this one."""
    mod = build_with_office(api, "Object property changes")
    open_module(page, mod)
    choose_the_office_ticket(page)
    picker(page, "office").select_option(label="HQ")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Alpha"], timeout=30000
    )
    picker(page, "office").select_option(label="Branch")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Beta"], timeout=30000
    )
    assert not any("Alpha" in o for o in options(page, "team"))


def test_before_the_object_is_chosen_the_form_says_which_box(page, api):
    mod = build_with_office(api, "Object property waiting")
    open_module(page, mod)
    choose_the_office_ticket(page)
    expect(page.get_by_test_id("choices-waiting")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("choices-waiting")).to_contain_text("Office")
    expect(page.get_by_test_id("choices-waiting")).to_contain_text("first")


# ---- the editor, and p.40 ------------------------------------------------------
def open_editor(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    row = page.locator("tr", has_text=mod.action["api_name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Parameters").click()
    expect(page.get_by_role("dialog")).to_be_visible()


def test_a_filter_written_in_the_panel_narrows_the_form(page, api):
    """**p.36's loop end to end through the screen**: write the filter in the
    dialog, then find the form offering only what it leaves."""
    mod = build(api, "Filter panel", dropdown_filters=[])
    open_editor(page, mod)

    page.get_by_label("Add a filter to team").click()
    page.get_by_label("Filter 1 on team property").select_option("region")
    page.get_by_label("Filter 1 on team value").fill("uk")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    team = next(p for p in saved["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == [static("region", "uk")]

    open_module(page, mod)
    choose_the_ticket(page)
    shown = options(page, "team")
    assert any("Beta" in o for o in shown), shown
    assert not any("Alpha" in o for o in shown), shown


def test_opening_and_saving_the_dialog_keeps_the_filters_it_did_not_touch(page, api):
    """**The regression a builder meets on their second visit**, and the
    *identical* one §329 had with its override blocks.

    The filters are part of the parameter and the dialog saves the parameters
    whole, so a dialog that did not load them would delete every filter the
    moment somebody opened it to fix a typo elsewhere. §329 found this by
    sweep, wrote the test, and the test did not travel when the pattern did —
    see the note in STATUS.md.
    """
    mod = build(api, "Filter kept", dropdown_filters=[static("region", "eu")])
    open_editor(page, mod)
    # An edit with nothing to do with the filters.
    page.get_by_label("Parameter 1 label").fill("Region now")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    where = next(p for p in saved["parameters"] if p["api_name"] == "where")
    assert where["display_name"] == "Region now"
    team = next(p for p in saved["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == [static("region", "eu")]


def test_the_panel_warns_about_a_typed_in_value_and_not_about_a_parameter(page, api):
    """p.40's concern, and p.41's own carve-out.

    Both directions, because a warning that is always on screen is one nobody
    reads: p.41 says a parameter-read filter exposes "no information about the
    underlying data", so switching the source must take the warning away.
    """
    mod = build(api, "Filter warning", dropdown_filters=[])
    open_editor(page, mod)
    page.get_by_label("Add a filter to team").click()

    warning = page.get_by_test_id("filter-static-warning")
    expect(warning).to_be_visible()
    expect(warning).to_contain_text("edit this action can read it")

    page.get_by_label("Filter 1 on team source").select_option("parameter")
    expect(warning).to_have_count(0)


def test_the_panel_will_not_offer_the_parameter_its_own_filter_is_on(page, api):
    """The dropdown would depend on the value it is offering. The server
    refuses it; this is why nobody meets that refusal by the obvious route."""
    mod = build(api, "Filter self", dropdown_filters=[])
    open_editor(page, mod)
    page.get_by_label("Add a filter to team").click()
    page.get_by_label("Filter 1 on team source").select_option("parameter")

    choices = page.get_by_label("Filter 1 on team parameter")
    expect(choices.locator("option")).to_contain_text(["Choose", "Region"])
    assert not any(
        "Team" in o for o in choices.locator("option").all_inner_texts()
    )


# ---- the reader the redaction is for (§332) ------------------------------------
def test_the_loop_works_for_somebody_who_may_not_edit_the_action(viewer_page, api):
    """**§331's redaction broke p.36's loop for exactly the people it protects.**

    A viewer is sent no `dropdown_filters` (p.40-41), and the form worked out
    which boxes to re-ask on by reading them — so it watched nothing, and
    choosing a region left the Team dropdown sitting on "choose Region first"
    forever. §214's control that looks like it works, and green in every suite,
    because every other browser test in this file runs as the owner.

    The same steps as `test_typing_in_one_box_changes_what_the_next_one_offers`,
    driven by the reader instead. Not a variation on it: the two differ only in
    who is holding the mouse, and that turned out to be the whole defect.
    """
    mod = build(api, "Filter as viewer",
                dropdown_filters=[from_parameter("region", "where")])
    # **Not `open_module`**, which clicks Preview: a viewer has no builder to
    # preview out of, so the module's own address is already the running app.
    viewer_page.goto(f"{WEB_BASE}{mod.url}")
    settled(viewer_page)
    choose_the_ticket(viewer_page)

    expect(viewer_page.get_by_test_id("choices-waiting")).to_be_visible(timeout=30000)
    field(viewer_page, "where").fill("uk")
    expect(viewer_page.get_by_test_id("choices-waiting")).to_have_count(0, timeout=30000)
    shown = options(viewer_page, "team")
    assert any("Beta" in o for o in shown), shown
    assert not any("Alpha" in o for o in shown), shown

    # And again, because a dropdown that narrowed once and then stopped
    # listening is the shape this test exists to refuse.
    field(viewer_page, "where").fill("us")
    expect(picker(viewer_page, "team").locator("option")).to_contain_text(
        ["Choose", "Gamma"], timeout=30000
    )
    assert not any("Beta" in o for o in options(viewer_page, "team"))


def test_the_panel_writes_p36s_third_kind_and_the_form_honours_it(page, api):
    """**The panel and the form, in one test** (§334).

    A panel that saved something the form does not honour, or a form narrowed
    by something no panel can write, would each pass every other test here.
    """
    mod = build_with_office(api, "Object property panel")
    # Start it as a plain unfiltered dropdown, so the narrowing below is the
    # panel's doing rather than the fixture's.
    api.call(
        "PUT",
        f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}/definition",
        {"parameters": [
             {"api_name": "office", "display_name": "Office",
              "data_type": "object", "object_type_id": mod.office_type},
             {"api_name": "team", "display_name": "Team", "data_type": "object",
              "object_type_id": mod.team_type},
         ],
         "rules": [{"kind": "modify_object",
                    "config": {"property": "note", "parameter": "team"}}],
         "criteria": []},
    )
    open_module(page, mod)
    choose_the_office_ticket(page)
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Alpha", "Beta", "Gamma"], timeout=30000
    )

    open_editor(page, mod)
    page.get_by_label("Add a filter to team").click()
    page.get_by_label("Filter 1 on team property").select_option("region")
    page.get_by_label("Filter 1 on team source").select_option("object_property")
    page.get_by_label("Filter 1 on team object", exact=True).select_option("office")
    page.get_by_label("Filter 1 on team object property").select_option("region")
    expect(page.get_by_test_id("filter-summary")).to_contain_text("Office's region")
    page.get_by_role("button", name="Save", exact=True).click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    saved = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/action-types/{mod.action['id']}"
    )
    team = next(p for p in saved["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == [{"property": "region", "values": [
        {"kind": "object_property", "parameter": "office", "property": "region"},
    ]}]

    open_module(page, mod)
    choose_the_office_ticket(page)
    picker(page, "office").select_option(label="Branch")
    expect(picker(page, "team").locator("option")).to_contain_text(
        ["Choose", "Beta"], timeout=30000
    )
    assert not any("Alpha" in o for o in options(page, "team"))


def test_the_panel_will_not_offer_the_third_kind_with_nothing_to_read_from(page, api):
    """A kind that can only produce a refusal is §214's control that looks like
    it works: this action has one object parameter and it is the one being
    filtered, so there is nothing to read a property off."""
    mod = build(api, "No object to read", dropdown_filters=[static("region", "eu")])
    open_editor(page, mod)
    source = page.get_by_label("Filter 1 on team source")
    shown = [t.strip() for t in source.locator("option").all_inner_texts()]
    assert "a property of a chosen object" not in shown, shown
    assert "another parameter" in shown, shown
