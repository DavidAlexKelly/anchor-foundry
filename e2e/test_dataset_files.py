"""Uploading a file into a dataset that already exists (§746; `dataset-preview`
p.10-11).

> "If the filename and schema of the new file are identical to a previous
>  upload, you can update data in the existing dataset. If the filename is
>  different from previous uploads, you can append data to an existing
>  dataset." (p.10)

> "Drag and drop the file into the dataset preview window." (p.11)

What each kind of file does to the rows is `apps/api/tests/test_dataset_files.py`'s,
and the sentences are `apps/web/src/lib/dataset-files.test.ts`'. What needs a
browser is that the preview tab says which of p.10's two it will be before
the press, and that the table it is on changes after it.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

SEED = b"id,val\n1,10\n2,20\n"


@pytest.fixture()
def uploaded(api):
    """An uploaded dataset of one file, `seed.csv`, in a project of its own:
    these tests change it."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Files {tag}", "slug": f"files-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    dataset = api.upload_csv(f"{base}/datasets/upload", f"Files {tag}", SEED)
    resources = api.call("GET", f"{base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == dataset["name"])
    return {"base": base, "dataset_id": dataset["id"], "resource_id": resource["id"], "api": api}


def open_preview(page, fixture) -> None:
    page.goto(f"{WEB_BASE}/r/{fixture['resource_id']}?tab=preview")
    expect(page.get_by_text("All 2 rows.")).to_be_visible(timeout=30000)


def pick(page, name: str, body: bytes) -> None:
    page.get_by_test_id("file-upload-input").set_input_files(
        {"name": name, "mimeType": "text/csv", "buffer": body})


def current(fixture) -> dict:
    return fixture["api"].call("GET", f"{fixture['base']}/datasets/{fixture['dataset_id']}")


def test_a_new_name_says_it_adds_and_the_table_grows(page, uploaded) -> None:
    open_preview(page, uploaded)
    expect(page.get_by_test_id("file-upload-panel")).to_have_count(0)
    pick(page, "february.csv", b"id,val\n3,30\n")
    panel = page.get_by_test_id("file-upload-panel")
    expect(page.get_by_test_id("file-intent")).to_have_text(
        "Adds february.csv beside seed.csv. Its columns must be the same as theirs.")
    expect(page.get_by_test_id("file-upload-confirm")).to_have_text("Add")
    page.get_by_test_id("file-upload-confirm").click()
    expect(page.get_by_test_id("file-uploaded")).to_contain_text(
        "Added february.csv. The dataset is version 2, 3 rows.")
    expect(page.get_by_text("All 3 rows.")).to_be_visible()
    expect(panel.locator("xpath=..").locator("table")).to_contain_text("30")
    assert current(uploaded)["current_version"] == 2

    # The re-parse panel names every file it will read.
    page.get_by_test_id("parse-again").click()
    expect(page.get_by_test_id("parse-files")).to_have_text("seed.csv, february.csv")

    page.goto(f"{WEB_BASE}/r/{uploaded['resource_id']}?tab=details")
    expect(page.get_by_test_id("ds-file")).to_have_count(2)
    expect(page.get_by_test_id("ds-file").nth(1)).to_contain_text("february.csv — v2")
    expect(page.get_by_test_id("ds-made-by")).to_contain_text("uploaded as february.csv")


def test_the_same_name_says_it_replaces_and_the_rows_are_the_new_ones(page, uploaded) -> None:
    open_preview(page, uploaded)
    pick(page, "seed.csv", b"id,val\n7,70\n")
    expect(page.get_by_test_id("file-intent")).to_have_text(
        "Replaces seed.csv with this file. Its columns must be the same as the one it replaces.")
    expect(page.get_by_test_id("file-upload-panel")).to_have_attribute("data-mode", "update")
    page.get_by_test_id("file-upload-confirm").filter(has_text="Replace").click()
    expect(page.get_by_test_id("file-uploaded")).to_contain_text("Replaced seed.csv.")
    expect(page.get_by_text("All 1 rows.")).to_be_visible()
    expect(page.locator("table")).to_contain_text("70")
    expect(page.locator("table")).not_to_contain_text("20")


def test_other_columns_are_refused_in_the_servers_words(page, uploaded) -> None:
    open_preview(page, uploaded)
    pick(page, "seed.csv", b"id,label\n1,x\n")
    page.get_by_test_id("file-upload-confirm").click()
    expect(page.get_by_test_id("file-upload-error")).to_contain_text(
        "seed.csv is already in this dataset, whose files read as")
    expect(page.get_by_test_id("file-uploaded")).to_have_count(0)
    assert current(uploaded)["current_version"] == 1


def test_a_file_of_another_kind_cannot_be_sent(page, uploaded) -> None:
    open_preview(page, uploaded)
    pick(page, "more.jsonl", b'{"id": 3, "val": 30}\n')
    expect(page.get_by_test_id("file-intent")).to_have_text(
        "This dataset's files are .csv files, so more.jsonl cannot join them.")
    expect(page.get_by_test_id("file-upload-confirm")).to_be_disabled()
    page.get_by_test_id("file-upload-cancel").click()
    expect(page.get_by_test_id("file-upload-panel")).to_have_count(0)
    assert current(uploaded)["current_version"] == 1


def test_a_file_dropped_on_the_preview_is_picked(page, uploaded) -> None:
    """p.11's drag and drop, into the preview window."""
    open_preview(page, uploaded)
    transfer = page.evaluate_handle("""() => {
        const dt = new DataTransfer();
        dt.items.add(new File(["id,val\\n9,90\\n"], "march.csv", { type: "text/csv" }));
        return dt;
    }""")
    page.get_by_test_id("ds-drop").dispatch_event("dragover", {"dataTransfer": transfer})
    expect(page.get_by_test_id("ds-drop")).to_have_class("ds-drop on")
    page.get_by_test_id("ds-drop").dispatch_event("drop", {"dataTransfer": transfer})
    expect(page.get_by_test_id("ds-drop")).to_have_class("ds-drop")
    expect(page.get_by_test_id("file-intent")).to_contain_text("Adds march.csv beside seed.csv.")
    page.get_by_test_id("file-upload-confirm").click()
    expect(page.get_by_text("All 3 rows.")).to_be_visible()


def test_somebody_who_may_not_edit_is_offered_no_upload(viewer_page, uploaded) -> None:
    open_preview(viewer_page, uploaded)
    expect(viewer_page.get_by_test_id("file-upload")).to_have_count(0)
    # Nor does a drop do anything.
    transfer = viewer_page.evaluate_handle("""() => {
        const dt = new DataTransfer();
        dt.items.add(new File(["id,val\\n9,90\\n"], "march.csv", { type: "text/csv" }));
        return dt;
    }""")
    viewer_page.get_by_test_id("ds-drop").dispatch_event("drop", {"dataTransfer": transfer})
    expect(viewer_page.get_by_test_id("file-upload-panel")).to_have_count(0)


def test_an_old_version_is_offered_no_upload(page, uploaded) -> None:
    """Time travel reads the past; a file goes into the dataset as it is now."""
    uploaded["api"].call("POST", f"{uploaded['base']}/datasets/{uploaded['dataset_id']}/parse",
                         {"add_row_number": True})
    page.goto(f"{WEB_BASE}/r/{uploaded['resource_id']}?tab=preview&version=1")
    expect(page.get_by_text("All 2 rows.")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("file-upload")).to_have_count(0)
    page.goto(f"{WEB_BASE}/r/{uploaded['resource_id']}?tab=preview")
    expect(page.get_by_test_id("file-upload")).to_be_visible(timeout=30000)


def test_the_parse_panel_opens_on_the_options_the_dataset_is_read_with(page, uploaded) -> None:
    """p.24's options are stored with the dataset (§746), so the panel starts
    from the read that is on screen rather than from the defaults."""
    uploaded["api"].call("POST", f"{uploaded['base']}/datasets/{uploaded['dataset_id']}/parse",
                         {"delimiter": ";", "null_values": ["NA", "-"], "add_row_number": True})
    page.goto(f"{WEB_BASE}/r/{uploaded['resource_id']}?tab=preview")
    page.get_by_test_id("parse-again").click()
    expect(page.get_by_test_id("parse-delimiter")).to_have_value(";")
    expect(page.get_by_test_id("parse-nulls")).to_have_value("NA\n-")
    expect(page.get_by_test_id("parse-add_row_number")).to_be_checked()
    expect(page.get_by_test_id("parse-add_file_path")).not_to_be_checked()
