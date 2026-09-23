"""p.115's dataset references by id (§444; `code-repositories` p.114-115).

    "Datasets can be referenced in code by using their exact location in
     Foundry (path) or by using their unique resource identifier (RID). While
     both options are valid, it is recommended to use RIDs where possible, as
     this allows resources to be moved from one location to another without
     needing any updates to the code in the repository." (p.114-115)

    "Automatically change to RIDs when possible — This option will insert the
     RID of the dataset… The editor will present the dataset name over the
     RID and allow editing it as needed." (p.115)

The resolution is `apps/api/tests/test_transform_publish.py`'s, the setting is
`commit-message.test.ts`'s and which text is inserted is
`completions.test.ts`'s. What needs a browser is the seam p.115 is actually
about: **the editor shows a name and types an id**, and the file that results
goes on publishing after the dataset is renamed — which is the sentence §435
wrote as a hazard.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually

PREFER_IDS = json.dumps({"datasetReferences": {"prefer": "id"}}, indent=2) + "\n"


def a_repository(api, name: str, settings: str | None) -> dict:
    mod = Module(api, name)
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Transforms {mod.tag}"})
    # Capitals so the name and its slug differ, and no space so a declaration
    # can carry it (`test_completions.py` learned both).
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload",
                              f"Raw_Orders_{mod.tag}", b"id,total\n1,10\n")
    files = {"src/t.sql": "-- output: out_x\nSELECT 1 AS id\n"}
    if settings is not None:
        files["repoSettings.json"] = settings
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/commits",
                 {"branch": "main", "files": files, "message": "a change"})
    return {"mod": mod, "repo": repo, "dataset": made}


def open_file(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/t.sql")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    expect(page.locator(".view-lines").first).to_be_visible(timeout=30000)


def suggestions(page) -> list[str]:
    return page.locator(".suggest-widget .monaco-list-row .label-name").evaluate_all(
        "rows => rows.map(r => r.textContent.trim())"
    )


def editor_text(page) -> str:
    return page.locator(".view-lines").inner_text().replace(" ", " ")


def declare_input(page, typed: str) -> None:
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+Home")
    page.keyboard.type(f"-- input: raw = {typed}")


@pytest.fixture(scope="module")
def prefers_ids(api):
    return a_repository(api, "Refs by id", PREFER_IDS)


@pytest.fixture(scope="module")
def prefers_names(api):
    return a_repository(api, "Refs by name", None)


def test_the_list_shows_the_name_and_the_editor_types_the_id(page, prefers_ids) -> None:
    """p.115 in one sentence: "the editor will present the dataset name over
    the RID". A list of ids would be one nobody could choose from."""
    made = prefers_ids
    open_file(page, made["repo"])
    declare_input(page, "Raw_Ord")

    eventually(lambda: suggestions(page), lambda s: made["dataset"]["name"] in s,
               what="the dataset offered by name")
    page.keyboard.press("Enter")
    eventually(lambda: editor_text(page), lambda t: made["dataset"]["id"] in t,
               what="the id to have been typed into the file")
    assert made["dataset"]["name"] not in editor_text(page).split("\n")[0]


def test_a_repository_that_does_not_ask_still_types_the_name(page, prefers_names) -> None:
    """**The half that has to be true for the other half to be safe.** Every
    repository here was written before the setting."""
    made = prefers_names
    open_file(page, made["repo"])
    declare_input(page, "Raw_Ord")

    eventually(lambda: suggestions(page), lambda s: made["dataset"]["name"] in s,
               what="the dataset offered by name")
    page.keyboard.press("Enter")
    eventually(lambda: editor_text(page), lambda t: made["dataset"]["name"] in t,
               what="the name to have been typed into the file")
    assert made["dataset"]["id"] not in editor_text(page)


def test_a_file_that_names_its_input_by_id_still_offers_that_datasets_columns(
    page, prefers_ids
) -> None:
    """**The case p.115 recommends, and the one that breaks quietly.** A file
    full of ids getting no column completions would make the recommended form
    the worse one to work in."""
    made = prefers_ids
    mod, repo = made["mod"], made["repo"]
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "by id",
         "files": {"repoSettings.json": PREFER_IDS,
                   "src/t.sql": f"-- output: out_y\n-- input: raw = {made['dataset']['id']}\n"
                                "SELECT 1 AS id\n"}},
    )
    open_file(page, repo)
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\nSELECT raw.")
    eventually(lambda: suggestions(page), lambda s: "total" in s,
               what="the columns of the dataset the id points at")


def test_a_reference_by_id_survives_the_rename_that_breaks_one_by_name(
    page, api
) -> None:
    """**p.115's whole claim, end to end** — and §435's hazard, answered.

    Two files in one repository, one naming the dataset each way. Rename the
    dataset, and the publish preview says exactly one of them is broken.
    """
    made = a_repository(api, "Refs rename", PREFER_IDS)
    mod, repo, ds = made["mod"], made["repo"], made["dataset"]
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "two ways",
         "files": {"repoSettings.json": PREFER_IDS,
                   "src/by_id.sql": f"-- output: out_id_{mod.tag}\n"
                                    f"-- input: raw = {ds['id']}\nSELECT 1 AS id\n",
                   "src/by_name.sql": f"-- output: out_name_{mod.tag}\n"
                                      f"-- input: raw = {ds['name']}\nSELECT 1 AS id\n"}},
    )
    published = mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/publish", {"branch": "main"})
    assert len(published["steps"]) == 2, published

    mod.api.call("PATCH", f"{mod.base}/datasets/{ds['id']}",
                 {"name": f"{ds['name']}_renamed"})

    # The whole repository refuses, because one file in it is now wrong — and
    # the refusal names *that* file rather than the one that survived.
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=publish")
    problem = page.locator(".state.error, .form-error").first
    expect(problem).to_be_visible(timeout=30000)
    expect(problem).to_contain_text("by_name.sql")
    expect(problem).not_to_contain_text("by_id.sql")
