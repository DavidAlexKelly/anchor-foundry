"""p.195-196's transactional export modes, chosen in the form (§748;
`data-connection` p.195-196; decision 0020 §4).

What each mode sends is the API's tests'. What needs a browser is that the
picker offers them, and that the history says what each run sent, since two
green runs no longer mean the same thing.
"""
from __future__ import annotations

import uuid

import psycopg
from playwright.sync_api import expect

from test_exports import (  # noqa: F401 (fixtures)
    DEST_DB, _dsn, a_warehouse, module, open_connections, warehouse,
)


def test_efficient_mirror_sends_an_appends_rows_and_the_history_says_so(
    page, api, module, warehouse
) -> None:
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS public.orders_txn")
        conn.execute("CREATE TABLE public.orders_txn (id bigint, email text)")
        conn.execute("GRANT ALL ON public.orders_txn TO export_e2e_user")
    a_warehouse(api, module, warehouse, enabled=True)
    made = api.upload_csv(f"{module.base}/datasets/upload", name=f"txn_{uuid.uuid4().hex[:6]}",
                          csv=b"id,email\n1,ada@example.com\n2,grace@example.com\n")

    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    panel.get_by_test_id("new-export").click()
    page.get_by_test_id("export-dataset").select_option(label=made["name"])
    name = f"Mirror {uuid.uuid4().hex[:4]}"
    page.get_by_test_id("export-name").fill(name)
    page.get_by_test_id("export-schema").fill("public")
    page.get_by_test_id("export-table").fill("orders_txn")
    mode = page.get_by_test_id("export-mode")
    expect(mode.locator("option")).to_have_count(6)
    mode.select_option("efficient_mirror")
    page.get_by_test_id("export-save").click()
    expect(panel.get_by_test_id("exports-table")).to_contain_text(
        "mirrors into public.orders_txn", timeout=15000)

    panel.get_by_test_id(f"run-export-{name}").click()
    expect(panel.get_by_test_id(f"export-state-{name}")).to_contain_text("up to date", timeout=30000)
    # p.10's new file: an APPEND, whose one row is all the next run sends.
    api.upload_csv(f"{module.base}/datasets/{made['id']}/files", name="",
                   csv=b"id,email\n3,alan@example.com\n", filename="more.csv")
    page.reload()
    expect(panel.get_by_test_id(f"export-state-{name}")).to_have_text("one version behind",
                                                                      timeout=30000)
    panel.get_by_test_id(f"run-export-{name}").click()
    expect(panel.get_by_test_id(f"export-state-{name}")).to_contain_text("up to date (v2)",
                                                                         timeout=30000)

    row = panel.get_by_test_id("exports-table").locator("tbody tr").filter(has_text=name)
    row.get_by_role("button", name="History").click()
    details = page.get_by_test_id("export-run-detail")
    expect(details).to_have_text([
        "sent the rows v2 added", "cleared the table, then sent the whole view at v1"])
    expect(page.get_by_test_id("export-runs").locator("tbody tr").first).to_contain_text("1 row")
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        assert [r[0] for r in conn.execute(
            "SELECT id FROM public.orders_txn ORDER BY id").fetchall()] == [1, 2, 3]


def test_a_run_that_outlasts_its_request_is_followed_to_its_end(
    page, api, module, warehouse
) -> None:
    """§968. A run the API is still doing when it has to answer comes back as
    a 202 with its row, running; the panel says so, will not start another,
    and settles once the history has it ended.

    Made to outlast its request in the browser rather than the API: the
    answer is rewritten into the one a long run gives, and the history holds
    the run as running until the test lets it end."""
    connection = a_warehouse(api, module, warehouse, enabled=True)
    made = api.upload_csv(f"{module.base}/datasets/upload", name=f"slow_{uuid.uuid4().hex[:6]}",
                          csv=b"id,email\n1,ada@example.com\n")
    name = f"Slow {uuid.uuid4().hex[:4]}"
    api.call("POST", f"{module.base}/exports", {
        "connection_id": connection["id"], "dataset_id": made["id"], "name": name,
        "mode": "mirror", "destination": {"schema": "public", "table": "orders"}})

    def long_answer(route) -> None:
        answer = route.fetch().json()
        route.fulfill(status=202, json={**answer, "status": "running", "rows_written": 0,
                                        "finished_at": None})

    released: list[bool] = []

    def history(route) -> None:
        page_of_runs = route.fetch().json()
        if not released:
            page_of_runs["runs"] = [{**run, "status": "running", "finished_at": None}
                                    for run in page_of_runs["runs"]]
        route.fulfill(json=page_of_runs)

    page.route("**/exports/*/run", long_answer)
    page.route("**/exports/*/runs?*", history)
    page.route("**/exports/*/runs", history)
    open_connections(page, module)
    panel = page.get_by_test_id("exports-panel")
    panel.get_by_test_id(f"run-export-{name}").click()
    expect(panel.get_by_test_id("export-running")).to_contain_text("Still running",
                                                                   timeout=30000)
    expect(panel.get_by_test_id(f"run-export-{name}")).to_be_disabled()
    expect(panel.get_by_test_id(f"run-export-{name}")).to_have_text("Running…")

    released.append(True)
    expect(panel.get_by_test_id("export-running")).to_have_count(0, timeout=15000)
    expect(panel.get_by_test_id(f"run-export-{name}")).to_have_text("Run")
    expect(panel.get_by_test_id(f"export-state-{name}")).to_contain_text("up to date",
                                                                         timeout=15000)
