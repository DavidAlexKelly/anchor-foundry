"""Scheduling from the lineage graph (§387; `data-lineage` p.10).

> "The schedules helper allows you to **set and edit** build schedules for
>  selected resources on the graph." (p.10)

The last of the README's three *work starts from the resource* rows. Schedules
already existed — `trigger_mode='cron'` with a `cron_schedule`, run by the
worker (db 0024) — so what is added is setting them over a selection.

**p.10's other half has nowhere to go**: "the schedules apply to the branches
(including fallback branches) configured in the graph", and this platform's
pipeline graph has no notion of a branch.

What the summary says, and which models count as already scheduled, are
`apps/web/src/lib/graph-schedules.test.ts`'s. What needs a browser is the
**seam**: that pressing Schedule puts the expression on the transforms the
summary counted, and that clearing takes it off.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from conftest import WEB_BASE, eventually

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def chain(api):
    """S → A → `A`'s output, with `A` on no schedule to begin with."""
    tag = uuid.uuid4().hex[:6]
    workspace = api.call("GET", "/workspaces")[0]
    project = api.call(
        "POST", f"/workspaces/{workspace['id']}/projects",
        {"name": f"Sched {tag}", "slug": f"sched-{tag}"},
    )
    base = f"/workspaces/{workspace['id']}/projects/{project['id']}"
    source = api.upload_csv(f"{base}/datasets/upload", f"S {tag}", ROWS)
    a = api.call("POST", f"{base}/models", {
        "name": f"A {tag}", "code": "SELECT id, val * 2 AS doubled FROM raw",
        "inputs": [{"dataset_id": source["id"], "input_alias": "raw"}],
    })
    api.call("POST", f"{base}/models/{a['id']}/run")
    return {"workspace_slug": workspace["slug"], "project_slug": project["slug"],
            "tag": tag, "base": base, "a": a["id"]}


def open_pipeline(page, chain) -> None:
    page.goto(f"{WEB_BASE}/{chain['workspace_slug']}/{chain['project_slug']}/pipeline")
    expect(page.get_by_test_id("graph-node").first).to_be_visible(timeout=30000)


def card(page, chain, kind: str, key: str):
    return (
        page.get_by_test_id("graph-node")
        .filter(has_text=kind)
        .filter(has_text=f"{key} {chain['tag']}")
        .first
    )


def model(api, chain) -> dict:
    return api.call("GET", f"{chain['base']}/models/{chain['a']}")


def test_scheduling_a_selected_transform_puts_it_on_a_schedule(page, api, chain) -> None:
    """**The seam.** p.10's "set", over a selection rather than one model's
    own page — which is the whole of what this row was missing."""
    open_pipeline(page, chain)
    card(page, chain, "model", "A").click()
    expect(page.get_by_test_id("selection-schedule-summary")).to_have_text("schedule 1 transform")

    page.get_by_test_id("selection-schedule-cron").fill("15 3 * * 1")
    page.get_by_test_id("selection-schedule-set").click()
    eventually(lambda: model(api, chain)["cron_schedule"], lambda c: c == "15 3 * * 1",
               what="the schedule to be written")
    assert model(api, chain)["trigger_mode"] == "cron"
    expect(page.get_by_test_id("pipeline-schedule-error")).to_have_count(0)


def test_the_summary_says_what_it_would_replace(page, api, chain) -> None:
    """§214, and p.10's "edit". A selection holding a model that already has a
    schedule is the ordinary case, so overwriting is right — being quiet about
    it is not. This runs after the test above, so `A` is on a schedule."""
    open_pipeline(page, chain)
    card(page, chain, "model", "A").click()
    expect(page.get_by_test_id("selection-schedule-summary")).to_contain_text("replacing 1 existing")


def test_clearing_takes_the_schedule_off(page, api, chain) -> None:
    """p.10's "edit" includes turning one off, which is `trigger_mode` back to
    manual — and the old expression goes with it, so nothing carries a
    schedule nobody can see."""
    open_pipeline(page, chain)
    card(page, chain, "model", "A").click()
    page.get_by_test_id("selection-schedule-clear").click()
    eventually(lambda: model(api, chain)["trigger_mode"], lambda t: t == "manual",
               what="the schedule to be cleared")
    assert model(api, chain)["cron_schedule"] is None


def test_clearing_is_absent_when_there_is_nothing_to_clear(page, chain) -> None:
    """The negative control. A Clear button over a selection that has no
    schedule is a control that would not change anything — §214's shape, and
    the reason `clearSummary` answers with nothing rather than "0"."""
    open_pipeline(page, chain)
    card(page, chain, "model", "A").click()
    expect(page.get_by_test_id("selection-schedule-summary")).to_be_visible()
    expect(page.get_by_test_id("selection-schedule-clear")).to_have_count(0)


def test_an_unfinished_expression_leaves_the_button_unusable(page, chain) -> None:
    """Five fields or the button does nothing — because a box holding three of
    them was never going to be a cron expression, and earning a refusal for
    something the reader can see is unfinished helps nobody.

    **Whether five fields mean anything is the server's**: this only checks the
    shape, which is why `99 99 99 99 99` gets through to be refused by name.
    """
    open_pipeline(page, chain)
    card(page, chain, "model", "A").click()
    cron = page.get_by_test_id("selection-schedule-cron")
    set_button = page.get_by_test_id("selection-schedule-set")

    cron.fill("0 * *")
    expect(set_button).to_be_disabled()
    cron.fill("")
    expect(set_button).to_be_disabled()
    # Positive control: five fields and it is usable again.
    cron.fill("0 2 * * *")
    expect(set_button).to_be_enabled()
