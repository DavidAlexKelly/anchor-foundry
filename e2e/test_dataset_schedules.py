"""The schedules that will update a dataset, on its Details tab (§508;
`dataset-preview` p.3).

    "Schedules: Information about any configured build schedules that will
     run to update the dataset." (p.3)

The rules are in `apps/api/tests/test_dataset_schedules.py` and
`apps/web/src/lib/dataset-schedules.test.ts`. What needs a browser is that the
tab says it, and that the transform it names opens.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def resource_of(mod: Module, name: str, kind: str) -> str:
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    return next(r for r in resources if r["name"] == name and r["kind"] == kind)["id"]


def test_a_scheduled_transform_output_says_when_it_runs(page, api) -> None:
    mod = Module(api, "Schedules cron")
    source = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"raw_{mod.tag}",
                                b"id,total\n1,10\n")
    model = mod.api.call("POST", f"{mod.base}/models", {
        "name": f"Nightly {mod.tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}]})
    mod.api.call("PATCH", f"{mod.base}/models/{model['id']}",
                 {"trigger_mode": "cron", "cron_schedule": "0 3 * * *"})
    out = mod.api.call("POST", f"{mod.base}/models/{model['id']}/run")["output_dataset"]

    page.goto(f"{WEB_BASE}/r/{resource_of(mod, out['name'], 'dataset')}?tab=details")
    schedule = page.get_by_test_id("ds-schedule")
    expect(schedule).to_have_count(1, timeout=30000)
    expect(schedule).to_contain_text(f"Transform Nightly {mod.tag} on cron 0 3 * * * · next run",
                                     timeout=30000)
    expect(page.get_by_test_id("ds-no-schedules")).to_have_count(0)
    schedule.get_by_role("link").click()
    expect(page).to_have_url(f"{WEB_BASE}/r/{resource_of(mod, model['name'], 'model')}",
                             timeout=30000)


def test_an_unscheduled_dataset_says_how_it_changes(page, api) -> None:
    mod = Module(api, "Schedules none")
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"ledger_{mod.tag}",
                              b"id,total\n1,10\n")
    page.goto(f"{WEB_BASE}/r/{resource_of(mod, made['name'], 'dataset')}?tab=details")
    expect(page.get_by_test_id("ds-no-schedules")).to_have_text(
        "Nothing is scheduled to update this dataset. It changes when somebody runs, syncs "
        "or uploads it.", timeout=30000)
    expect(page.get_by_test_id("ds-schedule")).to_have_count(0)
