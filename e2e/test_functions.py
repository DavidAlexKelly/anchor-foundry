"""Functions on the ontology page (decision 0018 option B; §769; Foundry
`ontology-manager` p.29, `functions` p.49-50).

The registry and the call are `apps/api/tests/test_functions.py`'s, and the
dialog's sentences `apps/web/src/lib/functions.test.ts`'. What needs a browser
is the round trip: a function written in the dialog, published, run with a
value typed into its form, and changed by publishing a version after it while
the first goes on answering.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE
from ontology_page import pick_type

ROWS = [
    {"code": "S1", "region": "north", "capacity": "10"},
    {"code": "S2", "region": "north", "capacity": "30"},
    {"code": "S3", "region": "south", "capacity": "25"},
]


@pytest.fixture(scope="module")
def world(api):
    mod = Module(api, "Functions")
    slug = f"site_{mod.tag}"
    sites = mod.object_type(columns=["code", "region", "capacity"], rows=ROWS, key="code",
                            title="code", slug=slug, types={"capacity": "integer"})
    return {"mod": mod, "sites": sites, "slug": slug}


def open_objects(page, mod) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/objects")
    expect(page.get_by_test_id("new-function")).to_be_visible(timeout=30000)


def test_a_function_is_written_published_run_and_versioned(page, world) -> None:
    mod, slug = world["mod"], world["slug"]
    name = f"Capacity {uuid.uuid4().hex[:4]}"
    api_name = name.lower().replace(" ", "_")
    open_objects(page, mod)
    page.get_by_test_id("new-function").click()
    expect(page.get_by_test_id("fn-problem")).to_have_text("Give the function a name.")
    page.get_by_test_id("fn-name").fill(name)
    expect(page.get_by_test_id("fn-api-name")).to_contain_text(api_name)
    expect(page.get_by_test_id("fn-no-inputs")).to_be_visible()

    # The table the query can name, with its columns, once it is read.
    pick_type(page, "fn-input-picker", {"id": world["sites"], "api_name": slug})
    page.get_by_test_id("fn-add-input").click()
    expect(page.get_by_test_id("fn-inputs")).to_contain_text(slug)
    expect(page.get_by_test_id("fn-inputs")).to_contain_text("__primary_key, code, region, capacity")

    page.get_by_test_id("fn-add-parameter").click()
    page.get_by_role("textbox", name="Parameter 1 name").fill("region")
    # Said before Publish, in the server's terms.
    expect(page.get_by_test_id("fn-problem")).to_have_text("Write the query.")
    page.get_by_test_id("fn-sql").fill(f"SELECT sum(capacity) FROM {slug}")
    expect(page.get_by_test_id("fn-problem")).to_have_text(
        "region is declared and the query never uses $region.")
    expect(page.get_by_test_id("fn-save")).to_be_disabled()
    page.get_by_test_id("fn-sql").fill(f"SELECT sum(capacity) FROM {slug} WHERE region = $region")
    expect(page.get_by_test_id("fn-problem")).to_have_count(0)
    page.get_by_test_id("fn-save").click()
    expect(page.get_by_test_id(f"fn-version-{api_name}")).to_have_text("1.0.0", timeout=15000)

    page.get_by_role("button", name=f"Run {api_name}").click()
    page.get_by_role("textbox", name="Value of region").fill("north")
    page.get_by_test_id("fn-run").click()
    expect(page.get_by_test_id("fn-result-line")).to_have_text("40", timeout=15000)
    page.get_by_role("button", name="Close", exact=True).click()

    # A new version starts from the last, with the next patch number.
    page.get_by_role("button", name=f"New version of {api_name}").click()
    expect(page.get_by_test_id("fn-version")).to_have_value("1.0.1", timeout=15000)
    expect(page.get_by_test_id("fn-sql")).to_have_value(
        f"SELECT sum(capacity) FROM {slug} WHERE region = $region")
    page.get_by_test_id("fn-version").fill("1.0.0")
    expect(page.get_by_test_id("fn-problem")).to_contain_text("must come after 1.0.0")
    page.get_by_test_id("fn-version").fill("1.1.0")
    page.get_by_test_id("fn-sql").fill(
        f"SELECT count(*) FROM {slug} WHERE region = $region")
    page.get_by_test_id("fn-save").click()
    expect(page.get_by_test_id(f"fn-version-{api_name}")).to_have_text("1.1.0", timeout=15000)

    # The newest by default; the first still answers as it did.
    page.get_by_role("button", name=f"Run {api_name}").click()
    page.get_by_role("textbox", name="Value of region").fill("north")
    page.get_by_test_id("fn-run").click()
    expect(page.get_by_test_id("fn-result-line")).to_have_text("2", timeout=15000)
    page.get_by_test_id("fn-run-version").select_option("1.0.0")
    page.get_by_test_id("fn-run").click()
    expect(page.get_by_test_id("fn-result-line")).to_have_text("40", timeout=15000)


def test_the_servers_refusal_is_said_in_the_dialog(page, world) -> None:
    """A misspelt column is what only running the query finds."""
    mod, slug = world["mod"], world["slug"]
    open_objects(page, mod)
    page.get_by_test_id("new-function").click()
    page.get_by_test_id("fn-name").fill(f"Broken {uuid.uuid4().hex[:4]}")
    pick_type(page, "fn-input-picker", {"id": world["sites"], "api_name": slug})
    page.get_by_test_id("fn-add-input").click()
    page.get_by_test_id("fn-sql").fill(f"SELECT sum(capacty) FROM {slug}")
    page.get_by_test_id("fn-save").click()
    expect(page.get_by_test_id("fn-error")).to_contain_text("capacty", timeout=15000)


def test_a_table_function_draws_its_rows(page, api, world) -> None:
    mod, slug = world["mod"], world["slug"]
    api_name = f"by_region_{uuid.uuid4().hex[:4]}"
    api.call("POST", f"/workspaces/{mod.workspace_id}/functions", {
        "api_name": api_name, "display_name": "By region",
        "version": {"version": "1.0.0", "inputs": [world["sites"]],
                    "output": {"kind": "table"},
                    "sql": f"SELECT region, count(*) AS n FROM {slug} GROUP BY 1 ORDER BY 1"}})
    open_objects(page, mod)
    page.get_by_role("button", name=f"Run {api_name}").click()
    page.get_by_test_id("fn-run").click()
    table = page.get_by_test_id("fn-result-table")
    expect(table.locator("tbody tr")).to_have_count(2, timeout=15000)
    expect(table.locator("thead th")).to_have_text(["region", "n"])
    expect(table.locator("tbody tr").first).to_contain_text("north")
    expect(page.get_by_test_id("fn-result-line")).to_have_text("2 rows")
