"""A version's transaction type on the History tab (§747; Foundry
`data-integration` p.22-26).

> "Because a new view only begins at a SNAPSHOT transaction, the number of
>  views in a dataset's history is equal to the number of SNAPSHOT
>  transactions it contains." (p.26)

Which writer stores which type is `apps/api/tests/test_transaction_types.py`'s,
and where views begin is `apps/web/src/lib/dataset-transactions.test.ts`'.
What needs a browser is that the History tab shows both on the rows they
belong to.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import WEB_BASE


def test_the_history_says_each_versions_type_and_where_views_begin(page, api) -> None:
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call("POST", f"/workspaces/{workspace['id']}/projects",
                       {"name": f"Txn {tag}", "slug": f"txn-{tag}"})
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    dataset = api.upload_csv(f"{base}/datasets/upload", f"Txn {tag}", b"id,val\n1,10\n")
    did = dataset["id"]
    # `upload_csv` sends a name field too, which the files route ignores.
    api.upload_csv(f"{base}/datasets/{did}/files", "", b"id,val\n2,20\n", filename="more.csv")
    api.upload_csv(f"{base}/datasets/{did}/files", "", b"id,val\n3,30\n", filename="seed.csv")
    resource = next(r for r in api.call("GET", f"{base}/resources")["resources"]
                    if r["name"] == dataset["name"])

    page.goto(f"{WEB_BASE}/r/{resource['id']}?tab=history")
    row = lambda n: page.locator(f"[data-testid='transaction'][data-version='{n}']")  # noqa: E731
    expect(row(1)).to_have_text("SNAPSHOT · new view")
    expect(row(2)).to_have_text("APPEND")
    expect(row(3)).to_have_text("UPDATE")
    expect(row(2)).to_have_attribute(
        "title", "Rows added to the view before it; no row of that view changed.")
    expect(page.get_by_test_id("current-view")).to_have_text(
        "This dataset has one view. The current one runs from v1 to v3.")

    # A re-parse reads every row again: a new view.
    api.call("POST", f"{base}/datasets/{did}/parse", {"add_row_number": True})
    page.reload()
    expect(row(4)).to_have_text("SNAPSHOT · new view")
    expect(page.get_by_test_id("current-view")).to_have_text(
        "This dataset has 2 views. The current one is v4 alone.")
