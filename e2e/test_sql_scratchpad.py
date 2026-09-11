"""p.15's SQL Scratchpad, in the repository application (§305–§306).

    "The SQL helper lets you quickly test out SQL queries. Write a SQL query
     and click [run] to preview the results of your query… To view queries
     marked as favorites, go to the [star] tab. To view a history of queries ran
     in the SQL helper, go to the [clock] tab." (p.15)

**The Explorer's opposite number.** That panel says what the project holds;
this one asks it a question. The wording and ordering rules are in
`apps/web/src/lib/sql-scratchpad.test.ts`, the reference syntax in
`apps/api/tests/test_scratchpad.py`, and the history's rules — one row per
distinct text, the cap, what a star exempts — in
`apps/api/tests/test_repository_routes.py`.

What needs a browser is the **seam**, and it is the only place a scratchpad
query actually reaches the engine: the API tests cover the refusals, which
never get that far, because reaching DuckDB needs a dataset with parquet
behind it and that is what this fixture has.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def seeded(mod: Module) -> str:
    """A dataset with rows in it, and its name."""
    mod.object_type(
        columns=["id", "town"],
        rows=[{"id": "1", "town": "Ely"}, {"id": "2", "town": "Wells"}],
        key="id",
    )
    return f"seed_{mod.tag}"


def open_scratchpad(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files")
    toggle = page.get_by_test_id("scratchpad-toggle")
    expect(toggle).to_be_visible(timeout=30000)
    toggle.click()


def test_a_query_written_in_p15s_syntax_runs_and_returns_rows(page, api) -> None:
    """**The seam, and the translation with it.**

    Foundry runs Spark, where a backtick quotes an identifier; DuckDB has no
    backtick syntax and fails at the parser. So this query is one the engine
    cannot parse, and the only reason it returns anything is `scratchpad.py`
    rewriting it — which the panel then shows, because an error from DuckDB
    would otherwise be about text the author never wrote.
    """
    mod = project(api, "Scratchpad runs")
    name = seeded(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_scratchpad(page, repo)
    page.get_by_test_id("scratchpad-sql").fill(f"SELECT town FROM `/data/{name}`")
    page.get_by_test_id("scratchpad-run").click()

    table = page.get_by_test_id("scratchpad-result")
    expect(table).to_be_visible(timeout=60000)
    expect(table).to_contain_text("Ely")
    expect(table).to_contain_text("Wells")
    # And it says what the engine was actually given, since that is not what
    # was typed.
    expect(page.get_by_test_id("scratchpad-ran")).to_contain_text(f'"{name}"')


def test_a_branch_qualifier_is_refused_and_names_the_model_difference(page, api) -> None:
    """p.15's other sentence, and the decision about it.

    Datasets here are versioned rather than branched (db 0025). Ignoring the
    qualifier would return a table, so nobody would check it.
    """
    mod = project(api, "Scratchpad branch")
    name = seeded(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_scratchpad(page, repo)
    page.get_by_test_id("scratchpad-sql").fill(
        f"SELECT * FROM `branch_A`.`/data/{name}`")
    page.get_by_test_id("scratchpad-run").click()

    refused = page.get_by_test_id("scratchpad-refused")
    expect(refused).to_be_visible(timeout=30000)
    expect(refused).to_contain_text("versioned")
    expect(page.get_by_test_id("scratchpad-result")).to_have_count(0)


def test_a_query_reaches_the_history_only_once_it_has_run(page, api) -> None:
    """p.15's tab is "a history of queries ran in the SQL helper".

    Both halves, because the refused one is the point: a history full of
    queries that never reached the engine is a list of typos, and the one you
    want back is never in it.
    """
    mod = project(api, "Scratchpad history")
    name = seeded(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_scratchpad(page, repo)
    # One that is refused before the engine sees it.
    page.get_by_test_id("scratchpad-sql").fill(f"SELECT * FROM `nosuch_{mod.tag}`")
    page.get_by_test_id("scratchpad-run").click()
    expect(page.get_by_test_id("scratchpad-refused")).to_be_visible(timeout=30000)

    # And one that runs.
    page.get_by_test_id("scratchpad-sql").fill(f"SELECT town FROM `{name}`")
    page.get_by_test_id("scratchpad-run").click()
    expect(page.get_by_test_id("scratchpad-result")).to_be_visible(timeout=60000)

    page.get_by_test_id("scratchpad-tab-history").click()
    listed = page.locator(".repo-scratchpad-list")
    expect(listed).to_contain_text(f"SELECT town FROM `{name}`", timeout=30000)
    expect(listed).not_to_contain_text(f"nosuch_{mod.tag}")


def test_a_history_entry_can_be_recalled_starred_and_forgotten(page, api) -> None:
    """p.15's star, and the whole reason the two tabs are one table.

    Starring is not a way of making a second copy: the favourites tab shows the
    same row, and it is still in the history.
    """
    mod = project(api, "Scratchpad star")
    name = seeded(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_scratchpad(page, repo)
    page.get_by_test_id("scratchpad-sql").fill(f"SELECT id FROM `{name}`")
    page.get_by_test_id("scratchpad-run").click()
    expect(page.get_by_test_id("scratchpad-result")).to_be_visible(timeout=60000)

    page.get_by_test_id("scratchpad-tab-history").click()
    row = page.locator(".repo-scratchpad-list li").first
    expect(row).to_be_visible(timeout=30000)

    # Before starring, the favourites tab is empty and says what to do.
    page.get_by_test_id("scratchpad-tab-favourites").click()
    empty = page.get_by_test_id("scratchpad-empty")
    expect(empty).to_be_visible()
    expect(empty).to_contain_text("Star a query in History")

    page.get_by_test_id("scratchpad-tab-history").click()
    page.get_by_role("button", name="Add to favourites").first.click()
    page.get_by_test_id("scratchpad-tab-favourites").click()
    expect(page.locator(".repo-scratchpad-list")).to_contain_text(
        f"SELECT id FROM `{name}`", timeout=30000)

    # It is still in the history: one row, seen twice.
    page.get_by_test_id("scratchpad-tab-history").click()
    expect(page.locator(".repo-scratchpad-list")).to_contain_text(
        f"SELECT id FROM `{name}`")

    # Recall puts it back in the box, on the Query tab.
    page.locator(".repo-scratchpad-recall").first.click()
    expect(page.get_by_test_id("scratchpad-sql")).to_have_value(
        f"SELECT id FROM `{name}`")

    # And it can be forgotten, because a scratchpad accumulates mistakes.
    page.get_by_test_id("scratchpad-tab-history").click()
    page.get_by_role("button", name=f"Forget SELECT id FROM `{name}`").click()
    expect(page.get_by_test_id("scratchpad-empty")).to_be_visible(timeout=30000)


def test_running_the_same_query_twice_is_one_history_row(page, api) -> None:
    """One row per distinct text, not per run — asserted on the screen because
    it is what makes the history readable at all."""
    mod = project(api, "Scratchpad twice")
    name = seeded(mod)
    repo = repository(mod, f"Transforms {mod.tag}")

    open_scratchpad(page, repo)
    page.get_by_test_id("scratchpad-sql").fill(f"SELECT id FROM `{name}`")
    for _ in range(2):
        page.get_by_test_id("scratchpad-run").click()
        expect(page.get_by_test_id("scratchpad-result")).to_be_visible(timeout=60000)

    page.get_by_test_id("scratchpad-tab-history").click()
    expect(page.locator(".repo-scratchpad-list li")).to_have_count(1, timeout=30000)
    # And it says how many times, which is what a per-run table would have said.
    expect(page.locator(".repo-scratchpad-list")).to_contain_text("ran 2 times")
