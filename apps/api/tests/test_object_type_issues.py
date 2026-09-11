"""p.29's issue column (§313; `ontology-manager` p.29; `ontology.md` §1, §6).

    "Object types whose backing datasources are unregistered or have failed to
     reindex into Object Storage v1 (Phonograph) will have red error messages
     in the issue column of the object type page." (p.29)

**Two rows, one mechanism.** `ontology.md` carried this twice — as "indexing /
reindexing state and errors surfaced per object type" and as p.29's red error
messages — and they are the same thing seen from the Ontology Manager and from
the type. Neither needed new storage: `object_type_sources` has carried
`sync_status`, `last_synced_at` and `last_error` since db 0003, and nothing has
ever shown them.

**Two numbers rather than one flag**, and that is the decision worth testing. A
type with no source was never pointed at data; a type whose source failed was,
and then broke. p.29 names both — "unregistered *or* have failed to reindex" —
and a single "has a problem" boolean would send both people to the same screen
to work out which they had.
"""
from __future__ import annotations

import io
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


def pbase(fx: Fixture) -> str:
    return f"{wbase(fx)}/projects/{fx.project}"


@pytest.fixture()
def a_type(client: TestClient, fx: Fixture) -> str:
    tag = uuid.uuid4().hex[:8]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"site_{tag}", "display_name": f"Site {tag}",
            "properties": [
                {"api_name": "code", "display_name": "Code", "data_type": "string",
                 "required": True},
            ],
            "title_property": "code",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture()
def a_dataset(client: TestClient, fx: Fixture) -> str:
    csv = b"code,name\nA1,Alpha\n"
    # `name` is a form field, not the filename: the route takes both and only
    # the field names the dataset.
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Sites {uuid.uuid4().hex[:8]}"},
        files={"file": ("sites.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def a_source(client, fx, type_id: str, dataset_id: str) -> str:
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": "code", "column_mappings": {"code": "code"}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def summary(client, fx, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return next(t for t in r.json()["items"] if t["id"] == type_id)


def break_the_source(fx, source_id: str, message: str) -> None:
    """Mark a source as having failed, the way a sync would.

    **Written through the service rather than through a route**, because there
    is no route that makes a sync fail on demand — the same thing §300 did to
    get a check into the `error` state. The alternative is a test that can only
    assert the happy path, which is the path p.29 is not about.
    """
    import asyncio
    from uuid import UUID

    from src.lib.db import user_connection
    from src.services import ontology as ontology_service

    async def go() -> None:
        async with user_connection(UUID(str(fx.editor))) as conn:
            await ontology_service.mark_source_synced(
                conn, UUID(source_id), ok=False, error=message
            )
            await conn.commit()

    asyncio.run(go())


# --- p.29's two conditions --------------------------------------------------


def test_a_type_with_no_source_is_not_reported_as_failing(
    client: TestClient, fx: Fixture, a_type: str
) -> None:
    """**The distinction the whole row turns on.**

    p.29 names two conditions, and a type nobody has pointed at data is the
    first — not the second. Reporting it as a failure would tell somebody
    something broke when nothing has been tried.
    """
    row = summary(client, fx, a_type)
    assert row["source_count"] == 0
    assert row["failing_source_count"] == 0
    assert row["source_error"] is None


def test_a_healthy_source_is_not_an_issue(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """A source that has never been synced is not a source that failed.

    `never_synced` is db 0003's default and the ordinary state of a source
    somebody just made; counting it would make the column red on every type the
    moment it was wired up.
    """
    a_source(client, fx, a_type, a_dataset)
    row = summary(client, fx, a_type)
    assert row["source_count"] == 1
    assert row["failing_source_count"] == 0
    assert row["source_error"] is None


def test_a_failed_source_is_counted_and_says_why(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """p.29's red error message, and it carries the failure's **own words**.

    "This type has an issue" is a fact nobody can act on; the message the sync
    produced is the one thing that says what to fix.
    """
    source = a_source(client, fx, a_type, a_dataset)
    break_the_source(fx, source, "column 'code' is not in the dataset any more")

    row = summary(client, fx, a_type)
    assert row["failing_source_count"] == 1
    assert row["source_error"] == "column 'code' is not in the dataset any more"


def test_a_type_with_one_failing_source_of_two_is_still_reported(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """**Counted, not joined**, which is why this is a subquery.

    A type may have several sources, and a join would multiply the row — so a
    type with two sources would appear twice in a list that is supposed to have
    one row per type.
    """
    first = a_source(client, fx, a_type, a_dataset)
    second_dataset_csv = b"code,name\nB2,Beta\n"
    made = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"More {uuid.uuid4().hex[:8]}"},
        files={"file": ("more.csv", io.BytesIO(second_dataset_csv), "text/csv")},
    )
    assert made.status_code == 201, made.text
    a_source(client, fx, a_type, made.json()["id"])
    break_the_source(fx, first, "one of two is broken")

    listed = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub)).json()
    rows = [t for t in listed["items"] if t["id"] == a_type]
    assert len(rows) == 1, "a type with two sources appears once"
    assert rows[0]["source_count"] == 2
    assert rows[0]["failing_source_count"] == 1
    assert rows[0]["source_error"] == "one of two is broken"


def test_a_source_that_recovers_stops_being_an_issue(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """The column reports the *current* state, not a history.

    A red mark that never clears is one people learn to ignore, which is worse
    than not having it — the same argument §300 made about a branch's checks.
    """
    source = a_source(client, fx, a_type, a_dataset)
    break_the_source(fx, source, "temporarily broken")
    assert summary(client, fx, a_type)["failing_source_count"] == 1

    import asyncio
    from uuid import UUID

    from src.lib.db import user_connection
    from src.services import ontology as ontology_service

    async def fixed() -> None:
        async with user_connection(UUID(str(fx.editor))) as conn:
            await ontology_service.mark_source_synced(
                conn, UUID(source), ok=True, error=None
            )
            await conn.commit()

    asyncio.run(fixed())

    row = summary(client, fx, a_type)
    assert row["failing_source_count"] == 0
    assert row["source_error"] is None


def test_another_types_failure_is_not_reported_on_this_one(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """The subquery is correlated, and this is what says so.

    A count written without the `object_type_id` clause would report every
    failure in the workspace against every type — and it would look right on a
    workspace with one broken source, which is exactly the state a first test
    leaves behind.
    """
    other = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"other_{uuid.uuid4().hex[:8]}",
              "display_name": f"Other {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "code", "display_name": "Code",
                              "data_type": "string", "required": True}],
              "title_property": "code"},
    ).json()["id"]
    source = a_source(client, fx, other, a_dataset)
    break_the_source(fx, source, "the other type is broken")

    assert summary(client, fx, other)["failing_source_count"] == 1
    mine = summary(client, fx, a_type)
    assert mine["failing_source_count"] == 0
    assert mine["source_error"] is None


def test_a_stale_error_on_a_healthy_source_is_not_reported(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """**The clause that says "from a source that is *currently* failing".**

    Nothing ties `sync_status` to `last_error` — there is no constraint, and
    `mark_source_synced` clearing the message on recovery is a convention of
    one function rather than a property of the column. So a source that is
    `ok` while still carrying the words of an old failure is a state the
    database allows, and a `source_error` picked without checking the status
    would report it: a healthy type quietly carrying a dead complaint in a
    public field.

    §313's mutation run is what found this. Removing the status clause broke
    no test, because every route that heals a source happens to clear the
    message too — so the guard was correct and unchecked, which is the state
    just before it gets deleted by somebody tidying.

    Written through the database, because no route produces the combination.
    """
    import psycopg

    source = a_source(client, fx, a_type, a_dataset)
    break_the_source(fx, source, "an old complaint")
    assert summary(client, fx, a_type)["source_error"] == "an old complaint"

    # Healthy again, but the message left behind.
    with psycopg.connect(
        os.environ.get(
            "TEST_ADMIN_DSN",
            "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
        ),
        autocommit=True,
    ) as c:
        c.execute(
            "UPDATE object_type_sources SET sync_status = 'ok' WHERE id = %s",
            (source,),
        )

    row = summary(client, fx, a_type)
    assert row["failing_source_count"] == 0
    assert row["source_error"] is None, "a healthy source's old words are not an issue"


# --- p.29's third home-page filter (§315) ------------------------------------
#
#     "These pages allow for filtering object types and link types based on
#      their visibility, development status, and indexing issues." (p.29)
#
# The row in `ontology.md` said this wanted "indexing state the sync path does
# not record". §313 showed that was wrong — `object_type_sources` has recorded
# it since db 0003 — so the blocker was never real and the filter is a WHERE
# clause over the same two conditions the column reports.


def listed(client, fx, **params) -> list[dict]:
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub),
                   params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_filtering_by_failing_finds_only_broken_types(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """p.29's filter, over the same condition §313's column reports.

    Asserted as *both* directions — the broken one is in and a healthy one is
    out — because a filter that returned everything would satisfy the first
    assertion on its own.
    """
    healthy = a_type
    a_source(client, fx, healthy, a_dataset)

    broken = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"broken_{uuid.uuid4().hex[:8]}",
              "display_name": f"Broken {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "code", "display_name": "Code",
                              "data_type": "string", "required": True}],
              "title_property": "code"},
    ).json()["id"]
    break_the_source(fx, a_source(client, fx, broken, a_dataset), "it broke")

    ids = {t["id"] for t in listed(client, fx, issue="failing")}
    assert broken in ids
    assert healthy not in ids


def test_filtering_by_unsourced_finds_types_nobody_pointed_at_data(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """p.29's other condition, and it is **not** the same set.

    A type with a broken source is not unsourced, which is the whole reason
    these are two values rather than one.
    """
    bare = a_type

    broken = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"withsrc_{uuid.uuid4().hex[:8]}",
              "display_name": f"With source {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "code", "display_name": "Code",
                              "data_type": "string", "required": True}],
              "title_property": "code"},
    ).json()["id"]
    break_the_source(fx, a_source(client, fx, broken, a_dataset), "it broke")

    ids = {t["id"] for t in listed(client, fx, issue="unsourced")}
    assert bare in ids
    assert broken not in ids, "a type with a broken source has a source"


def test_any_finds_both_kinds(client: TestClient, fx: Fixture, a_type: str,
                              a_dataset: str) -> None:
    """"Show me everything that needs attention" is the question somebody
    opening this filter is actually asking."""
    bare = a_type
    broken = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"anyk_{uuid.uuid4().hex[:8]}",
              "display_name": f"Any kind {uuid.uuid4().hex[:6]}",
              "properties": [{"api_name": "code", "display_name": "Code",
                              "data_type": "string", "required": True}],
              "title_property": "code"},
    ).json()["id"]
    break_the_source(fx, a_source(client, fx, broken, a_dataset), "it broke")

    ids = {t["id"] for t in listed(client, fx, issue="any")}
    assert bare in ids and broken in ids


def test_a_healthy_type_is_in_none_of_the_three(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """The assertion that keeps the other three meaning something."""
    a_source(client, fx, a_type, a_dataset)
    for value in ("failing", "unsourced", "any"):
        ids = {t["id"] for t in listed(client, fx, issue=value)}
        assert a_type not in ids, f"a working type matched {value!r}"


def test_an_unknown_issue_is_refused_rather_than_ignored(
    client: TestClient, fx: Fixture
) -> None:
    """The same choice the two filters beside it make: a typo in a URL that
    quietly shows everything is worse than no filter, because the reader
    believes the list."""
    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub),
                   params={"issue": "broken"})
    assert r.status_code == 422, r.text
    assert "failing" in r.text and "unsourced" in r.text


def test_the_filter_combines_with_the_others_rather_than_replacing_them(
    client: TestClient, fx: Fixture, a_type: str, a_dataset: str
) -> None:
    """And-ed, which is the shape the group and status controls already have.

    A filter that replaced the others would make two controls that cannot be
    used together, and nothing on the screen would say so.
    """
    break_the_source(fx, a_source(client, fx, a_type, a_dataset), "broken")
    assert a_type in {t["id"] for t in listed(client, fx, issue="failing")}
    # The same type, filtered to a status it does not have.
    assert a_type not in {
        t["id"] for t in listed(client, fx, issue="failing", status="deprecated")
    }


# --- The browser's copy of the vocabulary (§315) ------------------------------


#: Four levels: tests -> api -> apps -> the repository root.
ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
ISSUES_TS = os.path.join(
    ROOT, "apps", "web", "src", "lib", "object-type-issues.ts"
)


def offered_values() -> list[str]:
    """The `value:` of every option in `ISSUE_FILTER_OPTIONS`.

    Read out of the source rather than executed, for the reason
    `test_response_type_drift` reads `index.ts`: the two languages have no
    runtime in common, and a check that needed one would not be a check that
    runs here.
    """
    import re

    text = open(ISSUES_TS, encoding="utf-8").read()
    start = text.index("ISSUE_FILTER_OPTIONS")
    body = text[start : text.index("];", start)]
    return re.findall(r"value:\s*\"([^\"]*)\"", body)


def test_the_chooser_offers_exactly_what_the_server_accepts() -> None:
    """**The drift `test_response_type_drift` was written about, one list over.**

    `TYPE_ISSUES` and the browser's option list are two copies of one
    vocabulary, and neither language can see the other. A value the chooser
    gained and the server did not is a control that 422s on click; one the
    server gained and the chooser did not is a filter nobody can reach — and
    `tsc` and pytest are each internally happy in both cases.
    """
    from src.services.ontology import TYPE_ISSUES

    offered = offered_values()
    assert "" in offered, (
        "the chooser has no unfiltered option, so a reader who narrows the "
        "list cannot widen it again"
    )
    assert sorted(v for v in offered if v) == sorted(TYPE_ISSUES)


def test_every_offered_value_is_one_the_endpoint_takes(
    client: TestClient, fx: Fixture
) -> None:
    """The test above compares two lists; this one asks the endpoint.

    A vocabulary can agree with itself and still be refused — the route reads
    the query parameter, and nothing above proves the route passes it through
    rather than dropping it on the floor.
    """
    for value in offered_values():
        r = client.get(
            f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub),
            params={"issue": value} if value else {},
        )
        assert r.status_code == 200, f"{value!r}: {r.text}"
