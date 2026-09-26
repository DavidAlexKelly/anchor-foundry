"""How a dataset's current version was made (§506; `dataset-preview` p.3).

    "About: Information including … any tools and input datasets used to
     create the data" (p.3)

The rules are in `apps/api/tests/test_dataset_origin.py` and
`apps/web/src/lib/dataset-origin.test.ts`. What needs a browser is that the
Details tab says it, and that both the tool and the inputs open.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def resource_of(mod: Module, name: str, kind: str = "dataset") -> str:
    """By kind as well as name: a transform's output dataset takes the
    transform's name, so the name alone names two resources."""
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    return next(r for r in resources if r["name"] == name and r["kind"] == kind)["id"]


def test_a_transform_output_names_the_transform_and_its_input(page, api) -> None:
    mod = Module(api, "Origin transform")
    source = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"raw_{mod.tag}",
                                b"id,total\n1,10\n2,20\n")
    model = mod.api.call("POST", f"{mod.base}/models", {
        "name": f"Clean {mod.tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}]})
    out = mod.api.call("POST", f"{mod.base}/models/{model['id']}/run")["output_dataset"]

    page.goto(f"{WEB_BASE}/r/{resource_of(mod, out['name'])}?tab=details")
    made_by = page.get_by_test_id("ds-made-by")
    expect(made_by).to_have_text(f"Transform Clean {mod.tag}", timeout=30000)
    made_from = page.get_by_test_id("ds-made-from")
    expect(made_from).to_have_text(source["name"])

    made_from.get_by_role("link", name=source["name"]).click()
    expect(page).to_have_url(f"{WEB_BASE}/r/{resource_of(mod, source['name'])}", timeout=30000)
    page.go_back()
    page.get_by_test_id("ds-made-by").get_by_role("link").click()
    expect(page).to_have_url(f"{WEB_BASE}/r/{resource_of(mod, model['name'], 'model')}", timeout=30000)


def test_an_upload_says_its_file_and_links_nothing(page, api) -> None:
    mod = Module(api, "Origin upload")
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"ledger_{mod.tag}",
                              b"id,total\n1,10\n")
    page.goto(f"{WEB_BASE}/r/{resource_of(mod, made['name'])}?tab=details")
    made_by = page.get_by_test_id("ds-made-by")
    expect(made_by).to_have_text("An upload — uploaded as seed.csv", timeout=30000)
    expect(made_by.get_by_role("link")).to_have_count(0)
    expect(page.get_by_test_id("ds-made-from")).to_have_count(0)
