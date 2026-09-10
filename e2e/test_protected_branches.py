"""Protected branches and the sandbox rule (§284; `code-repositories.md` §2.1).

p.12: "To edit code in your repository, you must work in a sandbox branch —
protected branches cannot be directly edited." The spec calls it "the one to
take seriously… it is what makes the Pull requests tab load-bearing rather than
optional".

**Protection is the review gate, not a second switch.** A repository's default
branch is protected exactly when its project requires review — the choice §279's
Settings tab already states out loud, and the one §278 is the reason to make:
two controls for a rule that means the same thing is how they start to disagree.

The rules are in `apps/web/src/lib/protected-branches.test.ts` and the refusal
is in `apps/api/tests/test_transform_publish.py`. What needs a browser is the
part neither can hold: that somebody who types on a protected branch is offered
a branch that can take the work, rather than an error after the fact.
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


def review(mod: Module, on: bool) -> None:
    mod.api.call("PUT", f"{mod.base}/code/review-policy", {"require_code_review": on})


def branches(mod: Module, repo: dict) -> list[str]:
    return [b["name"] for b in
            mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/branches")]


def head_of(mod: Module, repo: dict, name: str) -> str | None:
    rows = mod.api.call("GET", f"{mod.base}/repositories/{repo['id']}/branches")
    row = next((b for b in rows if b["name"] == name), None)
    return row["head_commit_id"] if row else None


def open_file(page, repo: dict, path: str, *, branch: str | None = None) -> None:
    ref = f"&branch={branch}" if branch else ""
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}{ref}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def type_into_editor(page, text: str) -> None:
    """Put the caret in Monaco and type (§281's three findings)."""
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def a_repository_with_one_transform(api, name: str):
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"p_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    return mod, repo


def test_a_protected_branch_says_why_and_names_the_way_through(page, api) -> None:
    """A refusal that only says no teaches people the product is broken."""
    mod, repo = a_repository_with_one_transform(api, "Protected note")
    review(mod, True)

    open_file(page, repo, "src/t.sql")
    note = page.get_by_test_id("protected-branch")
    expect(note).to_be_visible(timeout=30000)
    expect(note).to_contain_text("main is protected")
    expect(note).to_contain_text("requires code review")
    expect(note).to_contain_text("sandbox branch")
    # §283 is what makes working on a sandbox not a detour, and the note says so.
    expect(note).to_contain_text("moves main to your commit")


def test_an_ungated_project_shows_no_note_and_commits_to_its_default_branch(
    page, api
) -> None:
    """Protection *is* the gate. A note that appeared regardless would be a
    second switch, and the Settings tab's description would stop matching."""
    mod, repo = a_repository_with_one_transform(api, "Protected off")

    open_file(page, repo, "src/t.sql")
    expect(page.get_by_test_id("protected-branch")).to_have_count(0)
    type_into_editor(page, "\n-- straight onto main")
    expect(page.get_by_role("button", name="Commit to main")).to_be_visible()


def test_typing_on_a_protected_branch_is_kept_and_offered_a_branch_to_go_to(
    page, api
) -> None:
    """**The alternative was a read-only editor, and it is worse.**

    People open a file, edit it, and think about branches afterwards. An editor
    that refused the typing would be right about the rule and wrong about the
    work; §214 asks not to take typing you will refuse to keep, so the typing is
    kept - on a branch that can hold it.
    """
    mod, repo = a_repository_with_one_transform(api, "Protected commit")
    review(mod, True)
    before = head_of(mod, repo, "main")

    open_file(page, repo, "src/t.sql")
    # **Wait for the note before typing.** The policy is a second query, and
    # until it answers the screen is showing an unprotected branch - so a test
    # that types straight away is acting on a state that is about to change
    # underneath it, which is §282's finding in another costume.
    expect(page.get_by_test_id("protected-branch")).to_be_visible(timeout=30000)
    type_into_editor(page, "\n-- work that needs a branch")
    page.get_by_label("Commit message").fill("Add a note")
    page.get_by_test_id("commit-to-sandbox").click()

    # A branch appeared, it holds the commit, and `main` did not move.
    eventually(lambda: branches(mod, repo), lambda b: "sandbox-1" in b,
               what="the sandbox branch to be created")
    assert head_of(mod, repo, "main") == before
    assert head_of(mod, repo, "sandbox-1") != before

    files = mod.api.call(
        "GET", f"{mod.base}/repositories/{repo['id']}/tree?branch=sandbox-1"
    )["files"]
    assert "-- work that needs a branch" in files["src/t.sql"], files["src/t.sql"]

    # And the editor followed the work rather than leaving it behind.
    #
    # **`page.wait_for_url`, not `eventually(lambda: page.url, ...)`.** `page.url`
    # is a cached value that Playwright updates when its driver processes a
    # navigation event, and `eventually` polls in a tight loop that never gives
    # the driver a turn - so it reads the same stale string for the whole
    # timeout and reports that nothing happened when the address bar had
    # changed seconds earlier. Cost a probe: the same click, with a
    # `wait_for_timeout` instead of a poll, passed every time.
    page.wait_for_url("**branch=sandbox-1", timeout=20000)
    expect(page.get_by_test_id("protected-branch")).to_have_count(0)


def test_the_second_sandbox_does_not_collide_with_the_first(page, api) -> None:
    """Offering a name the create endpoint refuses would turn a helpful default
    into an error somebody has to read and undo."""
    mod, repo = a_repository_with_one_transform(api, "Protected twice")
    review(mod, True)
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "sandbox-1", "from_branch": "main"})

    open_file(page, repo, "src/t.sql")
    type_into_editor(page, "\n-- the second one")
    page.get_by_label("Commit message").fill("Another note")
    page.get_by_test_id("commit-to-sandbox").click()

    eventually(lambda: branches(mod, repo), lambda b: "sandbox-2" in b,
               what="the next free sandbox name to be used")
