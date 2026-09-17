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


# ---- p.54's Expectations, answered as p.52 asks it (§371) --------------------

def add_rule(mod: Module, dataset_id: str, rule_type: str, column: str,
             config: dict | None = None, severity: str = "error") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/datasets/{dataset_id}/expectations",
        {"rule_type": rule_type, "column_name": column,
         "config": config or {}, "severity": severity},
    )


def output_of(mod: Module, model: dict) -> str:
    return str(mod.api.call("GET", f"{mod.base}/models/{model['id']}")["output_dataset_id"])


def test_a_reviewer_is_told_which_expectations_this_change_would_stop(page, api) -> None:
    """**What p.52 asks and p.54 lists, in one place.**

    Foundry builds the head branch to find out whether "all Data Expectations
    are met". This predicts the answer from the columns §365 already computes,
    so it costs nothing beyond the schema — and it is the reason the panel is
    worth opening at all on a dataset that has rules.

    Two rules on the removed column, because the outcomes differ and a reviewer
    reading one sentence for both has been told the wrong thing: the rule that
    *asserts the column* fails, and the rule that *needs* it stops being
    answerable. A third rule on a column the change keeps is what makes "the
    right ones are listed" distinguishable from "everything is" (§190).
    """
    mod = Module(api, "Expectations at risk")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    dataset_id = output_of(mod, model)
    add_rule(mod, dataset_id, "column_exists", "val")
    add_rule(mod, dataset_id, "not_null", "val", severity="warn")
    add_rule(mod, dataset_id, "not_null", "id")

    proposal = propose(
        mod, [{"model_id": model["id"], "code": "SELECT id FROM raw"}], "Drop val"
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("schema-ask").click()

    listed = page.get_by_test_id("schema-expectations")
    expect(listed).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("schema-expectations-summary")).to_have_text(
        "2 expectations at risk, 1 of which would stop this build"
    )
    # The two outcomes said differently, which is the whole point of the pair.
    expect(listed).to_contain_text("column_exists on val fails: the column is removed")
    expect(listed).to_contain_text("not_null on val can no longer run")
    # And the rule on the column that stays is not dragged in.
    expect(listed).not_to_contain_text("not_null on id")


def test_a_change_that_stops_no_expectations_says_nothing_about_them(page, api) -> None:
    """The silence is the feature. A dataset with a rule on it and a change
    that leaves the columns alone must not produce a panel reading "0
    expectations affected" — one that speaks on every review is one that gets
    dismissed on every review.

    The schema panel itself is asserted visible first, so this is a claim about
    the expectations block being absent rather than about the page not having
    loaded (§318).
    """
    mod = Module(api, "Expectations quiet")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    model = built_model(mod, source, f"Daily {mod.tag}")
    add_rule(mod, output_of(mod, model), "not_null", "val")

    proposal = propose(
        mod,
        [{"model_id": model["id"], "code": "SELECT id, val FROM raw WHERE id > 0"}],
        "Filter only",
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("schema-ask").click()

    change = page.get_by_test_id("schema-change")
    expect(change).to_be_visible(timeout=30000)
    expect(change).to_contain_text("No column changes.")
    expect(page.get_by_test_id("schema-expectations")).to_have_count(0)


# ---- p.54's Add datasets to analysis (§372) ----------------------------------

def reading_model(mod: Module, upstream: str, name: str, code: str) -> dict:
    model = mod.api.call("POST", f"{mod.base}/models", {
        "name": name, "code": code,
        "inputs": [{"dataset_id": upstream, "input_alias": "up"}],
    })
    mod.api.call("POST", f"{mod.base}/models/{model['id']}/run")
    return model


def test_a_reviewer_is_told_the_change_breaks_a_transform_below_it(page, api) -> None:
    """**The consequence a reviewer cannot read off the diff**, because the
    code that breaks is code the diff does not contain.

    p.54's row without p.52's precondition: Foundry needs the added datasets
    built to show impact; this chains previews, running the proposed transform
    over a sample and the one below it over that result.
    """
    mod = Module(api, "Downstream breaks")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    head = built_model(mod, source, f"Daily {mod.tag}")
    head_out = api.call("GET", f"{mod.base}/models/{head['id']}")["output_dataset_id"]
    api.call("PATCH", f"{mod.base}/datasets/{head_out}", {"name": f"Ledger {mod.tag}"})
    reading_model(mod, head_out, f"Rollup {mod.tag}", "SELECT id, val * 2 AS x FROM up")

    # Dropping `val` is fine here and fatal one step down.
    proposal = propose(
        mod, [{"model_id": head["id"], "code": "SELECT id FROM raw"}], "Drop val"
    )
    # **Counted, not inferred from what is drawn.** The control exists because
    # this previews a transform per hop, so "asked for" is a claim about the
    # *request*: a panel that fetched eagerly and hid the result until the
    # press would draw exactly the same screen and cost exactly as much.
    asked: list[str] = []
    page.on("request", lambda r: asked.append(r.url) if "/derived" in r.url else None)

    open_review(page, mod, proposal["id"])
    expect(page.get_by_test_id("derived-impact")).to_have_count(0)
    assert asked == [], asked

    page.get_by_test_id("derived-ask").click()

    listed = page.get_by_test_id("derived-impact")
    expect(listed).to_be_visible(timeout=60000)
    expect(page.get_by_test_id("derived-summary")).to_contain_text(
        "1 dataset built from this one"
    )
    row = page.get_by_test_id("derived-row")
    expect(row).to_have_count(1)
    expect(row).to_have_attribute("data-ok", "false")
    expect(row).to_contain_text("val")
    assert len(asked) == 1, asked


def test_a_dataset_below_that_still_builds_shows_its_own_column_changes(
    page, api
) -> None:
    """The other outcome, and the one that proves the chain is faithful rather
    than merely reachable: the transform below survives, and its columns moved
    because what it reads moved — a retype nothing in the diff mentions."""
    mod = Module(api, "Downstream retype")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    head = built_model(mod, source, f"Daily {mod.tag}")
    head_out = api.call("GET", f"{mod.base}/models/{head['id']}")["output_dataset_id"]
    api.call("PATCH", f"{mod.base}/datasets/{head_out}", {"name": f"Ledger {mod.tag}"})
    below = reading_model(mod, head_out, f"Rollup {mod.tag}", "SELECT id, val FROM up")
    below_out = api.call("GET", f"{mod.base}/models/{below['id']}")["output_dataset_id"]
    api.call("PATCH", f"{mod.base}/datasets/{below_out}", {"name": f"Tally {mod.tag}"})
    # A consumer nobody has built: there is no impact to report for it and it
    # is still something the change reaches, so it has to be named rather than
    # dropped — §364's rule, and the analysed row beside it is what makes
    # "named" distinguishable from "everything lands in this list" (§190).
    api.call("POST", f"{mod.base}/models", {
        "name": f"Draft {mod.tag}", "code": "SELECT val FROM up",
        "inputs": [{"dataset_id": head_out, "input_alias": "up"}],
    })

    proposal = propose(
        mod,
        [{"model_id": head["id"], "code": "SELECT id, val * 1.5 AS val FROM raw"}],
        "Scale val",
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("derived-ask").click()

    row = page.get_by_test_id("derived-row")
    expect(row).to_be_visible(timeout=60000)
    expect(row).to_have_attribute("data-ok", "true")
    expect(row).to_have_count(1)
    expect(row).to_contain_text(f"Tally {mod.tag}")
    expect(row).to_contain_text("1 step down")
    expect(row).to_contain_text("DECIMAL")

    unanalysed = page.get_by_test_id("derived-not-analysed")
    expect(unanalysed).to_contain_text(f"Draft {mod.tag}")
    expect(unanalysed).to_contain_text("never been built")


def test_a_change_with_nothing_below_it_says_so(page, api) -> None:
    """The common case, said rather than left as an empty panel — which is
    indistinguishable from one that failed to load."""
    mod = Module(api, "Downstream empty")
    source = api.upload_csv(f"{mod.base}/datasets/upload", f"Src {mod.tag}", ROWS)
    head = built_model(mod, source, f"Daily {mod.tag}")
    proposal = propose(
        mod, [{"model_id": head["id"], "code": "SELECT id FROM raw"}], "Drop val"
    )
    open_review(page, mod, proposal["id"])
    page.get_by_test_id("derived-ask").click()

    expect(page.get_by_test_id("derived-summary")).to_have_text(
        "Nothing is built from this dataset.", timeout=60000
    )
    expect(page.get_by_test_id("derived-row")).to_have_count(0)
