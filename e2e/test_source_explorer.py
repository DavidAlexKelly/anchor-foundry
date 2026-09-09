"""Exploring a source from the product (`data-connection` p.142-143; decision
0015; §269).

§268 built `preview()` on every connector and left it reachable only by posting
JSON. p.142 says where the screen belongs and what it is for: "explore the
source and the data it contains to preview syncs before they bring data into
Foundry", reached from the source itself.

**What needs a browser is the round trip no API test can see**: a table found
by typing in a search box, previewed by pressing a button, showing rows that
are really in somebody else's database — and then carried into a sync without
being picked out of a dropdown again.

The source is the platform's own Postgres in a database of its own, which is
`apps/api/tests/test_source_preview.py`'s arrangement: the local server as a
customer's *system* rather than as the platform's store.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN", "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable"
)
SOURCE_DB = "explore_e2e_source"
SOURCE_USER = "explore_e2e_user"
SOURCE_PASSWORD = "expl0re-E2E-7"


def _dsn(database: str) -> str:
    parts = urllib.parse.urlsplit(ADMIN_DSN)
    return urllib.parse.urlunsplit(parts._replace(path=f"/{database}"))


@pytest.fixture(scope="module")
def source():
    """A database standing in for the customer's, with tables chosen for what
    the screen has to say about them.

    `orders` has a null, because a blank cell and a null are the two things a
    preview must not merge. `shipments` carries `customer_email` and *not* the
    word "orders", so a search for a column finds a table whose name does not
    match. `orders_view` is a view, which p.143 includes in exploration and this
    platform excludes from syncing.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    with psycopg.connect(_dsn(SOURCE_DB), autocommit=True) as conn:
        conn.execute(
            "CREATE TABLE public.orders (id bigint PRIMARY KEY, note text)"
        )
        conn.execute("INSERT INTO public.orders VALUES (1, 'first order'), (2, NULL)")
        conn.execute(
            "CREATE TABLE public.shipments (id bigint, customer_email text)"
        )
        conn.execute("INSERT INTO public.shipments VALUES (1, 'ada@example.com')")
        conn.execute("CREATE VIEW public.orders_view AS SELECT * FROM public.orders")
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
    yield {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")


def build(api, name: str) -> Module:
    """A project per test, so the connections table on screen holds this test's
    row and nobody else's — §122's trap, and it bites here because the row is
    found by its name."""
    return Module(api, name)


def a_source(api, mod: Module, config: dict) -> dict:
    return api.call("POST", f"{mod.base}/connections", {
        "name": f"Customer DB {mod.tag}", "source_type": "postgres",
        "scope": "project", "config": config,
        "secret": {"password": SOURCE_PASSWORD},
    })


def open_explore(page, mod: Module, name: str):
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("explore-tree")).to_be_visible(timeout=30000)


def test_the_tree_lists_what_the_source_holds(page, api, source):
    """p.143's callout 1, and p.142's reason for the screen existing: what is
    in there, before anything is synced."""
    mod = build(api, "Explore tree")
    made = a_source(api, mod, source)
    open_explore(page, mod, made["name"])

    tree = page.get_by_test_id("explore-tree")
    expect(tree).to_contain_text("orders")
    expect(tree).to_contain_text("shipments")
    # A view is in the tree, because p.143 says "tables and views" — the
    # exclusion is from syncing, and it is asserted separately below.
    expect(tree).to_contain_text("orders_view")
    # Nothing is selected, and the panel says so rather than sitting blank.
    expect(page.get_by_test_id("explore-nothing-selected")).to_be_visible()


def test_the_search_finds_a_table_by_a_column_and_says_why(page, api, source):
    """p.143: "Use the free text search helper to find specific tables."

    **The interesting case is the one a name-only search cannot answer.**
    `customer_email` is a column of `shipments` and appears nowhere in its
    name, so a table arriving under that query has to explain itself — a match
    somebody cannot account for reads as a bug in the search.
    """
    mod = build(api, "Explore search")
    made = a_source(api, mod, source)
    open_explore(page, mod, made["name"])

    page.get_by_test_id("explore-search").fill("customer_email")
    tree = page.get_by_test_id("explore-tree")
    expect(page.get_by_test_id("explore-entry-shipments")).to_be_visible()
    expect(page.get_by_test_id("explore-why-shipments")).to_contain_text("matched column")
    # And the narrowing is real: `orders` does not have that column.
    expect(tree).not_to_contain_text("explore-entry-orders")
    expect(page.get_by_test_id("explore-entry-orders")).to_have_count(0)

    # A query that matches nothing says so rather than showing an empty box.
    page.get_by_test_id("explore-search").fill("zzz-nothing")
    expect(page.get_by_test_id("explore-no-matches")).to_be_visible()


def test_a_preview_shows_the_rows_that_are_really_there(page, api, source):
    """**The claim §269 exists for**, checked against rows nobody in this
    platform wrote — they are in the customer's database and arrive only by
    the connector reading them.

    The null is the second half. The server sends `null` rather than `""` so an
    empty column can be told from a missing one, and a screen that rendered
    both as a blank cell would throw that away at the last step.
    """
    mod = build(api, "Explore preview")
    made = a_source(api, mod, source)
    open_explore(page, mod, made["name"])

    # **Counted, not raced** (§266). "The sample is not there yet" is also what
    # an auto-fetch looks like for its first few hundred milliseconds, so
    # asserting an absent table would pass against a screen that queries the
    # customer's database on every click. What is asserted is the request.
    calls: list[str] = []
    page.on(
        "request",
        lambda r: calls.append(r.url) if "/preview" in r.url else None,
    )

    page.get_by_test_id("explore-entry-orders").click()
    expect(page.get_by_test_id("explore-selected")).to_contain_text("orders")
    # Columns are there from `discover`; the rows are not, until asked for.
    expect(page.get_by_test_id("explore-columns")).to_contain_text("note")
    expect(page.get_by_test_id("explore-sample")).to_have_count(0)
    # Long enough that a fetch-on-select would certainly have been issued — the
    # request goes out on render, so this is generous rather than marginal.
    page.wait_for_timeout(1500)
    assert calls == [], (
        "selecting a table must not query the source: a preview is a real read "
        "of somebody else's system with their credentials, and clicking through "
        "a tree of forty tables should not be forty queries"
    )

    page.get_by_test_id("explore-preview").click()
    sample = page.get_by_test_id("explore-sample")
    expect(sample).to_be_visible(timeout=30000)
    expect(sample).to_contain_text("first order")
    expect(sample).to_contain_text("null")
    # Two rows, all of them — so the caption says so rather than reading as a
    # row count of a table that might be bigger.
    expect(page.get_by_test_id("explore-sample-summary")).to_have_text("all 2 rows, 2 columns.")
    expect(page.get_by_test_id("explore-sample-caveat")).to_have_count(0)
    # And pressing it asked exactly once — the pair for the assertion above,
    # without which "no requests ever" would also pass.
    assert len(calls) == 1, calls


def test_a_view_is_previewed_and_not_offered_a_sync(page, api, source):
    """§214: a control that cannot work is worse than an absent one.

    A sync reads tables and files, so a Sync button on a view is a button whose
    only outcome is a refusal. The explanation stays, because "why not this
    one" is the question somebody is about to ask — and the preview stays too,
    since looking at a view is exactly what p.143 includes it for.
    """
    mod = build(api, "Explore view")
    made = a_source(api, mod, source)
    open_explore(page, mod, made["name"])

    page.get_by_test_id("explore-entry-orders_view").click()
    expect(page.get_by_test_id("explore-not-syncable")).to_contain_text("this is a view")
    expect(page.get_by_test_id("explore-sync")).to_have_count(0)

    page.get_by_test_id("explore-preview").click()
    expect(page.get_by_test_id("explore-sample")).to_contain_text("first order", timeout=30000)


def test_a_table_carries_into_the_sync_form_already_chosen(page, api, source):
    """p.145: "select Explore and create syncs to explore your data source and
    begin creating syncs directly from the exploration view."

    The point is that nobody has to find, in a dropdown, the row they were just
    looking at — so what is asserted is that the sync form opens with the
    dataset name already filled from the table, and that pressing Sync lands
    that table's rows.
    """
    mod = build(api, "Explore to sync")
    made = a_source(api, mod, source)
    open_explore(page, mod, made["name"])

    page.get_by_test_id("explore-entry-shipments").click()
    page.get_by_test_id("explore-sync").click()

    name = page.get_by_label("Dataset name")
    expect(name).to_have_value("shipments", timeout=15000)
    page.get_by_role("button", name="Sync now").click()
    expect(page.get_by_text("Find it under Datasets")).to_be_visible(timeout=60000)


def test_the_sample_is_capped_and_says_that_it_is(page, api, source):
    """Decision 0015 §4 and §5, on the screen they are about.

    A table bigger than the cap is the only state where "50 rows" would read as
    a row count, and the only one where the sample really is a *sample* — so
    the caption changes and the caveat appears. The pair for this is
    `test_a_preview_shows_the_rows_that_are_really_there`, which asserts the
    caveat is *absent* when every row is on screen; a caveat that is always
    there is one nobody reads.
    """
    mod = build(api, "Explore capped")
    made = a_source(api, mod, source)
    table = f"many_{uuid.uuid4().hex[:6]}"
    with psycopg.connect(_dsn(SOURCE_DB), autocommit=True) as conn:
        conn.execute(f"CREATE TABLE public.{table} (n int)")
        conn.execute(f"INSERT INTO public.{table} SELECT generate_series(1, 500)")
        conn.execute(f"GRANT ALL ON public.{table} TO {SOURCE_USER}")

    open_explore(page, mod, made["name"])
    page.get_by_test_id("explore-search").fill(table)
    page.get_by_test_id(f"explore-entry-{table}").click()
    page.get_by_test_id("explore-preview").click()

    expect(page.get_by_test_id("explore-sample-summary")).to_contain_text(
        "of more than", timeout=30000
    )
    expect(page.get_by_test_id("explore-sample-caveat")).to_contain_text("not the first rows")
