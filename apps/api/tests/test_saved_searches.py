"""Saved searches for the Object Explorer (ROADMAP.md phase 2, item 4.1).

The explorer itself has existed since `STATUS.md` §32. What is new is saving a
search, and the property worth protecting is not "can we store some json" but:
**a search that cannot run cannot be saved.** The explorer's rule - a property
filter needs exactly one type, because a property name only means something
within a type - used to live in the route. It now lives in one function that
both the route and the save path call, so the two cannot disagree.
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
            "api_name": f"vessel_{tag}", "display_name": f"Vessel {tag}",
            "properties": [
                {"api_name": "imo", "display_name": "IMO", "data_type": "string",
                 "required": True},
                {"api_name": "flag", "display_name": "Flag", "data_type": "string",
                 "required": False},
            ],
            "title_property": "imo",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def save(client: TestClient, fx: Fixture, definition: dict, name: str | None = None,
         sub: str | None = None):
    return client.post(
        f"{wbase(fx)}/object-searches", headers=hdr(sub or fx.editor_sub),
        json={"name": name or f"Search {uuid.uuid4().hex[:8]}", "definition": definition},
    )


# ---- what a saved search is --------------------------------------------------
def test_a_saved_search_stores_the_question_not_the_answer(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """"Vessels flagged NO" is a question, and the answer is different
    tomorrow. Storing rows would turn a live question into a stale report."""
    r = save(client, fx, {"q": "aurora", "type_ids": [a_type]})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["definition"]["q"] == "aurora"
    assert body["definition"]["type_ids"] == [a_type]
    assert "items" not in body and "results" not in body


def test_a_saved_search_resolves_its_type_names_for_display(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    made = save(client, fx, {"q": "x", "type_ids": [a_type]}).json()
    assert len(made["type_names"]) == 1 and made["type_names"][0].startswith("Vessel ")
    assert made["missing_types"] == []


def test_a_search_naming_a_deleted_type_still_opens_and_says_which(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """It still opens - that filter simply matches nothing - and saying so
    beats rendering a bare uuid, or refusing to open something somebody may
    want to repair."""
    made = save(client, fx, {"q": "x", "type_ids": [a_type]}).json()
    assert client.delete(
        f"{wbase(fx)}/object-types/{a_type}", headers=hdr(fx.editor_sub)
    ).status_code in (204, 200)

    again = client.get(f"{wbase(fx)}/object-searches", headers=hdr(fx.viewer_sub))
    assert again.status_code == 200, again.text
    row = next(s for s in again.json() if s["id"] == made["id"])
    assert row["type_names"] == []
    assert row["missing_types"] == [a_type]


# ---- the rule that used to live in the route ---------------------------------
def test_a_search_that_could_not_run_cannot_be_saved(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """The point of moving the rule: otherwise the person who finds out is not
    the person who made the mistake."""
    r = save(client, fx, {"property": "flag", "value": "NO"})
    assert r.status_code == 422, r.text
    assert "exactly one type_id" in r.json()["detail"]


def test_half_a_filter_is_refused_both_ways(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    for definition in (
        {"type_ids": [a_type], "property": "flag"},
        {"type_ids": [a_type], "value": "NO"},
    ):
        r = save(client, fx, definition)
        assert r.status_code == 422, (definition, r.text)
        assert "both" in r.json()["detail"]


def test_a_property_filter_with_one_type_is_fine(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    r = save(client, fx, {"type_ids": [a_type], "property": "flag", "value": "NO"})
    assert r.status_code == 201, r.text
    assert r.json()["definition"]["property"] == "flag"


def test_a_search_with_nothing_in_it_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """Browsing everything is a reasonable thing to do in the explorer. Saving
    it under a name is a named question with no question in it."""
    r = save(client, fx, {})
    assert r.status_code == 422, r.text
    assert "something to search for" in r.json()["detail"]


def test_the_explorer_still_browses_everything(client: TestClient, fx: Fixture) -> None:
    """The same function validates both, so this is the assertion that stops
    the shared rule from tightening the explorer by accident."""
    r = client.get(f"{wbase(fx)}/object-instances", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text


def test_the_explorer_still_refuses_a_property_across_two_types(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    other = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"port_{uuid.uuid4().hex[:8]}",
              "display_name": f"Port {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "flag", "display_name": "Flag",
                              "data_type": "string", "required": False}]},
    ).json()["id"]
    r = client.get(
        f"{wbase(fx)}/object-instances", headers=hdr(fx.viewer_sub),
        params=[("type_id", a_type), ("type_id", other),
                ("property", "flag"), ("value", "NO")],
    )
    assert r.status_code == 422, r.text


def test_the_same_type_twice_is_refused(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    r = save(client, fx, {"q": "x", "type_ids": [a_type, a_type]})
    assert r.status_code == 422, r.text
    assert "twice" in r.json()["detail"]


def test_a_deleted_type_matches_nothing_with_or_without_a_property_filter(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """A saved search outlives the type it names, so running one is the normal
    case, not an error case. It has to give the *same* answer either way - one
    branch refusing and the other quietly returning nothing is two behaviours
    for one question, and which one you hit would depend on a filter that has
    nothing to do with the type being gone."""
    assert client.delete(
        f"{wbase(fx)}/object-types/{a_type}", headers=hdr(fx.editor_sub)
    ).status_code in (204, 200)

    plain = client.get(
        f"{wbase(fx)}/object-instances", headers=hdr(fx.viewer_sub),
        params=[("type_id", a_type)],
    )
    filtered = client.get(
        f"{wbase(fx)}/object-instances", headers=hdr(fx.viewer_sub),
        params=[("type_id", a_type), ("property", "flag"), ("value", "NO")],
    )
    assert plain.status_code == 200, plain.text
    assert filtered.status_code == 200, filtered.text
    assert plain.json()["total"] == 0
    assert filtered.json()["total"] == 0


def test_a_type_in_the_list_says_where_it_opens(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """The explorer is workspace-wide and has no project in its URL, so it
    cannot build a project-scoped link to a type. It sends people to the type's
    own application instead (item 4.2), which needs the resource id on the type
    it already has - and the id has to *resolve*, since a plausible-looking
    uuid that 404s is worse than no link at all."""
    listed = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    assert listed.status_code == 200, listed.text
    row = next(t for t in listed.json() if t["id"] == a_type)

    resolved = client.get(f"/api/resources/{row['resource_id']}", headers=hdr(fx.viewer_sub))
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["kind"] == "object_type"
    assert resolved.json()["kind_id"] == a_type


# ---- managing them -----------------------------------------------------------
def test_searches_are_shared_within_the_workspace(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """A saved search is usually a definition of a cohort a team argues about.
    One only its author can see gets reinvented slightly differently by
    everybody else."""
    made = save(client, fx, {"q": "shared", "type_ids": [a_type]},
                sub=fx.editor_sub).json()
    seen = client.get(f"{wbase(fx)}/object-searches", headers=hdr(fx.viewer_sub))
    assert seen.status_code == 200, seen.text
    assert any(s["id"] == made["id"] for s in seen.json())


def test_two_searches_cannot_share_a_name(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """Two searches called "Active vessels" that differ is the thing sharing
    them exists to prevent."""
    name = f"Duplicate {uuid.uuid4().hex[:6]}"
    assert save(client, fx, {"q": "a", "type_ids": [a_type]}, name=name).status_code == 201
    again = save(client, fx, {"q": "b", "type_ids": [a_type]}, name=name)
    assert again.status_code == 409, again.text


def test_editing_a_search_revalidates_its_definition(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    made = save(client, fx, {"q": "fine", "type_ids": [a_type]}).json()
    r = client.patch(
        f"{wbase(fx)}/object-searches/{made['id']}", headers=hdr(fx.editor_sub),
        json={"definition": {"property": "flag", "value": "NO"}},
    )
    assert r.status_code == 422, r.text

    # and the stored definition is untouched
    still = client.get(f"{wbase(fx)}/object-searches", headers=hdr(fx.viewer_sub)).json()
    assert next(s for s in still if s["id"] == made["id"])["definition"]["q"] == "fine"


def test_renaming_and_deleting(client: TestClient, fx: Fixture, a_type: str) -> None:
    made = save(client, fx, {"q": "rename me", "type_ids": [a_type]}).json()
    renamed = client.patch(
        f"{wbase(fx)}/object-searches/{made['id']}", headers=hdr(fx.editor_sub),
        json={"name": f"Renamed {uuid.uuid4().hex[:6]}"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"].startswith("Renamed")
    assert renamed.json()["definition"]["q"] == "rename me", "a rename changed the question"

    assert client.delete(
        f"{wbase(fx)}/object-searches/{made['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    left = client.get(f"{wbase(fx)}/object-searches", headers=hdr(fx.viewer_sub)).json()
    assert not any(s["id"] == made["id"] for s in left)


# ---- permissions -------------------------------------------------------------
def test_a_viewer_reads_and_cannot_write(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    made = save(client, fx, {"q": "x", "type_ids": [a_type]}).json()
    assert client.get(
        f"{wbase(fx)}/object-searches", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    assert save(client, fx, {"q": "y", "type_ids": [a_type]},
                sub=fx.viewer_sub).status_code == 403
    assert client.delete(
        f"{wbase(fx)}/object-searches/{made['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 403


def test_another_workspace_cannot_see_them(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    save(client, fx, {"q": "private", "type_ids": [a_type]})
    for sub in (fx.outsider_sub, fx.foreign_sub):
        r = client.get(f"{wbase(fx)}/object-searches", headers=hdr(sub))
        assert r.status_code in (403, 404), (sub, r.text)
