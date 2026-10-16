"""A table sync that outlasts its request, from the connections page (§967).

What the API answers is `apps/api/tests/test_sync_outlasts_request.py`'s, and
the wording `apps/web/src/lib/sync-progress.test.ts`'. What needs a browser is
that the Sync dialog follows the run it was answered with until the history
has it ended, and then says what it did - rather than the 504 it used to show
while the sync went on and finished.

Made to outlast its request in the browser rather than the API: the answer is
rewritten into the one a long sync gives, and the history holds the run as
running until the test lets it end.
"""
from __future__ import annotations

import uuid

import psycopg
from playwright.sync_api import expect

from conftest import WEB_BASE
from test_exports import DEST_DB, _dsn, a_warehouse, module, warehouse  # noqa: F401 (fixtures)


def test_a_sync_that_outlasts_its_request_is_followed_to_its_end(page, api, module,
                                                                warehouse) -> None:
    with psycopg.connect(_dsn(DEST_DB), autocommit=True) as conn:
        conn.execute("DELETE FROM public.orders")
        conn.execute("INSERT INTO public.orders VALUES (1, 'ada@example.com'),"
                     " (2, 'grace@example.com')")
    source = a_warehouse(api, module, warehouse, enabled=False)
    name = f"Long orders {uuid.uuid4().hex[:6]}"

    def long_answer(route) -> None:
        answer = route.fetch().json()
        route.fulfill(status=202, json={**answer, "ok": None, "running": True,
                                        "rows_synced": 0, "dataset": None})

    released: list[bool] = []

    def history(route) -> None:
        runs = route.fetch().json()
        if not released:
            runs = [{**run, "status": "running", "finished_at": None} for run in runs]
        route.fulfill(json=runs)

    page.route(f"**/connections/{source['id']}/sync", long_answer)
    page.route(f"**/connections/{source['id']}/sync-runs", history)
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/connections")
    row = page.locator("tr").filter(has_text=source["name"]).first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Sync", exact=True).click()
    dialog = page.locator("dialog.dialog").filter(has_text="Sync from").last
    dialog.locator("select").first.select_option(label="public/orders (2 columns)")
    dialog.get_by_label("Dataset name").fill(name)
    dialog.get_by_role("button", name="Sync now").click()

    expect(dialog.get_by_test_id("sync-running")).to_contain_text("Still syncing",
                                                                  timeout=30000)
    released.append(True)
    expect(dialog.get_by_test_id("sync-result")).to_have_text(
        f"Synced 2 rows into the dataset {name}.", timeout=15000)
