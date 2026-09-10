"""p.19's Checks tab, in the repository application (§285).

`code-repositories.md` §1 wants five tabs; this is the last of them. §276 gave
Pull requests a home and §279 gave Settings one, and Checks was the row still
reading "checks run and block, no tab".

**The divergence the tab states rather than papers over.** Foundry runs checks
on a *commit*: you commit to a sandbox and checks start. Ours run on a
*proposal*, because the schema check asks what the code would do to the
project's datasets and a commit nobody has proposed has not said which change it
means to make. Since §284 a sandbox is where work happens and a proposal is how
it lands, so every commit that matters is on its way to being one.

The ordering and wording rules are in `apps/web/src/lib/branch-checks.test.ts`
and the query is in `apps/api/tests/test_transform_publish.py`. What needs a
browser is reachability: that the tab exists, that it follows the application's
branch selector, and that a check opens the change it is about.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def dataset(mod: Module, name: str) -> str:
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total\n1,10\n2,20\n")
    return str(made["name"])


def commit(mod: Module, repo: dict, files: dict[str, str], *, branch: str = "main") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": branch, "files": files, "message": "a change"},
    )


def sandbox(mod: Module, repo: dict, name: str, *, frm: str = "main") -> None:
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": name, "from_branch": frm})


def propose(mod: Module, repo: dict, commit_id: str, summary: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": summary, "description": "",
         "source_repo_id": repo["id"], "source_commit_id": commit_id},
    )


def run_checks(mod: Module, proposal_id: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/code/proposals/{proposal_id}/checks", {})


def sql(out: str, source: str, body: str = "SELECT id FROM raw") -> str:
    return f"-- output: {out}\n-- input: raw = {source}\n{body}\n"


def open_checks(page, repo: dict, *, branch: str | None = None) -> None:
    ref = f"&branch={branch}" if branch else ""
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=checks{ref}")
    expect(page.get_by_test_id("checks-tab")).to_be_visible(timeout=30000)


def a_checked_branch(api, name: str):
    """A sandbox with a proposal over it and its checks run."""
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"README.md": "# t\n"})
    sandbox(mod, repo, "work")
    made = commit(mod, repo, {
        "README.md": "# t\n",
        "src/t.sql": sql(f"c_{uuid.uuid4().hex[:6]}", source),
    }, branch="work")
    proposal = propose(mod, repo, made["id"], "Add a transform")
    run_checks(mod, proposal["id"])
    return mod, repo, proposal


def test_the_tab_shows_what_ran_on_the_branch_and_what_it_was_about(page, api) -> None:
    """**The point of the tab.** Before it, a check result could only be seen by
    opening the proposal that owns it, which is the wrong way round when the
    question is "is this branch all right"."""
    mod, repo, proposal = a_checked_branch(api, "Checks tab")

    open_checks(page, repo, branch="work")
    expect(page.get_by_test_id("checks-verdict")).to_contain_text("passing")
    rows = page.locator(".repo-check")
    expect(rows).to_have_count(2)
    # Both passed, and two checks of one run share a timestamp, so the order
    # falls through to the name. Pinned rather than loosened to a set: an order
    # that is stable is what stops a list of checks jumping about between
    # renders, and that is worth a test even when nothing is wrong.
    expect(page.locator(".repo-check code")).to_have_text(
        ["schema_compatible", "transform_runs"], timeout=20000
    )
    # Every check names the change it belongs to: a check without one is a
    # verdict on nothing.
    expect(page.locator(".repo-check-open").first).to_have_text("Add a transform")


def test_a_check_opens_the_change_it_is_about(page, api) -> None:
    """p.19: "Click on a specific check to view more detailed information."

    The detail a check has is the proposal it belongs to, so this goes there
    rather than opening a dialog that would restate what the row already says.
    """
    mod, repo, proposal = a_checked_branch(api, "Checks open")

    open_checks(page, repo, branch="work")
    page.locator(".repo-check-open").first.click()
    page.wait_for_url(f"**proposal={proposal['id']}", timeout=20000)
    # `exact=True`: the page it lands on has a "Back to pull requests" button,
    # and a loose name match picks up both.
    expect(
        page.get_by_role("button", name="Pull requests", exact=True)
    ).to_have_attribute("aria-current", "true")


def test_the_tab_follows_the_applications_branch_selector(page, api) -> None:
    """p.19: "Use the dropdown branch menu to select a different branch."

    The application already has one, at the top of every tab. A second selector
    inside this tab would be a second answer to "which branch am I looking at".
    """
    mod, repo, _ = a_checked_branch(api, "Checks branch")

    open_checks(page, repo, branch="work")
    expect(page.locator(".repo-check")).to_have_count(2)

    open_checks(page, repo, branch="main")
    expect(page.locator(".repo-check")).to_have_count(0)
    # And it says which empty this is, rather than looking like a broken runner.
    expect(page.locator(".repo-checks .state")).to_contain_text("look at the sandbox branch")


def test_the_tab_says_checks_run_on_a_pull_request_rather_than_a_commit(
    page, api
) -> None:
    """**The divergence, out loud.** Somebody reading a thin list would
    otherwise assume the runner is broken rather than that it runs somewhere
    else."""
    mod, repo, _ = a_checked_branch(api, "Checks scope")

    open_checks(page, repo, branch="work")
    scope = page.get_by_test_id("checks-scope")
    expect(scope).to_contain_text("rather than on every commit")
    expect(scope).to_contain_text("Foundry runs them per commit")


def test_a_failing_check_leads_the_list_and_the_verdict(page, api) -> None:
    """The list is read to find the failure, so the failure goes first - and a
    branch with one is not "passing" on the strength of the check that did."""
    mod = project(api, "Checks failing")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"README.md": "# t\n"})
    sandbox(mod, repo, "work")
    # A transform that cannot run: the column does not exist.
    made = commit(mod, repo, {
        "README.md": "# t\n",
        "src/t.sql": sql(f"f_{uuid.uuid4().hex[:6]}", source,
                         body="SELECT no_such_column FROM raw"),
    }, branch="work")
    proposal = propose(mod, repo, made["id"], "A transform that does not run")
    run_checks(mod, proposal["id"])

    open_checks(page, repo, branch="work")
    eventually(lambda: page.locator(".repo-check").first.get_attribute("class"),
               lambda c: c is not None and "fail" in c,
               what="the failing check to lead the list")
    expect(page.get_by_test_id("checks-verdict")).to_contain_text("failing")
    expect(page.get_by_test_id("checks-verdict")).to_contain_text("blocks the proposal")
