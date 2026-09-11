"""Tags on the Branches tab (§299; `code-repositories.md` §3, p.17).

    "The branches tab also lets you access a list of tags, which are like
     immutable branches. A tag can be used to mark a significant version of the
     code for future reference by giving it a version number or name. To create
     a new tag, navigate to the tags section of the branches tab and click the
     'New Tag' button. A tag can be created from the current version of a
     branch, or from any arbitrary commit." (p.17)

The wording rules are in `apps/web/src/lib/tags.test.ts` and the refusals are in
`apps/api/tests/test_repository_routes.py` — including `repoSettings.json`'s
`tagNameValidation`, which is **the first thing in this platform to read that
file**. What needs a browser is that the section is where p.17 says it is, that
a tag survives the branch moving on, and that the repository's own error message
reaches the person typing.
"""
from __future__ import annotations

import json
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

SEMVER_SETTINGS = json.dumps({
    # p.17's own example, verbatim.
    "tagNameValidation": {
        "regex": r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-rc\d+)?$",
        "errorMessage": "Tag name must have the format x.x.x or x.x.x-rcx.",
    }
})


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def commit(mod: Module, repo: dict, files: dict[str, str], message: str = "a change") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": message},
    )


def open_branches(page, repo: dict) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=branches")
    expect(page.get_by_test_id("tags-section")).to_be_visible(timeout=30000)


def test_a_tag_is_made_on_the_branches_tab_and_survives_the_branch_moving_on(
    page, api
) -> None:
    """**"Like immutable branches", and the second half of that is the point.**

    A branch is a name whose commit moves; a tag is a name whose commit does
    not. Asserted by moving the branch afterwards and looking again — a test
    that only made a tag would pass against an implementation that stored a
    branch name.
    """
    mod = project(api, "Tag made")
    repo = repository(mod, f"Transforms {mod.tag}")
    first = commit(mod, repo, {"src/a.sql": "SELECT 1\n"}, "the first cut")

    open_branches(page, repo)
    expect(page.get_by_test_id("tags-empty")).to_contain_text("never moves")

    page.get_by_test_id("tag-name").fill("1.0.0")
    page.get_by_test_id("tag-message").fill("shipped to acme")
    page.get_by_test_id("tag-create").click()

    row = page.get_by_test_id("tag-1.0.0")
    expect(row).to_be_visible(timeout=30000)
    # The commit, in the same eight characters the History tab uses, and the
    # tag's own message rather than the commit's - somebody who wrote down why
    # this version mattered has said something the commit message does not.
    expect(page.get_by_test_id("tags-list")).to_contain_text(first["id"][:8])
    expect(page.get_by_test_id("tags-list")).to_contain_text("shipped to acme")

    # **The branch moves; the tag does not.**
    commit(mod, repo, {"src/a.sql": "SELECT 2\n"}, "and on we go")
    page.reload()
    expect(page.get_by_test_id("tag-1.0.0")).to_be_visible(timeout=30000)
    expect(page.get_by_test_id("tags-list")).to_contain_text(first["id"][:8])


def test_the_repositorys_own_error_message_reaches_the_person_typing(page, api) -> None:
    """p.17's `tagNameValidation`, with its `errorMessage`.

    **The repository's sentence, not ours.** It was written by somebody for
    their colleagues, and a platform that replaced it with "invalid tag name"
    would throw away the only part of the refusal that helps.
    """
    mod = project(api, "Tag convention")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"repoSettings.json": SEMVER_SETTINGS, "src/a.sql": "SELECT 1\n"})

    open_branches(page, repo)
    page.get_by_test_id("tag-name").fill("release-candidate")
    page.get_by_test_id("tag-create").click()
    expect(page.get_by_test_id("tag-failure")).to_contain_text(
        "Tag name must have the format x.x.x", timeout=30000
    )

    # And a name that matches is taken, so the refusal is about the convention
    # rather than about tagging being broken.
    page.get_by_test_id("tag-name").fill("1.4.0-rc2")
    page.get_by_test_id("tag-create").click()
    expect(page.get_by_test_id("tag-1.4.0-rc2")).to_be_visible(timeout=30000)


def test_a_name_the_column_cannot_hold_is_refused_before_a_round_trip(page, api) -> None:
    """The floor db 0072 puts on the column — **not** the repository's
    convention, which is read from the commit being tagged and which the browser
    does not have. A second copy of that regex here would disagree with the file
    the first time somebody edited it."""
    mod = project(api, "Tag shape")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": "SELECT 1\n"})

    open_branches(page, repo)
    page.get_by_test_id("tag-name").fill("-leading-dash")
    expect(page.get_by_test_id("tag-name-problem")).to_contain_text(
        "starts with a letter or digit"
    )
    expect(page.get_by_test_id("tag-create")).to_be_disabled()

    # And an empty box says nothing at all: a form that turns red before you
    # have done anything wrong is a form people learn to ignore.
    page.get_by_test_id("tag-name").fill("")
    expect(page.get_by_test_id("tag-name-problem")).to_have_count(0)


def test_deleting_a_tag_asks_first_and_says_what_is_not_at_risk(page, api) -> None:
    """p.17 warns about deleting *branches* because that can lose work. A tag
    cannot — the commit is held by `ON DELETE RESTRICT` and is exactly as safe
    afterwards — so the confirmation says so rather than borrowing the branch
    warning's weight for a much smaller act."""
    mod = project(api, "Tag delete")
    repo = repository(mod, f"Transforms {mod.tag}")
    commit(mod, repo, {"src/a.sql": "SELECT 1\n"})

    open_branches(page, repo)
    page.get_by_test_id("tag-name").fill("2.0.0")
    page.get_by_test_id("tag-create").click()
    expect(page.get_by_test_id("tag-2.0.0")).to_be_visible(timeout=30000)

    asked: list[str] = []

    def refuse(dialog):
        asked.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", refuse)
    page.get_by_test_id("tag-delete-2.0.0").click()
    expect(page.get_by_test_id("tag-2.0.0")).to_be_visible()
    assert asked and "stays exactly where it is" in asked[0], asked

    page.once("dialog", lambda d: d.accept())
    page.get_by_test_id("tag-delete-2.0.0").click()
    expect(page.get_by_test_id("tag-2.0.0")).to_have_count(0, timeout=30000)
    # And the tag having gone did not take the code with it.
    expect(page.get_by_test_id("tags-empty")).to_be_visible()


def test_an_empty_repository_is_not_offered_the_form(page, api) -> None:
    """Two absences with two remedies, and only one is something the reader can
    do here. A repository with nothing committed has no version to mark, and the
    server would refuse anyway — saying it first is the difference between a
    form that explains and one that argues."""
    mod = project(api, "Tag empty")
    repo = repository(mod, f"Transforms {mod.tag}")

    open_branches(page, repo)
    expect(page.get_by_test_id("tags-empty")).to_contain_text("no version to tag")
    expect(page.get_by_test_id("tag-create")).to_have_count(0)
