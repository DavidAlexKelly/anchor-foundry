"""Inline edits backed by a function (§776; `workshop` p.240-242,
`action-types` p.84; decision 0018 option B).

> "The action should either use a single "Modify object" rule or be
> function-backed." (p.240)

The per-row call and the twenty-row limit are
`apps/api/tests/test_function_inline_edits.py`'s. What needs a browser: a table
whose inline edits are submitted through a function, the function's answer -
not what was typed - on the object afterwards.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module, settled
from test_object_table_inline_edit import ROWS, cell, mirror_values


def build(api, name: str) -> Module:
    mod = Module(api, name)
    slug = f"iticket_{mod.tag}"
    type_id = mod.object_type(columns=["id", "status", "note"], rows=ROWS, key="id",
                              title="id", slug=slug)
    fn = api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": f"shout_{mod.tag}", "display_name": "Shout", "version": {
            "version": "1.0.0", "inputs": [type_id],
            "parameters": [{"api_name": "ticket", "data_type": "object",
                            "object_type_id": type_id},
                           {"api_name": "status", "data_type": "string"}],
            "output": {"kind": "edits", "object_type_id": type_id},
            "sql": (f"SELECT __primary_key, upper($status) AS status FROM {slug} "
                    "WHERE __primary_key = $ticket")}})
    action = api.call("POST", f"/workspaces/{mod.workspace_id}/action-types", {
        "object_type_id": type_id, "api_name": f"inline_{uuid.uuid4().hex[:8]}",
        "display_name": "Edit ticket", "editable_properties": ["status"]})
    api.call("PUT", f"/workspaces/{mod.workspace_id}/action-types/{action['id']}/definition", {
        "parameters": [{"api_name": "status", "display_name": "Status",
                        "data_type": "string"}],
        "rules": [{"kind": "function", "config": {
            "function_id": fn["id"], "version": "1.0.0",
            "inputs": {"ticket": {"subject": True}, "status": {"parameter": "status"}}}}],
        "criteria": []})
    table = {"objectSetVariable": "v_all", "pageSize": 25, "activeVariable": None,
             "autoSelect": False}
    mod.define({
        "format": 2,
        "layout": layout({
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                **table, "columns": "status,note", "inlineEditAction": action["id"],
                "inlineEditMapping": {"status": "status"}}},
            "mirror": {"resolvedName": "CanvasObjectTable", "props": {
                **table, "columns": "status"}},
        }),
        "variables": {"v_all": {"id": "v_all", "kind": "object_set", "label": "All",
                                "object_set": object_set(type_id)}},
        "events": {},
    })
    return mod


def test_a_function_backed_inline_edit_writes_what_the_function_says(page, api) -> None:
    mod = build(api, "Function inline edit")
    open_module(page, mod)
    settled(page)
    page.get_by_test_id("inline-edit-toggle").click()
    cell(page, "T1", "status").fill("triaged")
    cell(page, "T2", "status").fill("closed")
    expect(page.get_by_test_id("inline-edit-count")).to_have_text("2 rows edited")
    page.get_by_test_id("inline-edit-submit").click()
    page.get_by_test_id("inline-edit-confirm-submit").click()
    eventually(lambda: mirror_values(page),
               lambda v: v[:3] == ["TRIAGED", "CLOSED", "open"],
               what="the function's answers on the objects, the third untouched")
