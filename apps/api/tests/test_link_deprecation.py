"""p.254's deprecation note on a link type (§631; `object-link-types` p.253-256).

> "A deprecated resource also has metadata that includes: A description for
> why it is being deprecated; A deadline for when it is expected to be deleted
> from the system; and The resource that is meant to replace the one that is
> deprecated." (p.254)

Object types, properties and interfaces could carry the note; a link type
had the column (db 0055) and nothing that wrote it. The PATCH route writes it
now, with the status it belongs to, and an ontology file's note is applied.
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

NOTE = {"reason": "Replaced by the crew roster", "deadline": "2027-01-31"}


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


def make_type(client: TestClient, fx: Fixture, prop: str) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"thing_{tag}", "display_name": f"Thing {tag}",
              "properties": [{"api_name": prop, "data_type": "string"}],
              "title_property": prop},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.fixture
def link(client: TestClient, fx: Fixture) -> dict:
    a = make_type(client, fx, "name")
    b = make_type(client, fx, "code")
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"crew_{uuid.uuid4().hex[:6]}", "display_name": "Crew",
              "from_type_id": a["id"], "to_type_id": b["id"],
              "cardinality": "one_to_many",
              "from_property": "name", "to_property": "code"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def patch(client: TestClient, fx: Fixture, link: dict, status_code: int = 200, **body):
    r = client.patch(
        f"{wbase(fx)}/link-types/{link['id']}", headers=hdr(fx.editor_sub),
        json={"from_property": "name", "to_property": "code", **body},
    )
    assert r.status_code == status_code, r.text
    return r.json()


def stored(client: TestClient, fx: Fixture, link: dict) -> dict:
    links = client.get(f"{wbase(fx)}/link-types", headers=hdr(fx.viewer_sub)).json()
    return next(item for item in links if item["id"] == link["id"])


def test_a_deprecated_link_records_why_when_and_what_instead(
    client: TestClient, fx: Fixture, link: dict,
) -> None:
    out = patch(client, fx, link, status="deprecated", deprecation=NOTE)
    assert (out["status"], out["deprecation"]) == ("deprecated", NOTE)
    assert stored(client, fx, link)["deprecation"] == NOTE


def test_an_edit_that_says_nothing_of_the_note_keeps_it(
    client: TestClient, fx: Fixture, link: dict,
) -> None:
    """Editing the join, or the side names, is not a request to forget why the
    link is going."""
    patch(client, fx, link, status="deprecated", deprecation=NOTE)
    assert patch(client, fx, link, from_side_name="Captain")["deprecation"] == NOTE
    assert patch(client, fx, link, status="deprecated")["deprecation"] == NOTE
    # Null is a request to clear it, and leaves the link deprecated.
    cleared = patch(client, fx, link, status="deprecated", deprecation=None)
    assert (cleared["status"], cleared["deprecation"]) == ("deprecated", None)


def test_leaving_deprecated_drops_the_note(
    client: TestClient, fx: Fixture, link: dict,
) -> None:
    """p.254's rule as the other kinds have it: a link that is no longer going
    does not keep explaining why it was."""
    patch(client, fx, link, status="deprecated", deprecation=NOTE)
    out = patch(client, fx, link, status="experimental")
    assert (out["status"], out["deprecation"]) == ("experimental", None)


def test_a_note_on_a_link_that_is_not_deprecated_is_refused(
    client: TestClient, fx: Fixture, link: dict,
) -> None:
    r = patch(client, fx, link, status_code=422, status="experimental", deprecation=NOTE)
    assert "only to a deprecated" in str(r)
    r = patch(client, fx, link, status_code=422, status="deprecated",
              deprecation={"deadline": "soon"})
    assert "ISO 8601" in str(r)
    assert stored(client, fx, link)["deprecation"] is None
