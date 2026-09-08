"""Exports from the product (`data-connection` p.192-206; decision 0014; §267).

§265 built the rule, the store, the runner and the routes, and left every one
of them reachable only by posting JSON. p.203 says where the screen belongs:
"navigate to the Overview page of the source to which you want to export".

**What needs a browser is the round trip no API test can see**: an export
configured entirely through the form, run from the row, moving real rows into a
real table. The API suite asserts the same rule against rows it wrote itself.

The destination is the platform's own Postgres in a database of its own, which
is `apps/api/tests/test_export_runs.py`'s arrangement — the local server as a
customer's *warehouse* rather than as a customer's source.
"""
from __future__ import annotations

import os
import sys
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
DEST_DB = "export_e2e_dest"
DEST_USER = "export_e2e_user"
DEST_PASSWORD = "e2e-D3st-88"

ORDERS = [
    {"id": "1", "email": "ada@example.com"},
    {"id": "2", "email": "grace@example.com"},
]


def _dsn(database: str) -> str:
    import urllib.parse

    parts = urllib.parse.urlsplit(ADMIN_DSN)
    return urllib.parse.urlunsplit(parts._replace(path=f"/{database}"))


@pytest.fixture(scope="module")
def warehouse():
    """A database standing in for the customer's, with a login role of its own.

    Its own role rather than the platform owner, because p.197's truncation
    permission is a real constraint and cannot be exercised as the owner of
    everything.
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")
        conn.execute(f"CREATE ROLE {DEST_USER} LOGIN PASSWORD '{DEST_PASSWORD}'")
        conn.execute(f"GRANT {DEST_USER} TO platform")
        conn.execute(f"CREATE DATABASE {DEST_DB} OWNER {DEST_USER}")
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        conn.execute("CREATE TABLE public.orders (id bigint, email text)")
        conn.execute(f"GRANT ALL ON public.orders TO {DEST_USER}")
    yield {"host": "localhost", "port": 5432, "database": DEST_DB, "user": DEST_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {DEST_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {DEST_USER}")


def rows_out() -> list[tuple]:
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        return conn.execute("SELECT id, email FROM public.orders ORDER BY id").fetchall()


@pytest.fixture(scope="module")
def module(api):
    return Module(api, "Exports")


def open_connections(page, module) -> None:
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/connections")
    expect(page.get_by_test_id("exports-panel")).to_be_visible(timeout=30000)


def a_dataset(api, module) -> str:
    """A dataset with two rows, uploaded as a CSV."""
    name = f"orders_{uuid.uuid4().hex[:6]}"
    csv = "id,email\n" + "".join(f"{r['id']},{r['email']}\n" for r in ORDERS)
    made = api.upload_csv(f"{module.base}/datasets/upload", name=name, csv=csv.encode())
    return made["name"]


def a_warehouse(api, module, warehouse: dict, *, enabled: bool) -> dict:
    made = api.call("POST", f"{module.base}/connections", {
        "name": f"Warehouse {uuid.uuid4().hex[:6]}", "source_type": "postgres",
        "scope": "project", "config": warehouse,
        "secret": {"password": DEST_PASSWORD},
    })
    if enabled:
        api.call(
            "PUT", f"{module.base}/connections/{made['id']}/exports-enabled",
            {"enabled": True},
        )
    return made


def test_a_source_nobody_enabled_says_so_and_offers_the_switch(page, api, module, warehouse):
    """p.202: "you must enable exports in the Connection settings section of
    the source to which you are exporting."

    **Two sentences, not one.** A source that *could* be a destination and has
    not been turned on is a different situation from one that could never be,
    and a panel that merged them would send somebody to ask the wrong question.
    """
    source = a_warehouse(api, module, warehouse, enabled=False)
    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    expect(panel.get_by_test_id("exports-not-enabled")).to_be_visible()
    expect(panel.get_by_test_id("exports-not-enabled")).to_contain_text(source["name"])
    expect(panel.get_by_test_id("new-export")).to_be_disabled()

    # And the switch is right there, because the dev owner is a workspace admin.
    panel.get_by_test_id(f"enable-exports-{source['id']}").click()
    expect(panel.get_by_test_id("new-export")).to_be_enabled(timeout=15000)


def test_an_export_written_in_the_form_moves_real_rows(page, api, module, warehouse):
    """**The claim §267 exists for**, checked at the far end of the wire rather
    than in the row the form wrote.

    Every step is the form's: choose the source, choose the dataset, name it,
    name the table, press Create, press Run. What is asserted is what is in
    somebody else's database afterwards.
    """
    a_warehouse(api, module, warehouse, enabled=True)
    dataset = a_dataset(api, module)
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        conn.execute("TRUNCATE public.orders")

    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    panel.get_by_test_id("new-export").click()
    page.get_by_test_id("export-dataset").select_option(label=dataset)
    name = f"Nightly {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("export-name").fill(name)
    page.get_by_test_id("export-schema").fill("public")
    page.get_by_test_id("export-table").fill("orders")
    page.get_by_test_id("export-save").click()

    expect(panel.get_by_test_id("exports-table")).to_contain_text(name, timeout=15000)
    # Never run, and the row says so rather than showing a blank cell.
    expect(panel.get_by_test_id(f"export-state-{name}")).to_have_text("never run")

    panel.get_by_test_id(f"run-export-{name}").click()
    expect(panel.get_by_test_id(f"export-state-{name}")).to_contain_text(
        "up to date", timeout=30000
    )
    assert rows_out() == [(1, "ada@example.com"), (2, "grace@example.com")]


def test_running_it_again_says_there_was_nothing_new(page, api, module, warehouse):
    """p.192: "exports with no new files or rows to be exported will be marked
    as `success`."

    **That change is why the history needs its own word for a skip.** After it,
    a run that did nothing and a run that wrote everything are both green, and
    a list of ticks stops answering the question somebody opened it to ask.
    """
    a_warehouse(api, module, warehouse, enabled=True)
    dataset = a_dataset(api, module)
    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    panel.get_by_test_id("new-export").click()
    page.get_by_test_id("export-dataset").select_option(label=dataset)
    name = f"Twice {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("export-name").fill(name)
    page.get_by_test_id("export-schema").fill("public")
    page.get_by_test_id("export-table").fill("orders")
    page.get_by_test_id("export-save").click()
    expect(panel.get_by_test_id("exports-table")).to_contain_text(name, timeout=15000)

    panel.get_by_test_id(f"run-export-{name}").click()
    expect(panel.get_by_test_id(f"export-state-{name}")).to_contain_text(
        "up to date", timeout=30000
    )
    panel.get_by_test_id(f"run-export-{name}").click()
    page.wait_for_timeout(1500)

    row = panel.get_by_test_id("exports-table").locator("tbody tr").filter(has_text=name)
    row.get_by_role("button", name="History").click()
    runs = page.get_by_test_id("export-runs")
    expect(runs).to_be_visible(timeout=15000)
    # The skip is its own word, above the run that actually wrote.
    expect(runs.locator("tbody tr").first).to_contain_text("nothing new")
    expect(runs.locator("tbody tr").nth(1)).to_contain_text("2 rows")


def test_a_dataset_the_destination_cannot_take_fails_with_the_column_named(
    page, api, module, warehouse
):
    """p.197's 1:1 match, surfaced where somebody can act on it.

    The failure names the column rather than quoting a driver, and it happens
    before any row is written — which is the half Foundry leaves to run time.
    """
    a_warehouse(api, module, warehouse, enabled=True)
    name = f"wide_{uuid.uuid4().hex[:6]}"
    api.upload_csv(
        f"{module.base}/datasets/upload", name=name,
        csv=b"id,email,extra\n1,ada@example.com,x\n",
    )
    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    panel.get_by_test_id("new-export").click()
    page.get_by_test_id("export-dataset").select_option(label=name)
    export_name = f"Wide {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("export-name").fill(export_name)
    page.get_by_test_id("export-schema").fill("public")
    page.get_by_test_id("export-table").fill("orders")
    page.get_by_test_id("export-save").click()
    expect(panel.get_by_test_id("exports-table")).to_contain_text(export_name, timeout=15000)

    panel.get_by_test_id(f"run-export-{export_name}").click()
    failure = page.get_by_test_id("export-failed")
    expect(failure).to_be_visible(timeout=30000)
    expect(failure).to_contain_text("extra")
    expect(failure).to_contain_text("p.197")


@pytest.fixture
def editor_page(browser):
    """A page signed in as somebody who is **not** a workspace admin.

    Local to this file because one test needs it. The dev editor is a project
    editor and an organisation member — exactly the person who can reach the
    connections page and cannot work p.202's switch.
    """
    import json

    from conftest import FIRST_RENDER_MS, TOKENS_FILE

    with open(TOKENS_FILE) as handle:
        token = json.load(handle)["editor@acme.dev.local"]
    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    opened = context.new_page()
    opened.goto(f"{WEB_BASE}/login")
    opened.fill("input[placeholder='Paste an access token']", token)
    opened.get_by_role("button", name="Use token").click()
    opened.wait_for_url(lambda url: "/login" not in url, timeout=FIRST_RENDER_MS)
    yield opened
    context.close()


@pytest.fixture(scope="module")
def lonely(api):
    """A project of its own, holding exactly one source and that one disabled.

    The tests above enable exports on their warehouses and share a project, so
    by the time this one runs the panel has a usable destination and correctly
    does not render the "none enabled" explanation at all. A test about an
    empty state needs somewhere that is actually empty — §122's trap in its
    quietest form, where the leftovers are not noise but a *different valid
    state*.
    """
    return Module(api, "Exports lonely")


def test_somebody_who_cannot_work_the_switch_is_not_offered_it(
    editor_page, api, lonely, warehouse
):
    """p.202 makes enabling exports a privileged act, and §265's route enforces
    it — so a button offered to a project editor is a button whose only outcome
    is a 403.

    **§214: a control that cannot work is worse than an absent one.** The
    explanation stays, because the editor still needs to know *why* they cannot
    make an export here; what goes is the button that would lie to them.

    §267's harness found this one, and the reason it could is worth keeping:
    every other test in this file runs as the dev owner, who is a workspace
    admin, so `canAdmin` was true in every fixture and the false branch had
    nothing on the other side of it to be wrong about (§257).
    """
    a_warehouse(api, lonely, warehouse, enabled=False)
    editor_page.goto(
        f"{WEB_BASE}/{lonely.workspace_slug}/{lonely.project_slug}/connections"
    )
    panel = editor_page.get_by_test_id("exports-panel")
    expect(panel).to_be_visible(timeout=30000)
    expect(panel.get_by_test_id("exports-not-enabled")).to_be_visible()
    # The reason is still there…
    expect(panel.get_by_test_id("exports-need-an-admin")).to_be_visible()
    # …and the button that would 403 is not.
    expect(panel.get_by_role("button", name="Enable exports to")).to_have_count(0)
