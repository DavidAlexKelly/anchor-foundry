"""The size of the table, on the Details tab (§509; `dataset-preview` p.3).

    "About: Information including … the size of the table …" (p.3)

The wording is `apps/web/src/lib/dataset-size.test.ts`. What needs a browser
is that the number is the current version's as the History tab measures it,
and that a file gone from storage is said to be gone rather than shown as
nothing.
"""
from __future__ import annotations

import os

import psycopg
from playwright.sync_api import expect

from api import Module
from conftest import ADMIN_DSN, WEB_BASE

STORAGE_ROOT = os.environ.get("STORAGE_ROOT", "/tmp/anchor-storage")


def bytes_text(n: int) -> str:
    """`lib/bytes.ts`'s wording, so the check does not depend on how big a
    small parquet file happens to be."""
    if n < 1024:
        return f"{n} B"
    value, units, i = n / 1024, ["KB", "MB", "GB", "TB"], 0
    while value >= 1024 and i < len(units) - 1:
        value, i = value / 1024, i + 1
    return f"{value:.1f} {units[i]}" if value < 10 else f"{round(value)} {units[i]}"


def test_the_details_tab_says_columns_and_bytes(page, api) -> None:
    mod = Module(api, "Size")
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"sized_{mod.tag}",
                              b"id,total,note\n1,10,a\n2,20,b\n")
    resources = mod.api.call("GET", f"{mod.base}/resources")["resources"]
    rid = next(r for r in resources if r["name"] == made["name"] and r["kind"] == "dataset")["id"]
    [version] = mod.api.call("GET", f"{mod.base}/datasets/{made['id']}/versions")["items"]

    page.goto(f"{WEB_BASE}/r/{rid}?tab=details")
    size = page.get_by_test_id("ds-size")
    expect(size).to_have_text(f"3 columns · {bytes_text(version['size_bytes'])} in storage",
                              timeout=30000)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        key = conn.execute("SELECT s3_manifest_key FROM dataset_versions WHERE id = %s",
                           (version["id"],)).fetchone()[0]
    os.remove(os.path.join(STORAGE_ROOT, key))
    page.reload()
    expect(page.get_by_test_id("ds-size")).to_have_text(
        "3 columns · not measured: its file is not in storage", timeout=30000)
