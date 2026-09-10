"""p.14's File Changes helper (§287; `code-repositories.md` §2.4).

"The File Changes helper can be used to view any uncommitted changes to the
current file, as well as compare previous versions of the file."

The diff itself is built by the same aligner the review surface uses — a second
alignment would be a second answer the first time either was improved — and its
rules are in `apps/api/tests/test_transform_publish.py`. The wording and the
context window are in `apps/web/src/lib/file-changes.test.ts`.

What needs a browser is the part neither can hold: that the panel is looking at
what is *in the editor* rather than at what was committed, and that the version
picker changes what it is compared against.
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


def commit(mod: Module, repo: dict, files: dict[str, str], *,
           branch: str = "main", message: str = "a change") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": branch, "files": files, "message": message},
    )


def sql(out: str, source: str, body: str = "SELECT id, total FROM raw") -> str:
    return f"-- output: {out}\n-- input: raw = {source}\n{body}\n"


def open_files(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def show_changes(page) -> None:
    page.get_by_role("button", name="File changes", exact=True).click()
    expect(page.get_by_test_id("file-changes-headline")).to_be_visible(timeout=20000)


def type_into_editor(page, text: str) -> None:
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def test_a_committed_file_with_nothing_typed_says_there_is_nothing(page, api) -> None:
    """"Nothing has changed" and "there is nothing here" are different answers,
    and the panel is read for the first."""
    mod = project(api, "Changes clean")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"src/t.sql": sql(f"c_{uuid.uuid4().hex[:6]}", source)})

    open_files(page, repo, "src/t.sql")
    show_changes(page)
    expect(page.get_by_test_id("file-changes-headline")).to_contain_text(
        "No uncommitted changes"
    )
    expect(page.locator(".repo-diff-row")).to_have_count(0)


def test_the_panel_shows_what_is_in_the_editor_not_what_was_committed(
    page, api
) -> None:
    """**The point of the panel**, and the only part that cannot be checked
    without an editor: it is the *working* file it describes."""
    mod = project(api, "Changes typed")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"src/t.sql": sql(f"t_{uuid.uuid4().hex[:6]}", source)})

    open_files(page, repo, "src/t.sql")
    # **No leading newline.** The committed file ends with one, so Monaco's
    # `Control+End` already puts the caret on an empty last line; typing "\n"
    # first would add a blank line as well and the count would be +2 - correct,
    # and not what this test means to say.
    type_into_editor(page, "-- a line nobody has committed")
    show_changes(page)

    eventually(lambda: page.get_by_test_id("file-changes-headline").inner_text(),
               lambda t: "+1" in t and "−0" in t,
               what="the panel to count the typed line")
    added = page.locator(".repo-diff-row.added")
    expect(added).to_have_count(1)
    expect(added).to_contain_text("a line nobody has committed")


def test_comparing_with_a_previous_version(page, api) -> None:
    """p.14's second half. The picker offers the commits that *changed* this
    file — not every commit on the branch, most of which said nothing about
    it."""
    mod = project(api, "Changes versions")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"v_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {"src/t.sql": sql(out, source)}, message="First version")
    # A commit that says nothing about this file: it must not be offered.
    commit(mod, repo, {"src/t.sql": sql(out, source), "README.md": "# a\n"},
           message="Only the readme")
    commit(mod, repo, {
        "src/t.sql": sql(out, source, body="SELECT id FROM raw"),
        "README.md": "# a\n",
    }, message="Second version")

    open_files(page, repo, "src/t.sql")
    show_changes(page)
    expect(page.get_by_test_id("file-changes-headline")).to_contain_text(
        "No uncommitted changes"
    )

    picker = page.get_by_label("Compare with")
    options = picker.locator("option")
    expect(options).to_have_count(3)  # the latest, plus the two that changed it
    texts = options.all_inner_texts()
    assert any("First version" in t for t in texts), texts
    assert any("Second version" in t for t in texts), texts
    assert not any("Only the readme" in t for t in texts), texts

    first = next(t for t in texts if "First version" in t)
    picker.select_option(label=first)
    eventually(lambda: page.get_by_test_id("file-changes-headline").inner_text(),
               lambda t: "+1" in t and "−1" in t,
               what="the diff against the older version")
    expect(page.locator(".repo-diff-row.changed")).to_have_count(1)


def test_a_file_that_was_never_committed_says_so_rather_than_offering_nothing(
    page, api
) -> None:
    """A file that has never been committed has no previous versions, which is
    a different answer from a file whose history this branch does not have."""
    mod = project(api, "Changes new file")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"src/t.sql": sql(f"n_{uuid.uuid4().hex[:6]}", source)})

    open_files(page, repo, "src/t.sql")
    page.once("dialog", lambda d: d.accept("src/brand-new.sql"))
    page.get_by_role("button", name="New file", exact=True).click()
    expect(page.locator(".repo-file-head code")).to_have_text("src/brand-new.sql")

    show_changes(page)
    expect(page.get_by_test_id("file-changes-versions-empty")).to_contain_text(
        "not committed yet"
    )


def test_the_version_list_is_this_branchs_history(page, api) -> None:
    """A branch's history is *its* history, and the picker is a view of it.

    Asserted in the browser as well as against the API because what is under
    test here is the *wiring*: a panel that asked for versions without saying
    which branch it was on would get the default branch's, and on `main` - the
    branch every other test in this file uses - that is the same answer.
    """
    mod = project(api, "Changes branchy")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"b_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {"src/t.sql": sql(out, source)}, message="On main")
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "side", "from_branch": "main"})
    commit(mod, repo, {"src/t.sql": sql(out, source, body="SELECT id FROM raw")},
           branch="side", message="On the sandbox")

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/t.sql&branch=side")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    show_changes(page)
    texts = page.get_by_label("Compare with").locator("option").all_inner_texts()
    assert any("On the sandbox" in t for t in texts), texts
    assert any("On main" in t for t in texts), texts

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/t.sql&branch=main")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    show_changes(page)
    on_main = page.get_by_label("Compare with").locator("option").all_inner_texts()
    assert not any("On the sandbox" in t for t in on_main), on_main


def test_opening_another_file_forgets_the_version_that_was_chosen(page, api) -> None:
    """**A commit chosen for one file is not an answer about another.**

    The picker's options come from *this* file's history, so a selection kept
    across a file switch would leave the control showing "the latest commit"
    while comparing against something else - a control that lies about what it
    is doing, which is worse than one that forgets.
    """
    mod = project(api, "Changes reset")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    a, b = f"a_{uuid.uuid4().hex[:6]}", f"b_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {"src/a.sql": sql(a, source)}, message="First a")
    commit(mod, repo, {
        "src/a.sql": sql(a, source, body="SELECT id FROM raw"),
        "src/b.sql": sql(b, source),
    }, message="Second a and first b")

    open_files(page, repo, "src/a.sql")
    show_changes(page)
    picker = page.get_by_label("Compare with")
    first = next(t for t in picker.locator("option").all_inner_texts() if "First a" in t)
    picker.select_option(label=first)
    eventually(lambda: page.get_by_test_id("file-changes-headline").inner_text(),
               lambda t: "+1" in t, what="the diff against the older version of a.sql")

    page.locator(".repo-tree").get_by_role("button", name="src/b.sql").click()
    expect(page.locator(".repo-file-head code")).to_have_text("src/b.sql")
    # Back to the latest, rather than still pointing at a commit chosen for a
    # different file.
    eventually(lambda: page.get_by_label("Compare with").input_value(),
               lambda v: v == "",
               what="the comparison to reset to the latest commit")
    expect(page.get_by_test_id("file-changes-headline")).to_contain_text(
        "No uncommitted changes"
    )
