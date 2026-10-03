"""The Inline Action's **Action table** layout (§702; Foundry `workshop` p.511-512).

> "Action tables … are recommended for large-scale datasets … The table layout
> offers several benefits, including keyboard navigation" (p.511)
> "End-user features: Configure additional user interactions, including layout
> switching, row management … Also note that batch call limits apply to the
> table layout, as well as the requirement that edits do not conflict." (p.512)

Which actions a table can draw is `apps/api/tests/test_action_table.py`, and
what a row lacks is `action-table.test.ts`. What needs a browser is the table
itself: a row per object, cells seeded from it, rows added and removed, every
row checked before any is sent, and the layout switch.

**Each test that writes gets its own module**, for `test_action_form.py`'s
reason.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, no_console_errors, open_module


def build(api, name: str, *, layout_switch: bool = False, props: dict | None = None,
          events: dict | None = None, variables: dict | None = None,
          prefill: str | None = None, tickets: int = 3,
          prefill_keys: list[str] | None = None, with_table: bool = False,
          function_backed: bool = False, creates: bool = False) -> Module:
    """`prefill`: "same" fills the table from a set of this action's own type
    (p.512), "other" from a set of a second type, which p.512 says must not."""
    mod = Module(api, name)
    type_id = mod.object_type(
        columns=["ticket_id", "status"],
        rows=[{"ticket_id": k, "status": "open"}
              for k in (("T1", "T2", "T3") if tickets == 3
                        else [f"T{n:02d}" for n in range(1, tickets + 1)])],
        key="ticket_id",
        title="ticket_id",
    )
    if prefill:
        set_type = type_id if prefill == "same" else mod.object_type(
            columns=["code"], rows=[{"code": "X"}], key="code", title="code",
            slug=f"other_{uuid.uuid4().hex[:6]}")
        variables = {**(variables or {}), "v_rows": {
            "id": "v_rows", "kind": "object_set", "label": "Rows",
            "object_set": object_set(set_type, [
                {"property": "$primary_key", "op": "in", "value": prefill_keys}]
                if prefill_keys else None)}}
        props = {**(props or {}), "prefillVariable": "v_rows"}
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": type_id,
        "api_name": f"set_{uuid.uuid4().hex[:8]}",
        "display_name": "Set status",
        "editable_properties": ["status"],
    })
    rules = [{"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}]
    if function_backed:
        # p.240's other shape, whose batch is p.131's twenty rows (§776).
        slug = api.call("GET", f"/workspaces/{mod.workspace_id}/object-types/{type_id}")["api_name"]
        fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
            "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
                "version": "1.0.0", "inputs": [type_id],
                "parameters": [{"api_name": "ticket", "data_type": "object",
                                "object_type_id": type_id},
                               {"api_name": "status", "data_type": "string"}],
                "output": {"kind": "edits", "object_type_id": type_id},
                "sql": (f"SELECT __primary_key, $status AS status FROM {slug} "
                        "WHERE __primary_key = $ticket")}})
        rules = [{"kind": "function", "config": {
            "function_id": fn["id"], "version": "1.0.0", "auto_upgrade": False,
            "inputs": {"ticket": {"subject": True}, "status": {"parameter": "status"}}}}]
    if creates:
        # Opens a follow-up as well: a create, which the inline edit's batch
        # cannot take, so the rows go as a batch call of rows (§800).
        rules = rules + [{"kind": "create_object", "config": {
            "primary_key": "follow",
            "properties": {"ticket_id": "follow", "status": "status"}}}]
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string",
             "required": True},
            *([{"api_name": "follow", "display_name": "Follow-up", "data_type": "string",
                "required": True}] if creates else []),
        ],
        "rules": rules,
        "criteria": [
            {"message": "Tickets cannot be marked deleted.",
             "config": {"left": {"kind": "parameter", "parameter": "status"},
                        "operator": "is_not",
                        "right": {"kind": "value", "value": "deleted"}}},
        ],
    })
    if with_table:
        # The module's other reads, which a submission has to refresh.
        variables = {**(variables or {}), "v_all": {
            "id": "v_all", "kind": "object_set", "label": "All",
            "object_set": object_set(type_id)}}
    mod.define({
        "format": 2,
        "layout": layout({
            **({"tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_all", "columns": "status", "pageSize": 25,
                "activeVariable": None, "autoSelect": False}}} if with_table else {}),
            "txt": {"resolvedName": "CanvasText",
                    "props": {"tag": "p", "text": "Fired: {{v_done}}"}},
            "frm": {"resolvedName": "CanvasActionForm",
                    "props": {"actionTypeId": action["id"], "layout": "table",
                              "layoutSwitch": layout_switch, **(props or {})}},
        }),
        "variables": {"v_done": {"id": "v_done", "kind": "string", "label": "Done"},
                      **(variables or {})},
        "events": events or {},
    })
    mod.type_id = type_id
    return mod


def statuses(api, mod: Module) -> dict[str, str]:
    items = api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances"
    )["items"]
    return {i["primary_key"]: i["properties"]["status"] for i in items}


def rows(page):
    return page.get_by_test_id("action-table-row")


def fill_row(page, index: int, ticket: str, status: str) -> None:
    row = rows(page).nth(index)
    row.locator("select").first.select_option(label=ticket)
    cell = row.locator("[data-cell$=':1'] input")
    # Seeded from the object first (p.27), then typed over.
    expect(cell).to_have_value("open")
    cell.fill(status)


def test_each_row_is_one_object_and_starts_at_what_it_says(page, api) -> None:
    mod = build(api, "Action table seed")
    open_module(page, mod)
    expect(page.get_by_test_id("action-table")).to_be_visible()
    expect(rows(page)).to_have_count(1)
    rows(page).first.locator("select").first.select_option(label="T2")
    expect(rows(page).first.locator("[data-cell$=':1'] input")).to_have_value("open")
    page.get_by_test_id("action-table-add").click()
    expect(rows(page)).to_have_count(2)
    rows(page).nth(1).get_by_role("button", name="Remove row 2").click()
    expect(rows(page)).to_have_count(1)
    assert not no_console_errors(page)


def test_every_row_is_submitted(page, api) -> None:
    """As one batch call (§796; p.512's "batch call limits apply to the table
    layout"): an action that changes only each row's own object takes the
    Object Table's batch, so every row lands or none does."""
    mod = build(api, "Action table submit")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "waiting")
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url.rsplit("/", 1)[-1])
            if r.method == "POST" and "/actions/" in r.url else None)
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2)
    eventually(lambda: statuses(api, mod),
               lambda got: got == {"T1": "closed", "T2": "waiting", "T3": "open"},
               what="both rows written, the third object untouched")
    expect(page.get_by_test_id("action-table-submit")).to_be_disabled()
    assert [u for u in sent if u.startswith("execute")] == ["execute-batch"], sent


def test_a_batch_refreshes_what_the_module_shows(page, api) -> None:
    mod = build(api, "Action table refresh", with_table=True)
    open_module(page, mod)
    table = page.locator(".data-grid").filter(has_text="T1").first
    expect(table).to_contain_text("open", timeout=15000)
    fill_row(page, 0, "T1", "archived")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(1)
    expect(table).to_contain_text("archived", timeout=15000)


def test_a_batch_the_server_refuses_writes_no_row(page, api) -> None:
    """p.138's whole-or-nothing (§796): a row whose object is gone by the
    time the batch lands refuses the batch, and the other row is not
    written either."""
    mod = build(api, "Action table atomic")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "waiting")
    # T2 is deleted after its row was filled, which no pre-check can see.
    remover = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"drop_{uuid.uuid4().hex[:8]}",
        "display_name": "Drop", "editable_properties": ["status"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{remover['id']}/definition",
             {"parameters": [], "rules": [{"kind": "delete_object", "config": {}}],
              "criteria": []})
    t2 = next(i for i in api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances")["items"]
        if i["primary_key"] == "T2")
    api.call("POST", f"{mod.base}/actions/{remover['id']}/execute",
             {"instance_id": t2["id"], "values": {}})
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_have_count(2, timeout=15000)
    expect(page.get_by_test_id("action-table-done")).to_have_count(0)
    assert statuses(api, mod)["T1"] == "open"


def test_more_rows_than_one_batch_takes_are_refused(page, api) -> None:
    """p.512's "batch call limits apply to the table layout" (§796): p.131's
    limit, twenty rows for a function-backed action."""
    mod = build(api, "Action table limit", prefill="same", tickets=21, function_backed=True)
    open_module(page, mod)
    expect(rows(page)).to_have_count(21, timeout=30000)
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem").first).to_contain_text(
        "One submission takes at most 20 rows (action-types p.131).", timeout=60000)
    expect(page.get_by_test_id("action-table-done")).to_have_count(0)


def test_one_object_in_two_rows_sends_nothing(page, api) -> None:
    """p.512's "the requirement that edits do not conflict"."""
    mod = build(api, "Action table conflict")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T1", "waiting")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text("also in row 1")
    assert statuses(api, mod)["T1"] == "open"


def test_a_refused_row_is_found_before_anything_is_written(page, api) -> None:
    """Every row's criteria are asked first, so a refusal in the second row
    leaves the first unwritten - and the message is the criterion's own (p.56)."""
    mod = build(api, "Action table refusal")
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "deleted")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text(
        "Tickets cannot be marked deleted.")
    expect(page.get_by_test_id("action-table-done")).to_have_count(0)
    assert statuses(api, mod) == {"T1": "open", "T2": "open", "T3": "open"}

    # Fixed, and sent: both rows, since neither went the first time.
    rows(page).nth(1).locator("[data-cell$=':1'] input").fill("waiting")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2)


def test_a_required_cell_left_empty_is_named(page, api) -> None:
    mod = build(api, "Action table required")
    open_module(page, mod)
    fill_row(page, 0, "T1", "")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_contain_text("Status is required.")


def test_enter_moves_down_a_column(page, api) -> None:
    """p.511's keyboard navigation."""
    mod = build(api, "Action table keys")
    open_module(page, mod)
    page.get_by_test_id("action-table-add").click()
    first = rows(page).nth(0).locator("[data-cell$=':1'] input")
    first.focus()
    first.press("Enter")
    expect(rows(page).nth(1).locator("[data-cell$=':1'] input")).to_be_focused()
    rows(page).nth(1).locator("[data-cell$=':1'] input").press("Shift+Enter")
    expect(first).to_be_focused()


def test_a_reader_can_switch_layouts(page, api) -> None:
    """p.512's "layout switching", where the builder allowed it."""
    mod = build(api, "Action table switch", layout_switch=True)
    open_module(page, mod)
    switch = page.get_by_test_id("action-layout-switch")
    expect(page.get_by_test_id("action-table")).to_be_visible()
    switch.get_by_role("button", name="Form").click()
    expect(page.get_by_test_id("action-table")).to_have_count(0)
    expect(page.locator("form select").first).to_be_visible()
    switch.get_by_role("button", name="Table").click()
    expect(page.get_by_test_id("action-table")).to_be_visible()


def test_a_whole_batch_fires_the_submit_event(page, api) -> None:
    """p.513's "On successful action submit", once every row went through."""
    mod = build(api, "Action table event", events={
        "e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                   "effects": [{"type": "set_variable",
                                "config": {"variable": "v_done", "value": "yes"}}]}})
    open_module(page, mod)
    expect(page.get_by_text("Fired:")).to_be_visible()
    fill_row(page, 0, "T3", "closed")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(1)
    expect(page.get_by_text("Fired: yes")).to_be_visible()


def test_rows_pick_their_own_objects_when_the_form_is_bound(page, api) -> None:
    """The form edits the bound object; a table's rows are each about one, so
    the list of objects is still there to pick from."""
    mod = build(api, "Action table bound", props={"subjectVariable": "v_pick"},
                variables={"v_pick": {"id": "v_pick", "kind": "single_object",
                                      "label": "Picked"}})
    open_module(page, mod)
    expect(rows(page).first.locator("select").first.locator("option")).to_have_count(4)


def test_an_action_the_table_cannot_hold_is_a_form(page, api) -> None:
    """p.511: "some Actions … are not yet usable in the Table because some
    feature of the Action is only supported in the Form layout" - said, and the
    form drawn, since the action is still one somebody can submit."""
    mod = Module(api, "Action table refused")
    type_id = mod.object_type(
        columns=["site_id", "where"],
        rows=[{"site_id": "S1", "where": "51.5,-0.12"}],
        key="site_id", title="site_id", types={"where": "geopoint"},
    )
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": type_id, "api_name": f"move_{uuid.uuid4().hex[:8]}",
        "display_name": "Move site", "editable_properties": ["where"],
    })
    mod.define({
        "format": 2,
        "layout": layout({"frm": {"resolvedName": "CanvasActionForm",
                                  "props": {"actionTypeId": action["id"], "layout": "table"}}}),
        "variables": {}, "events": {},
    })
    open_module(page, mod)
    expect(page.get_by_test_id("action-table-refused")).to_contain_text("geopoint")
    expect(page.get_by_test_id("action-table")).to_have_count(0)
    expect(page.locator("form")).to_be_visible()


# ---- §703: pre-fill with variable, and CSV upload ------------------------------
def row_keys(page) -> list[str]:
    selects = rows(page).locator("td:first-child select")
    return [s.evaluate("e => e.options[e.selectedIndex].text")
            for s in selects.all()]


def test_a_variable_fills_the_table_with_its_objects(page, api) -> None:
    """p.512: "Pre-populate table rows by mapping an object set variable to an
    object reference action parameter"."""
    mod = build(api, "Action table prefill", prefill="same")
    open_module(page, mod)
    expect(rows(page)).to_have_count(3)
    assert sorted(row_keys(page)) == ["T1", "T2", "T3"]
    # Each row seeded from its own object.
    expect(rows(page).first.locator("[data-cell$=':1'] input")).to_have_value("open")


def test_a_set_of_another_type_fills_nothing(page, api) -> None:
    """p.512: "The variable's object type must match the action parameter's
    defined object type"."""
    mod = build(api, "Action table prefill other", prefill="other")
    open_module(page, mod)
    expect(page.get_by_test_id("action-table-note")).to_contain_text("different object type")
    expect(rows(page)).to_have_count(1)


def test_a_csv_fills_rows_by_key_and_says_what_it_skipped(page, api) -> None:
    """p.511's "CSV file upload capabilities"."""
    mod = build(api, "Action table csv")
    open_module(page, mod)
    page.get_by_test_id("action-table-csv").set_input_files({
        "name": "rows.csv", "mimeType": "text/csv",
        "buffer": b"Object,Status,colour\nT1,closed,red\nT9,open,blue\nT2,,green\n",
    })
    expect(rows(page)).to_have_count(3)
    note = page.get_by_test_id("action-table-note")
    expect(note).to_contain_text("Read 3 rows.")
    expect(note).to_contain_text("ignored: colour")
    expect(rows(page).nth(0).locator("[data-cell$=':1'] input")).to_have_value("closed")
    # An empty cell keeps what the object says.
    expect(rows(page).nth(2).locator("[data-cell$=':1'] input")).to_have_value("open")
    expect(rows(page).nth(1)).to_contain_text('No object has the key "T9".')

    rows(page).nth(1).get_by_role("button", name="Remove row 2").click()
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2)
    eventually(lambda: statuses(api, mod),
               lambda got: got == {"T1": "closed", "T2": "open", "T3": "open"},
               what="the file's rows written")


def test_a_csv_without_an_object_column_is_refused(page, api) -> None:
    mod = build(api, "Action table csv refused")
    open_module(page, mod)
    page.get_by_test_id("action-table-csv").set_input_files({
        "name": "rows.csv", "mimeType": "text/csv", "buffer": b"Status\nclosed\n"})
    expect(page.get_by_test_id("action-table-note")).to_contain_text(
        "needs a column naming each row's object")
    expect(rows(page)).to_have_count(1)


def test_objects_past_the_first_page_can_be_rows(page, api) -> None:
    """The Object dropdown starts with 25 objects. A pre-fill or a file may
    name others, and a row has to be able to show the object it is about."""
    mod = build(api, "Action table far", tickets=30, prefill="same",
                prefill_keys=["T29", "T30"])
    open_module(page, mod)
    expect(rows(page)).to_have_count(2)
    assert sorted(row_keys(page)) == ["T29", "T30"]
    page.get_by_test_id("action-table-csv").set_input_files({
        "name": "rows.csv", "mimeType": "text/csv", "buffer": b"key,status\nT28,closed\n"})
    expect(rows(page)).to_have_count(3)
    assert row_keys(page)[2] == "T28"


def fill_follow_up(page, index: int, key: str) -> None:
    rows(page).nth(index).locator("[data-cell$=':2'] input").fill(key)


def drop(api, mod: Module, key: str) -> None:
    """Delete one ticket behind the table's back, which no pre-check sees."""
    remover = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": mod.type_id, "api_name": f"drop_{uuid.uuid4().hex[:8]}",
        "display_name": "Drop", "editable_properties": ["status"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{remover['id']}/definition",
             {"parameters": [], "rules": [{"kind": "delete_object", "config": {}}],
              "criteria": []})
    gone = next(i for i in api.call(
        "GET", f"/workspaces/{mod.workspace_id}/object-types/{mod.type_id}/instances")["items"]
        if i["primary_key"] == key)
    api.call("POST", f"{mod.base}/actions/{remover['id']}/execute",
             {"instance_id": gone["id"], "values": {}})


def test_rows_of_an_action_that_creates_go_as_one_batch_call(page, api) -> None:
    """p.84's "all edits are applied atomically at the end of the action call"
    for an action the inline edit's batch cannot take (§800): both rows'
    edits and both follow-ups, and p.513's submit event once."""
    mod = build(api, "Action table creates", creates=True, events={
        "e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                   "effects": [{"type": "set_variable",
                                "config": {"variable": "v_done", "value": "yes"}}]}})
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    fill_follow_up(page, 0, "F1")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "waiting")
    fill_follow_up(page, 1, "F2")
    sent: list[str] = []
    page.on("request", lambda r: sent.append(r.url.rsplit("/", 1)[-1])
            if "/actions/" in r.url and r.method == "POST" else None)
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-done")).to_have_count(2, timeout=15000)
    expect(page.get_by_text("Fired: yes")).to_be_visible()
    assert statuses(api, mod) == {"T1": "closed", "T2": "waiting", "T3": "open",
                                  "F1": "closed", "F2": "waiting"}
    assert [u for u in sent if u.startswith("execute")] == ["execute-rows"]


def test_a_creating_batch_the_server_refuses_writes_no_row(page, api) -> None:
    """Every row or none (§800): the second row's object is gone by the time
    the batch lands, so the first row's edit and follow-up are not written."""
    mod = build(api, "Action table creates atomic", creates=True, events={
        "e_done": {"id": "e_done", "trigger": {"node": "frm", "on": "submit"},
                   "effects": [{"type": "set_variable",
                                "config": {"variable": "v_done", "value": "yes"}}]}})
    open_module(page, mod)
    fill_row(page, 0, "T1", "closed")
    fill_follow_up(page, 0, "F1")
    page.get_by_test_id("action-table-add").click()
    fill_row(page, 1, "T2", "waiting")
    fill_follow_up(page, 1, "F2")
    drop(api, mod, "T2")
    page.get_by_test_id("action-table-submit").click()
    expect(page.get_by_test_id("action-table-problem")).to_have_count(2, timeout=15000)
    # Refused for the object that went, and nothing else.
    expect(page.get_by_test_id("action-table-problem").first).to_contain_text(
        "object instance not found")
    expect(page.get_by_test_id("action-table-done")).to_have_count(0)
    assert statuses(api, mod) == {"T1": "open", "T3": "open"}
    # p.513's "On successful action submit" is for a submit that succeeded.
    # A wait, because the absence of an event is only seen once it would have
    # run: the event's effects land a render after the rows are marked.
    page.wait_for_timeout(1500)
    expect(page.get_by_text("Fired: yes")).to_have_count(0)
