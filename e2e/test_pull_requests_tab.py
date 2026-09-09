"""p.18-19's Pull requests tab, in the repository application (§276).

`code-repositories.md` §1 wants five tabs and calls proposals "Pull requests";
ours lived on the project's Code pillar page, which is the page B.1 deletes.
`ReviewSurface` has been a shared component since §60 — it takes a proposal id
and nothing else — so what is new here is *reachability*, not review.

The rules are in `apps/web/src/lib/pull-requests.test.ts`. What needs a browser
is the tab: that it exists, that opening a proposal is a link somebody can
send, and that an empty one says where the others are rather than looking like
nothing is happening.
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


def dataset(mod: Module, name: str) -> str:
    """A dataset for a transform to read, so a commit can declare one."""
    made = mod.api.upload_csv(f"{mod.base}/datasets/upload", name,
                              b"id,total\n1,10\n2,20\n")
    return str(made["name"])


def commit(mod: Module, repo: dict, files: dict[str, str], *, branch: str = "main") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": branch, "files": files, "message": "a change"},
    )


def propose_commit(mod: Module, repo: dict, commit_id: str, summary: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": summary, "description": "",
         "source_repo_id": repo["id"], "source_commit_id": commit_id},
    )


def open_tab(page, repo: dict, tab: str = "pulls") -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab={tab}")
    expect(page.get_by_role("button", name="Pull requests")).to_be_visible(timeout=30000)


def test_a_commit_proposal_is_reachable_from_its_own_repository(page, api) -> None:
    """**The point of the tab.** Before it, a proposal about this repository
    could only be opened from the project's Code page — the one B.1 deletes."""
    mod = project(api, "Pulls reachable")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"daily_{uuid.uuid4().hex[:6]}"
    made = commit(mod, repo, {
        "src/daily.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    summary = f"Publish {out}"
    proposal = propose_commit(mod, repo, made["id"], summary)

    open_tab(page, repo)
    row = page.get_by_test_id(f"pull-{proposal['id']}")
    expect(row).to_be_visible()
    expect(row).to_contain_text(summary)
    # The commit it would publish, in the same eight characters the History tab
    # and the publish plan use, so the three can be read against each other.
    expect(row).to_contain_text(made["id"][:8])

    row.click()
    expect(page.get_by_test_id("pulls-back")).to_be_visible()
    # And the review surface itself arrived, rather than an empty shell.
    expect(page.get_by_text(summary).first).to_be_visible()


def test_the_open_proposal_is_in_the_url_so_a_review_can_be_sent(page, api) -> None:
    """A review is a thing people send each other, so it has to be a link.
    Asserted by *reloading* rather than by reading the address bar: a URL that
    is written and not read is a URL that looks right and does nothing."""
    mod = project(api, "Pulls deep link")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"linked_{uuid.uuid4().hex[:6]}"
    made = commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    proposal = propose_commit(mod, repo, made["id"], f"Publish {out}")

    open_tab(page, repo)
    page.get_by_test_id(f"pull-{proposal['id']}").click()
    expect(page.get_by_test_id("pulls-back")).to_be_visible()
    assert f"proposal={proposal['id']}" in page.url, page.url

    page.reload()
    expect(page.get_by_test_id("pulls-back")).to_be_visible(timeout=30000)


def test_another_repositorys_proposal_is_not_shown_here(page, api) -> None:
    """A proposal is project-level and a repository is one of several (db
    0039), so "this project's proposals" and "this repository's" are different
    lists. Showing the first would put another repository's review in front of
    somebody looking at this one."""
    mod = project(api, "Pulls scoped")
    mine = repository(mod, f"Mine {mod.tag}")
    theirs = repository(mod, f"Theirs {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"other_{uuid.uuid4().hex[:6]}"
    made = commit(mod, theirs, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    proposal = propose_commit(mod, theirs, made["id"], f"Publish {out}")

    open_tab(page, mine)
    expect(page.get_by_test_id(f"pull-{proposal['id']}")).to_have_count(0)
    # And it says so rather than showing an empty list: "belongs to something
    # else" is a different answer from "nothing is happening", and only one of
    # them means the reader should stop looking.
    expect(page.get_by_test_id("pulls-empty")).to_contain_text("belongs to something else")

    # The same proposal *is* on its own repository's tab, which is what makes
    # the assertion above about scoping rather than about it being missing.
    open_tab(page, theirs)
    expect(page.get_by_test_id(f"pull-{proposal['id']}")).to_be_visible()


def test_an_empty_tab_with_nothing_anywhere_says_only_that(page, api) -> None:
    mod = project(api, "Pulls empty")
    repo = repository(mod, f"Transforms {mod.tag}")

    open_tab(page, repo)
    expect(page.get_by_test_id("pulls-empty")).to_have_text(
        "No open proposals for this repository."
    )
