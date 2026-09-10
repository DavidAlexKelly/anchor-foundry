"""p.15's status bar, in the repository application (§307).

    "The status bar provides information on the state of the environment and
     checks results… Code Assist state… Problems - when problems are detected
     in your code, an indication appears on the left side of the status bar.
     Click on the indication to open the Problems helper… Checks status…
     File saving." (p.15)

**It reports, it does not decide.** Every number on it is computed somewhere
else, so the rules are tested where they live — the wording in
`apps/web/src/lib/status-bar.test.ts`, the checks verdict in
`branch-checks.test.ts`, the draft outcomes in `editor-drafts.test.ts`.

What needs a browser is the **seam**, and there are three of them: that the bar
reads the *editor's* readiness rather than the page's, that the Problems
indicator opens the Problems helper as p.15 says it does, and that the saving
indicator moves when somebody types. `code-repositories.md` §2.5 is what the
first is for: the lesson worth copying is that Foundry tells you when the thing
that makes the editor smart is not ready, rather than silently behaving like a
dumb editor.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def commit(mod: Module, repo: dict, files: dict[str, str]) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "a transform"},
    )


def open_file(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def test_the_bar_reports_the_editor_rather_than_the_page(page, api) -> None:
    """**The one indicator that needs a browser to mean anything.**

    `editorReady` comes from Monaco's own `onMount`, not from the one-tick
    mount guard beside it: the guard fires one tick after the page appears,
    every time, which would make this indicator always right and never useful.
    Asserted as it *settling* on a state that is not "loading", because the
    dynamic import is the thing being waited for.
    """
    mod = project(api, "Status editor")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.sql": "-- output: daily\nSELECT 1 AS id\n"})

    open_file(page, repo, "src/daily.sql")
    bar = page.get_by_test_id("status-bar")
    expect(bar).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("status-assist")).not_to_have_text(
        "Editor loading", timeout=30000)


def test_nothing_is_being_analysed_until_something_asks(page, api) -> None:
    """The divergence from Foundry, said out loud rather than papered over.

    Foundry's Code Assist runs continuously; ours is a round trip, and one on
    every keystroke would cost more than it tells you (§286). A bar reading
    "Ready" while nothing was watching would be exactly the silence p.15 warns
    about, dressed as reassurance.
    """
    mod = project(api, "Status idle")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.sql": "-- output: daily\nSELECT 1 AS id\n"})

    open_file(page, repo, "src/daily.sql")
    assist = page.get_by_test_id("status-assist")
    expect(assist).to_have_text("Analysis on demand", timeout=30000)
    # And the hover says why, naming Foundry's own feature so the difference is
    # legible rather than looking like a fault.
    assert "Code Assist" in (assist.get_attribute("title") or "")


def test_the_problems_indicator_opens_the_problems_helper(page, api) -> None:
    """p.15's own sentence: "Click on the indication to open the Problems
    helper." """
    mod = project(api, "Status problems")
    repo = repository(mod, f"Transforms {mod.tag}")
    # A file the Problems panel has something to say about: no output declared,
    # which is one of the rules the publish already refuses (§286).
    commit(mod, repo, {"src/broken.sql": "SELECT 1 AS id\n"})

    open_file(page, repo, "src/broken.sql")
    # Nothing is claimed before anything has been asked: zero problems and
    # never having looked are the same number, and only one is a fact.
    expect(page.get_by_test_id("status-problems")).to_have_count(0)

    # Opened by role, which is how `test_problems_panel.py` opens it — the
    # toggle carries no test id and adding one here would be a second way to
    # find the same button.
    page.get_by_role("button", name="Problems", exact=True).click()
    expect(page.get_by_test_id("problems-summary")).to_be_visible(timeout=20000)
    indicator = page.get_by_test_id("status-problems")
    expect(indicator).to_be_visible(timeout=30000)

    # Close the panel, then reopen it from the status bar, which is p.15's verb.
    page.get_by_role("button", name="Hide problems", exact=True).click()
    expect(page.get_by_test_id("problems-summary")).to_have_count(0)
    indicator.click()
    expect(page.get_by_test_id("problems-summary")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("problems-panel")).to_contain_text(
        "declares no transform")


def test_the_saving_indicator_says_where_the_work_is(page, api) -> None:
    """**The dangerous misreading, and the wording that prevents it.**

    Foundry's editor saves to the branch. Ours keeps drafts in `localStorage`
    (§281), and nothing reaches the repository until somebody commits — so a
    bar saying "Saved" would let somebody shut the laptop believing their work
    is in the repository. It would be true in the sense the word usually
    carries and false in the sense that matters.
    """
    mod = project(api, "Status saving")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.sql": "-- output: daily\nSELECT 1 AS id\n"})

    open_file(page, repo, "src/daily.sql")
    saving = page.get_by_test_id("status-saving")
    expect(saving).to_have_text("Nothing uncommitted", timeout=30000)

    page.locator(".monaco-editor textarea").first.fill(
        "-- output: daily\nSELECT 2 AS id\n")
    expect(saving).to_have_text("1 file kept in this browser", timeout=30000)
    # And the hover is the sentence that keeps "kept" from being read as
    # "committed".
    assert "not in the repository until you commit" in (
        saving.get_attribute("title") or "")


def test_the_checks_indicator_says_when_nothing_has_been_checked(page, api) -> None:
    """p.15 puts the checks on the right. A fresh branch has none, and "No
    checks" is a different answer from "Checks passed" — the fourth screen this
    session to need that sentence."""
    mod = project(api, "Status checks")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/daily.sql": "-- output: daily\nSELECT 1 AS id\n"})

    open_file(page, repo, "src/daily.sql")
    expect(page.get_by_test_id("status-checks")).to_have_text(
        "No checks", timeout=30000)
