"""A saved time series analysis in its own resource view (§668; `workshop`
p.397).

> "Saved analyses can be opened in a standalone resource view or loaded into
> the Workshop widget using its RID." (p.397)

An analysis saved as a reader's Save saves it - North's root plot and its
running total on a canvas of its own, with an event set on the total - is
listed with the project's analyses, and opened there shows its plots, their
statistics, its canvases and its events, read now, and the RID a widget
loads it by (§663).
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module, object_set
from conftest import WEB_BASE
from test_series_column import module  # noqa: F401


def saved(api, module, name: str, state: dict) -> tuple[Module, str]:
    mod = Module(api, name, beside=module)
    made = api.call("POST", f"{mod.base}/series-analyses",
                    {"name": f"{name} {mod.tag}", "visibility": "private", "state": state})
    return mod, made["id"]


def north(api, mod: Module, module) -> dict:
    found = api.call("POST", f"/workspaces/{mod.workspace_id}/object-sets/evaluate",
                     {"definition": object_set(module.sensor_type), "limit": 5})
    obj = next(i for i in found["instances"] if i["properties"]["name"] == "North sensor")
    return {"id": f"root:{obj['id']}", "label": "North sensor", "canvas": 1, "style": "solid",
            "root": {"typeId": module.sensor_type, "objectId": obj["id"], "property": "readings",
                     "objectLabel": "North sensor"},
            "parent": None, "transforms": []}


def stat(page, label: str, which: str):
    return page.locator(f"[data-testid='series-plots'] tbody tr[data-label='{label}'] td[data-stat='{which}']")


def test_a_saved_analysis_listed_and_opened_in_its_view(page, api, module) -> None:
    mod = Module(api, "Analysis view", beside=module)
    root = north(api, mod, module)
    total = {"id": "plot-2", "label": "Running North", "canvas": 2, "style": "solid", "root": None,
             "parent": root["id"], "transforms": [{"kind": "cumulative", "aggregate": "sum"}]}
    events = {"id": "events-1", "label": "Past fifty", "plot": "plot-2", "op": "gt", "value": 50,
              "highlight": True}
    made = api.call("POST", f"{mod.base}/series-analyses", {
        "name": f"Viewed {mod.tag}", "visibility": "private",
        "state": {"plots": [root, total], "canvases": 2, "eventSets": [events], "axes": {}}})

    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/series-analyses")
    row = page.locator(f"[data-testid='series-analyses'] tr[data-label='Viewed {mod.tag}']")
    expect(row).to_contain_text("You")
    expect(row).to_contain_text("private")
    row.get_by_role("link", name=f"Viewed {mod.tag}").click()

    expect(page.get_by_role("heading", name=f"Viewed {mod.tag}")).to_be_visible()
    expect(page.get_by_test_id("series-analysis-rid")).to_have_text(made["id"])
    expect(page.get_by_test_id("series-analysis-about")).to_contain_text("Private · by you")
    expect(page.locator("[data-testid='series-plots'] tbody tr")).to_have_count(2)
    expect(stat(page, "North sensor", "max")).to_have_text("40")
    expect(stat(page, "Running North", "min")).to_have_text("10")
    expect(stat(page, "Running North", "max")).to_have_text("100")
    # Each on its canvas, as saved.
    expect(page.locator("[data-testid='series-canvas-1'] path[data-plot]")).to_have_count(1)
    expect(page.locator("[data-testid='series-canvas-2'] path[data-plot]")).to_have_count(1)
    # The running total passes 50 at its third reading and stays past it.
    expect(page.locator("[data-testid='series-event-sets'] tr[data-label='Past fifty'] td[data-stat='events']")
           ).to_have_text("1")
    # Shaded where the plot it searched is drawn, and nowhere else.
    expect(page.locator("[data-testid='series-canvas-2'] rect[data-event-set='events-1']")).to_have_count(1)
    expect(page.locator("[data-testid='series-canvas-1'] rect[data-event-set='events-1']")).to_have_count(0)


def test_an_analysis_with_no_plots_says_so(page, api, module) -> None:
    mod, rid = saved(api, module, "Analysis empty", {"plots": [], "canvases": 0, "eventSets": [], "axes": {}})
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/series-analyses/{rid}")
    expect(page.get_by_test_id("series-analysis-view-empty")).to_be_visible()
    expect(page.get_by_test_id("series-analysis-rid")).to_have_text(rid)


def test_another_reader_s_private_analysis_is_not_found(viewer_page, api, module) -> None:
    mod, rid = saved(api, module, "Analysis hidden", {"plots": [], "canvases": 0, "eventSets": [], "axes": {}})
    viewer_page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/series-analyses/{rid}")
    expect(viewer_page.locator(".form-error")).to_be_visible()
    expect(viewer_page.get_by_test_id("series-analysis-rid")).to_have_count(0)
