"""Where a change to a transform outside a repository is reviewed (§290).

**This is the last thing standing between B.1 and deleting the Code pillar
page.** §276 gave the repository application a Pull requests tab and
deliberately left one shape out of it: a proposal whose `source_repo_id` is
null belongs to *no* repository (db 0039), so it cannot honestly be listed
under one. The tab's own empty state said those were "reviewed on the Code
screen" — a sentence that would have become a lie the moment that page went,
with nothing to notice.

So they live here, beside the transforms they change. Nothing creates them any
more (§277 and §289 made the answer for a transform outside a repository "move
it into one"), which is exactly why they need a home rather than a migration:
what is left is a finite set of already-open reviews, and stranding those would
be deleting somebody's work rather than deleting a screen.

The wording rules are in `apps/web/src/lib/pull-requests.test.ts`. What needs a
browser is *reachability*: that the list is on the screen, that opening one is
a link somebody can send, and that a repository's proposals do not leak into it.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


def project(api, name: str) -> Module:
    return Module(api, name)


def make_model(mod: Module, name: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/models",
        {"name": name, "language": "sql", "code": "SELECT 1", "inputs": []},
    )


def propose_typed_change(mod: Module, model: dict, summary: str, code: str) -> dict:
    """The shape with no repository: files typed into the proposal itself."""
    return mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": summary, "description": "",
         "changes": [{"model_id": model["id"], "code": code}]},
    )


def models_screen(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/models")
    # `.table`, not `.data-grid`: this screen's list is the former and the
    # history dialog is the latter, so the wrong one waits forever.
    expect(page.locator(".table tbody tr").first).to_be_visible(timeout=30000)


def test_a_change_to_a_transform_outside_a_repository_is_reachable(page, api) -> None:
    """**The point of the unit.** Before it, this proposal could only be opened
    from the project's Code page — the one B.1 deletes — and the Pull requests
    tab told people to go there."""
    mod = project(api, "Direct reachable")
    name = f"direct_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name)
    summary = f"Widen {name}"
    proposal = propose_typed_change(mod, model, summary, "SELECT 1 AS id, 2 AS total")

    models_screen(page, mod)
    section = page.get_by_test_id("direct-proposals")
    expect(section).to_be_visible(timeout=30000)
    # **Why it is there, not just that it is.** A list with no explanation reads
    # as a feature somebody should be using, and nothing creates these any more.
    expect(section).to_contain_text("opened before")
    expect(section).to_contain_text("1 open proposal")

    row = page.get_by_test_id(f"direct-{proposal['id']}")
    expect(row).to_contain_text(summary)
    # The file count, which is what identifies a typed change the way a commit
    # id identifies a publish.
    expect(row).to_contain_text("1 file")

    row.click()
    expect(page.get_by_test_id("direct-back")).to_be_visible()
    # And the review surface itself arrived, rather than an empty shell: the
    # proposal's own summary, fetched by `ReviewSurface` rather than passed to
    # it, is the cheapest proof the detail request landed.
    expect(page.get_by_text(summary).first).to_be_visible()


def test_the_open_review_is_in_the_url_so_it_can_be_sent(page, api) -> None:
    """A review is a thing people send each other, so it has to be a link.

    Asserted by *reloading* rather than by reading the address bar: a URL that
    is written and never read is a URL that looks right and does nothing — and
    that is the exact failure §282 found in the file tabs.
    """
    mod = project(api, "Direct deep link")
    name = f"linked_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name)
    proposal = propose_typed_change(mod, model, f"Change {name}", "SELECT 2")

    models_screen(page, mod)
    page.get_by_test_id(f"direct-{proposal['id']}").click()
    expect(page.get_by_test_id("direct-back")).to_be_visible()
    assert f"proposal={proposal['id']}" in page.url, page.url

    page.reload()
    expect(page.get_by_test_id("direct-back")).to_be_visible(timeout=30000)

    # And back is a way out that leaves the models where they were, rather than
    # a dead end somebody has to retype the URL to escape.
    page.get_by_test_id("direct-back").click()
    expect(page.get_by_test_id(f"direct-{proposal['id']}")).to_be_visible()
    assert "proposal=" not in page.url, page.url


def test_a_repositorys_proposal_does_not_leak_into_this_list(page, api) -> None:
    """The mirror of §276's scoping test, from the other side.

    A proposal that publishes a commit is reviewed on that repository's Pull
    requests tab, where the branch it would move can be shown (§283). Listing
    it here as well would give one review two homes that disagree about what
    applying it does.

    And with nothing left to list, **the section is absent rather than empty**:
    a permanent empty box for a shape nothing creates is a box that teaches
    people to look past this part of the screen.
    """
    mod = project(api, "Direct scoped")
    name = f"scoped_{uuid.uuid4().hex[:6]}"
    make_model(mod, name)
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Transforms {mod.tag}"})
    source = mod.api.upload_csv(f"{mod.base}/datasets/upload", f"orders_{mod.tag}",
                                b"id,total\n1,10\n")
    out = f"pub_{uuid.uuid4().hex[:6]}"
    made = mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "message": "a change", "files": {
            "src/t.sql": f"-- output: {out}\n-- input: raw = {source['name']}\n"
                         "SELECT id FROM raw\n",
        }},
    )
    proposal = mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": f"Publish {out}", "description": "",
         "source_repo_id": repo["id"], "source_commit_id": made["id"]},
    )

    models_screen(page, mod)
    expect(page.get_by_test_id(f"direct-{proposal['id']}")).to_have_count(0)
    expect(page.get_by_test_id("direct-proposals")).to_have_count(0)

    # **And it is on the tab that does own it**, which is what makes the two
    # assertions above about scoping rather than about a proposal that is
    # simply missing everywhere.
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=pulls")
    expect(page.get_by_test_id(f"pull-{proposal['id']}")).to_be_visible(timeout=30000)


def test_a_withdrawn_review_leaves_the_list(page, api) -> None:
    """**The list is open reviews, not history.**

    This is what makes the section finite rather than permanent: every one of
    these ends, nothing creates more, and when the last is decided the section
    goes with it. A list that kept them would be a growing monument to a shape
    the product no longer has.
    """
    mod = project(api, "Direct withdrawn")
    name = f"gone_{uuid.uuid4().hex[:6]}"
    model = make_model(mod, name)
    proposal = propose_typed_change(mod, model, f"Retire {name}", "SELECT 3")

    models_screen(page, mod)
    expect(page.get_by_test_id(f"direct-{proposal['id']}")).to_be_visible(timeout=30000)

    mod.api.call("POST", f"{mod.base}/code/proposals/{proposal['id']}/withdraw", {})
    eventually(
        lambda: mod.api.call("GET", f"{mod.base}/code/proposals?state=open"),
        lambda rows: all(r["id"] != proposal["id"] for r in rows),
        what="the proposal to be closed at the server",
    )

    page.reload()
    expect(page.locator(".table tbody tr").first).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("direct-proposals")).to_have_count(0)
