"""Parsing an uploaded file again (parity `datasets-lineage.md` §1.2/§1.4;
Foundry `dataset-preview` p.14, p.24).

> "CSV schemas can be manipulated in the Edit Schema UI, available from Dataset
>  Preview when viewing the preview tab. This will help visualize the options
>  available and how they affect the output dataset." (p.24)

What each option does to a file is `apps/api/tests/test_dataset_parsing.py`'s,
and the wording of what Apply will do is
`apps/web/src/lib/parse-options.test.ts`'s. What needs a browser is p.24's own
claim: that you can **see the effect before choosing it**, and that choosing it
changes the table you were looking at.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE

#: `^` is not in DuckDB's delimiter candidate set, so this uploads as a single
#: column called `id^val` — a dataset that looks fine and is not, which is the
#: case the panel exists for.
CARETS = b"id^val\n1^10\n2^20\n"


@pytest.fixture()
def wrongly_parsed(api):
    """A dataset whose upload parsed badly, in a project of its own.

    Function-scoped because these tests *change* the dataset; a shared one
    would make each test's starting point depend on which ran first.
    """
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Parsing {tag}", "slug": f"parsing-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    dataset = api.upload_csv(f"{base}/datasets/upload", f"Carets {tag}", CARETS)
    assert [c["name"] for c in dataset["table_schema"]] == ["id^val"], dataset["table_schema"]

    resources = api.call("GET", f"{base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == dataset["name"])
    return {"tag": tag, "base": base, "dataset_id": dataset["id"],
            "resource_id": resource["id"], "api": api}


def open_preview(page, fixture) -> None:
    page.goto(f"{WEB_BASE}/r/{fixture['resource_id']}?tab=preview")
    expect(page.get_by_test_id("parse-again")).to_be_visible(timeout=30000)


def dataset(fixture) -> dict:
    return fixture["api"].call(
        "GET", f"{fixture['base']}/datasets/{fixture['dataset_id']}"
    )


def test_the_options_are_where_the_bad_parse_is(page, wrongly_parsed) -> None:
    """p.24 puts this on the preview tab, which is where somebody is looking at
    the parse that went wrong."""
    open_preview(page, wrongly_parsed)
    expect(page.get_by_test_id("parse-panel")).to_have_count(0)
    page.get_by_test_id("parse-again").click()
    expect(page.get_by_test_id("parse-panel")).to_be_visible()
    expect(page.get_by_test_id("parse-panel")).to_contain_text("seed.csv")


def test_a_preview_shows_the_effect_without_choosing_it(page, wrongly_parsed) -> None:
    """**p.24's whole claim.** The rehearsal shows two columns; the dataset is
    still the one-column mistake until Apply is pressed."""
    open_preview(page, wrongly_parsed)
    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-delimiter").fill("^")
    page.get_by_test_id("parse-preview").click()

    result = page.get_by_test_id("parse-result")
    expect(result).to_be_visible()
    expect(result).to_contain_text("2 rows, 2 columns")

    after = dataset(wrongly_parsed)
    assert [c["name"] for c in after["table_schema"]] == ["id^val"], "nothing written"
    assert after["current_version"] == 1


def test_apply_waits_for_a_preview(page, wrongly_parsed) -> None:
    """A re-parse writes a version, and p.24's arrangement is that you see the
    effect first. Enabled is asserted after the rehearsal, so the disabled
    state is a state and not a permanently dead button."""
    open_preview(page, wrongly_parsed)
    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-delimiter").fill("^")
    expect(page.get_by_test_id("parse-apply")).to_be_disabled()

    page.get_by_test_id("parse-preview").click()
    expect(page.get_by_test_id("parse-result")).to_be_visible()
    expect(page.get_by_test_id("parse-apply")).to_be_enabled()


def test_changing_a_field_after_previewing_takes_the_rehearsal_away(
    page, wrongly_parsed
) -> None:
    """A preview table sitting under options it was not produced from is the
    one thing this panel must not show — it would be a rehearsal of a parse
    nobody is about to run."""
    open_preview(page, wrongly_parsed)
    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-delimiter").fill("^")
    page.get_by_test_id("parse-preview").click()
    expect(page.get_by_test_id("parse-result")).to_be_visible()

    page.get_by_test_id("parse-add_row_number").check()
    expect(page.get_by_test_id("parse-result")).to_have_count(0)
    expect(page.get_by_test_id("parse-apply")).to_be_disabled()


def test_the_panel_says_what_apply_will_do(page, wrongly_parsed) -> None:
    """The difference between two parses can be invisible in a hundred rows —
    a null marker retypes a column and the rows look the same — so the panel
    says it in words, from the options rather than from the preview."""
    open_preview(page, wrongly_parsed)
    page.get_by_test_id("parse-again").click()
    expect(page.get_by_test_id("parse-summary")).to_have_count(0)

    page.get_by_test_id("parse-delimiter").fill("^")
    page.get_by_test_id("parse-add_row_number").check()
    summary = page.get_by_test_id("parse-summary")
    expect(summary).to_contain_text('fields split on "^"')
    expect(summary).to_contain_text("row number")


def test_applying_changes_the_table_that_was_being_read(page, wrongly_parsed) -> None:
    """**The assertion the panel exists for.** The preview tab was showing one
    column; after Apply it shows two, without a reload."""
    open_preview(page, wrongly_parsed)
    expect(page.locator("table.ds-table thead th")).to_have_count(1)

    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-delimiter").fill("^")
    page.get_by_test_id("parse-preview").click()
    expect(page.get_by_test_id("parse-result")).to_be_visible()
    page.get_by_test_id("parse-apply").click()

    # The panel closes on success and the table underneath is the new parse.
    expect(page.get_by_test_id("parse-panel")).to_have_count(0)
    expect(page.locator("table.ds-table thead th")).to_have_count(2)

    after = dataset(wrongly_parsed)
    assert after["current_version"] == 2
    assert [c["name"] for c in after["table_schema"]] == ["id", "val"]


def test_a_file_read_the_wrong_way_says_so_rather_than_failing_quietly(
    page, wrongly_parsed
) -> None:
    """An encoding the file is not is refused by the server, and the panel puts
    the refusal where the options were typed."""
    open_preview(page, wrongly_parsed)
    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-encoding").select_option("utf-16")
    page.get_by_test_id("parse-preview").click()
    expect(page.get_by_test_id("parse-error")).to_be_visible()
    expect(page.get_by_test_id("parse-apply")).to_be_disabled()


def test_the_null_markers_box_reaches_the_parse(page, wrongly_parsed) -> None:
    """**The textarea is wired to the request, not only to a pure function.**

    `parseNullMarkers` is unit-tested and the server's `nullstr` is
    API-tested; what neither can say is that the box on screen is what the
    request carries. The mutation sweep found exactly this gap — a build that
    sent `null_values: []` whatever was typed passed every other test here.

    `NA` in a numeric column is the case that makes it visible: without the
    marker both columns stay text, and with it they become numbers and the
    value reads as empty.
    """
    dataset = wrongly_parsed["api"].upload_csv(
        f"{wrongly_parsed['base']}/datasets/upload",
        f"Markers {wrongly_parsed['tag']}", b"id^val\n1^NA\n2^20\n",
    )
    resources = wrongly_parsed["api"].call(
        "GET", f"{wrongly_parsed['base']}/resources"
    )["resources"]
    resource = next(r for r in resources if r["name"] == dataset["name"])

    page.goto(f"{WEB_BASE}/r/{resource['id']}?tab=preview")
    expect(page.get_by_test_id("parse-again")).to_be_visible(timeout=30000)
    page.get_by_test_id("parse-again").click()
    page.get_by_test_id("parse-delimiter").fill("^")
    page.get_by_test_id("parse-nulls").fill("NA")
    page.get_by_test_id("parse-preview").click()

    result = page.get_by_test_id("parse-result")
    expect(result).to_be_visible()
    # The first row's `val` is null because "NA" was named, not because the
    # file changed — the row is there and the value is not. The table draws a
    # null as the word rather than as a blank cell (`.ds-null`), which is the
    # distinction this assertion depends on: an empty cell and a null are
    # different answers.
    first_val = result.locator("tbody tr").first.locator("td").nth(1)
    expect(first_val.locator(".ds-null")).to_have_count(1)
    # And the row after it still has its value, so this is one cell becoming
    # null rather than the whole column being dropped.
    expect(result.locator("tbody tr").nth(1).locator("td").nth(1)).to_have_text("20")


def test_a_dataset_nothing_uploaded_is_not_offered_the_panel(page, api) -> None:
    """`whyNotParseable`'s first case, on screen: a model output has no
    uploaded file, so the control is absent rather than present-and-failing."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Built {tag}", "slug": f"built-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"Src {tag}", b"id,val\n1,10\n")
    model = api.call("POST", f"{base}/models", {
        "name": f"Copy {tag}", "code": "SELECT * FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    run = api.call("POST", f"{base}/models/{model['id']}/run")
    output = run["output_dataset"]["id"]
    name = api.call("GET", f"{base}/datasets/{output}")["name"]
    resources = api.call("GET", f"{base}/resources")["resources"]
    resource = next(r for r in resources if r["name"] == name)

    page.goto(f"{WEB_BASE}/r/{resource['id']}?tab=preview")
    # §318: wait for something that *is* there before asserting an absence.
    expect(page.locator("table.ds-table thead th").first).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("parse-again")).to_have_count(0)
