"""Several files open at once (§282; `code-repositories.md` §2.3).

The spec calls tabs "the single biggest thing making ours feel unlike an IDE",
and put them *second* in build-order item 2 for a reason it stated: "tabs are
what make the loss expensive". §281 shipped persistence first and the order
paid twice — it found a bug tabs would have multiplied, and it is why the open
set needs no store of its own here.

The rules are in `apps/web/src/lib/editor-tabs.test.ts`. What needs a browser
is the part no pure function can hold:

  * that a reload **rebuilds** the strip from the drafts rather than restoring
    it from a second store that could disagree;
  * that closing a tab with unsaved work in it keeps the work — the strip and
    the working set are two views of one thing, and this is where they could
    come apart;
  * that a deleted file's tab goes with it.
"""
from __future__ import annotations

import uuid

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually, stays


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


def three_files(mod: Module, repo: dict) -> dict[str, str]:
    """A repository with three transforms, so a strip has something to be."""
    source = dataset(mod, f"orders_{mod.tag}")
    files = {}
    for name in ("a", "b", "c"):
        out = f"{name}_{uuid.uuid4().hex[:6]}"
        files[f"src/{name}.sql"] = (
            f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n"
        )
    commit(mod, repo, files)
    return files


def open_file(page, repo: dict, path: str, *, branch: str | None = None) -> None:
    ref = f"&branch={branch}" if branch else ""
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}{ref}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def tab_names(page) -> list[str]:
    return page.locator(".repo-tabs-strip [role=tab]").all_inner_texts()


def tree_file(page, path: str):
    """A file in the tree, by path.

    **Scoped to the tree, and not an exact name match**, because neither works
    alone: a file with unsaved work gets a brass dot from `.repo-file.edited`
    and Chromium folds `::after` content into the accessible name, so
    `exact=True` stops matching the moment somebody types; and a loose match
    picks up the tab's own close button, whose label contains the same path.
    """
    return page.locator(".repo-tree").get_by_role("button", name=path)


def open_from_tree(page, path: str) -> None:
    """Click a file in the tree, and wait for the editor to be showing it.

    **The strip gains the tab before the selection moves**, and that is not a
    bug to design around: `?file=` is the single source of truth for what is
    open (`use-url-state.tsx`), and `router.replace` does not land
    synchronously, so for a moment the new tab is present while the previous
    file is still highlighted and still in the editor. What is on screen stays
    consistent throughout - which is exactly why a test that acts on the click
    alone is testing a state no person is ever looking at. Two of these went
    wrong before this helper existed: one typed into the file it had just
    navigated away from, and one deleted it.
    """
    tree_file(page, path).click()
    expect(page.locator(".repo-file-head code")).to_have_text(path, timeout=20000)


def type_into_editor(page, text: str) -> None:
    """Put the caret in Monaco and type (the three findings from §281).

    Clicking `.monaco-editor textarea` fails - it sits *under* the rendered
    text and Playwright reports a span intercepting pointer events - so
    `.view-lines` is the layer to click; and `Control+End` rather than `End`,
    which only reaches the end of a line.
    """
    page.locator(".view-lines").first.click()
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def editor_text(page) -> str:
    """What the editor shows, with Monaco's U+00A0 spaces normalised."""
    return page.locator(".view-lines").first.inner_text().replace("\xa0", " ")


def test_opening_a_second_file_keeps_the_first(page, api) -> None:
    """**The unit, in one test.** Before this, opening `b.sql` was how you
    stopped having `a.sql` open."""
    mod = project(api, "Tabs open")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql"],
               what="the first file to take a tab")

    open_from_tree(page, "src/b.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql"],
               what="the second file to open beside the first")

    # And clicking back is a click, not a reload of the file from the server.
    page.locator(".repo-tabs-strip [role=tab]").first.click()
    expect(page.locator(".repo-tab.on [role=tab]")).to_have_text("a.sql")


def test_closing_the_active_tab_moves_to_the_neighbour(page, api) -> None:
    """**The one to the right, falling back to the left.**

    People close tabs working forwards through a list, and landing back on the
    first tab every time would throw them to the start of the list they are
    working through. Asserted in the browser and not only in
    `editor-tabs.test.ts` because the selection is the *URL*, and the rule is
    only real if the close hands the URL the neighbour's path.
    """
    mod = project(api, "Tabs neighbour")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    open_from_tree(page, "src/b.sql")
    open_from_tree(page, "src/c.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql", "c.sql"],
               what="three tabs")

    open_from_tree(page, "src/b.sql")
    page.get_by_role("button", name="Close src/b.sql", exact=True).click()
    expect(page.locator(".repo-file-head code")).to_have_text("src/c.sql")
    expect(page.locator(".repo-tab.on [role=tab]")).to_have_text("c.sql")

    # And the last tab falls back to the left, since there is no right.
    page.get_by_role("button", name="Close src/c.sql", exact=True).click()
    expect(page.locator(".repo-file-head code")).to_have_text("src/a.sql")


def test_a_clean_tabs_close_button_does_not_claim_to_keep_work(page, api) -> None:
    """The other half of the label, and the half that makes it mean something.

    A close button that said "keeps your unsaved changes" on every tab would be
    noise on the tabs that have none, and would stop being read on the one that
    does.
    """
    mod = project(api, "Tabs clean label")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    open_from_tree(page, "src/b.sql")
    type_into_editor(page, "\n-- only b is dirty")
    eventually(lambda: editor_text(page), lambda t: "-- only b is dirty" in t,
               what="the typing to land in b")

    # `exact=True` is doing the work: the dirty label *contains* this one.
    expect(page.get_by_role("button", name="Close src/a.sql", exact=True)).to_be_visible()
    expect(
        page.get_by_role("button", name="Close src/b.sql (keeps your unsaved changes)")
    ).to_be_visible()


def test_a_link_to_a_file_this_tree_does_not_have_opens_no_tab(page, api) -> None:
    """A tab pointing at nothing renders an empty editor, which reads as a file
    whose contents failed to load.

    The link is the way to arrive at one: a stale bookmark, a path that was
    deleted, a branch that never had it. The strip is pruned against the tree
    on every render for this, and the pane says which empty it is.
    """
    mod = project(api, "Tabs stale link")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/never-existed.sql")
    expect(page.get_by_role("button", name="Files")).to_be_visible(timeout=30000)
    stays(lambda: tab_names(page), lambda t: t == [],
          what="no tab for a file that is not there")
    expect(page.locator(".repo-viewer .state")).to_have_text(
        "No file open. Choose one from the tree."
    )


def test_closing_a_tab_with_unsaved_work_keeps_the_work(page, api) -> None:
    """**Where the strip and the working set could come apart.**

    A tab is a view, not a container: the draft lives in the working set and in
    storage. So closing a tab with unsaved changes in it does *not* discard
    them - which has to be true, because the commit that follows will include
    them, and it has to be *said*, because somebody closing a tab meaning "undo
    this" would otherwise commit work they thought they had thrown away.
    """
    mod = project(api, "Tabs close")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- unsaved and about to be closed")
    eventually(lambda: editor_text(page),
               lambda t: "-- unsaved and about to be closed" in t,
               what="the typing to land")

    # The close button says what it does before it is pressed.
    close = page.get_by_role("button", name="Close src/a.sql (keeps your unsaved changes)")
    expect(close).to_be_visible()
    close.click()

    eventually(lambda: tab_names(page), lambda t: t == [],
               what="the tab to close")
    # The commit bar is the proof the edit is still in the working set: it
    # counts changed files, and it is counting this one.
    expect(page.locator(".repo-dirty")).to_contain_text("1 file changed")

    # And reopening it shows the work, rather than the committed file.
    #
    # **This click is also the regression test for a race it found.** Reopening
    # immediately, before `router.replace` has landed, means `?file=` reads
    # `src/a.sql` the whole way through - cleared and set again inside a window
    # React never observes - so the effect keyed on it never fired and the tab
    # never came back, while the address bar went on naming the file. Do not
    # add a wait here: the wait is what hid it.
    open_from_tree(page, "src/a.sql")
    eventually(lambda: editor_text(page),
               lambda t: "-- unsaved and about to be closed" in t,
               what="the draft to still be there")


def test_a_reload_reopens_the_files_with_unsaved_work(page, api) -> None:
    """**The strip is rebuilt, not restored.**

    Everything expensive in it is already persisted, so there is no second
    store for the open set - which means there is no second store that can come
    back disagreeing with the first about what somebody was doing. What returns
    is a tab for every file with uncommitted work, plus the one the link names.
    """
    mod = project(api, "Tabs reload")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    type_into_editor(page, "\n-- work in a")
    eventually(lambda: editor_text(page), lambda t: "-- work in a" in t,
               what="the typing in a.sql to land")

    open_from_tree(page, "src/b.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql"],
               what="b.sql to open")
    type_into_editor(page, "\n-- work in b")
    eventually(lambda: editor_text(page), lambda t: "-- work in b" in t,
               what="the typing in b.sql to land")

    # `c.sql` is opened and *not* edited, which is the file the rebuild is
    # allowed to forget.
    open_from_tree(page, "src/c.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql", "c.sql"],
               what="c.sql to open")

    open_file(page, repo, "src/a.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql"],
               what="the two files with work in them to come back")
    eventually(lambda: editor_text(page), lambda t: "-- work in a" in t,
               what="a.sql's draft to survive")


def test_deleting_a_file_takes_its_tab_with_it(page, api) -> None:
    """A tab pointing at nothing renders an empty editor, which reads as a file
    whose contents failed to load."""
    mod = project(api, "Tabs delete")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)

    open_file(page, repo, "src/a.sql")
    open_from_tree(page, "src/b.sql")
    open_from_tree(page, "src/c.sql")
    open_from_tree(page, "src/b.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql", "c.sql"],
               what="three tabs, with the middle one selected")

    page.get_by_role("button", name="Delete file", exact=True).click()
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "c.sql"],
               what="the deleted file's tab to go")
    stays(lambda: tab_names(page), lambda t: "b.sql" not in t,
          what="the deleted file staying gone")
    # **And it lands on the neighbour**, which is the part the pruning does not
    # do for free: a deleted file leaves the working set on its own, so its tab
    # goes either way, but without the close the selection drops to the first
    # tab rather than to the one beside it.
    expect(page.locator(".repo-file-head code")).to_have_text("src/c.sql")


def test_the_strip_does_not_follow_you_to_another_branch(page, api) -> None:
    """The same path on two branches is two files (§281), and the strip is
    seeded from the drafts, so it is keyed by branch for free."""
    mod = project(api, "Tabs branch")
    repo = repository(mod, f"Transforms {mod.tag}")
    three_files(mod, repo)
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "sandbox", "from_branch": "main"})

    open_file(page, repo, "src/a.sql")
    open_from_tree(page, "src/b.sql")
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql", "b.sql"],
               what="two tabs on main")

    open_file(page, repo, "src/a.sql", branch="sandbox")
    # Only the file the link names: neither file has work on this branch.
    eventually(lambda: tab_names(page), lambda t: t == ["a.sql"],
               what="the other branch to open only what was asked for")
