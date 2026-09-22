"""The command palette (§428; `code-repositories` p.11).

    "To expose keyboard shortcuts via the command palette, use the F1 key in
     Windows or Fn+F1 on macOS."

What a query matches and where the highlight lands is arithmetic, and it is
proved in `apps/web/src/lib/command-palette.test.ts` and
`repository-commands.test.ts`. What needs a browser is the half no pure
function can hold:

  * that F1 reaches the palette at all — the binding is on the window, and a
    listener that was never attached is a feature nobody can open;
  * that the arrows move a highlight a reader can *see*, and Enter runs the
    row they were looking at rather than the one under some index;
  * that Escape leaves without running anything, which is the only way out
    that has to be safe;
  * and that Monaco keeps its own palette — the editor binds F1 too, and two
    palettes over one keystroke is the bug the `defaultPrevented` line in
    `opensPalette` exists to prevent.
"""
from __future__ import annotations

from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually, stays


def project(api, name: str) -> Module:
    return Module(api, name)


def repository(mod: Module, name: str) -> dict:
    return mod.api.call("POST", f"{mod.base}/repositories", {"name": name})


def commit(mod: Module, repo: dict, files: dict[str, str], *, branch: str = "main") -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/repositories/{repo['id']}/commits",
        {"branch": branch, "files": files, "message": "a change"},
    )


# **Three names beginning with `z`, and two of them sharing `beta`.** The
# palette's list is everything this page can do, so a query has to be one no
# tab label, branch name or group word answers, or a test that thinks it is
# looking at three files is looking at nine commands. `z` is that query here,
# and `zb` is the narrowing that keeps the last two.
FILES = {
    "z1.md": "# one\n",
    "z2beta.md": "# two\n",
    "z3beta.md": "# three\n",
}


def a_repository(api, name: str) -> dict:
    mod = project(api, name)
    repo = repository(mod, f"Transforms {mod.tag}")
    made = commit(mod, repo, FILES)
    return {**repo, "commit_id": made["id"]}


def open_repo(page, repo: dict, *, tab: str = "files") -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab={tab}")
    expect(page.get_by_test_id("open-command-palette")).to_be_visible(timeout=30000)


def palette(page):
    return page.get_by_test_id("command-palette")


def rows(page) -> list[str]:
    return [
        r.get_attribute("data-command") or ""
        for r in page.get_by_test_id("command-row").all()
    ]


def highlighted(page) -> str | None:
    hit = page.locator("[data-testid=command-row][data-highlighted=true]")
    return hit.first.get_attribute("data-command") if hit.count() else None


def current_tab(page) -> str:
    return page.locator(".repo-tabs .ds-tab.on").inner_text()


def open_palette(page) -> None:
    """F1, which is what p.11 names — not the button beside it.

    The button exists so the palette is findable with a mouse, but it is not
    what this page cites, and a suite that only ever clicked it would pass
    with the key binding deleted.
    """
    page.keyboard.press("F1")
    expect(palette(page)).to_be_visible(timeout=10000)


def test_f1_opens_the_palette(page, api) -> None:
    """**The unit, in one keystroke.**

    The listener is attached to the window rather than to a focused element,
    so this presses F1 with focus wherever the page left it — which is the
    claim: a reader who has just clicked the file tree can reach the palette
    without clicking back into anything.
    """
    repo = a_repository(api, "Palette opens")
    open_repo(page, repo)

    expect(palette(page)).to_have_count(0)
    open_palette(page)
    expect(page.get_by_test_id("command-query")).to_be_focused()


def test_f1_is_taken_from_the_browser(page, api) -> None:
    """**The keystroke is consumed, not shared.**

    Chrome and Firefox both open their own help on F1. Without
    `preventDefault` the palette appears underneath a browser window nobody
    asked for — which no assertion about the page can see, so this asks the
    event itself: a listener added *after* the palette's own runs after it,
    and reads the flag it set.
    """
    repo = a_repository(api, "Palette preventDefault")
    open_repo(page, repo)

    page.evaluate(
        "window.__f1 = [];"
        "window.addEventListener('keydown', (e) => {"
        "  if (e.key === 'F1') window.__f1.push(e.defaultPrevented);"
        "});"
    )
    open_palette(page)
    assert page.evaluate("window.__f1") == [True]


def test_clicking_a_row_runs_it(page, api) -> None:
    """The mouse reaches the same commands the keyboard does.

    Worth a test of its own because the rows run on `mousedown` rather than
    `click` — the click would first blur the query box, and a palette that
    closed on blur would take the row out of the document before the click
    landed on it.
    """
    repo = a_repository(api, "Palette clicking")
    open_repo(page, repo)

    open_palette(page)
    page.locator("[data-testid=command-row][data-command='tab:branches']").click()

    expect(palette(page)).to_have_count(0)
    eventually(lambda: current_tab(page), lambda t: t == "Branches",
               what="the clicked command to move the page to its tab")


def test_a_row_runs_without_a_mouse_press(page, api) -> None:
    """**Activation, not a mouse gesture.**

    A row reached by assistive technology is activated with a `click` and
    nothing else — no `mousedown`, no `mouseup`. `dispatch_event` sends
    exactly that one event, which a real `.click()` cannot isolate, and it is
    the whole difference between the rows being reachable by everybody and
    being reachable by a mouse and the Enter key.
    """
    repo = a_repository(api, "Palette activation")
    open_repo(page, repo)

    open_palette(page)
    page.locator(
        "[data-testid=command-row][data-command='tab:checks']"
    ).dispatch_event("click")

    eventually(lambda: current_tab(page), lambda t: t == "Checks",
               what="the activated command to move the page to its tab")


def test_enter_runs_the_highlighted_command(page, api) -> None:
    """Typing a command's name and pressing Enter is the whole palette."""
    repo = a_repository(api, "Palette runs")
    open_repo(page, repo)
    assert current_tab(page) == "Files"

    open_palette(page)
    page.keyboard.type("checks")
    eventually(lambda: rows(page), lambda r: r[:1] == ["tab:checks"],
               what="the Checks tab to come top of the list")
    page.keyboard.press("Enter")

    expect(palette(page)).to_have_count(0)
    eventually(lambda: current_tab(page), lambda t: t == "Checks",
               what="the command to move the page to its tab")


def test_the_arrows_move_the_highlight(page, api) -> None:
    """A highlight is a promise about what Enter will do, so it has to be
    visible — `data-highlighted` is the attribute the row is styled from."""
    repo = a_repository(api, "Palette arrows")
    open_repo(page, repo)

    open_palette(page)
    page.keyboard.type("z")
    eventually(lambda: rows(page),
               lambda r: r == ["file:z1.md", "file:z2beta.md", "file:z3beta.md"],
               what="the three files to be the whole list")

    # The first row starts highlighted, because there is always something for
    # Enter to run.
    assert highlighted(page) == "file:z1.md"
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert highlighted(page) == "file:z3beta.md"
    # And it wraps: three rows is short enough that stopping at the end reads
    # as the key not working.
    page.keyboard.press("ArrowDown")
    assert highlighted(page) == "file:z1.md"
    page.keyboard.press("ArrowUp")
    assert highlighted(page) == "file:z3beta.md"


def test_the_highlight_follows_the_command_not_the_row(page, api) -> None:
    """**The one bug a palette must not have.**

    The reader highlights the third row, types one more letter, and the first
    row disappears. A palette that remembered "row 3" would move the highlight
    to whatever landed there — and Enter would open a file nobody was looking
    at. Here the third row becomes the second and keeps the highlight.
    """
    repo = a_repository(api, "Palette highlight")
    open_repo(page, repo)

    open_palette(page)
    page.keyboard.type("z")
    eventually(lambda: rows(page), lambda r: len(r) == 3,
               what="all three files to match")
    page.keyboard.press("ArrowDown")
    page.keyboard.press("ArrowDown")
    assert highlighted(page) == "file:z3beta.md"

    page.keyboard.type("b")
    eventually(lambda: rows(page), lambda r: r == ["file:z2beta.md", "file:z3beta.md"],
               what="the narrower query to drop the first file")
    assert highlighted(page) == "file:z3beta.md"

    page.keyboard.press("Enter")
    eventually(lambda: page.locator(".repo-file-head code").inner_text(),
               lambda t: t == "z3beta.md",
               what="the file the reader was looking at to open")


def test_escape_leaves_without_running_anything(page, api) -> None:
    """The only way out that has to be safe.

    A positive wait — the palette is gone — before the negative one, so "the
    tab did not change" is not a sentence about a page that had not rendered
    yet (§318).
    """
    repo = a_repository(api, "Palette escape")
    open_repo(page, repo)

    open_palette(page)
    page.keyboard.type("checks")
    eventually(lambda: rows(page), lambda r: r[:1] == ["tab:checks"],
               what="a command to be highlighted and ready to run")
    page.keyboard.press("Escape")
    expect(palette(page)).to_have_count(0)

    stays(lambda: current_tab(page), lambda t: t == "Files",
          what="the tab Escape did not change")


def test_a_command_that_cannot_run_says_why(page, api) -> None:
    """**Disabled and present, rather than absent.**

    A reader on the Files tab who types "files" and finds nothing learns that
    the palette is broken. One who finds a greyed row saying "already here"
    learns where they are (§214).
    """
    repo = a_repository(api, "Palette disabled")
    open_repo(page, repo)

    open_palette(page)
    page.keyboard.type("files")
    row = page.locator("[data-testid=command-row][data-command='tab:files']")
    expect(row).to_be_visible()
    expect(row).to_be_disabled()
    expect(row.locator(".command-note")).to_have_text("already here")

    # And Enter over it does nothing at all - it does not close the palette
    # either, because a box that vanished would read as a command that ran.
    page.keyboard.press("Enter")
    stays(lambda: palette(page).count(), lambda n: n == 1,
          what="the palette a refused command left open")


def test_a_file_opens_from_another_tab(page, api) -> None:
    """Opening a file is a file *and* a tab.

    Running "z1.md" from History and staying on History would look like the
    command did nothing — the editor is where a file opens.
    """
    repo = a_repository(api, "Palette from history")
    open_repo(page, repo, tab="history")
    assert current_tab(page) == "History"

    open_palette(page)
    page.keyboard.type("z1")
    eventually(lambda: rows(page), lambda r: r == ["file:z1.md"],
               what="the file to be the only match")
    page.keyboard.press("Enter")

    eventually(lambda: current_tab(page), lambda t: t == "Files",
               what="the command to bring the editor's tab with it")
    eventually(lambda: page.locator(".repo-file-head code").inner_text(),
               lambda t: t == "z1.md", what="the file to be open")


def test_a_pinned_commit_changes_what_the_palette_offers(page, api) -> None:
    """**The one state where the palette says no and offers a way out.**

    A page pinned to a commit has its branch picker disabled, so the branch
    commands are disabled too and say why — a palette that switched anyway
    would be the page's second answer to the same question. The command that
    *is* enabled here is the one that exists for this state, and it is not
    offered at any other time.
    """
    repo = a_repository(api, "Palette pinned")
    page.goto(
        f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&commit={repo['commit_id']}"
    )
    expect(page.get_by_test_id("open-command-palette")).to_be_visible(timeout=30000)

    open_palette(page)
    page.keyboard.type("main")
    switch = page.locator("[data-testid=command-row][data-command='branch:main']")
    expect(switch).to_be_disabled()
    expect(switch.locator(".command-note")).to_have_text("viewing a commit")

    page.keyboard.press("Escape")
    open_palette(page)
    page.keyboard.type("back")
    back = page.locator("[data-testid=command-row][data-command=unpin]")
    expect(back).to_be_enabled()
    back.click()

    eventually(lambda: page.locator(".repo-pinned").count(), lambda n: n == 0,
               what="the command to take the page off the pinned commit")


def test_monaco_keeps_its_own_palette(page, api) -> None:
    """**Two palettes over one keystroke is the bug this avoids.**

    The editor is a real Monaco instance and binds F1 to its own command list
    — fold, go to line, change all occurrences — and calls `preventDefault`.
    This listener sits on the window and runs after it, so with the caret in
    the editor Monaco answers and this palette stays shut. That is the whole
    of what `opensPalette`'s `defaultPrevented` line buys, and nothing but a
    browser with Monaco in it can say whether it worked.
    """
    repo = a_repository(api, "Palette in the editor")
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=z1.md")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    # `.view-lines` rather than the textarea, which sits underneath it and
    # cannot be clicked.
    page.locator(".view-lines").first.click()

    page.keyboard.press("F1")
    # The positive wait first: Monaco's own quick input has to appear, or the
    # assertion below is about a keystroke that did nothing (§318).
    expect(page.locator(".quick-input-widget")).to_be_visible(timeout=10000)
    expect(palette(page)).to_have_count(0)
