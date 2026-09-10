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
from conftest import WEB_BASE, eventually, stays


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


# ---- the Settings tab (§279) -------------------------------------------------
def test_the_review_gate_has_a_home_that_is_not_the_page_b1_deletes(page, api) -> None:
    """**Why this tab exists at all.**

    §278 found `setReviewPolicy` had exactly one control in the product, on the
    Code pillar page B.1 removes. Nothing would have errored when that page
    went; a project would simply have lost the ability to require review of its
    transforms, which is governance rather than convenience.
    """
    mod = project(api, "Settings gate")
    repo = repository(mod, f"Transforms {mod.tag}")

    open_tab(page, repo, tab="settings")
    box = page.get_by_test_id("settings-require-review")
    expect(box).to_be_visible()
    expect(box).not_to_be_checked()
    # What it does, said in terms of what happens to a change rather than as a
    # flag - this is the sentence somebody deciding actually reads.
    expect(page.get_by_test_id("settings-review-effect")).to_contain_text(
        "changed directly"
    )

    # **`click`, not `check`.** Playwright's `check` clicks and then re-reads
    # the element to confirm the state took - and this box is controlled by the
    # server's answer, so during the round trip `check` can re-read a value it
    # does not expect and report "clicking the checkbox did not change its
    # state" about a click that worked. Clicking and then asserting what the
    # reader sees is both more robust and a better description of the act.
    box.click()
    expect(box).to_be_checked()
    expect(page.get_by_test_id("settings-review-effect")).to_contain_text(
        "other than their author"
    )

    # **And it is the real setting, not a checkbox that only looks checked.**
    # Polled rather than read once: the box shows what was asked for while the
    # request is in flight, which is right for a reader and means the screen no
    # longer marks the moment the server agreed. This caller is a second client
    # and has no reason to see the first one's write until it lands.
    eventually(
        lambda: mod.api.call("GET", f"{mod.base}/code/review-policy")["require_code_review"],
        lambda got: got is True,
        what="the review gate to be on at the server",
    )

    box.click()
    expect(box).not_to_be_checked()
    expect(page.get_by_test_id("settings-review-effect")).to_contain_text("optional")
    eventually(
        lambda: mod.api.call("GET", f"{mod.base}/code/review-policy")["require_code_review"],
        lambda got: got is False,
        what="the review gate to be off at the server",
    )


def test_the_tab_says_the_setting_is_the_projects_not_this_repositorys(
    page, api
) -> None:
    """The divergence, said out loud. Foundry sets required review per
    repository (`repoSettings.json`, p.20); ours is per project, because the
    gate has to cover transforms no repository holds. Somebody who discovered
    that by flipping it in one repository and finding it flipped in another
    would be right to be annoyed."""
    mod = project(api, "Settings scope")
    one = repository(mod, f"One {mod.tag}")
    repository(mod, f"Two {mod.tag}")

    open_tab(page, one, tab="settings")
    scope = page.get_by_test_id("settings-review-scope")
    expect(scope).to_contain_text("whole project")
    expect(scope).to_contain_text("all 2 repositories")
    expect(scope).to_contain_text("Foundry sets this per repository")


# ---- drafts survive a reload (§281) ------------------------------------------
def open_file(page, repo: dict, path: str) -> None:
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file={path}")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)


def type_into_editor(page, text: str) -> None:
    """Put the caret in Monaco and type.

    **Clicking `.monaco-editor textarea` does not work**: the textarea carries
    the value but sits *under* the rendered text, so Playwright reports
    `<span class="mtk8">…</span> … intercepts pointer events` and retries until
    it gives up. `.view-lines` is the layer a person actually clicks on, and
    clicking it is what moves the caret.
    """
    page.locator(".view-lines").first.click()
    # `Control+End`, not `End`: the click leaves the caret wherever it landed,
    # and appending to the document is what these tests mean.
    page.keyboard.press("Control+End")
    page.keyboard.type(text)


def editor_text(page) -> str:
    """What the editor shows, with **Monaco's non-breaking spaces normalised**.

    Monaco renders every space as U+00A0, so `get_by_text("-- a thought I have
    not committed")` matches nothing at all — the DOM holds
    `--\xa0a\xa0thought\xa0…`. The failure reads as "the text is not there",
    which is true of the string being searched for and false of the editor.
    """
    return page.locator(".view-lines").first.inner_text().replace("\xa0", " ")


def test_an_uncommitted_draft_survives_a_reload(page, api) -> None:
    """**`code-repositories.md` §2.3's warning, closed.**

    "Uncommitted edits live in `useState` keyed by path with no persistence
    anywhere. That survives switching files but not a page reload — so a
    five-tab editor with unsaved work is five ways to lose work at once."

    That is why persistence comes before tabs: tabs are what make the loss
    expensive, and shipping them first would multiply a bug rather than find
    it.
    """
    mod = project(api, "Draft reload")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"draft_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })

    open_file(page, repo, "src/t.sql")
    type_into_editor(page, "\n-- a thought I have not committed")
    eventually(lambda: editor_text(page),
               lambda t: "-- a thought I have not committed" in t,
               what="the typing to land in the editor")

    page.reload()
    open_file(page, repo, "src/t.sql")
    # The whole unit, in one assertion: the typing is still there.
    eventually(lambda: editor_text(page),
               lambda t: "-- a thought I have not committed" in t,
               what="the draft to survive the reload")


def test_a_draft_does_not_follow_you_to_another_branch(page, api) -> None:
    """**The one outcome worse than losing a draft**: pasting one branch's work
    onto another's. The same path on two branches is two files, so the store is
    keyed by both."""
    mod = project(api, "Draft branch")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"br_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "sandbox", "from_branch": "main"})

    open_file(page, repo, "src/t.sql")
    type_into_editor(page, "\n-- only on main")
    eventually(lambda: editor_text(page), lambda t: "-- only on main" in t,
               what="the typing to land")

    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/t.sql&branch=sandbox")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    stays(lambda: editor_text(page), lambda t: "-- only on main" not in t,
          what="the other branch staying clean")

    # And it is still on main, rather than having been discarded by the trip.
    page.goto(f"{WEB_BASE}/r/{repo['resource_id']}?tab=files&file=src/t.sql&branch=main")
    expect(page.locator(".code-editor-loading")).to_have_count(0, timeout=30000)
    eventually(lambda: editor_text(page), lambda t: "-- only on main" in t,
               what="the draft still on the branch it was typed on")


# ---- where applying puts the code (§283) -------------------------------------
def test_the_review_surface_says_which_branch_applying_moves(page, api) -> None:
    """**Applying a commit proposal publishes the code and moves the branch.**

    That was invisible while everything was committed to the default branch
    first: the branch was already at the commit, so "the branch does not move"
    and "the branch is right" were the same picture. They come apart the moment
    work happens on a sandbox, which is the whole point of a pull request - and
    a screen that mentioned neither would leave "the branch will be updated" as
    the thing people assume in every case, including the one where it will not.

    The wording rules are in `apps/web/src/lib/proposal-landing.test.ts`; what
    needs a browser is that the API's answer reaches the screen at all.
    """
    mod = project(api, "Landing line")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    commit(mod, repo, {"README.md": "# transforms\n"})
    mod.api.call("POST", f"{mod.base}/repositories/{repo['id']}/branches",
                 {"name": "work", "from_branch": "main"})
    out = f"land_{uuid.uuid4().hex[:6]}"
    made = commit(mod, repo, {
        "README.md": "# transforms\n",
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    }, branch="work")
    proposal = propose_commit(mod, repo, made["id"], "Land the transform")

    page.goto(
        f"{WEB_BASE}/r/{repo['resource_id']}?tab=pulls&proposal={proposal['id']}"
    )
    landing = page.get_by_test_id("proposal-landing")
    expect(landing).to_be_visible(timeout=30000)
    expect(landing).to_contain_text("moves main to this commit")


def test_a_proposal_over_a_commit_the_branch_already_has_says_nothing_will_move(
    page, api
) -> None:
    """The other half, and the reason the line is not silent here: "nothing
    will happen to the branch" and "the branch will be updated" look identical
    on a screen that mentions neither."""
    mod = project(api, "Landing landed")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"already_{uuid.uuid4().hex[:6]}"
    made = commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    proposal = propose_commit(mod, repo, made["id"], "Already on main")

    page.goto(
        f"{WEB_BASE}/r/{repo['resource_id']}?tab=pulls&proposal={proposal['id']}"
    )
    landing = page.get_by_test_id("proposal-landing")
    expect(landing).to_be_visible(timeout=30000)
    expect(landing).to_contain_text("already has this commit")


# ---- Reset (§288; code-repositories.md §2.2, p.13) ---------------------------
# "Reset the contents of all files to match the latest commit on your remote
# branch. This will clear any changes that have not yet been committed."
#
# The button existed and nothing tested it. Since §281 it also has to take the
# *persisted* draft with it - a Discard that left the draft in storage would
# bring the work back on the next reload, which is the exact opposite of what
# the button says.
def test_discarding_asks_first_and_keeps_the_work_when_the_answer_is_no(
    page, api
) -> None:
    """**The one control here that destroys work, beside the one that saves
    it.** An accidental click costs everything typed since the last commit -
    and since drafts persist, that may be days of it rather than this
    session's."""
    mod = project(api, "Discard cancel")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"d_{uuid.uuid4().hex[:6]}"
    commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })

    open_file(page, repo, "src/t.sql")
    type_into_editor(page, "\n-- work I do not want to lose")
    eventually(lambda: editor_text(page), lambda t: "-- work I do not want to lose" in t,
               what="the typing to land")

    asked: list[str] = []

    def refuse(dialog):
        asked.append(dialog.message)
        dialog.dismiss()

    page.once("dialog", refuse)
    page.get_by_role("button", name="Discard", exact=True).click()

    eventually(lambda: asked, lambda a: len(a) == 1, what="the confirmation to be asked")
    assert "1 file?" in asked[0], asked
    assert "cannot be undone" in asked[0], asked
    stays(lambda: editor_text(page), lambda t: "-- work I do not want to lose" in t,
          what="the work surviving a refused discard")


def test_discarding_takes_the_persisted_draft_with_it(page, api) -> None:
    """**The obligation §281 created and nothing pinned.**

    `setEdits({})` is what removes the stored key, through the save effect - an
    emergent consequence of writing an empty map, not something anybody wrote
    down. A change to `writeDrafts` that stopped removing on empty would
    silently resurrect discarded work on the next reload, and no test would
    have noticed.
    """
    mod = project(api, "Discard drafts")
    repo = repository(mod, f"Transforms {mod.tag}")
    source = dataset(mod, f"orders_{mod.tag}")
    out = f"dd_{uuid.uuid4().hex[:6]}"
    committed = f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n"
    commit(mod, repo, {"src/t.sql": committed})

    open_file(page, repo, "src/t.sql")
    type_into_editor(page, "\n-- about to be thrown away")
    eventually(lambda: editor_text(page), lambda t: "-- about to be thrown away" in t,
               what="the typing to land")

    page.once("dialog", lambda d: d.accept())
    page.get_by_role("button", name="Discard", exact=True).click()
    eventually(lambda: editor_text(page), lambda t: "-- about to be thrown away" not in t,
               what="the editor to go back to the committed file")

    # And it stays gone across a reload, which is the half that needs storage
    # to have been cleared rather than just state.
    page.reload()
    open_file(page, repo, "src/t.sql")
    stays(lambda: editor_text(page), lambda t: "-- about to be thrown away" not in t,
          what="the discarded draft staying discarded")
