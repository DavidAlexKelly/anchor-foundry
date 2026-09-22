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


def withdraw(mod: Module, proposal: dict) -> None:
    mod.api.call("POST", f"{mod.base}/code/proposals/{proposal['id']}/withdraw", {})


def two_proposals(mod: Module, repo: dict) -> tuple[dict, dict]:
    """One proposal per commit, with a word of their own in each summary.

    Two commits rather than two repositories, because the tab's filters are
    about *this* repository's list — a fixture that put them in two places
    would let a filter pass by scoping rather than by filtering.
    """
    # **Stamped per call, not per module.** Two repositories in one project
    # both want a source, and a name derived from the module alone is a 409 the
    # second time round (§271).
    stamp = uuid.uuid4().hex[:6]
    source = dataset(mod, f"orders_{stamp}")
    alpha = f"alpha_{uuid.uuid4().hex[:6]}"
    beta = f"beta_{uuid.uuid4().hex[:6]}"
    files = {
        "src/alpha.sql": f"-- output: {alpha}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    }
    first = commit(mod, repo, dict(files))
    files["src/beta.sql"] = (
        f"-- output: {beta}\n-- input: raw = {source}\nSELECT id FROM raw\n"
    )
    second = commit(mod, repo, files)
    return (
        propose_commit(mod, repo, first["id"], "Alpha work"),
        propose_commit(mod, repo, second["id"], "Beta work"),
    )


def one_proposal(mod: Module, repo: dict, summary: str) -> dict:
    """A single open proposal with a summary of its own."""
    stamp = uuid.uuid4().hex[:6]
    source = dataset(mod, f"orders_{stamp}")
    out = f"t_{stamp}"
    made = commit(mod, repo, {
        "src/t.sql": f"-- output: {out}\n-- input: raw = {source}\nSELECT id FROM raw\n",
    })
    return propose_commit(mod, repo, made["id"], summary)


def shown(page) -> list[str]:
    return page.locator("[data-testid^=pull-]:not([data-testid^=pull-state-])").evaluate_all(
        "rows => rows.map(r => r.getAttribute('data-testid'))"
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


# ---- p.18's two filters (§429) ----------------------------------------------
#
#     "You can switch between a list of open and closed Pull requests by
#      clicking the 'Open' / 'Closed' button at the top of the pull requests
#      list, and use the search bar to further filter the list based on title
#      or author."
#
# The rules are in `apps/web/src/lib/proposal-filters.test.ts`. What needs a
# browser is that the two controls reach the server and the URL: the bucket is
# a different *request*, the search is not, and both have to survive a reload
# or a filtered list is not a list anybody can send.
def test_the_switch_shows_the_ones_that_are_over(page, api) -> None:
    """**The Closed list, which had no way to be seen at all.**

    The tab asked for `state=open` and nothing else, so a proposal that was
    applied or withdrawn left the screen for good — and "it is gone" and "it
    was merged" looked the same.
    """
    mod = project(api, "Pulls buckets")
    repo = repository(mod, f"Transforms {mod.tag}")
    still_open, closed = two_proposals(mod, repo)
    withdraw(mod, closed)

    open_tab(page, repo)
    expect(page.get_by_test_id(f"pull-{still_open['id']}")).to_be_visible()
    expect(page.get_by_test_id(f"pull-{closed['id']}")).to_have_count(0)

    page.get_by_test_id("pulls-bucket-closed").click()
    expect(page.get_by_test_id(f"pull-{closed['id']}")).to_be_visible()
    expect(page.get_by_test_id(f"pull-{still_open['id']}")).to_have_count(0)
    # And the row says *which* ending, because the bucket holds two of them.
    expect(page.get_by_test_id(f"pull-state-{closed['id']}")).to_have_text("Closed")


def test_the_bucket_is_in_the_url(page, api) -> None:
    """Asserted by reloading rather than by reading the address bar: a URL
    that is written and not read is one that looks right and does nothing."""
    mod = project(api, "Pulls bucket link")
    repo = repository(mod, f"Transforms {mod.tag}")
    _, closed = two_proposals(mod, repo)
    withdraw(mod, closed)

    open_tab(page, repo)
    page.get_by_test_id("pulls-bucket-closed").click()
    expect(page.get_by_test_id(f"pull-{closed['id']}")).to_be_visible()
    assert "pulls=closed" in page.url, page.url

    page.reload()
    expect(page.get_by_test_id(f"pull-{closed['id']}")).to_be_visible(timeout=30000)


def test_the_search_narrows_the_list(page, api) -> None:
    mod = project(api, "Pulls search")
    repo = repository(mod, f"Transforms {mod.tag}")
    alpha, beta = two_proposals(mod, repo)

    open_tab(page, repo)
    eventually(lambda: shown(page), lambda r: len(r) == 2,
               what="both proposals to be listed")

    page.get_by_test_id("pulls-search").fill("beta")
    eventually(lambda: shown(page), lambda r: r == [f"pull-{beta['id']}"],
               what="the search to leave one row")

    page.get_by_test_id("pulls-search").fill("")
    eventually(lambda: shown(page), lambda r: len(r) == 2,
               what="clearing the box to bring the list back")


def test_the_search_matches_the_author(page, api) -> None:
    """p.18 names title *or* author, and the author is the half a title search
    cannot reach: "who has something open" is the question a reviewer arriving
    at a busy repository actually has."""
    mod = project(api, "Pulls author")
    repo = repository(mod, f"Transforms {mod.tag}")
    alpha, beta = two_proposals(mod, repo)

    open_tab(page, repo)
    # No summary here contains an "@", so a list that still has both rows can
    # only have matched the address.
    page.get_by_test_id("pulls-search").fill("owner@")
    eventually(lambda: sorted(shown(page)),
               lambda r: r == sorted([f"pull-{alpha['id']}", f"pull-{beta['id']}"]),
               what="the author search to keep both rows")


def test_a_search_that_finds_nothing_says_where_to_look(page, api) -> None:
    """**The sentence somebody needs is not "no results".**

    A reviewer searching for a proposal that was merged last week and one
    searching for a typo get the same empty list, and they want opposite next
    actions. So the note names the query and says how many the *other* bucket
    has — and offers to go there.
    """
    mod = project(api, "Pulls search elsewhere")
    repo = repository(mod, f"Transforms {mod.tag}")
    alpha, beta = two_proposals(mod, repo)
    withdraw(mod, beta)

    open_tab(page, repo)
    page.get_by_test_id("pulls-search").fill("beta")
    note = page.get_by_test_id("pulls-search-empty")
    expect(note).to_contain_text("beta")
    expect(note).to_contain_text("1 closed proposal matches")

    page.get_by_test_id("pulls-switch").click()
    expect(page.get_by_test_id(f"pull-{beta['id']}")).to_be_visible()
    # The search came with it, rather than being cleared by the switch - the
    # button is an answer to the search, so dropping it would undo the act.
    expect(page.get_by_test_id("pulls-search")).to_have_value("beta")


def test_a_search_with_no_answer_anywhere_does_not_point_at_an_empty_list(
    page, api,
) -> None:
    """A button that switched to a bucket with nothing in it would be a
    control that looks like it works (§214). The positive wait comes first —
    the note is on screen — so the absence below is about a rendered page."""
    mod = project(api, "Pulls search nowhere")
    repo = repository(mod, f"Transforms {mod.tag}")
    two_proposals(mod, repo)

    open_tab(page, repo)
    page.get_by_test_id("pulls-search").fill("gamma")
    expect(page.get_by_test_id("pulls-search-empty")).to_contain_text("gamma")
    expect(page.get_by_test_id("pulls-switch")).to_have_count(0)


def test_an_empty_bucket_says_which_list_is_empty(page, api) -> None:
    """**The word is not decoration, and a search replaces the sentence.**

    Two ways this goes wrong once there are two lists. A Closed tab reporting
    "No open proposals" is a screen answering a question nobody asked; and a
    tab that showed the bucket's empty note *and* the search's at once would
    be telling somebody two things about one keystroke.
    """
    mod = project(api, "Pulls empty bucket")
    repo = repository(mod, f"Transforms {mod.tag}")
    one_proposal(mod, repo, "Alpha work")

    open_tab(page, repo)
    page.get_by_test_id("pulls-bucket-closed").click()
    expect(page.get_by_test_id("pulls-empty")).to_have_text(
        "No closed proposals for this repository."
    )

    page.get_by_test_id("pulls-search").fill("beta")
    # The search's sentence takes over: it is about the words that were typed,
    # which is the more specific answer.
    expect(page.get_by_test_id("pulls-search-empty")).to_contain_text("beta")
    expect(page.get_by_test_id("pulls-empty")).to_have_count(0)


def test_the_other_buckets_count_is_about_this_repository(page, api) -> None:
    """**The hint counts what switching would actually show.**

    A proposal is project-level and a repository is one of several (db 0039),
    so a count taken before the repository filter would promise rows that are
    not there — and the reader would switch, find an empty list, and conclude
    the search is broken rather than that the proposal is somewhere else.
    """
    mod = project(api, "Pulls elsewhere scoped")
    mine = repository(mod, f"Mine {mod.tag}")
    theirs = repository(mod, f"Theirs {mod.tag}")
    one_proposal(mod, mine, "Alpha work")
    withdraw(mod, one_proposal(mod, mine, "Gamma work"))
    withdraw(mod, one_proposal(mod, theirs, "Beta work"))

    open_tab(page, mine)
    # **The positive wait first, and it is what makes the negative one mean
    # anything** (§318). The other bucket is a second request, so a page that
    # has not received it yet offers nothing — which is indistinguishable from
    # a page that correctly found nothing to offer. Searching for this
    # repository's own withdrawn proposal proves the request landed and the
    # note re-rendered; the answer is then cached under the same key, so the
    # search below is computed from data that is already here.
    page.get_by_test_id("pulls-search").fill("gamma")
    expect(page.get_by_test_id("pulls-search-empty")).to_contain_text(
        "1 closed proposal matches"
    )
    expect(page.get_by_test_id("pulls-switch")).to_be_visible()

    # The other repository's withdrawn "Beta work" matches the words and is not
    # in this list, so there is nothing here to offer.
    page.get_by_test_id("pulls-search").fill("beta")
    note = page.get_by_test_id("pulls-search-empty")
    expect(note).to_contain_text("beta")
    stays(lambda: note.inner_text(), lambda t: "closed proposal" not in t,
          what="a count that does not reach into another repository")
    expect(page.get_by_test_id("pulls-switch")).to_have_count(0)


def test_the_search_is_in_the_url(page, api) -> None:
    mod = project(api, "Pulls search link")
    repo = repository(mod, f"Transforms {mod.tag}")
    alpha, beta = two_proposals(mod, repo)

    open_tab(page, repo)
    page.get_by_test_id("pulls-search").fill("alpha")
    eventually(lambda: shown(page), lambda r: r == [f"pull-{alpha['id']}"],
               what="the search to leave one row")

    page.reload()
    expect(page.get_by_test_id("pulls-search")).to_have_value("alpha", timeout=30000)
    eventually(lambda: shown(page), lambda r: r == [f"pull-{alpha['id']}"],
               what="the reloaded page to be filtered the same way")


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
