"""p.114's commit message rule, in the editor (§441; `code-repositories`
p.114).

    "By default commit messages will be auto-generated when clicking the commit
     button or when building a dataset. You can encourage more meaningful
     messages by disabling this option. The commit message dialog will open
     before each commit and require a message to be submitted."

**The divergence, stated once here rather than met as a surprise**: this
platform has never auto-generated a commit message, so there is no option to
disable. What p.114 is steering people *towards* is the requirement, and that
is what the setting turns on — off unless `repoSettings.json` asks, because a
requirement arriving by default would refuse the next commit in every
repository that already exists.

The refusals are `apps/api/tests/test_repository_routes.py`'s and the wording
is `apps/web/src/lib/commit-message.test.ts`'s. What needs a browser is the
sentence p.114 actually cares about — *"before each commit"*. A rule met by a
422 after the press is a rule the writer meets having already lost the moment;
the button has to be closed, and it has to say why.
"""
from __future__ import annotations

import json
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

SETTINGS = json.dumps({
    "commitMessages": {
        "required": True,
        "errorMessage": "Say what changed — the release notes are built from these.",
    }
}, indent=2) + "\n"


def repository(api, name: str, files: dict[str, str]) -> tuple[Module, dict]:
    mod = Module(api, name)
    repo = mod.api.call("POST", f"{mod.base}/repositories",
                        {"name": f"Transforms {mod.tag}"})
    mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": "main", "files": files, "message": "the first cut"},
    )
    return mod, repo


def open_file(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def type_into_editor(page, text: str) -> None:
    """An edit, so the commit bar exists at all — it is drawn only when there
    is work to commit.

    `.view-lines`, not `.monaco-editor textarea`: the textarea sits *under* the
    rendered text and Playwright reports a span intercepting the click. And
    `Control+End`, which reaches the end of the file rather than of a line.
    `test_editor_tabs.py` has the same three findings written out.
    """
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)
    expect(page.get_by_test_id("commit-message")).to_be_visible(timeout=30000)


def commits(mod: Module, repo: dict) -> list[dict]:
    return mod.api.call(
        "GET", f"{mod.base}/repositories/{repo['id']}/commits?branch=main")


@pytest.fixture(scope="module")
def strict(api):
    return repository(api, "Commit strict",
                      {"repoSettings.json": SETTINGS, "src/a.sql": "SELECT 1\n"})


@pytest.fixture(scope="module")
def relaxed(api):
    return repository(api, "Commit relaxed", {"src/a.sql": "SELECT 1\n"})


def test_the_button_is_closed_until_the_message_is_written(page, strict) -> None:
    """p.114's "before each commit". A rule met by a refusal after the press is
    one the writer meets having already lost the moment."""
    mod, repo = strict
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- a change")

    button = page.get_by_role("button", name="Commit to main")
    expect(button).to_be_disabled()

    page.get_by_test_id("commit-message").fill("add a comment")
    expect(button).to_be_enabled()


def test_the_closed_button_says_why_in_the_repositorys_own_words(page, strict) -> None:
    """A disabled button with no reason beside it is the control §214 is about
    — and the sentence is the repository's, because "a commit message is
    required" does not say why the rule exists."""
    mod, repo = strict
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- another change")

    why = page.get_by_test_id("commit-message-why")
    expect(why).to_be_visible(timeout=30000)
    expect(why).to_contain_text("release notes")


def test_a_space_does_not_open_the_button(page, strict) -> None:
    """The browser's rule has to be the server's, or the button opens onto a
    422 (§191)."""
    mod, repo = strict
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- spaces")

    page.get_by_test_id("commit-message").fill("   ")
    expect(page.get_by_role("button", name="Commit to main")).to_be_disabled()


def test_the_field_says_the_message_is_required_where_it_is(page, strict) -> None:
    """Said where somebody is about to type, rather than after (§337)."""
    mod, repo = strict
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- placeholder")
    expect(page.get_by_test_id("commit-message")).to_have_attribute(
        "placeholder", "What changed, and why — this repository requires it")


def test_a_repository_that_does_not_ask_still_commits_without_one(page, relaxed) -> None:
    """**The half that has to be true for the other half to be safe.**

    Every repository in this platform predates the setting, and a requirement
    that arrived by default would refuse the next commit in all of them.
    """
    mod, repo = relaxed
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, f"\n-- {uuid.uuid4().hex[:6]}")

    expect(page.get_by_test_id("commit-message-why")).to_have_count(0)
    button = page.get_by_role("button", name="Commit to main")
    expect(button).to_be_enabled()
    button.click()

    # **The seam.** A button that opened and committed nothing looks the same.
    expect(page.get_by_test_id("commit-message")).to_have_count(0, timeout=30000)
    assert len(commits(mod, repo)) == 2, commits(mod, repo)


def test_the_message_written_to_get_past_the_rule_is_the_one_stored(
    page, strict
) -> None:
    """The rule exists to get a sentence into the history. A gate that let the
    press through and dropped the words would have satisfied every assertion
    above."""
    mod, repo = strict
    open_file(page, repo, "src/a.sql")
    type_into_editor(page, f"\n-- {uuid.uuid4().hex[:6]}")

    said = f"widen the column {uuid.uuid4().hex[:6]}"
    page.get_by_test_id("commit-message").fill(said)
    page.get_by_role("button", name="Commit to main").click()
    expect(page.get_by_test_id("commit-message")).to_have_count(0, timeout=30000)

    assert commits(mod, repo)[0]["message"] == said, commits(mod, repo)[:2]
