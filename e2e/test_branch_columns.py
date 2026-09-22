"""p.16's Checks and Pull request columns on the Branches tab (§300).

    "The 'Checks' column indicates whether or not the automatic code checks have
     passed for a branch. The 'Pull request' column tells you about any existing
     Pull requests in a branch and lets you create new Pull requests… If you
     don't see the button to create a new Pull request, it means that a Pull
     request already exists for a branch. Click on the 'Open' / 'Closed' /
     'Merged' button to open the full Pull request." (p.16-17)

That last sentence is a **rule**: the button and the state occupy one slot, and
which of them is there says which situation you are in. The wording rules are in
`apps/web/src/lib/branch-columns.test.ts` and the server's answers in
`apps/api/tests/test_repository_routes.py`. What needs a browser is the slot.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def declaring(name: str) -> str:
    """A file that actually declares - a proposal cannot be made over a commit
    with nothing to publish, and the publish path is right to refuse it."""
    return f"-- output: {name}\nSELECT 1 AS id\n"


def commit(mod: Module, repo: dict, files: dict[str, str], branch: str = "main") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": branch, "files": files, "message": "a change"},
    )


def open_branches(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=branches")
    expect(page.get_by_test_id("tags-section")).to_be_visible(timeout=30000)


def test_a_branch_nothing_has_run_against_does_not_show_a_pass(page, api) -> None:
    """**The column somebody glances at before merging.** "Nothing failed" and
    "everything passed" are the same number, and a green tick over a branch
    nothing has run against is the lie §295 refuses about a test suite."""
    mod = project(api, "Columns none")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})

    open_branches(page, repo)
    expect(page.get_by_test_id("branch-checks-main")).to_have_text("not run", timeout=30000)


def test_the_button_and_the_state_are_one_slot(page, api) -> None:
    """p.16-17's rule, on the screen: a branch with a pull request shows its
    state and no button; a branch without one shows the button. Both at once
    would answer a question the reader did not have to ask."""
    mod = project(api, "Columns slot")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "sandbox", "from_branch": "main"})
    made = commit(mod, repo, {"src/b.sql": declaring(f"s_{uuid.uuid4().hex[:6]}")},
                  branch="sandbox")

    open_branches(page, repo)
    # No proposal yet: the button is there on both.
    expect(page.get_by_test_id("branch-propose-sandbox")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("branch-pr-sandbox")).to_have_count(0)

    mod.api.call("POST", f"{mod.base}/code/proposals",
                 {"summary": "Publish the sandbox", "description": "",
                  "source_repo_id": repo["id"], "source_commit_id": made["id"]})
    page.reload()

    # Now the state, and the button is gone - which is how p.16 says you know.
    state = page.get_by_test_id("branch-pr-sandbox")
    expect(state).to_have_text("Open", timeout=30000)
    expect(page.get_by_test_id("branch-propose-sandbox")).to_have_count(0)

    # And it opens the full pull request (p.17).
    state.click()
    expect(page.get_by_test_id("pulls-back")).to_be_visible(timeout=30000)


def test_the_default_branch_is_told_why_it_cannot_be_proposed(page, api) -> None:
    """**Disabled with the reason on it, not hidden.**

    p.16 makes the *absence* of the button mean "a pull request already exists",
    so hiding it for a second reason would make that sentence untrue. Applying a
    proposal lands its commit on the default branch (§283), so proposing that
    branch into itself is a review of nothing.
    """
    mod = project(api, "Columns default")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})

    open_branches(page, repo)
    button = page.get_by_test_id("branch-propose-main")
    expect(button).to_be_visible(timeout=30000)
    expect(button).to_be_disabled()
    assert "where applied changes land" in (button.get_attribute("title") or "")


def test_propose_changes_takes_you_where_a_proposal_is_made(page, api) -> None:
    """p.16's "Propose changes". A proposal needs a summary, so the button goes
    to the tab where one is written rather than making an empty review and
    putting it in front of somebody."""
    mod = project(api, "Columns propose")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "work", "from_branch": "main"})
    commit(mod, repo, {"src/b.sql": declaring(f"w_{uuid.uuid4().hex[:6]}")}, branch="work")

    open_branches(page, repo)
    page.get_by_test_id("branch-propose-work").click()
    page.wait_for_url(lambda url: "tab=publish" in url and "branch=work" in url, timeout=30000)


# ---- p.17's "View code", and p.16's dropdown that is not here (§430) ---------
def test_view_code_opens_the_branch_in_the_editor(page, api) -> None:
    """p.17: "Click 'View code' next to a branch name to view the code on that
    branch."

    **The capability was here and the name was not**, which is why the parity
    row read ○ for as long as it did: the branch *name* was the button, so a
    reader who did not think to click a label never found it, and one who did
    got taken to another tab by a control that had said nothing about going
    anywhere (§337).
    """
    mod = project(api, "Branches view code")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "work", "from_branch": "main"})
    commit(mod, repo, {"src/b.sql": declaring(f"w_{uuid.uuid4().hex[:6]}")}, branch="work")

    open_branches(page, repo)
    # The name is still on the row - it stopped being the control, not the
    # label, and a list of buttons with no branch names on it would be worse
    # than the thing this fixed.
    expect(page.locator(".repo-branch-list .repo-branch-name")).to_have_text(
        ["main", "work"], timeout=30000
    )
    page.get_by_test_id("branch-view-work").click()
    page.wait_for_url(lambda url: "tab=files" in url and "branch=work" in url, timeout=30000)
    # And the tree it opens is that branch's, not the default's - the file
    # committed only to `work` is the proof.
    expect(page.locator(".repo-tree").get_by_role("button", name="src/b.sql")).to_be_visible(
        timeout=30000
    )


def test_the_publish_tab_says_where_a_proposal_will_land(page, api) -> None:
    """**p.16's dropdown, answered in a sentence.**

        "If you want to merge your changes into a branch other than master,
         select a different branch from the dropdown menu." (p.16)

    There is no dropdown, and the screen says why rather than leaving somebody
    hunting for one: a proposal here is a request to *publish*, so it lands on
    the branch every reader opens. Said at the moment they would be looking
    for the control, which is before the proposal exists — the review surface
    says it again afterwards (§283).
    """
    mod = project(api, "Branches landing note")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "work", "from_branch": "main"})
    commit(mod, repo, {"src/b.sql": declaring(f"w_{uuid.uuid4().hex[:6]}")}, branch="work")
    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": True})

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=publish&branch=work")
    note = page.get_by_test_id("publish-lands-on")
    expect(note).to_be_visible(timeout=30000)
    # The branch it names is the repository's default, not the one being
    # published - which is the whole content of the sentence.
    expect(note).to_contain_text("main")
    expect(note).to_contain_text("default branch")
    # And it points at the control that *does* move one branch onto another.
    expect(note).to_contain_text("Merge")

    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": False})


def test_an_ungated_project_is_not_told_about_landing(page, api) -> None:
    """The sentence is about applying a *proposal*, and an ungated project
    publishes directly — telling it about a landing that will not happen is
    the kind of note people learn to read past.

    The positive wait comes first: the publish button proves the tab rendered,
    so the absence below is about a page rather than about a race (§318).
    """
    mod = project(api, "Branches ungated")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": declaring(f"d_{uuid.uuid4().hex[:6]}")})

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=publish")
    expect(page.get_by_role("button", name="Publish 1 transform")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("publish-lands-on")).to_have_count(0)
