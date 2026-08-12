"""Searching the ontology (parity `docs/parity/ontology.md` §6; Foundry
`ontology-manager` p.28).

> "Use the search bar in the header … to search across object types,
> properties, link types, action types, shared properties, interfaces, and
> functions." (p.28)

Two things are worth testing and they are not the same thing: that each kind is
reachable at all, and that the result says **which field matched** - p.28's
"the search results highlight the specific field that matched your query". A
search that returned the right rows with the wrong reason would pass every
weaker check.
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


@pytest.fixture(scope="module")
def ontology(client: TestClient, fx: Fixture) -> dict:
    """One of each searchable kind, all naming the same distinctive word.

    A shared nonsense word is what makes "did every kind get searched" a single
    query rather than four, and it cannot collide with the accumulated ontology
    of every previous test run in this database.
    """
    word = f"zarquon{uuid.uuid4().hex[:6]}"
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"t_{word}",
            "display_name": f"Type {word}",
            "properties": [
                {"api_name": "status", "data_type": "string",
                 "display_name": f"Status {word}"},
                {"api_name": f"p_{word}", "data_type": "string"},
                {"api_name": "notes", "data_type": "string",
                 "description": f"holds a {word} somewhere in the description"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"far_{word}",
            "display_name": f"Far {word}",
            "properties": [{"api_name": "code", "data_type": "string"}],
        },
    )
    far_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/link-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"l_{word}",
            "display_name": f"Link {word}",
            "from_type_id": type_id,
            "to_type_id": far_id,
            "cardinality": "one_to_many",
            "from_property": "status",
            "to_property": "code",
        },
    )
    assert r.status_code == 201, r.text
    link_id = r.json()["id"]

    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "api_name": f"a_{word}",
            "display_name": f"Action {word}",
            "editable_properties": ["status"],
        },
    )
    assert r.status_code == 201, r.text
    return {"word": word, "type_id": type_id, "far_id": far_id, "link_id": link_id}


def search(client: TestClient, fx: Fixture, q: str, sub: str | None = None) -> list[dict]:
    r = client.get(
        f"{wbase(fx)}/ontology-search?q={q}", headers=hdr(sub or fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_one_query_reaches_every_kind_we_have(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """p.28 lists seven kinds; four exist here. This is the check that all four
    are actually looked at - a search that quietly skipped one would be
    indistinguishable from an ontology that had none of them."""
    hits = search(client, fx, ontology["word"])
    assert {h["kind"] for h in hits} == {
        "object_type", "property", "link_type", "action_type",
    }


def test_a_result_says_which_field_matched(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """**p.28's requirement, and the one a `LIKE` cannot meet.** A database
    query that returns rows says a row matched; it does not say why, and
    "highlight the specific field that matched" needs why."""
    hits = search(client, fx, ontology["word"])
    by_field = {h["matched_field"] for h in hits}
    # All three searched fields are represented by the fixture, on purpose:
    # `p_<word>` matches on api_name, `Status <word>` on display_name, and
    # `notes` only in its description.
    assert by_field == {"api_name", "display_name", "description"}
    notes = next(h for h in hits if h["api_name"] == "notes")
    assert notes["matched_field"] == "description"
    assert ontology["word"] in notes["matched_value"]


def test_a_property_says_which_object_type_it_is_on(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """A property called "status" is not a place anybody can navigate to."""
    hits = search(client, fx, f"p_{ontology['word']}")
    hit = next(h for h in hits if h["kind"] == "property")
    assert hit["object_type_id"] == ontology["type_id"]
    assert hit["object_type_name"].endswith(ontology["word"])


def test_the_search_is_case_insensitive(client: TestClient, fx: Fixture, ontology: dict) -> None:
    assert search(client, fx, ontology["word"].upper())


def test_an_exact_api_name_comes_first(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """Somebody typing a machine name has one particular thing in mind. Ranking
    by table order instead would bury it under whatever happened to be queried
    first."""
    hits = search(client, fx, f"p_{ontology['word']}")
    assert hits[0]["api_name"] == f"p_{ontology['word']}"
    assert hits[0]["matched_field"] == "api_name"


def test_a_description_match_ranks_below_a_name_match(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    """The weakest signal, and last. A description mentioning the word is a
    hint; a name containing it is the thing."""
    hits = search(client, fx, ontology["word"])
    fields = [h["matched_field"] for h in hits]
    assert fields[-1] == "description"


def test_a_blank_query_finds_nothing(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """A search box whose empty state is the whole ontology is a list, and the
    Ontology Manager already has one of those."""
    assert search(client, fx, "") == []
    assert search(client, fx, "%20%20") == []


def test_a_query_matching_nothing_is_an_empty_list(client: TestClient, fx: Fixture) -> None:
    assert search(client, fx, f"nothing{uuid.uuid4().hex}") == []


def test_a_link_type_matches_on_a_side_name(client: TestClient, fx: Fixture, ontology: dict) -> None:
    """A link's side names are what the relationship is *called* from each end
    (`object-link-types` p.192), so somebody looking for "Direct reports" is
    looking for a side rather than for the link's own name."""
    side = f"sidename{uuid.uuid4().hex[:6]}"
    r = client.patch(
        f"{wbase(fx)}/link-types/{ontology['link_id']}",
        headers=hdr(fx.editor_sub),
        json={"from_side_name": side},
    )
    assert r.status_code == 200, r.text
    hits = search(client, fx, side)
    assert [h["kind"] for h in hits] == ["link_type"]
    assert hits[0]["matched_field"] == "from_side_name"


def test_an_outsider_cannot_search_this_workspace(
    client: TestClient, fx: Fixture, ontology: dict
) -> None:
    r = client.get(
        f"{wbase(fx)}/ontology-search?q={ontology['word']}", headers=hdr(fx.outsider_sub)
    )
    assert r.status_code in (403, 404)


def test_the_limit_is_honoured(client: TestClient, fx: Fixture, ontology: dict) -> None:
    r = client.get(
        f"{wbase(fx)}/ontology-search?q={ontology['word']}&limit=2",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200
    assert len(r.json()) == 2
