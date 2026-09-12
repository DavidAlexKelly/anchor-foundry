"""p.137's comments, on the screen (§322; `object-views` p.137).

    "Object Explorer allows users to comment on an object, mention other users,
     and attach files and images. You can open the Comments Helper for any
     object using the **View comments** button in the header of any Object
     View." (p.137)

The storing, the mention resolution and the notification are in
`apps/api/tests/test_object_comments.py`, and the wording in
`apps/web/src/lib/object-comments.test.ts`. What needs a browser is the half
p.137 spends its second sentence on and neither of those can reach: **where the
button is**.

p.137 says "the header of any Object View", and this platform has two
renderings of one — the generated standard view and somebody's Workshop module
— so "any" is the whole claim. A button placed inside either rendering would
exist for one kind of object and not the other, which is exactly the trap §312
met putting p.34's star "next to its title".
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE, eventually


@pytest.fixture(scope="module")
def talked_about(api):
    """One object to have a conversation about."""
    mod = Module(api, "Comments")
    mod.object_type(
        columns=["id", "town"],
        rows=[{"id": "1", "town": "Ely"}],
        key="id", title="town",
    )
    return mod


def open_object(page, module) -> None:
    """Open the Explorer on this type and click into the object.

    p.137 puts commenting in the Object Explorer, so this is the route a person
    takes rather than a URL a test invents.
    """
    page.goto(f"{WEB_BASE}/{module.workspace_slug}/explore?type={module.object_type_id}")
    # **The Explore button, not the cell.** The Explorer's rows are a table;
    # the object opens from the button on the row, which is how every other
    # suite reaches one (`test_object_links.py`).
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    expect(page.get_by_test_id("view-comments")).to_be_visible(timeout=30000)


def test_the_button_is_in_the_object_view_header(page, talked_about) -> None:
    """**p.137's placement**, and the only claim a browser can check.

    The panel is closed until it is asked for — p.137 calls it a Helper you
    *open*, and a conversation unfurled under every object would push the
    object off the screen.
    """
    open_object(page, talked_about)
    expect(page.get_by_test_id("comments-panel")).to_have_count(0)
    page.get_by_test_id("view-comments").click()
    expect(page.get_by_test_id("comments-panel")).to_be_visible(timeout=30000)


def test_an_object_nobody_has_discussed_invites_a_comment(page, api) -> None:
    """"0 comments" is a true sentence that reads as a dead end, and the button
    is also how you add the first one — so it says "Comment"."""
    mod = Module(api, "Comments empty")
    mod.object_type(columns=["id", "town"], rows=[{"id": "1", "town": "Ripon"}],
                    key="id", title="town")
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/explore?type={mod.object_type_id}")
    page.locator("tbody tr").first.get_by_role("button", name="Explore").click()
    button = page.get_by_test_id("view-comments")
    expect(button).to_have_text("Comment", timeout=30000)

    button.click()
    expect(page.get_by_test_id("comments-empty")).to_be_visible()
    # The empty state teaches the mention syntax, because there is nowhere else
    # in the product that would.
    expect(page.get_by_test_id("comments-empty")).to_contain_text("@")


def test_a_comment_is_posted_and_appears_in_the_thread(page, talked_about) -> None:
    """p.137's first capability, end to end through the screen."""
    said = f"this needs checking {uuid.uuid4().hex[:6]}"
    open_object(page, talked_about)
    page.get_by_test_id("view-comments").click()
    expect(page.get_by_test_id("comments-panel")).to_be_visible(timeout=30000)

    page.get_by_test_id("comment-draft").fill(said)
    page.get_by_test_id("comment-submit").click()
    expect(page.get_by_test_id("comment-list")).to_contain_text(said, timeout=30000)
    # The draft is cleared, so a second comment is not the first one again.
    expect(page.get_by_test_id("comment-draft")).to_have_value("")


def test_the_button_counts_what_is_behind_it(page, talked_about) -> None:
    """A button that says nothing about whether there is anything behind it is
    one people stop pressing — and the count has to move when a comment is
    posted, or it is a number that goes stale in front of the reader."""
    open_object(page, talked_about)
    button = page.get_by_test_id("view-comments")
    before = button.inner_text()
    button.click()
    page.get_by_test_id("comment-draft").fill(f"counting {uuid.uuid4().hex[:6]}")
    page.get_by_test_id("comment-submit").click()
    # The posted comment is the positive wait; the label is then read off a
    # panel that has demonstrably updated (§318).
    expect(page.get_by_test_id("comment-list")).to_contain_text("counting", timeout=30000)
    eventually(lambda: button.inner_text(), lambda t: t != before and "comment" in t,
               what="the button's count to move")


def test_a_mention_is_marked_with_the_server_s_own_span(page, api, talked_about) -> None:
    """**p.137's second capability, drawn from the answer rather than re-found.**

    §146's rule: a browser that re-derived the span would be a second matcher,
    free to disagree with the one that decided who was notified — and the
    disagreement shows as a highlight on a name nobody was told about.
    """
    members = api.call("GET", f"/workspaces/{talked_about.workspace_id}/members")
    named = next(m for m in members if m.get("display_name"))

    open_object(page, talked_about)
    page.get_by_test_id("view-comments").click()
    expect(page.get_by_test_id("comments-panel")).to_be_visible(timeout=30000)
    page.get_by_test_id("comment-draft").fill(
        f"@{named['display_name']} please look {uuid.uuid4().hex[:6]}"
    )
    page.get_by_test_id("comment-submit").click()

    mention = page.get_by_test_id("comment-mention").last
    expect(mention).to_be_visible(timeout=30000)
    expect(mention).to_have_text(f"@{named['display_name']}")


def test_an_at_that_names_nobody_is_not_marked(page, talked_about) -> None:
    """The other direction, and the one that makes the marking mean something.

    Without it, "a mention is highlighted" is satisfied by a panel that
    highlights every `@` it sees — which would put a mark on an email address
    and imply somebody had been told.
    """
    open_object(page, talked_about)
    page.get_by_test_id("view-comments").click()
    expect(page.get_by_test_id("comments-panel")).to_be_visible(timeout=30000)
    tag = uuid.uuid4().hex[:6]
    page.get_by_test_id("comment-draft").fill(f"mail nobody@example.org about {tag}")
    page.get_by_test_id("comment-submit").click()

    posted = page.get_by_test_id("comment-list")
    expect(posted).to_contain_text(tag, timeout=30000)
    # The comment is on screen — that is the positive wait — so the absence of
    # a mark inside it is about the product rather than about timing (§318).
    expect(posted.get_by_text("nobody@example.org")).to_be_visible()
    assert page.get_by_test_id("comment-mention").filter(
        has_text="nobody@example.org"
    ).count() == 0
