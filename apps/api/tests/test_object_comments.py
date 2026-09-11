"""Comments on an object (§322; db 0078; `object-views` p.137).

    "Object Explorer allows users to comment on an object, mention other users,
     and attach files and images." (p.137)

**The mention parser is pure and most of this file is about it**, because it is
the part with a decision in it. Everything else p.137 names — storing a
comment, hanging files off it, reading the thread back — has one obvious
implementation; who `@Ada` refers to when there is also an `@Ada Lovelace` does
not.

The parsing tests need no database at all. The three that do are the ones about
what gets *stored* and who gets *told*.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import object_comments as comments  # noqa: E402


def member(name: str, email: str, user_id: str | None = None) -> dict:
    return {
        "user_id": user_id or str(uuid.uuid4()),
        "display_name": name,
        "email": email,
    }


ADA = member("Ada Lovelace", "ada@example.com")
GRACE = member("Grace Hopper", "grace@example.com")
# Deliberately a prefix of Ada's name — the case the algorithm is *for*.
ADA_SHORT = member("Ada", "ada.short@example.com")


# --- p.137's mentions ---------------------------------------------------------


def test_a_name_that_is_here_is_a_mention() -> None:
    found = comments.find_mentions("thanks @Ada Lovelace", [ADA])
    assert [m["user_id"] for m in found] == [ADA["user_id"]]
    assert found[0]["label"] == "Ada Lovelace"


def test_the_span_covers_the_at_and_the_name() -> None:
    """Stored so the thread can mark exactly those characters — and **not**
    re-derived in the browser, which would be §146's second matcher, free to
    disagree with the one that decided who was notified."""
    body = "thanks @Ada Lovelace"
    found = comments.find_mentions(body, [ADA])
    assert body[found[0]["start"]:found[0]["end"]] == "@Ada Lovelace"


def test_the_longest_name_wins() -> None:
    """**The rule, not an optimisation.**

    Display names have spaces, so there is no token boundary to split on:
    `@Ada` and `@Ada Lovelace` are both readings of the same characters, and
    the longer one is what the writer typed. With both people present, the text
    `@Ada Lovelace` must reach Ada Lovelace and not the other Ada.
    """
    found = comments.find_mentions("@Ada Lovelace please look", [ADA_SHORT, ADA])
    assert [m["user_id"] for m in found] == [ADA["user_id"]]


def test_the_shorter_name_still_works_on_its_own() -> None:
    """The other half — without it, "longest wins" is satisfied by a matcher
    that only ever finds the longest name in the workspace."""
    found = comments.find_mentions("@Ada please look", [ADA_SHORT, ADA])
    assert [m["user_id"] for m in found] == [ADA_SHORT["user_id"]]


def test_an_at_that_matches_nobody_is_left_alone() -> None:
    """An email address in a comment is not a mention, and neither is `@here`.

    Guessing would mean notifying somebody whose name merely starts the same
    way — which is worse than not linking the text, because the person finds
    out by being interrupted.
    """
    assert comments.find_mentions("mail me at bob@example.org", [ADA]) == []
    assert comments.find_mentions("@here anyone?", [ADA]) == []


def test_an_email_is_a_mention_when_it_is_a_member_s_own() -> None:
    """The two ways a person is named here are their display name and the
    address this platform knows them by."""
    found = comments.find_mentions("@ada@example.com ping", [ADA])
    assert [m["user_id"] for m in found] == [ADA["user_id"]]


def test_case_does_not_matter() -> None:
    """Somebody typing a name at speed is not choosing between capitalisations
    — the same argument `ontology_search` makes about casefolding."""
    found = comments.find_mentions("@ADA LOVELACE", [ADA])
    assert [m["user_id"] for m in found] == [ADA["user_id"]]
    # And the **label is the member's own spelling**, not the typist's: the
    # thread should read as the person is called, not as they were typed.
    assert found[0]["label"] == "Ada Lovelace"


def test_several_mentions_come_back_in_the_order_they_appear() -> None:
    found = comments.find_mentions("@Grace Hopper and @Ada Lovelace", [ADA, GRACE])
    assert [m["label"] for m in found] == ["Grace Hopper", "Ada Lovelace"]
    assert found[0]["start"] < found[1]["start"]


def test_a_group_is_not_mentionable() -> None:
    """A workspace member can be a group (`workspace_members.group_id`), and
    p.137 says "mention other users". A group has no user id to notify, so it
    is skipped rather than half-handled."""
    group = {"user_id": None, "display_name": "Operations", "email": None}
    assert comments.find_mentions("@Operations look at this", [group]) == []


def test_nobody_in_the_workspace_means_no_mentions() -> None:
    # The vacuity guard: a parser that returned nothing would pass most of the
    # tests above if the member list were the thing that was broken.
    assert comments.find_mentions("@Ada Lovelace", []) == []
    assert len(comments.find_mentions("@Ada Lovelace", [ADA])) == 1


# --- p.137's attachments ------------------------------------------------------


def test_too_many_files_is_refused_with_a_way_forward() -> None:
    many = [{"key": f"k{i}"} for i in range(comments.MAX_ATTACHMENTS + 1)]
    with pytest.raises(comments.CommentRefused) as refused:
        comments.check_attachments(many)
    assert "at most" in str(refused.value)
    # The refusal says what to do instead, which is the difference between a
    # limit and a wall.
    assert "comments" in str(refused.value)


def test_an_attachment_without_its_key_is_refused() -> None:
    with pytest.raises(comments.CommentRefused):
        comments.check_attachments([{"filename": "notes.pdf"}])


def test_the_allowed_number_is_allowed() -> None:
    # Without this, "too many is refused" is satisfied by refusing everything.
    comments.check_attachments([{"key": f"k{i}"} for i in range(comments.MAX_ATTACHMENTS)])
    comments.check_attachments([])


# --- through the endpoints ----------------------------------------------------


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


@pytest.fixture
def an_object(client: TestClient, fx: Fixture) -> dict:
    """A type and an instance id to hang comments on.

    **The instance need not exist in the store.** db 0078 has no foreign key to
    it — an instance is not a row this schema can reference — so a comment is
    about an id, and this fixture is honest about that rather than building a
    dataset to produce one.
    """
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"c_{uuid.uuid4().hex[:10]}",
              "display_name": f"Comments {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    return {"type_id": r.json()["id"], "instance_id": str(uuid.uuid4())}


def cbase(fx: Fixture, o: dict) -> str:
    return (
        f"{wbase(fx)}/object-types/{o['type_id']}"
        f"/instances/{o['instance_id']}/comments"
    )


def test_a_comment_is_stored_and_read_back(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    r = client.post(cbase(fx, an_object), headers=hdr(fx.editor_sub),
                    json={"body": "this object looks wrong"})
    assert r.status_code == 201, r.text
    r = client.get(cbase(fx, an_object), headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    assert [c["body"] for c in r.json()] == ["this object looks wrong"]
    assert r.json()[0]["author_name"]


def test_the_thread_reads_oldest_first(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """**The opposite of every other listing here**, and not a matter of taste:
    favourites and the scratchpad's history come back newest first because they
    are lists of *your* things. This is a conversation, and a conversation read
    backwards is a different conversation."""
    for said in ("first", "second", "third"):
        client.post(cbase(fx, an_object), headers=hdr(fx.editor_sub),
                    json={"body": said})
    r = client.get(cbase(fx, an_object), headers=hdr(fx.viewer_sub))
    assert [c["body"] for c in r.json()] == ["first", "second", "third"]


def test_an_empty_comment_is_refused(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    for body in ("", "   ", "\n\t "):
        r = client.post(cbase(fx, an_object), headers=hdr(fx.editor_sub),
                        json={"body": body})
        assert r.status_code == 422, (body, r.text)


def test_a_mention_notifies_the_person_named(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """**p.137's second capability, and the half that reaches somebody.**

    A mention that only decorated the text would be a feature nobody could tell
    was working — the point of naming a colleague is that they find out.
    """
    r = client.get(f"{wbase(fx)}/members", headers=hdr(fx.editor_sub))
    viewer = next(m for m in r.json() if str(m["user_id"]) == str(fx.viewer))

    before = client.get("/api/notifications", headers=hdr(fx.viewer_sub)).json()
    r = client.post(
        cbase(fx, an_object), headers=hdr(fx.editor_sub),
        json={"body": f"@{viewer['display_name']} can you look at this"},
    )
    assert r.status_code == 201, r.text
    assert len(r.json()["mentions"]) == 1

    after = client.get("/api/notifications", headers=hdr(fx.viewer_sub)).json()
    assert len(after["items"]) == len(before["items"]) + 1
    newest = after["items"][0]
    assert "comment" in newest["subject"].lower()
    # It links to the object, which is what §309 gave objects URLs for.
    assert newest["link_url"]


def test_mentioning_yourself_does_not_notify_you(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """Naming yourself in your own comment is a way of writing, not a request
    to be interrupted."""
    r = client.get(f"{wbase(fx)}/members", headers=hdr(fx.editor_sub))
    editor = next(m for m in r.json() if str(m["user_id"]) == str(fx.editor))

    before = client.get("/api/notifications", headers=hdr(fx.editor_sub)).json()
    r = client.post(
        cbase(fx, an_object), headers=hdr(fx.editor_sub),
        json={"body": f"@{editor['display_name']} noting this for myself"},
    )
    assert r.status_code == 201, r.text
    # The mention is still recorded — the text says it, and the thread should
    # mark it — but nobody was told.
    assert len(r.json()["mentions"]) == 1
    after = client.get("/api/notifications", headers=hdr(fx.editor_sub)).json()
    assert len(after["items"]) == len(before["items"])


def test_a_mention_of_somebody_outside_the_workspace_is_not_a_mention(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """**The reason mentions are resolved on the server.**

    If the client sent a list of user ids, anybody could have a comment
    delivered to somebody who cannot see the object it is about. Resolving from
    the text against this workspace's members means a mention can only ever
    name somebody already here.
    """
    r = client.post(
        cbase(fx, an_object), headers=hdr(fx.editor_sub),
        json={"body": "@Somebody Else take a look"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["mentions"] == []


def test_the_count_answers_the_header_button(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """p.137 puts a **View comments** button in the header of every Object
    View, and a button that says nothing about whether there is anything behind
    it is a button people stop pressing."""
    r = client.get(f"{cbase(fx, an_object)}/count", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200 and r.json()["count"] == 0
    client.post(cbase(fx, an_object), headers=hdr(fx.editor_sub),
                json={"body": "one"})
    client.post(cbase(fx, an_object), headers=hdr(fx.editor_sub),
                json={"body": "two"})
    r = client.get(f"{cbase(fx, an_object)}/count", headers=hdr(fx.viewer_sub))
    assert r.json()["count"] == 2


def test_a_comment_carries_its_files(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """p.137's third capability. The shape is the upload route's own, so
    nothing new stores bytes — the key is exchanged for them by the download
    route, which is the only place the caller's permission can be checked."""
    r = client.post(
        cbase(fx, an_object), headers=hdr(fx.editor_sub),
        json={"body": "see attached",
              "attachments": [{"key": "k1", "filename": "notes.pdf",
                               "content_type": "application/pdf", "size": 12}]},
    )
    assert r.status_code == 201, r.text
    r = client.get(cbase(fx, an_object), headers=hdr(fx.viewer_sub))
    assert r.json()[0]["attachments"][0]["filename"] == "notes.pdf"


def test_a_viewer_may_read_but_not_write(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    """Reading a conversation about an object is reading the object's context;
    adding to it is a write, and the floor is the same as every other write to
    workspace content."""
    assert client.get(cbase(fx, an_object), headers=hdr(fx.viewer_sub)).status_code == 200
    r = client.post(cbase(fx, an_object), headers=hdr(fx.viewer_sub),
                    json={"body": "may I?"})
    assert r.status_code == 403, r.text


def test_an_outsider_sees_nothing(
    client: TestClient, fx: Fixture, an_object: dict
) -> None:
    r = client.get(cbase(fx, an_object), headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text
