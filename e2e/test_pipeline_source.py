"""p.42's data source on the lineage graph (§420; `data-lineage` p.42-43).

> "Data source: This is the name of the data source as it appears in Data
> Connection." (p.42)

> "Syncs: Datasets with this indicator on them have syncs to other databases or
> systems." (p.43)

Both of p.42-43's halves are the same fact, and one node with an arrow says it
once: a graph drawn whole does not need a badge announcing a neighbour it
already draws (§355's argument). Which connections are on the graph and what
status each carries is `apps/api/tests/test_pipeline.py`'s. What needs a
browser is the part no API test can claim: that the source is **drawn**, that
it is addressable the way the other three kinds are — filtered to, searched
for, coloured — and that clicking it lands somewhere that answers the question
it raises.
"""
from __future__ import annotations

import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from conftest import ADMIN_DSN, WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n"


@pytest.fixture(scope="module")
def sourced(api):
    """A connection that has filled a dataset, beside one that was uploaded.

    The sync run is written straight into the table rather than performed: a
    real sync needs a reachable source database, and what this file is about
    is what the graph makes of the row afterwards.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Source {tag}", "slug": f"source-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    filled = api.upload_csv(f"{base}/datasets/upload", f"Filled {tag}", ROWS)
    api.upload_csv(f"{base}/datasets/upload", f"Typed {tag}", ROWS)
    connection = api.call("POST", f"{base}/connections", {
        "name": f"Warehouse {tag}", "source_type": "postgres",
        "config": {"host": "nowhere.invalid", "port": 5432,
                   "database": "src", "user": "u"},
        "secret": {"password": "x"},
    })
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO sync_runs (connection_id, dataset_id, mode, source_table,"
            "                       status, finished_at) "
            "VALUES (%s, %s, 'full', 'public.orders', 'succeeded', now())",
            (connection["id"], filled["id"]),
        )
    return {"tag": tag, "workspace_slug": workspace["slug"],
            "project_slug": project["slug"], "connection": connection["id"],
            "filled": filled["id"]}


def open_graph(page, sourced, query: str = "") -> None:
    page.goto(
        f"{WEB_BASE}/{sourced['workspace_slug']}/{sourced['project_slug']}"
        f"/pipeline{query}"
    )
    expect(page.get_by_test_id("graph-search")).to_be_visible(timeout=30000)


def source_card(page, sourced):
    return page.locator(
        f"[data-testid='graph-node'][data-node='connection:{sourced['connection']}']"
    )


def test_the_source_is_drawn_with_its_type_under_its_name(page, sourced) -> None:
    """p.42 names both: the connection's name is what somebody called it, and
    the source type is what tells a reader whether this is a Postgres or an S3
    bucket."""
    open_graph(page, sourced)
    card = source_card(page, sourced)
    expect(card).to_be_visible()
    expect(card).to_contain_text(f"Warehouse {sourced['tag']}")
    expect(card).to_contain_text("postgres")
    # Named on the card as well, because "connection" is the table's word and
    # "data source" is p.42's.
    expect(card).to_contain_text("data source")


def test_the_source_is_upstream_of_the_dataset_it_filled(page, sourced) -> None:
    """The arrow is p.43's Syncs indicator, said as lineage. A badge would say
    *that* there are syncs; the arrow says which data came from where."""
    open_graph(page, sourced)
    source = source_card(page, sourced)
    filled = page.locator(
        f"[data-testid='graph-node'][data-node='dataset:{sourced['filled']}']"
    )
    expect(source).to_be_visible()
    expect(filled).to_be_visible()
    # Left of it on the canvas, which is what the layering means here — every
    # edge on this graph points strictly rightwards.
    assert source.bounding_box()["x"] < filled.bounding_box()["x"]


def test_a_source_is_one_of_the_kinds_the_graph_can_filter_to(page, sourced) -> None:
    """§420's mirror, from the reader's end: a kind the graph draws and the
    chips do not offer is a node nobody can narrow to."""
    open_graph(page, sourced)
    chip = page.get_by_test_id("search-kind-connection")
    # **The chip's own words, not only its handle** (§337). Labelled "datasets"
    # it would be one of two chips reading the same thing, and a reader
    # narrowing to data sources would be clicking whichever came first.
    expect(chip).to_have_text("data sources")
    chip.click()
    expect(page.get_by_test_id("graph-node").and_(
        page.locator("[data-kind='connection']")
    )).to_have_count(1)
    expect(page.get_by_test_id("search-count")).to_contain_text("1 of")


def test_a_source_is_found_by_name(page, sourced) -> None:
    open_graph(page, sourced)
    page.get_by_test_id("search-query").fill("warehouse")
    expect(source_card(page, sourced)).to_have_attribute("data-match", "true")


def test_a_source_has_its_own_colour_under_resource_type(page, sourced) -> None:
    """§419's Resource type colouring: a fourth kind that coloured as "not
    known" would be a legend row saying the graph does not recognise a node it
    drew."""
    open_graph(page, sourced)
    page.get_by_test_id("graph-colouring").select_option("kind")
    expect(source_card(page, sourced)).to_have_attribute("data-colour", "connection")
    expect(page.get_by_test_id("legend-connection")).to_have_attribute("data-count", "1")


def test_a_succeeded_sync_colours_the_source_the_way_a_run_does(page, sourced) -> None:
    """The default colouring, over `sync_runs`' vocabulary rather than an
    object type's — a source scored against the wrong list reads as never
    having run."""
    open_graph(page, sourced)
    expect(source_card(page, sourced)).to_have_attribute("data-colour", "ok")


def test_a_source_opens_where_it_is_configured(page, sourced) -> None:
    """Not the dataset it filled: the question a source node raises is "where
    is this data coming from, and is it still pointed at the right table"."""
    open_graph(page, sourced)
    source_card(page, sourced).click()
    page.get_by_test_id("node-open").click()
    expect(page).to_have_url(
        f"{WEB_BASE}/{sourced['workspace_slug']}/{sourced['project_slug']}/connections"
    )
