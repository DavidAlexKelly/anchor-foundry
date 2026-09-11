"""Favourite objects (§312; db 0074; `getting-started` p.34).

    "When you navigate to an individual object view, you can select the star
     next to its title to save it as a favorite. This will add the object to
     your sidebar… Think of favorites as shortcuts that you can add and remove
     to keep frequently used resources close at hand." (p.34)

The star and the sidebar need a browser. What is here is everything that is
*not* a screen: that starring twice is one star, that the list is private, that
a full list refuses rather than evicting, and that a favourite survives the
object it points at going away — which p.34's "shortcut" implies and db 0074
cannot enforce, because an instance is not a row this schema can reference.
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


@pytest.fixture()
def a_type(client: TestClient, fx: Fixture) -> str:
    tag = uuid.uuid4().hex[:8]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"ship_{tag}", "display_name": f"Ship {tag}",
            "properties": [
                {"api_name": "imo", "display_name": "IMO", "data_type": "string",
                 "required": True},
            ],
            "title_property": "imo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def star(client, fx, type_id, instance_id, *, label="", sub=None):
    return client.put(
        f"{wbase(fx)}/object-favourites",
        headers=hdr(sub or fx.editor_sub),
        json={"object_type_id": type_id, "instance_id": str(instance_id),
              "label": label},
    )


def mine(client, fx, *, sub=None):
    r = client.get(f"{wbase(fx)}/object-favourites", headers=hdr(sub or fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


# --- The star ---------------------------------------------------------------


def test_starring_an_object_puts_it_in_the_list(client: TestClient, fx: Fixture,
                                                a_type: str) -> None:
    """p.34's shortcut, kept."""
    instance = uuid.uuid4()
    answer = star(client, fx, a_type, instance, label="IMO 9074729")
    assert answer.status_code == 200, answer.text

    row = next(f for f in mine(client, fx) if f["instance_id"] == str(instance))
    assert row["label"] == "IMO 9074729"
    assert row["object_type_id"] == a_type
    # The type's name is joined, so a row can say what kind of thing it is
    # without the reader having to recognise a UUID.
    assert row["object_type_name"].startswith("Ship ")


def test_starring_twice_is_one_star(client: TestClient, fx: Fixture,
                                    a_type: str) -> None:
    """**PUT rather than POST**, and this is why: the button's state arrived a
    moment ago, so a second press is the ordinary case rather than a mistake.
    A route that refused it would be a toggle that can fail for having worked.
    """
    instance = uuid.uuid4()
    first = star(client, fx, a_type, instance, label="once")
    again = star(client, fx, a_type, instance, label="once")
    assert again.status_code == 200, again.text
    assert again.json()["id"] == first.json()["id"]
    assert len([f for f in mine(client, fx) if f["instance_id"] == str(instance)]) == 1


def test_starring_again_refreshes_the_label(client: TestClient, fx: Fixture,
                                            a_type: str) -> None:
    """The label is a snapshot, and this is the one moment the current name is
    in hand — the object may have been renamed since it was first starred."""
    instance = uuid.uuid4()
    star(client, fx, a_type, instance, label="old name")
    star(client, fx, a_type, instance, label="new name")
    row = next(f for f in mine(client, fx) if f["instance_id"] == str(instance))
    assert row["label"] == "new name"


def test_the_star_can_be_asked_about_one_object(client: TestClient, fx: Fixture,
                                                a_type: str) -> None:
    """An object view has no reason to fetch a hundred favourites to decide the
    state of one button."""
    instance = uuid.uuid4()
    where = f"{wbase(fx)}/object-favourites/{a_type}/{instance}"
    assert client.get(where, headers=hdr(fx.editor_sub)).json() == {"favourite": False}
    star(client, fx, a_type, instance)
    assert client.get(where, headers=hdr(fx.editor_sub)).json() == {"favourite": True}


def test_unstarring_takes_it_out(client: TestClient, fx: Fixture, a_type: str) -> None:
    """Addressed by what it points at rather than by the row's id, because that
    is what the star has."""
    instance = uuid.uuid4()
    star(client, fx, a_type, instance)
    gone = client.delete(
        f"{wbase(fx)}/object-favourites/{a_type}/{instance}",
        headers=hdr(fx.editor_sub),
    )
    assert gone.status_code == 204, gone.text
    assert [f for f in mine(client, fx) if f["instance_id"] == str(instance)] == []


def test_unstarring_something_that_is_not_starred_says_so(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """404 rather than a silent success: a star that refuses to come off is a
    bug, and a route that reports success either way cannot tell you which
    happened."""
    answer = client.delete(
        f"{wbase(fx)}/object-favourites/{a_type}/{uuid.uuid4()}",
        headers=hdr(fx.editor_sub),
    )
    assert answer.status_code == 404, answer.text


# --- Whose they are ---------------------------------------------------------


def test_another_persons_favourites_are_not_visible(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """**db 0074's policy, not a service rule.** p.34 puts these in *your*
    sidebar; a shared list would be a different feature, and workspace access
    alone would put everybody's shortcuts in everybody's sidebar."""
    instance = uuid.uuid4()
    star(client, fx, a_type, instance, label="mine", sub=fx.editor_sub)
    assert [f for f in mine(client, fx, sub=fx.admin_sub)
            if f["instance_id"] == str(instance)] == []


def test_two_people_can_star_the_same_object(client: TestClient, fx: Fixture,
                                             a_type: str) -> None:
    """The uniqueness is per person. A shortcut somebody else already has is
    not a shortcut you are refused."""
    instance = uuid.uuid4()
    assert star(client, fx, a_type, instance, sub=fx.editor_sub).status_code == 200
    assert star(client, fx, a_type, instance, sub=fx.admin_sub).status_code == 200
    assert client.get(
        f"{wbase(fx)}/object-favourites/{a_type}/{instance}", headers=hdr(fx.admin_sub)
    ).json() == {"favourite": True}


def test_a_viewer_may_keep_favourites(client: TestClient, fx: Fixture,
                                      a_type: str) -> None:
    """A favourite is a note to yourself about what you are reading. An editor
    floor would mean somebody who may read an object may not keep a shortcut
    to it."""
    instance = uuid.uuid4()
    assert star(client, fx, a_type, instance, sub=fx.viewer_sub).status_code == 200


# --- The edges --------------------------------------------------------------


def test_a_type_from_another_workspace_is_refused_with_a_message(
    client: TestClient, fx: Fixture
) -> None:
    """The policy makes such a type invisible rather than refused, so without
    this the caller gets a foreign-key error about a row they cannot see."""
    answer = star(client, fx, str(uuid.uuid4()), uuid.uuid4())
    assert answer.status_code == 404, answer.text


def test_a_full_list_refuses_rather_than_evicting(client: TestClient, fx: Fixture,
                                                  a_type: str) -> None:
    """**The opposite of §306's scratchpad history, for the opposite reason.**

    A history is a record of what you did, so dropping its oldest entry loses
    nothing anybody chose. A favourite *is* the choice, so silently dropping
    the least recent would delete a decision — and the person it happened to
    would find out by not finding something.
    """
    from src.services.object_favourites import MAX_FAVOURITES

    # Its own person, so the cap is about this test rather than about whatever
    # else has run against this workspace.
    who = fx.viewer_sub
    for f in mine(client, fx, sub=who):
        client.delete(
            f"{wbase(fx)}/object-favourites/{f['object_type_id']}/{f['instance_id']}",
            headers=hdr(who),
        )

    for _ in range(MAX_FAVOURITES):
        assert star(client, fx, a_type, uuid.uuid4(), sub=who).status_code == 200

    full = star(client, fx, a_type, uuid.uuid4(), sub=who)
    assert full.status_code == 409, full.text
    assert str(MAX_FAVOURITES) in full.json()["detail"]
    assert len(mine(client, fx, sub=who)) == MAX_FAVOURITES


def test_a_full_list_still_lets_you_restar_something_in_it(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """The cap counts rows about to be *added*. Refusing a re-star of something
    already in a full list would make the button fail on the object it is
    already pointing at."""
    from src.services.object_favourites import MAX_FAVOURITES

    who = fx.viewer_sub
    for f in mine(client, fx, sub=who):
        client.delete(
            f"{wbase(fx)}/object-favourites/{f['object_type_id']}/{f['instance_id']}",
            headers=hdr(who),
        )
    kept = uuid.uuid4()
    assert star(client, fx, a_type, kept, label="first", sub=who).status_code == 200
    for _ in range(MAX_FAVOURITES - 1):
        assert star(client, fx, a_type, uuid.uuid4(), sub=who).status_code == 200

    again = star(client, fx, a_type, kept, label="still here", sub=who)
    assert again.status_code == 200, again.text
    assert again.json()["label"] == "still here"


def test_deleting_the_object_type_takes_its_favourites_with_it(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """db 0074's `ON DELETE CASCADE` on the *type*, and the reason it is there:
    a shortcut cannot be resolved once the type it names is gone, so leaving
    the row would leave one nothing can ever render."""
    instance = uuid.uuid4()
    star(client, fx, a_type, instance)
    assert client.delete(
        f"{wbase(fx)}/object-types/{a_type}", headers=hdr(fx.editor_sub)
    ).status_code in (200, 204)
    assert [f for f in mine(client, fx) if f["instance_id"] == str(instance)] == []


def test_a_favourite_outlives_the_object_it_names(client: TestClient, fx: Fixture,
                                                  a_type: str) -> None:
    """**A real state, not a defect.**

    An instance lives in the instance store rather than in a table this schema
    can reference, so there is no foreign key that could clean this up — and
    p.34's shortcut to something since deleted is exactly the case §309's
    dead-link message was written for. The row stays and the list shows it;
    following it is what says the object is gone.
    """
    never_existed = uuid.uuid4()
    assert star(client, fx, a_type, never_existed, label="ghost").status_code == 200
    row = next(f for f in mine(client, fx) if f["instance_id"] == str(never_existed))
    assert row["label"] == "ghost"


def test_the_newest_favourite_is_first(client: TestClient, fx: Fixture,
                                       a_type: str) -> None:
    """p.34's shortcuts are what somebody is working on *now*. A list sorted by
    a label the reader did not choose would bury today's work under a name
    beginning with A."""
    who = fx.admin_sub
    older, newer = uuid.uuid4(), uuid.uuid4()
    star(client, fx, a_type, older, label="zebra", sub=who)
    star(client, fx, a_type, newer, label="apple", sub=who)
    listed = [f["instance_id"] for f in mine(client, fx, sub=who)]
    assert listed.index(str(newer)) < listed.index(str(older))
