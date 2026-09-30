"""p.51's third question on the lineage graph (§583).

> "Have we received up-to-date data from the source?" (`data-lineage` p.51)

Which datasets are behind their source is `apps/api/tests/
test_pipeline_sources_behind.py`'s. What needs a browser is that the graph
says so on the card, in words that say which of the two ways, and colours it
under Out of date.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def behind(api):
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call("POST", f"/workspaces/{workspace['id']}/projects",
                       {"name": f"Behind {tag}", "slug": f"behind-{tag}"})
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    failed = api.upload_csv(f"{base}/datasets/upload", f"Failed {tag}", ROWS)
    overdue = api.upload_csv(f"{base}/datasets/upload", f"Overdue {tag}", ROWS)
    fine = api.upload_csv(f"{base}/datasets/upload", f"Fine {tag}", ROWS)
    connection = api.call("POST", f"{base}/connections", {
        "name": f"Warehouse {tag}", "source_type": "postgres",
        "config": {"host": "nowhere.invalid", "port": 5432, "database": "src", "user": "u"},
        "secret": {"password": "x"}})
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        for dataset, status in ((failed, "failed"), (overdue, "succeeded"),
                                (fine, "succeeded")):
            conn.execute(
                "INSERT INTO sync_runs (connection_id, dataset_id, mode, source_table,"
                " status, finished_at) VALUES (%s, %s, 'full', 'public.t', %s, now())",
                (connection["id"], dataset["id"], status))
        conn.execute(
            "UPDATE connections SET sync_schedule = '0 * * * *', sync_dataset_id = %s,"
            " sync_next_run_at = now() - interval '3 hours' WHERE id = %s",
            (overdue["id"], connection["id"]))
    return {"tag": tag, "workspace_slug": workspace["slug"], "project_slug": project["slug"],
            "failed": failed["id"], "overdue": overdue["id"], "fine": fine["id"]}


def card(page, dataset: str):
    return page.locator(f"[data-testid='graph-node'][data-node='dataset:{dataset}']")


def open_graph(page, behind, query: str = "") -> None:
    page.goto(f"{WEB_BASE}/{behind['workspace_slug']}/{behind['project_slug']}/pipeline{query}")
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def test_the_card_says_how_its_source_is_behind(page, behind) -> None:
    open_graph(page, behind)
    expect(card(page, behind["failed"]).get_by_test_id("node-out-of-date")).to_contain_text(
        "its latest sync from its source failed")
    expect(card(page, behind["overdue"]).get_by_test_id("node-out-of-date")).to_contain_text(
        "a scheduled sync from its source has not run")
    expect(card(page, behind["fine"]).get_by_test_id("node-out-of-date")).to_have_count(0)


def test_the_out_of_date_colouring_names_the_source(page, behind) -> None:
    open_graph(page, behind)
    page.get_by_test_id("graph-colouring").select_option("out_of_date")
    expect(card(page, behind["failed"])).to_have_attribute("data-colour", "source")
    expect(card(page, behind["fine"])).to_have_attribute("data-colour", "current")
    expect(page.get_by_text("Out of date with its source")).to_be_visible()
