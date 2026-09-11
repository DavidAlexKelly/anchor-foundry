"""What was edited last (§317; db 0075; `ontology-manager` p.30).

    "Hovering over the Back home button will also bring up quick links to
     recently edited object types, link types, and action types, as well as
     all resources that are related to the one you are currently viewing."
     (p.30)

**The shared workspace is the whole difficulty here.** Every test run in this
database adds to one ontology, so "my type is in the list" is a claim about how
many other things happened to be edited since — and it would pass against an
endpoint that returned everything. So the assertions below are about *order*
and about *what moves an entry*, both of which stay true however much else is
in the workspace: edit a thing, and it is the first row; edit a second thing,
and the first drops behind it.
"""
from __future__ import annotations

import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import ontology_recent  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)


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


def recent(client: TestClient, fx: Fixture, sub: str | None = None,
           **params: object) -> list[dict]:
    r = client.get(
        f"{wbase(fx)}/ontology-recent", headers=hdr(sub or fx.viewer_sub),
        params=params,
    )
    assert r.status_code == 200, r.text
    return r.json()


def a_type(client: TestClient, fx: Fixture, tag: str) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"recent_{tag}", "display_name": f"Recent {tag}",
              "properties": [{"api_name": "code", "data_type": "string",
                              "display_name": "Code"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rename(client: TestClient, fx: Fixture, type_id: str, name: str) -> None:
    r = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": name, "description": "", "icon": "cube",
              "colour": "#4f46e5",
              "properties": [{"api_name": "code", "data_type": "string",
                              "display_name": "Code"}],
              "title_property": None},
    )
    assert r.status_code == 200, r.text


@pytest.fixture(scope="module")
def pair(client: TestClient, fx: Fixture) -> dict:
    """Two types and a link between them, so all three of p.30's kinds exist."""
    tag = uuid.uuid4().hex[:8]
    near = a_type(client, fx, f"near{tag}")
    far = a_type(client, fx, f"far{tag}")
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"lk_{tag}", "display_name": f"Link {tag}",
              "from_type_id": near, "to_type_id": far,
              "cardinality": "one_to_many",
              "from_property": "code", "to_property": "code"},
    )
    assert r.status_code == 201, r.text
    link = r.json()["id"]
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": near, "api_name": f"act_{tag}",
              "display_name": f"Action {tag}", "editable_properties": ["code"]},
    )
    assert r.status_code == 201, r.text
    return {"tag": tag, "near": near, "far": far, "link": link,
            "action": r.json()["id"]}


def test_the_thing_just_edited_is_first(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """**p.30's whole claim**, and the only form of it that survives a shared
    workspace: whatever was edited last is at the top, whoever else has been
    editing.
    """
    rename(client, fx, pair["near"], f"Renamed {uuid.uuid4().hex[:6]}")
    rows = recent(client, fx)
    assert rows[0]["id"] == pair["near"], [r["display_name"] for r in rows[:3]]
    assert rows[0]["kind"] == "object_type"


def test_editing_the_other_one_moves_it_ahead(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """The direction, which a list sorted by *anything* recent would satisfy
    only by accident.

    A single "my thing is first" passes against a list ordered by created_at,
    by id, or by whatever the planner felt like — this one fails for all three,
    because it changes the answer between two reads without creating anything.
    """
    rename(client, fx, pair["near"], f"First {uuid.uuid4().hex[:6]}")
    assert recent(client, fx)[0]["id"] == pair["near"]
    rename(client, fx, pair["far"], f"Second {uuid.uuid4().hex[:6]}")
    rows = recent(client, fx)
    assert rows[0]["id"] == pair["far"]
    assert rows[1]["id"] == pair["near"]


def test_an_edited_link_type_reaches_the_list(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """**The kind that had no column to read** (db 0075).

    `link_types` gained six editable columns over fifty migrations and never an
    `updated_at`, so before this unit a link type could be renamed, restatused
    and remapped without any record that anything had happened. This is the
    assertion that would have gone red for the whole of that time.
    """
    r = client.patch(
        f"{wbase(fx)}/link-types/{pair['link']}", headers=hdr(fx.editor_sub),
        json={"from_side_name": f"side{uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text
    rows = recent(client, fx)
    assert rows[0]["id"] == pair["link"]
    assert rows[0]["kind"] == "link_type"
    # It belongs to the type at its `from` end — a link listed under no type is
    # a quick link to nowhere.
    assert rows[0]["object_type_id"] == pair["near"]


def test_an_edited_action_type_reaches_the_list(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """p.30's third kind. Action types have carried `updated_at` since db 0013,
    so this one only had to be asked."""
    r = client.patch(
        f"{wbase(fx)}/action-types/{pair['action']}", headers=hdr(fx.editor_sub),
        json={"display_name": f"Renamed {uuid.uuid4().hex[:6]}"},
    )
    assert r.status_code == 200, r.text
    rows = recent(client, fx)
    assert rows[0]["id"] == pair["action"]
    assert rows[0]["kind"] == "action_type"
    assert rows[0]["object_type_id"] == pair["near"]


def test_a_new_link_type_does_not_claim_to_be_older_than_it_is(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """db 0075's backfill, from the other end.

    A `DEFAULT now()` column with no backfill would have told every link type
    in every workspace that it was edited the moment the migration ran; a
    backfill from `created_at` says the last moment we can vouch for. Either
    way a *newly created* link type must say it was touched when it was made,
    not at some default.
    """
    tag = uuid.uuid4().hex[:8]
    near = a_type(client, fx, f"fresh{tag}")
    far = a_type(client, fx, f"freshfar{tag}")
    r = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"fl_{tag}", "display_name": f"Fresh {tag}",
              "from_type_id": near, "to_type_id": far,
              "cardinality": "one_to_many",
              "from_property": "code", "to_property": "code"},
    )
    assert r.status_code == 201, r.text
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        row = c.execute(
            "SELECT created_at, updated_at FROM link_types WHERE id = %s",
            (r.json()["id"],),
        ).fetchone()
    assert row is not None
    assert row[0] == row[1], "a link type nobody has edited was born edited"


def test_only_the_three_kinds_p30_names_are_in_the_list(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """Shared properties, groups, value types and interfaces are findable by
    name in the search this sits beside; p.30's list stops at three, and a
    fourth kind here would be a specification we invented."""
    rename(client, fx, pair["near"], f"Kinds {uuid.uuid4().hex[:6]}")
    kinds = {r["kind"] for r in recent(client, fx, limit=ontology_recent.MAX_LIMIT)}
    assert kinds <= {"object_type", "link_type", "action_type"}


def test_the_list_is_as_short_as_it_says(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """A quick-links hover is not a listing. The default is small on purpose,
    and the caller can ask for fewer."""
    assert len(recent(client, fx)) <= ontology_recent.DEFAULT_LIMIT
    assert len(recent(client, fx, limit=2)) == 2


def test_a_limit_outside_the_range_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """A "quick links" endpoint asked for a thousand rows is a listing endpoint
    under a name that promises it is cheap."""
    for bad in (0, ontology_recent.MAX_LIMIT + 1):
        r = client.get(
            f"{wbase(fx)}/ontology-recent", headers=hdr(fx.viewer_sub),
            params={"limit": bad},
        )
        assert r.status_code == 422, (bad, r.text)


def test_the_service_refuses_the_same_range_the_route_does() -> None:
    """The route bounds the query parameter so FastAPI can name it in a 422;
    the service refuses because it is the thing that knows what the number
    means. Both, deliberately — a caller that is not this route (a script, a
    future endpoint) gets the same answer."""
    import asyncio

    with pytest.raises(ValueError):
        asyncio.run(ontology_recent.recent(None, uuid.uuid4(), limit=0))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        asyncio.run(
            ontology_recent.recent(
                None, uuid.uuid4(), limit=ontology_recent.MAX_LIMIT + 1  # type: ignore[arg-type]
            )
        )


def test_an_outsider_sees_nothing_of_this_workspace(
    client: TestClient, fx: Fixture, pair: dict
) -> None:
    """The row policy decides which workspace's rows exist at all, so this can
    only ever mean "recently edited in a workspace you can already list"."""
    r = client.get(
        f"{wbase(fx)}/ontology-recent", headers=hdr(fx.outsider_sub)
    )
    assert r.status_code in (403, 404), r.text
