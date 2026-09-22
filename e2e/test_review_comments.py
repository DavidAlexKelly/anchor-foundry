"""Line-by-line review with comments, in a browser (§440;
`code-repositories.md` §4; Foundry `code-repositories` p.51).

    "Reviewers can leave comments on individual lines of code." (p.51)

STATUS §92 built this — the server aligns the two sides itself, a comment
records the version of the file it was written against, and an outdated one is
shown rather than hidden. `apps/api/tests/test_code_review.py` owns all of
that: where a comment may hang, who may write one, when it goes outdated, and
what settling it means.

**What was never checked is the half that only exists in a browser**, and it is
the half the whole design turns on: a comment *hangs on a line and is written
where it hangs*. There is no "which file and which line did you mean" form,
because that form is how comments end up on the wrong line — so the thing to
check is that clicking line N opens a box against line N, that what comes back
sits against that same line, and that two boxes are never open at once. A
review surface that posted every comment to line 1 would pass every API test
there is.

The parity row for this had read "◑ — §52 built a review surface; verify it is
line-level, not file-level" since it was written. The verification is this
file; the row cited the wrong section, and nobody had done what it asked.
"""
from __future__ import annotations

import json
import uuid

from playwright.sync_api import expect

from api import Module
from conftest import TOKENS_FILE, WEB_BASE

LIVE = "SELECT 1\nFROM a\nWHERE x\n"
PROPOSED = "SELECT 2\nFROM a\nWHERE y\n"


def make_model(mod: Module, name: str) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/models",
        {"name": name, "language": "sql", "code": LIVE, "inputs": []},
    )


def propose(mod: Module, model: dict, code: str = PROPOSED) -> dict:
    return mod.api.call(
        "POST", f"{mod.base}/code/proposals",
        {"summary": "Change it", "description": "",
         "changes": [{"model_id": model["id"], "code": code}]},
    )


def a_proposal(api, name: str) -> tuple[Module, dict, dict]:
    """**Three lines, two of which changed.** A one-line file cannot tell a
    comment anchored to the line it was written on from one anchored to the
    only line there is — which is precisely the defect this file exists to
    catch."""
    mod = Module(api, name)
    model = make_model(mod, f"v_{uuid.uuid4().hex[:6]}")
    return mod, model, propose(mod, model)


def open_review(page, mod: Module, proposal_id: str) -> None:
    page.goto(
        f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/models"
        f"?proposal={proposal_id}"
    )
    expect(page.get_by_test_id("file-marks")).to_be_visible(timeout=30000)


def add_line(page, side: str, line: int):
    """The `+` beside one line of one side, by the name it announces itself
    under. Not by position: the two sides are two columns of the same row, and
    an index would pick whichever the DOM ordered first (§337)."""
    return page.get_by_role("button", name=f"Comment on {side} line {line}", exact=True)


def say(page, side: str, line: int, body: str) -> None:
    add_line(page, side, line).click()
    box = page.get_by_label(f"Comment on line {line}", exact=True)
    expect(box).to_be_visible(timeout=30000)
    box.fill(body)
    page.get_by_role("button", name="Comment", exact=True).click()


def test_a_comment_lands_on_the_line_it_was_written_on(page, api) -> None:
    """**The claim the whole design rests on.** A surface that posted every
    comment to line 1 would satisfy every API test there is, because the API
    is told a line number and believes it — the browser is what decides which
    number that is.
    """
    mod, _, proposal = a_proposal(api, "Comment line")
    open_review(page, mod, proposal["id"])

    say(page, "proposed", 3, "why y?")

    bubble = page.get_by_test_id("review-comment")
    expect(bubble).to_have_count(1, timeout=30000)
    expect(bubble).to_contain_text("why y?")

    # And it came back against **line 3**, which is asked of the server rather
    # than of the screen: the screen is what is under test.
    stored = mod.api.call(
        "GET", f"{mod.base}/code/proposals/{proposal['id']}")["comments"]
    assert [(c["side"], c["line"]) for c in stored] == [("proposed", 3)], stored


def test_the_box_opens_against_the_line_that_was_clicked(page, api) -> None:
    """p.51's "individual lines", said by the box itself. A box that named no
    line, or named the wrong one, is how a comment ends up somewhere its author
    did not mean — and it is the part a reader can check before they type."""
    mod, _, proposal = a_proposal(api, "Comment box")
    open_review(page, mod, proposal["id"])

    add_line(page, "proposed", 1).click()
    expect(page.get_by_label("Comment on line 1", exact=True)).to_be_visible(timeout=30000)
    expect(page.get_by_label("Comment on line 3", exact=True)).to_have_count(0)


def test_opening_a_second_box_closes_the_first(page, api) -> None:
    """Two open boxes is two half-written comments, and one of them gets lost.

    §318: the first box is waited for before the assertion that it is gone, so
    this is about the second click rather than about the page not having drawn.
    """
    mod, _, proposal = a_proposal(api, "Comment one box")
    open_review(page, mod, proposal["id"])

    add_line(page, "proposed", 1).click()
    first = page.get_by_label("Comment on line 1", exact=True)
    expect(first).to_be_visible(timeout=30000)

    add_line(page, "proposed", 3).click()
    expect(page.get_by_label("Comment on line 3", exact=True)).to_be_visible(timeout=30000)
    expect(first).to_have_count(0)


def test_the_two_sides_are_two_different_anchors(page, api) -> None:
    """A comment on the live line 1 is about the code being replaced; one on
    the proposed line 1 is about its replacement. A surface that collapsed the
    sides would answer "what about the old one?" with a remark about the new.
    """
    mod, _, proposal = a_proposal(api, "Comment sides")
    open_review(page, mod, proposal["id"])

    say(page, "live", 1, "this was fine")
    expect(page.get_by_test_id("review-comment")).to_have_count(1, timeout=30000)
    say(page, "proposed", 1, "and this is not")
    expect(page.get_by_test_id("review-comment")).to_have_count(2, timeout=30000)

    stored = mod.api.call(
        "GET", f"{mod.base}/code/proposals/{proposal['id']}")["comments"]
    assert sorted((c["side"], c["line"]) for c in stored) == [
        ("live", 1), ("proposed", 1)], stored


def test_a_line_that_exists_on_only_one_side_is_not_commentable_on_the_other(
    page, api
) -> None:
    """An empty cell is the absence of a line, not line zero. Giving it a
    number would make it commentable — and a comment on a line that is not
    there is one nobody can answer."""
    mod, model, _ = a_proposal(api, "Comment blank")
    # A proposal that only *adds*: the live side has no line 4.
    proposal = propose(mod, model, LIVE + "LIMIT 1\n")
    open_review(page, mod, proposal["id"])

    expect(add_line(page, "proposed", 4)).to_be_visible(timeout=30000)
    expect(add_line(page, "live", 4)).to_have_count(0)
    # **Counted, not only named** — and the sweep is the only reason this line
    # is here. Removing the `row.live_line !== null` guard puts a `+` on the
    # blank cell, and that button announces itself as "Comment on live line
    # **null**" rather than as line 4, so the assertion above passes over
    # exactly the defect it was written for. A test that can only find a
    # control by the name it would have if it were correct cannot find it when
    # it is wrong (§337).
    #
    # Three live lines and four proposed ones is seven places a comment may
    # hang. The eighth would be the blank.
    expect(page.locator(".review-add-comment")).to_have_count(7)


def test_a_comment_can_be_settled_and_reopened_from_the_bubble(page, api) -> None:
    """"We settled this" is a decision somebody made, and the control for it is
    on the remark rather than in a list somewhere else."""
    mod, _, proposal = a_proposal(api, "Comment settle")
    open_review(page, mod, proposal["id"])
    say(page, "proposed", 1, "is 2 right?")

    bubble = page.get_by_test_id("review-comment")
    expect(bubble).to_have_attribute("data-resolved", "false", timeout=30000)
    page.get_by_test_id("comment-settle").click()
    expect(bubble).to_have_attribute("data-resolved", "true", timeout=30000)

    page.get_by_test_id("comment-settle").click()
    expect(bubble).to_have_attribute("data-resolved", "false", timeout=30000)


def test_an_edit_marks_the_comments_written_before_it_rather_than_hiding_them(
    page, api
) -> None:
    """db 0036's rule, on the screen: a remark about a line is a claim about a
    *version* of the file.

    Shown and marked, never hidden — it said something true about the code it
    was written against, and hiding it loses the reason a change was made.
    """
    mod, model, proposal = a_proposal(api, "Comment outdated")
    open_review(page, mod, proposal["id"])
    say(page, "proposed", 1, "why 2?")
    expect(page.get_by_test_id("review-comment")).to_have_attribute(
        "data-outdated", "false", timeout=30000)

    mod.api.call(
        "PATCH", f"{mod.base}/code/proposals/{proposal['id']}",
        {"changes": [{"model_id": model["id"], "code": "SELECT 3\nFROM a\nWHERE y\n"}]},
    )
    open_review(page, mod, proposal["id"])

    bubble = page.get_by_test_id("review-comment")
    expect(bubble).to_have_count(1, timeout=30000)
    expect(bubble).to_contain_text("why 2?")
    expect(bubble).to_have_attribute("data-outdated", "true")
    expect(bubble).to_contain_text("outdated")


def test_a_comment_on_the_file_rather_than_on_a_line_is_its_own_place(
    page, api
) -> None:
    """Not every remark is about a line — "this whole change is the wrong
    approach" has no line to hang on. It goes under the diff rather than
    against an arbitrary row."""
    mod, _, proposal = a_proposal(api, "Comment file")
    open_review(page, mod, proposal["id"])

    page.get_by_role("button", name="Comment on this file").click()
    box = page.locator(".review-file-say textarea")
    expect(box).to_be_visible(timeout=30000)
    box.fill("wrong approach")
    page.get_by_role("button", name="Comment", exact=True).click()

    expect(page.locator(".review-file-comments")).to_contain_text(
        "wrong approach", timeout=30000)
    stored = mod.api.call(
        "GET", f"{mod.base}/code/proposals/{proposal['id']}")["comments"]
    assert [c["line"] for c in stored] == [None], stored


def test_somebody_elses_comment_is_on_the_line_it_was_written_on(page, api) -> None:
    """**Read as well as written.** Every test above writes its own comment, so
    all of them would pass over a surface that drew a comment wherever it had
    just put the box rather than where the comment says it is.
    """
    mod, model, proposal = a_proposal(api, "Comment read")
    with open(TOKENS_FILE) as handle:
        tokens = json.load(handle)
    from api import Api

    admin = Api(api.base, tokens["admin@acme.dev.local"])
    admin.call(
        "POST", f"{mod.base}/code/proposals/{proposal['id']}/comments",
        {"model_id": model["id"], "side": "proposed", "line": 3, "body": "theirs"},
    )

    open_review(page, mod, proposal["id"])
    bubble = page.get_by_test_id("review-comment")
    expect(bubble).to_have_count(1, timeout=30000)
    expect(bubble).to_contain_text("theirs")
    # The thread sits in the row **below line 3**, which is what "against the
    # line" means on screen. Asserted through the box for that line, because
    # the box and the thread share the row.
    row = page.locator(".review-thread-row")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("theirs")
