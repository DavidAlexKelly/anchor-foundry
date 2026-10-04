"""A file sync set up and run from the connections page (§751; decision 0021;
`data-connection` p.160-164).

What a run takes and writes is the API's and worker's tests'
(`apps/api/tests/test_file_syncs.py`, `apps/worker/tests/test_s3_sync_configs.py`),
and the form's sentences are `apps/web/src/lib/file-sync-form.test.ts`'. What
needs a browser is that the dialog offers a folder for an S3 source and
nowhere else, that p.160's modes are chosen by name, and that a run says
which files it took.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

pytest.importorskip("moto", reason="moto not installed")
import boto3  # noqa: E402

BUCKET = "anchor-e2e-files"
REGION = "eu-north-1"
KEY, SECRET = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.fixture(scope="module")
def s3():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, "-m", "moto.server", "-p", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    endpoint = f"http://127.0.0.1:{port}"
    client = boto3.client("s3", endpoint_url=endpoint, region_name=REGION,
                          aws_access_key_id=KEY, aws_secret_access_key=SECRET)
    client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
    yield client, endpoint
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def module(api):
    return Module(api, "File syncs")


def a_bucket_source(api, module, endpoint: str) -> dict:
    return api.call("POST", f"{module.base}/connections", {
        "name": f"Drops {uuid.uuid4().hex[:6]}", "source_type": "s3",
        "config": {"bucket": BUCKET, "prefix": "in/", "region": REGION, "endpoint_url": endpoint},
        "secret": {"access_key_id": KEY, "secret_access_key": SECRET}})


def open_schedule(page, module, name: str):
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/{module.project_slug}/connections")
    row = page.locator("tr").filter(has_text=name).first
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Scheduled sync").click()
    return page.locator("dialog.dialog").filter(has_text="Scheduled sync").last


def test_an_append_file_sync_is_set_in_the_form_and_takes_only_new_files(
    page, api, module, s3
) -> None:
    client, endpoint = s3
    folder = f"daily-{uuid.uuid4().hex[:6]}"
    client.put_object(Bucket=BUCKET, Key=f"in/{folder}/a.csv", Body=b"id,v\n1,a\n")
    source = a_bucket_source(api, module, endpoint)

    dialog = open_schedule(page, module, source["name"])
    dialog.get_by_test_id("sync-mode").select_option("files")
    dialog.get_by_test_id("file-folder").fill(folder)
    dialog.get_by_test_id("file-ingestion").select_option("append")
    # How a change is seen is an UPDATE's question only.
    expect(dialog.get_by_test_id("file-by-modified")).to_have_count(0)
    expect(dialog.get_by_test_id("file-ingestion-says")).to_have_text(
        "Every run takes only files it has not taken before, and adds them to the dataset.")
    dialog.get_by_label("Cron schedule").fill("")
    dialog.get_by_role("button", name="Save schedule").click()
    expect(dialog.get_by_test_id("sync-configured")).to_have_text(
        f"Incremental mirror (APPEND) of the files in {folder}/ - no cron, run manually "
        "with the button below", timeout=15000)

    dialog.get_by_role("button", name="Run now").click()
    expect(dialog.get_by_test_id("sync-result")).to_contain_text("Took 1 file: a.csv.",
                                                                 timeout=30000)
    client.put_object(Bucket=BUCKET, Key=f"in/{folder}/b.csv", Body=b"id,v\n2,b\n")
    dialog.get_by_role("button", name="Run now").click()
    expect(dialog.get_by_test_id("sync-result")).to_contain_text("Took 1 file: b.csv.",
                                                                 timeout=30000)
    expect(dialog.get_by_test_id("sync-result")).to_contain_text("v2")

    # Reopened, the form says what was saved.
    page.reload()
    dialog = open_schedule(page, module, source["name"])
    expect(dialog.get_by_test_id("sync-mode")).to_have_value("files")
    expect(dialog.get_by_test_id("file-folder")).to_have_value(folder)
    expect(dialog.get_by_test_id("file-ingestion")).to_have_value("append")


def test_an_update_sync_must_be_able_to_see_a_change(page, api, module, s3) -> None:
    _client, endpoint = s3
    source = a_bucket_source(api, module, endpoint)
    dialog = open_schedule(page, module, source["name"])
    dialog.get_by_test_id("sync-mode").select_option("files")
    dialog.get_by_test_id("file-ingestion").select_option("update")
    dialog.get_by_test_id("file-by-modified").uncheck()
    dialog.get_by_role("button", name="Save schedule").click()
    expect(dialog.get_by_test_id("file-sync-problem")).to_contain_text(
        "needs a way to see a file change")
    dialog.get_by_test_id("file-filters").locator("summary").click()
    dialog.get_by_test_id("file-limit").fill("0")
    dialog.get_by_test_id("file-by-size").check()
    dialog.get_by_role("button", name="Save schedule").click()
    expect(dialog.get_by_test_id("file-sync-problem")).to_have_text(
        "The file limit is a whole number of at least 1.")
    dialog.get_by_test_id("file-limit").fill("10")
    dialog.get_by_role("button", name="Save schedule").click()
    expect(dialog.get_by_test_id("sync-configured")).to_contain_text(
        "Incremental mirror with changes (UPDATE) of the files in the prefix's root",
        timeout=15000)
    saved = api.call("GET", f"{module.base}/connections/{source['id']}/scheduled-sync")
    assert saved["sync_file_filters"] == {
        "exclude_synced": {"by_modified": False, "by_size": True}, "limit": 10}


def test_a_database_source_offers_no_folder(page, api, module) -> None:
    source = api.call("POST", f"{module.base}/connections", {
        "name": f"Warehouse {uuid.uuid4().hex[:6]}", "source_type": "postgres",
        "config": {"host": "localhost", "port": 5432, "database": "x", "user": "y"},
        "secret": {"password": "z"}})
    dialog = open_schedule(page, module, source["name"])
    expect(dialog.get_by_test_id("sync-mode").locator("option")).to_have_count(2)
