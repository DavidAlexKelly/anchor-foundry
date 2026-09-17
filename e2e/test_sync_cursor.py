"""The initial incremental state, from the product (`data-connection` p.175-176;
§363).

> "Configure the sync's incremental state. This state consists of an
>  incremental column **and an initial value**, which can be configured in the
>  user interface." (p.175)

`apps/api/tests/test_scheduled_sync.py` owns what the value does — that a blank
field leaves the stored progress alone, that changing the cursor column clears
it, that forgetting it keeps the rest of the configuration. What needs a
browser is the pair neither can see: that the **box on the screen is what the
request carries**, and that p.176's remedy — forgetting where the sync got to —
is reachable by somebody who has only the page.

The source is a database of this suite's own making, following
`apps/api/tests/test_connections.py`'s fixture rather than pointing a test
connection at the platform's own database.
"""
from __future__ import annotations

import json
import uuid

import psycopg
import pytest
from playwright.sync_api import expect

from api import Module
from conftest import ADMIN_DSN, WEB_BASE

SOURCE_DB = "e2e_cursor_source"
SOURCE_USER = "e2e_cursor_user"
SOURCE_PASSWORD = "e2ecursorpass"


def _for_database(dsn: str, database: str) -> str:
    """Swap the database in a libpq DSN. Written out rather than reaching into
    `packages/db/dsn.py` because `e2e/` runs with its own path, and the whole
    operation is one `rsplit` — the hazard that module exists for (a silent
    no-op `.replace`) is not present when the separator is asserted."""
    head, sep, tail = dsn.rpartition("/")
    assert sep, dsn
    query = tail.split("?", 1)
    suffix = f"?{query[1]}" if len(query) > 1 else ""
    return f"{head}/{database}{suffix}"


@pytest.fixture(scope="module")
def source_database():
    """A separate database and login role acting as the customer's system."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")
        conn.execute(f"CREATE ROLE {SOURCE_USER} LOGIN PASSWORD '{SOURCE_PASSWORD}'")
        conn.execute(f"GRANT {SOURCE_USER} TO platform")
        conn.execute(f"CREATE DATABASE {SOURCE_DB} OWNER {SOURCE_USER}")
    with psycopg.connect(_for_database(ADMIN_DSN, SOURCE_DB), autocommit=True) as conn:
        conn.execute(
            """CREATE TABLE public.orders (
                   id bigint PRIMARY KEY,
                   customer_email text NOT NULL,
                   placed_at timestamptz
               )"""
        )
        conn.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {SOURCE_USER}")
    yield {"host": "localhost", "port": 5432, "database": SOURCE_DB, "user": SOURCE_USER}
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {SOURCE_DB}")
        conn.execute(f"DROP ROLE IF EXISTS {SOURCE_USER}")


@pytest.fixture()
def synced(api, source_database):
    """A connection with an incremental sync already configured.

    A project per test, since these tests change the stored position and a
    shared one would make each test's starting point depend on the order.
    """
    mod = Module(api, f"Cursor {uuid.uuid4().hex[:6]}")
    connection = api.call("POST", f"{mod.base}/connections", {
        "name": f"Orders {mod.tag}", "source_type": "postgres", "scope": "project",
        "config": source_database, "secret": {"password": SOURCE_PASSWORD},
    })
    api.call("PUT", f"{mod.base}/connections/{connection['id']}/scheduled-sync", {
        "mode": "incremental", "source_schema": "public", "source_table": "orders",
        "primary_key_column": "id", "cursor_column": "id",
        "cron_schedule": "*/15 * * * *",
    })
    return {"mod": mod, "connection": connection, "api": api}


def schedule_of(synced) -> dict:
    return synced["api"].call(
        "GET",
        f"{synced['mod'].base}/connections/{synced['connection']['id']}/scheduled-sync",
    )


def open_sync_panel(page, synced) -> None:
    mod = synced["mod"]
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=synced["connection"]["name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Scheduled sync").click()
    expect(page.get_by_test_id("cursor-start")).to_be_visible()
    # **The panel is not ready when its fields appear.** The stored schedule
    # fills them in; the *source schema* arrives separately, and until it does
    # the form cannot be submitted. Waiting on Save rather than on a field is
    # what makes "open the panel" mean "the panel can be used" - without it a
    # test types into a box and presses a button that does nothing, which is
    # how this helper's callers failed in CI and nowhere else (§318).
    expect(page.get_by_role("button", name="Save schedule")).to_be_enabled(timeout=30000)


def test_save_is_not_offered_until_the_source_schema_has_been_read(page, synced) -> None:
    """**§214, and the reason a test in this file went red in CI and nowhere
    else.**

    A configured schedule fills the form from what is stored, so `table` is set
    the moment the panel loads - but resolving it needs `discover`, which is a
    live round trip to the customer's database and answers later. Save was
    enabled in that window and submitted *nothing*: in incremental mode the
    column pickers are `required` and held values whose options did not exist
    yet, so the browser refused the form into a native bubble that no assertion
    and no reader ever sees. Not a slow save - a press that was never going to
    do anything. (In full mode the same press reached `save.mutate` and failed
    with "Couldn't save the schedule.", which is a worse sentence than silence:
    it blames the save for a request that was never sent.)

    Held rather than slowed, because a delay races the test back - a sleeping
    route handler blocks the dispatcher, so the click lands *after* discovery
    and the panel is in the state this test exists to avoid.
    """
    held = []
    page.route("**/discover", lambda route: held.append(route))
    save = page.get_by_role("button", name="Save schedule")
    try:
        mod = synced["mod"]
        page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
        row = page.get_by_role("row").filter(has_text=synced["connection"]["name"])
        expect(row).to_be_visible(timeout=30000)
        row.get_by_role("button", name="Scheduled sync").click()

        # The form is on screen and filled in from the schedule...
        expect(page.get_by_test_id("cursor-start")).to_be_visible()
        expect(page.get_by_text("Reading the source schema")).to_be_visible()
        # ...and Save says so, instead of accepting a press it cannot honour.
        expect(save).to_be_disabled()
    finally:
        for route in held:
            route.continue_()

    # And it is a wait, not a dead control - the pair matters, because a button
    # disabled for good would satisfy the assertion above and satisfy nobody.
    expect(save).to_be_enabled()
    assert len(held) == 1, held


def test_a_source_that_cannot_be_read_says_so_rather_than_leaving_a_dead_save(
    page, synced
) -> None:
    """The other half of the one above, and its cost.

    Save waiting on the source schema means a discovery that never succeeds
    leaves it disabled for good - so the panel has to say why, or a reader is
    left pressing a button that will never respond and told nothing. The
    message is the one the API sent, not a house sentence over the top of it:
    "could not connect" and "permission denied for table orders" are different
    problems with different remedies.

    The failure is injected rather than arranged, because what is under test is
    the page's response to it; `apps/api/tests/test_connections.py` owns what a
    source that is really unreachable returns.
    """
    page.route("**/discover", lambda route: route.fulfill(
        status=502,
        content_type="application/json",
        body=json.dumps({"detail": "could not connect to the source"}),
    ))

    mod = synced["mod"]
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=synced["connection"]["name"])
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Scheduled sync").click()

    expect(page.get_by_text("could not connect to the source")).to_be_visible()
    expect(page.get_by_role("button", name="Save schedule")).to_be_disabled()


def test_the_start_value_typed_in_is_the_one_that_is_stored(page, synced) -> None:
    """**p.175's initial value, end to end.** Without it, converting a table
    that is already loaded re-reads all of it on the first run."""
    assert schedule_of(synced)["sync_last_cursor_value"] is None

    open_sync_panel(page, synced)
    # It opens empty, and that matters as much as what typing into it does: a
    # box that arrived carrying a value would send that value on every save,
    # including saves that were about something else entirely.
    expect(page.get_by_test_id("cursor-start")).to_have_value("")
    page.get_by_test_id("cursor-start").fill("2000")
    page.get_by_role("button", name="Save schedule").click()
    expect(page.get_by_test_id("cursor-position")).to_contain_text("2000")

    assert schedule_of(synced)["sync_last_cursor_value"] == "2000"


def test_saving_again_with_the_box_empty_keeps_the_position(page, synced) -> None:
    """The decision the field turns on, seen from the screen: the box is not
    pre-filled with where the sync got to, and leaving it empty is not a
    request to re-read the table."""
    open_sync_panel(page, synced)
    page.get_by_test_id("cursor-start").fill("2000")
    page.get_by_role("button", name="Save schedule").click()
    expect(page.get_by_test_id("cursor-position")).to_contain_text("2000")

    # The box is empty again on the next render — it says "start here", not
    # "here is where you are".
    expect(page.get_by_test_id("cursor-start")).to_have_value("")
    page.get_by_role("button", name="Save schedule").click()
    expect(page.get_by_test_id("cursor-position")).to_contain_text("2000")
    assert schedule_of(synced)["sync_last_cursor_value"] == "2000"


def test_the_position_can_be_forgotten_from_the_page(page, synced) -> None:
    """**p.176's remedy, reachable.** `run_incremental_sync` has always told
    people to "clear the schedule's stored cursor and run a full sync first",
    and until §363 there was no way to do it — an error naming a button nobody
    had."""
    open_sync_panel(page, synced)
    page.get_by_test_id("cursor-start").fill("2000")
    page.get_by_role("button", name="Save schedule").click()
    expect(page.get_by_test_id("forget-cursor")).to_be_visible()

    page.get_by_test_id("forget-cursor").click()
    expect(page.get_by_test_id("cursor-position")).to_have_count(0)
    assert schedule_of(synced)["sync_last_cursor_value"] is None

    # And the sync is still configured — forgetting a position is not
    # unconfiguring the sync.
    after = schedule_of(synced)
    assert after["sync_source_table"] == "orders"
    assert after["sync_cursor_column"] == "id"


def test_nothing_offers_to_forget_a_position_that_does_not_exist(page, synced) -> None:
    """§214: a control for a state the sync is not in. A fresh incremental sync
    has nowhere to carry on from, so there is nothing to forget."""
    open_sync_panel(page, synced)
    expect(page.get_by_test_id("cursor-start")).to_be_visible()
    expect(page.get_by_test_id("forget-cursor")).to_have_count(0)
    expect(page.get_by_test_id("cursor-position")).to_have_count(0)
