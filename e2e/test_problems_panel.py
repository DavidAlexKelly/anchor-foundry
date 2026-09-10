"""p.14's Problems helper (§286; `code-repositories.md` §2.4).

"The Problems helper tells you about any issues detected in your code. Click on
a specific issue listed here to open up the problematic code."

**Everything it reports is something the publish already refuses.** What the
panel changes is *when* you hear about it, and that it names a line rather than
a commit — a refusal at publish time is a refusal hours after the mistake,
about the whole snapshot.

The rules are in `apps/api/tests/test_transform_publish.py` and the wording is
in `apps/web/src/lib/problems.test.ts`. What needs a browser is the second half
of p.14's sentence: that clicking a problem opens the file it is in **and puts
the caret on the line**, which is the only part of this that cannot be checked
without an editor.
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


def open_files(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def show_problems(page) -> None:
    page.get_by_role("button", name="Problems", exact=True).click()
    expect(page.get_by_test_id("problems-summary")).to_be_visible(timeout=20000)


def caret_line(page) -> str:
    """Which line the caret is on, as Monaco's own status renders it.

    Read from the active line number in the margin rather than from a status
    bar, because the editor has no status bar - `.active-line-number` is the
    element Monaco marks, and it is what a person sees highlighted.
    """
    return page.locator(".line-numbers.active-line-number").first.inner_text()


def test_the_panel_reports_a_syntax_error_and_says_it_will_refuse_a_publish(
    page, api
) -> None:
    mod = project(api, "Problems syntax")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"p_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELEC id FROM raw\n",
    })

    open_files(page, repo, "src/t.sql")
    show_problems(page)
    summary = page.get_by_test_id("problems-summary")
    expect(summary).to_contain_text("1 error")
    expect(summary).to_contain_text("refuse a publish")
    expect(page.locator(".repo-problem")).to_have_count(1)
    expect(page.locator(".repo-problem code")).to_have_text("src/t.sql:3")


def test_clicking_a_problem_opens_the_file_and_lands_on_the_line(page, api) -> None:
    """**The second half of p.14's sentence**, and the only part that cannot be
    checked without an editor: "click on a specific issue listed here to open up
    the problematic code".

    A panel that named a line and then left the caret at the top would be a
    panel that made you scroll - which is what it exists to save.
    """
    mod = project(api, "Problems click")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    good = f"g_{uuid.uuid4().hex[:6]}"
    bad = f"b_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/a_fine.sql": f"-- output: {good}\n-- input: raw = {source}\nSELECT id FROM raw\n",
        # The error is deliberately far down the file: landing on it has to be
        # a scroll, not an accident of the file being short.
        "src/z_broken.sql": (
            f"-- output: {bad}\n-- input: raw = {source}\n"
            + "-- padding\n" * 30
            + "SELEC id FROM raw\n"
        ),
    })

    open_files(page, repo, "src/a_fine.sql")
    show_problems(page)
    expect(page.locator(".repo-problem code")).to_have_text("src/z_broken.sql:33")

    page.locator(".repo-problem-open").first.click()
    # The file it names, not the one that was open.
    expect(page.locator(".repo-file-head code")).to_have_text("src/z_broken.sql")
    eventually(lambda: caret_line(page), lambda n: n == "33",
               what="the caret to land on the line the problem names")


def test_a_warning_does_not_claim_to_stop_a_publish(page, api) -> None:
    """A `.sql` file declaring no transform is perfectly legal - a repository
    may hold anything - so this cannot be an error. But a file somebody *meant*
    to be a transform and mistyped the output line of looks exactly the same."""
    mod = project(api, "Problems warning")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {
        "src/t.sql": f"-- output: w_{uuid.uuid4().hex[:6]}\n-- input: raw = {source}\nSELECT id FROM raw\n",
        "src/notes.sql": "SELECT 1\n",
    })

    open_files(page, repo, "src/t.sql")
    show_problems(page)
    summary = page.get_by_test_id("problems-summary")
    expect(summary).to_contain_text("1 warning")
    expect(summary).to_contain_text("nothing here will stop a publish")
    expect(page.locator(".repo-problem.warning")).to_have_count(1)


def test_the_panel_sees_what_has_been_typed_rather_than_what_was_committed(
    page, api
) -> None:
    """**The point of the panel.** The commit is fine; what the author has
    typed is not, and telling them at publish time is telling them too late."""
    mod = project(api, "Problems working")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"w_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })

    open_files(page, repo, "src/t.sql")
    show_problems(page)
    expect(page.get_by_test_id("problems-summary")).to_contain_text("No problems found")

    # Type something that does not parse, then ask again.
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\nSELEC nonsense")
    page.get_by_role("button", name="Hide problems", exact=True).click()
    show_problems(page)
    eventually(lambda: page.get_by_test_id("problems-summary").inner_text(),
               lambda t: "1 error" in t,
               what="the panel to see the uncommitted edit")


def test_a_clean_repository_says_so(page, api) -> None:
    mod = project(api, "Problems clean")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {
        "src/t.sql": f"-- output: c_{uuid.uuid4().hex[:6]}\n-- input: raw = {source}\nSELECT id FROM raw\n",
        "README.md": "# transforms\n",
    })

    open_files(page, repo, "src/t.sql")
    show_problems(page)
    expect(page.get_by_test_id("problems-summary")).to_contain_text("No problems found")
    expect(page.locator(".repo-problem")).to_have_count(0)
