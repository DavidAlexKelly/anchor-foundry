"""Every reading of a set reached by following a link (§544).

A `traverse_set` variable is "the objects linked to these" - Ada's issues,
where the base set holds Ada. Evaluation resolved that hop, so a table over the
variable showed Ada's two issues; the count, grouping, distribution, cross-tab
and time-series routes read the set's own filters and never the hop, so a
Metric Card beside that table said 4 and a chart drew Grace's issues too.

The routes are `test_object_set_traversal.py`'s. What needs a browser is that
the widgets people read a traversed variable through say the same thing as the
table beside them.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module, layout, object_set
from conftest import eventually, open_module

EMPLOYEES = [{"id": "E1", "name": "Ada"}, {"id": "E2", "name": "Grace"}]
ISSUES = [
    {"id": "I1", "employee_id": "E1", "title": "Ada one"},
    {"id": "I2", "employee_id": "E1", "title": "Ada two"},
    {"id": "I3", "employee_id": "E2", "title": "Grace one"},
    {"id": "I4", "employee_id": "E2", "title": "Grace two"},
]


@pytest.fixture(scope="module")
def adas_issues(api):
    mod = Module(api, "Traversed readings")
    tag = uuid.uuid4().hex[:8]
    employee_type = mod.object_type(
        columns=["id", "name"], rows=EMPLOYEES, key="id", title="name", slug=f"emp_{tag}")
    issue_type = mod.object_type(
        columns=["id", "employee_id", "title"], rows=ISSUES, key="id", title="title",
        slug=f"iss_{tag}")
    link = api.call(
        "POST", f"/workspaces/{mod.workspace_id}/link-types",
        {"api_name": f"raised_by_{tag}", "display_name": "Raised by",
         "from_type_id": issue_type, "to_type_id": employee_type,
         "cardinality": "one_to_many",
         "from_property": "employee_id", "to_property": "$primary_key"},
    )
    mod.define({
        "format": 2,
        "layout": layout({
            "card": {"resolvedName": "CanvasMetricCard", "props": {
                "objectSetVariable": "v_issues", "aggregation": "count", "property": None,
                "label": "Issues"}},
            "chart": {"resolvedName": "CanvasChart", "props": {
                "objectSetVariable": "v_issues", "kind": "bar", "dimension": "employee_id"}},
            "tbl": {"resolvedName": "CanvasObjectTable", "props": {
                "objectSetVariable": "v_issues", "columns": "id,title", "pageSize": 25}},
        }),
        "variables": {
            "v_ada": {"id": "v_ada", "kind": "object_set", "label": "Ada",
                      "object_set": object_set(employee_type, [
                          {"property": "name", "op": "eq", "value": "Ada"}])},
            "v_issues": {"id": "v_issues", "kind": "object_set", "label": "Ada's issues",
                         "derivation": {"transform": "traverse_set", "inputs": ["v_ada"],
                                        "config": {"link_type_id": link["id"],
                                                   "object_type_id": issue_type}}},
        },
        "events": {},
    })
    return mod


def test_a_count_and_a_chart_of_a_traversed_set_agree_with_its_table(page, adas_issues) -> None:
    open_module(page, adas_issues)
    cells = page.locator(".data-grid tbody tr td:first-child")
    eventually(lambda: sorted(c.strip() for c in cells.all_text_contents()),
               lambda got: got == ["I1", "I2"], what="Ada's issues in the table")
    expect(page.get_by_test_id("metric-value")).to_have_text("2")
    expect(page.locator("svg[aria-label='Bar chart'] rect title")).to_have_text(["E1: 2"])
