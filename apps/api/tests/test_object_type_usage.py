"""Usage metrics per object type (§320; db 0077; `ontology-manager` p.32-34).

    "Note that one read represents one load request… Many objects loaded or
     aggregated at once will only be recorded as a single read. Also note that
     any object type or link type usage happening in Ontology Manager is not
     included." (p.32)

p.32's two sentences are the whole of what is hard here, and both are rules a
plausible implementation gets wrong in the same direction: counting per
*object* instead of per *request* makes every number roughly five hundred times
too big, and counting the Ontology Manager makes a type look used by the person
deciding whether to change it.

**The window is faked by writing rows in the past**, through the admin
connection. Thirty days is not a thing a test can wait for, and the alternative
— parameterising the window and passing a small one — would test a number the
product never uses.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import object_type_usage as usage  # noqa: E402

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


@pytest.fixture
def a_type(client: TestClient, fx: Fixture) -> str:
    """A type of its own per test, so a count is about this test's requests.

    Module-scoped would make every assertion below a claim about how many
    other tests had run first — the shape §310 turned into five CI failures.
    """
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"usage_{uuid.uuid4().hex[:10]}",
              "display_name": f"Usage {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def write_usage(type_id: str, *, user_id: str | None, days_ago: int,
                application: str, reads: int = 0, writes: int = 0) -> None:
    """Put a row in the past, which is the only way to test a 30-day window."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as c:
        c.execute(
            "INSERT INTO object_type_usage"
            " (object_type_id, user_id, day, application, reads, writes)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (type_id, user_id, date.today() - timedelta(days=days_ago),
             application, reads, writes),
        )


def summary(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}/usage", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- p.32's counting rules ----------------------------------------------------


def test_the_ontology_manager_does_not_count() -> None:
    """**p.32's exclusion, by name**: "any object type or link type usage
    happening in Ontology Manager is not included."

    Decided here rather than by a caller that happens not to call, because the
    same endpoints serve the Ontology Manager's object list and the Object
    Explorer's — so the exclusion has to be something the recorder recognises.
    """
    assert usage.counts("explorer") is True
    assert usage.counts(usage.ONTOLOGY_MANAGER) is False


def test_an_application_nobody_declared_still_counts() -> None:
    """A new screen that forgot to add itself is a mislabelled row.

    Dropping its usage would make the numbers quietly wrong in the direction
    nobody checks — a type would look less used than it is, which is the
    direction that gets a property renamed.
    """
    assert usage.counts("some_screen_built_later") is True


def test_the_window_is_thirty_days() -> None:
    """Named once, because a 30 written in four places is a 30 that becomes a
    31 in one of them."""
    assert usage.WINDOW_DAYS == 30


# --- the four numbers ---------------------------------------------------------


def test_a_type_nobody_has_used_reports_zeroes(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """p.33's "No usage for the last 30 days", as numbers rather than an
    absence: a screen has to be able to draw the empty state, and a 404 or a
    null would make every caller invent one."""
    said = summary(client, fx, a_type)
    assert said["reads"] == 0 and said["writes"] == 0
    assert said["interactions"] == 0 and said["active_users"] == 0
    assert said["window_days"] == 30


def test_interactions_is_reads_plus_writes(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """p.32: "Interactions: The total number of reads and writes on objects of
    this type over the last 30 days."

    **Computed, not stored.** A stored total is a third number free to disagree
    with the two it came from.
    """
    write_usage(a_type, user_id=str(fx.viewer), days_ago=1,
                application="explorer", reads=7, writes=2)
    said = summary(client, fx, a_type)
    assert (said["reads"], said["writes"]) == (7, 2)
    assert said["interactions"] == 9


def test_usage_older_than_the_window_is_not_counted(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """The window is the point of the number: p.33 wants it "to quickly
    understand the implications of making a breaking change", and usage from
    last spring does not bear on that."""
    write_usage(a_type, user_id=str(fx.viewer), days_ago=1,
                application="explorer", reads=3)
    write_usage(a_type, user_id=str(fx.viewer), days_ago=45,
                application="explorer", reads=100)
    assert summary(client, fx, a_type)["reads"] == 3


def test_active_users_counts_people_not_requests(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """p.32: "the number of unique user IDs that triggered the reads and writes
    recorded over the last 30 days".

    **This is the number that changes the decision.** Thirty reads by one
    person and thirty by thirty people are the same `reads` and a completely
    different answer to "can I rename this property".
    """
    write_usage(a_type, user_id=str(fx.viewer), days_ago=1,
                application="explorer", reads=20)
    write_usage(a_type, user_id=str(fx.editor), days_ago=2,
                application="workshop", reads=1)
    said = summary(client, fx, a_type)
    assert said["reads"] == 21
    assert said["active_users"] == 2


def test_a_request_with_nobody_behind_it_counts_as_usage_but_not_as_a_user(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """A background job's reads are reads. p.32 counts "unique user IDs", and a
    service account has none — so the row is kept and the headcount does not
    include it, rather than the read being thrown away to keep the two
    numbers looking consistent."""
    write_usage(a_type, user_id=None, days_ago=1, application="api", reads=5)
    said = summary(client, fx, a_type)
    assert said["reads"] == 5
    assert said["active_users"] == 0


# --- p.33's "in which Foundry applications" -----------------------------------


def test_usage_is_broken_down_by_application(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """p.33: "who has used each object type, when, and in which Foundry
    applications"."""
    write_usage(a_type, user_id=str(fx.viewer), days_ago=1,
                application="explorer", reads=2)
    write_usage(a_type, user_id=str(fx.editor), days_ago=1,
                application="workshop", reads=9, writes=1)
    r = client.get(
        f"{wbase(fx)}/object-types/{a_type}/usage/by-application",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    # Ordered by how much each did, because the question is "who would notice
    # if I changed this" and the biggest user is the answer.
    assert [x["application"] for x in rows] == ["workshop", "explorer"]
    assert rows[0]["interactions"] == 10
    assert rows[1]["interactions"] == 2


def test_usage_is_broken_down_by_day(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """p.33's "when". **Days with no usage are absent rather than zero** — a
    query that manufactured thirty rows would be inventing data to make a chart
    easier, and every reader would then have to know which rows were real."""
    write_usage(a_type, user_id=str(fx.viewer), days_ago=1,
                application="explorer", reads=2)
    write_usage(a_type, user_id=str(fx.viewer), days_ago=3,
                application="explorer", reads=4)
    r = client.get(
        f"{wbase(fx)}/object-types/{a_type}/usage/daily",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 2, rows
    assert rows[0]["day"] < rows[1]["day"]
    assert rows[1]["reads"] == 2


def test_an_outsider_cannot_read_this_type_s_usage(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """The row policy decides which workspace's rows exist; the route asks for
    viewer, like everything else that reads the ontology's shape."""
    r = client.get(
        f"{wbase(fx)}/object-types/{a_type}/usage", headers=hdr(fx.outsider_sub)
    )
    assert r.status_code in (403, 404), r.text


# --- the counting, through the endpoints that do it ---------------------------


@pytest.fixture
def with_objects(client: TestClient, fx: Fixture, a_type: str) -> str:
    """The type from `a_type`, with a source and two objects behind it."""
    import io

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"UsageRows {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(b"k,name\n1,one\n2,two\n"), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": a_type, "dataset_id": r.json()["id"],
              "primary_key_column": "k", "column_mappings": {"name": "name"}},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 200, r.text
    return a_type


def test_loading_a_page_of_objects_counts_as_one_read(
    client: TestClient, fx: Fixture, with_objects: str
) -> None:
    """**p.32's counting rule, and the one an implementation gets wrong in the
    expensive direction**: "Many objects loaded or aggregated at once will only
    be recorded as a single read."

    Two objects come back and the count goes up by one. A recorder passing
    `len(rows)` would make every number here roughly a page-size too big, and
    nothing else in the product would look wrong.
    """
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances?application=explorer",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2, "the fixture must load more than one row"
    assert summary(client, fx, with_objects)["reads"] == 1


def test_reads_accumulate_across_requests(
    client: TestClient, fx: Fixture, with_objects: str
) -> None:
    """Two requests are two reads — the counter adds rather than replaces, and
    a day's second request must not overwrite the first."""
    for _ in range(3):
        client.get(
            f"{wbase(fx)}/object-types/{with_objects}/instances?application=explorer",
            headers=hdr(fx.viewer_sub),
        )
    assert summary(client, fx, with_objects)["reads"] == 3


def test_the_ontology_manager_s_own_reads_are_not_counted(
    client: TestClient, fx: Fixture, with_objects: str
) -> None:
    """**p.32's exclusion, through the endpoint that has to honour it.**

    The Ontology Manager lists a type's objects through the same route the
    Explorer uses, so this is the only place the exclusion can be checked:
    the read happens, the objects come back, and the number does not move.
    Somebody deciding whether to rename a property must not be counted as the
    type's user for having looked.
    """
    before = summary(client, fx, with_objects)["reads"]
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances"
        f"?application={usage.ONTOLOGY_MANAGER}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2, "the read really happened"
    assert summary(client, fx, with_objects)["reads"] == before


def test_a_caller_that_names_no_application_is_counted_as_the_api(
    client: TestClient, fx: Fixture, with_objects: str
) -> None:
    """A caller that says nothing is an API caller, which is what it is — and
    counting it is the point: p.32 lists "API call" among the things a write is
    recorded for."""
    client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances",
        headers=hdr(fx.viewer_sub),
    )
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/usage/by-application",
        headers=hdr(fx.viewer_sub),
    )
    assert [x["application"] for x in r.json()] == ["api"]


def test_reading_one_object_is_a_read(
    client: TestClient, fx: Fixture, with_objects: str
) -> None:
    """p.32 counts load *requests*, and one object is one request."""
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances?application=explorer",
        headers=hdr(fx.viewer_sub),
    )
    one = r.json()["items"][0]["id"]
    before = summary(client, fx, with_objects)["reads"]
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances/{one}"
        "?application=object_view",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert summary(client, fx, with_objects)["reads"] == before + 1


def test_a_failing_counter_does_not_fail_the_read(
    client: TestClient, fx: Fixture, with_objects: str, monkeypatch
) -> None:
    """**The one place this codebase swallows an exception on purpose.**

    A read that returned five hundred objects and then raised because a counter
    row could not be written would have turned a working feature into an outage
    for a number nobody is waiting on. Asserted rather than trusted, because a
    `try/except Exception: pass` that is never exercised is indistinguishable
    from one that catches the wrong thing.
    """
    from src.services import object_type_usage as service

    async def explode(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("the counter is down")

    monkeypatch.setattr(service, "record", explode)
    r = client.get(
        f"{wbase(fx)}/object-types/{with_objects}/instances?application=explorer",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert len(r.json()["items"]) == 2
