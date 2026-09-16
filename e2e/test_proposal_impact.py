"""What a proposal changes, on the review surface (parity
`code-repositories.md` §4.1; Foundry `code-repositories` p.52-55).

> "The Impact analysis tab provides information on datasets affected by the
>  pull request. By default, it will only show **directly affected**
>  datasets." (p.53)

§4.1 calls this the largest single gap in that file: "ours reviews text;
Foundry reviews the consequences of text."

`apps/api/tests/test_proposal_impact.py` owns which datasets a proposal
affects and the three states a file can be in;
`apps/web/src/lib/proposal-impact.test.ts` owns the wording. What needs a
browser is the claim neither can make: that a reviewer opening the proposal is
**told what it changes before reading any code**.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


def open_review(page, mod: Module, proposal_id: str) -> None:
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/models"
        f"?proposal={proposal_id}"
    )
    expect(page.get_by_test_id("impact-panel")).to_be_visible(timeout=30000)


def built_model(mod: Module, source: dict, name: str) -> dict:
    model = mod.api.call("POST", f"{mod.base}/models", {
        "name": name, "code": "SELECT id, val FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    mod.api.call("POST", f"{mod.base}/models/{model['id']}/run")
    return model


def propose(mod: Module, changes: list[dict], summary: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/code/proposals", {
        "summary": summary, "description": "", "changes": changes,
    })


def test_a_reviewer_is_told_which_dataset_this_changes(page, api) -> None:
    """**The point of the unit.** The review surface showed a diff and nothing
    about its consequences; the first thing on it now is which dataset moves."""
    mod = Module(api, "Impact seen")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    dataset = api.call("GET", f"{mod.base}/models/{model['id']}")["output_dataset_id"]
    named = api.call("GET", f"{mod.base}/datasets/{dataset}")["name"]

    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT id FROM raw"}], "Drop a column"
    )
    open_review(page, mod, proposal["id"])

    expect(page.get_by_test_id("impact-summary")).to_contain_text("1 dataset changes")
    row = page.get_by_test_id("impact-row")
    expect(row).to_have_count(1)
    expect(row).to_contain_text(named)
    expect(row).to_have_attribute("data-state", "affected")


def test_a_transform_nobody_has_built_says_so_rather_than_going_missing(
    page, api
) -> None:
    """The state that matters most on a screen: a proposal against an unbuilt
    transform has a real consequence and no dataset to name, and a panel that
    listed only datasets would show nothing at all — which reads as a change
    that affects nothing."""
    mod = Module(api, "Impact unbuilt")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = api.call("POST", f"{mod.base}/models", {
        "name": f"Unbuilt {mod.tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })

    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT val FROM raw"}], "Change it"
    )
    open_review(page, mod, proposal["id"])

    expect(page.get_by_test_id("impact-summary")).to_contain_text("No datasets change")
    row = page.get_by_test_id("impact-row")
    expect(row).to_have_count(1)
    expect(row).to_have_attribute("data-state", "never_built")
    expect(row).to_contain_text("never been built")
    expect(row).to_contain_text(f"Unbuilt {mod.tag}")


def test_the_list_is_as_long_as_the_diff(page, api) -> None:
    """One row per file, with the two states side by side — the arrangement
    that tells a partial answer from a complete one."""
    mod = Module(api, "Impact both")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    built = built_model(mod, source, f"Built {mod.tag}")
    unbuilt = api.call("POST", f"{mod.base}/models", {
        "name": f"Fresh {mod.tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })

    proposal = propose(mod, [
        {"model_id": built["id"], "code": "SELECT id FROM raw"},
        {"model_id": unbuilt["id"], "code": "SELECT val FROM raw"},
    ], "Two files")
    open_review(page, mod, proposal["id"])

    expect(page.get_by_test_id("impact-row")).to_have_count(2)
    expect(page.get_by_test_id("impact-summary")).to_contain_text("1 dataset changes")
    expect(page.get_by_test_id("impact-summary")).to_contain_text("1 file has no dataset")
    expect(page.locator('[data-testid="impact-row"][data-state="affected"]')).to_have_count(1)
    expect(page.locator('[data-testid="impact-row"][data-state="never_built"]')).to_have_count(1)


def test_the_panel_says_what_it_does_not_cover(page, api) -> None:
    """p.53's own default is the same, and Foundry offers **Add datasets to
    analysis** to go further. That is not built, so the limit is on the screen
    rather than left to be discovered by trusting a short list (§214)."""
    mod = Module(api, "Impact limit")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT id FROM raw"}], "Narrow it"
    )
    open_review(page, mod, proposal["id"])
    expect(page.get_by_test_id("impact-limit")).to_contain_text("downstream")


# ---- p.54's Schema: what the code does to the columns (§365) -----------------

def test_a_reviewer_can_ask_what_the_columns_do(page, api) -> None:
    """**p.54, and without p.52's two builds.** Foundry needs the dataset built
    on head and base to compare two outputs; this runs the proposed code over a
    sample and diffs the columns, so the answer exists on a proposal nobody has
    built."""
    mod = Module(api, "Schema seen")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT id FROM raw"}], "Drop val"
    )
    open_review(page, mod, proposal["id"])

    # **Asked for, not computed on arrival.** Running every transform in a
    # proposal to draw its first screen would make opening a review cost more
    # the more it changes.
    expect(page.get_by_test_id("schema-change")).to_have_count(0)
    page.get_by_test_id("schema-ask").click()

    change = page.get_by_test_id("schema-change")
    expect(change).to_be_visible()
    expect(change).to_have_attribute("data-ok", "true")
    expect(change).to_contain_text("val")


def test_code_that_does_not_run_is_said_where_the_columns_would_be(page, api) -> None:
    """The most important of the three answers: a reviewer shown "no column
    changes" for a transform that does not compile has been told something true
    and useless."""
    mod = Module(api, "Schema broken")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT nope FROM raw"}], "Break it"
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("schema-ask").click()

    change = page.get_by_test_id("schema-change")
    expect(change).to_be_visible()
    expect(change).to_have_attribute("data-ok", "false")
    expect(change).to_contain_text("nope")


def test_no_column_change_is_said_rather_than_left_blank(page, api) -> None:
    """An empty space is indistinguishable from a panel that did not load, and
    "nothing moved" is the answer a reviewer most wants."""
    mod = Module(api, "Schema same")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT id, val FROM raw WHERE id > 0"}],
        "Filter only",
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("schema-ask").click()
    expect(page.get_by_test_id("schema-change")).to_contain_text("No column changes")


def test_a_transform_with_no_dataset_is_not_asked_about_its_columns(page, api) -> None:
    """§214: the control is absent where there is nothing to compare against,
    rather than present and then apologising."""
    mod = Module(api, "Schema unbuilt")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = api.call("POST", f"{mod.base}/models", {
        "name": f"Unbuilt {mod.tag}", "code": "SELECT id FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT val FROM raw"}], "Change it"
    )
    open_review(page, mod, proposal["id"])
    expect(page.get_by_test_id("impact-row")).to_have_count(1)
    expect(page.get_by_test_id("schema-ask")).to_have_count(0)
