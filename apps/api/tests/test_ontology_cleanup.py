"""The Ontology cleanup queue (§325; db 0080; `ontology-manager` p.68-74).

    "The Ontology cleanup tool is a safe way to delete object types… The tool
     aims to help Ontology editors determine the safety of deleting an object
     type and provides a deprecation option which informs object type users of
     its future removal." (p.68)

    "By default, the table is sorted by the highest priority among the flags
     that an object type triggers." (p.70)

    "**Snooze**: Hide object types from your cleanup queue for a configurable
     amount of time. Snoozing is an action that will affect only the user that
     performs it." (p.71)

**Every flag gets a type of its own**, and that is the lesson §320 and §323
both taught the hard way: a fixture that trips two flags at once cannot tell a
query that computes them separately from one that conflates them, and a suite
sharing one type between tests cannot tell "this flag fired" from "some flag
fired". Each test below builds the exact type it is about.
"""
from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import date, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import ontology_cleanup as cleanup  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402

ADMIN_DSN = os.environ.get(
    "TEST_ADMIN_DSN",
    "postgresql://platform:devpass@localhost:5432/platform?sslmode=disable",
)

ROWS = b"row_id,name\nr1,First\nr2,Second\n"


# ---- p.70's ordering, decided without a database ------------------------------
def test_the_worst_flag_decides_where_a_type_sits() -> None:
    """p.70: "sorted by the highest priority among the flags that an object
    type triggers"."""
    assert cleanup.priority_of(["no_description", "past_deprecation"]) < \
        cleanup.priority_of(["no_description"])


def test_a_type_with_no_flags_sorts_last() -> None:
    """It is in the answer at all only because a caller asked for everything,
    and putting it above a type with a real flag would be the queue arguing
    with itself."""
    assert cleanup.priority_of([]) == len(cleanup.FLAG_PRIORITY)
    assert cleanup.priority_of([]) > cleanup.priority_of(["no_description"])


def test_the_order_is_about_deleting_rather_than_about_alarm() -> None:
    """**The priority order is a judgement, so it is written down as one.**

    `past_deprecation` first: somebody already decided this type should go and
    announced a date that has passed, so the queue is surfacing a decision
    rather than making one. `unused` second: thirty days of nobody touching it
    is the strongest evidence that deleting it would be noticed by nobody,
    which is the question p.68 says the tool exists to answer.
    `no_description` last: that is a fact about the documentation, not about
    whether anybody would miss the type.
    """
    order = list(cleanup.FLAG_PRIORITY)
    assert order[0] == "past_deprecation"
    assert order[1] == "unused"
    assert order[-1] == "no_description"


def test_p74_s_two_default_markers_are_the_page_s_own() -> None:
    """p.74: "The default value of `\\[test|deprecated\\]` would match object
    types that have `[test]` or `[deprecated]` in their display names."
    """
    assert cleanup.TEMPORARY_MARKERS == ("[test]", "[deprecated]")


# ---- the queue over types that really exist -----------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("cleanup-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def a_type(client: TestClient, fx: Fixture, *, description: str = "A type",
           display_name: str | None = None) -> str:
    """One object type, built exactly as the test about it needs.

    **Its own, every time.** A type shared between these tests would trip
    several flags at once, and a queue that reports "some flag fired" cannot be
    told apart from one that reports the right flag.
    """
    tag = uuid.uuid4().hex[:8]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"clean_{tag}",
              "display_name": display_name or f"Clean {tag}",
              "description": description,
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def give_it_a_source(client: TestClient, fx: Fixture, type_id: str) -> str:
    up = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"CleanRows {uuid.uuid4().hex[:6]}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert up.status_code == 201, up.text
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": up.json()["id"],
              "primary_key_column": "row_id",
              "column_mappings": {"name": "name"}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def queue(client: TestClient, fx: Fixture, *, flag: str | None = None,
          include_snoozed: bool = False, sub: str | None = None):
    params = []
    if flag:
        params.append(f"flag={flag}")
    if include_snoozed:
        params.append("include_snoozed=true")
    q = ("?" + "&".join(params)) if params else ""
    r = client.get(f"{wbase(fx)}/ontology-cleanup{q}",
                   headers=hdr(sub or fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def entry(rows: list[dict], type_id: str) -> dict | None:
    return next((c for c in rows if c["id"] == type_id), None)


def sql(statement: str, params: tuple) -> None:
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(statement, params)


def test_a_type_nobody_has_used_is_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """**The flag p.74 does not list**, and p.73 licenses: "The following list
    of flags is aimed at answering common issues, but is not exhaustive."

    db 0077 counts interactions per type over thirty days, so *nobody has used
    this* is available here — and it is a stronger safety signal than anything
    on p.74's list, because it answers p.68's actual question: would deleting
    this be noticed.
    """
    type_id = a_type(client, fx)
    found = entry(queue(client, fx), type_id)
    assert found is not None, "a type nobody has touched is a cleanup candidate"
    assert "unused" in found["flags"]
    assert found["interactions"] == 0


def test_a_type_somebody_used_is_not_flagged_as_unused(
    client: TestClient, fx: Fixture
) -> None:
    """**The other direction, and the one that makes the flag mean something.**

    Without it, "unused types are flagged" is satisfied by a queue that flags
    every type — which would put the whole ontology in a list whose buttons
    delete things.
    """
    type_id = a_type(client, fx)
    # One read through the ordinary route, which is what db 0077 counts.
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/instances?application=explorer",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text

    found = entry(queue(client, fx), type_id)
    assert found is not None  # it still has no description or source
    assert "unused" not in found["flags"], found
    assert found["interactions"] >= 1


def test_a_deprecation_deadline_in_the_past_is_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """p.74: "Object type currently has the `deprecated` status and the
    deprecation date field is in the past.\""""
    type_id = a_type(client, fx)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    # p.258's bulk-status route, which is what p.71's Deprecate button drives.
    # The `PATCH` on an object type is a whole-definition write (see
    # `ObjectTypeUpdate`) and sending one here would mean this test restating
    # the type's properties to change its status.
    r = client.post(
        f"{wbase(fx)}/object-types/bulk-status", headers=hdr(fx.editor_sub),
        json={"object_type_ids": [type_id], "status": "deprecated",
              "deprecation": {"reason": "Replaced", "deadline": yesterday}},
    )
    assert r.status_code == 200, r.text

    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "past_deprecation" in found["flags"], found["flags"]
    # p.70's ordering: this is the worst thing that can be said about a type,
    # so it decides where the row sits whatever else is lit.
    assert found["priority"] == 0


def test_a_deadline_still_ahead_is_not_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """A plan is not a lapse. A type deprecated with three months' notice is
    doing exactly what p.71's Deprecate button is for, and a queue that flagged
    it immediately would be a queue arguing with its own button."""
    type_id = a_type(client, fx)
    later = (date.today() + timedelta(days=90)).isoformat()
    r = client.post(
        f"{wbase(fx)}/object-types/bulk-status", headers=hdr(fx.editor_sub),
        json={"object_type_ids": [type_id], "status": "deprecated",
              "deprecation": {"reason": "Going", "deadline": later}},
    )
    assert r.status_code == 200, r.text
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "past_deprecation" not in found["flags"], found["flags"]


def test_a_deadline_on_a_type_nobody_deprecated_is_not_a_lapse(
    client: TestClient, fx: Fixture
) -> None:
    """**Both halves of p.74's sentence.** "currently has the deprecated status
    **and** the deprecation date field is in the past" — a date on an active
    type is somebody's note about a plan, and reading it as an overdue
    deprecation would flag a type nobody has deprecated at all."""
    type_id = a_type(client, fx)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    sql("UPDATE object_types SET deprecation = %s::jsonb WHERE id = %s",
        ('{"reason": "maybe", "deadline": "' + yesterday + '"}', type_id))

    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert found["status"] == "experimental"
    assert "past_deprecation" not in found["flags"], found["flags"]


def test_a_type_with_no_mapping_is_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """p.74's "Trashed datasource", as near as this platform gets — there is no
    trash here, so a source is mapped or it is not (§315's `unsourced`)."""
    # **The type first, then the queue.** Written as
    # `entry(queue(...), a_type(...))` this read the queue *before* creating
    # the type — Python evaluates arguments left to right — so the assertion
    # was about a list that could not contain it. Four tests here failed that
    # way on the first run.
    type_id = a_type(client, fx)
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "no_source" in found["flags"]


def test_a_mapped_type_is_not_flagged_as_sourceless(
    client: TestClient, fx: Fixture
) -> None:
    type_id = a_type(client, fx)
    give_it_a_source(client, fx, type_id)
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "no_source" not in found["flags"], found["flags"]


def test_a_failing_source_is_flagged(client: TestClient, fx: Fixture) -> None:
    """§315's other issue. p.74's "Phonograph deindexed" is the equivalent
    question for Object Storage v1 and p.74 says there is no v2 equivalent, so
    this goes in under its own name rather than Foundry's."""
    type_id = a_type(client, fx)
    source_id = give_it_a_source(client, fx, type_id)
    sql("UPDATE object_type_sources SET sync_status = 'error', last_error = %s "
        "WHERE id = %s", ("the dataset went away", source_id))

    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "failing_source" in found["flags"], found["flags"]
    assert "no_source" not in found["flags"], (
        "a source that is failing is a source; the two flags are different "
        "problems with different remedies (§315)"
    )


def test_a_source_nobody_has_synced_lately_is_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """p.74's "Datasource not updated in [x] days"."""
    type_id = a_type(client, fx)
    source_id = give_it_a_source(client, fx, type_id)
    long_ago = f"{cleanup.STALE_SOURCE_DAYS + 5} days"
    sql("UPDATE object_type_sources SET sync_status = 'ok', "
        "last_synced_at = now() - %s::interval WHERE id = %s",
        (long_ago, source_id))

    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "stale_source" in found["flags"], found["flags"]


def test_one_fresh_mapping_keeps_a_type_off_the_stale_list(
    client: TestClient, fx: Fixture
) -> None:
    """**Every source, not any source.** A type mapped from two datasets where
    one syncs nightly and the other was a one-off import is being kept up to
    date; flagging it would put a healthy type in a list of deletion
    candidates."""
    type_id = a_type(client, fx)
    old = give_it_a_source(client, fx, type_id)
    fresh = give_it_a_source(client, fx, type_id)
    sql("UPDATE object_type_sources SET sync_status = 'ok', "
        "last_synced_at = now() - %s::interval WHERE id = %s",
        (f"{cleanup.STALE_SOURCE_DAYS + 5} days", old))
    sql("UPDATE object_type_sources SET sync_status = 'ok', "
        "last_synced_at = now() WHERE id = %s", (fresh,))

    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "stale_source" not in found["flags"], found["flags"]


def test_a_blank_description_is_flagged(client: TestClient, fx: Fixture) -> None:
    """p.74: "The object type has a blank description. Does not check for
    descriptions on all properties of the object type.\""""
    type_id = a_type(client, fx, description="")
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "no_description" in found["flags"]


def test_whitespace_is_not_a_description(client: TestClient, fx: Fixture) -> None:
    """A space is what somebody types to get past a required field."""
    type_id = a_type(client, fx, description="   ")
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "no_description" in found["flags"], found["flags"]


def test_a_described_type_is_not_flagged(client: TestClient, fx: Fixture) -> None:
    type_id = a_type(client, fx, description="Real one")
    found = entry(queue(client, fx), type_id)
    assert found is not None
    assert "no_description" not in found["flags"], found["flags"]


def test_a_name_marked_as_temporary_is_flagged(
    client: TestClient, fx: Fixture
) -> None:
    """p.74's regex flag, at its own default: "would match object types that
    have `[test]` or `[deprecated]` in their display names\"."""
    for marked in ("[test] Vessels", "Vessels [DEPRECATED]"):
        type_id = a_type(client, fx, display_name=marked)
        found = entry(queue(client, fx), type_id)
        assert found is not None, marked
        assert "name_looks_temporary" in found["flags"], (marked, found["flags"])


def test_an_ordinary_name_is_not_flagged(client: TestClient, fx: Fixture) -> None:
    """The direction that stops the marker meaning nothing — and `testing` is
    the word that catches a substring match written without thinking."""
    for ordinary in ("Vessels", "Testing centre", "Deprecated goods"):
        type_id = a_type(client, fx, display_name=ordinary)
        found = entry(queue(client, fx), type_id)
        assert found is not None, ordinary
        assert "name_looks_temporary" not in found["flags"], (
            ordinary, found["flags"]
        )


def test_the_queue_is_worst_first(client: TestClient, fx: Fixture) -> None:
    """p.70's ordering, over the whole answer rather than one row."""
    rows = queue(client, fx)
    assert rows, "this suite has made plenty of candidates"
    assert [c["priority"] for c in rows] == sorted(c["priority"] for c in rows)


def test_the_queue_can_be_narrowed_to_one_flag(
    client: TestClient, fx: Fixture
) -> None:
    """p.69: "The list can be filtered to specific flags"."""
    marked = a_type(client, fx, display_name="[test] Narrowed")
    plain = a_type(client, fx, display_name="Narrowed plainly")

    rows = queue(client, fx, flag="name_looks_temporary")
    assert entry(rows, marked) is not None
    assert entry(rows, plain) is None, (
        "a type without the flag is not in a list filtered to it"
    )
    assert all("name_looks_temporary" in c["flags"] for c in rows)


def test_a_flag_nothing_recognises_returns_nothing(
    client: TestClient, fx: Fixture
) -> None:
    """**Nothing rather than everything**, which is the safe direction for a
    screen whose buttons delete things: a typo in a filter must not quietly
    widen the list it was meant to narrow."""
    assert queue(client, fx, flag="no_such_flag") == []


# ---- p.71's snooze ------------------------------------------------------------
def test_snoozing_takes_a_type_out_of_your_queue(
    client: TestClient, fx: Fixture
) -> None:
    """p.71: "Hide object types from your cleanup queue for a configurable
    amount of time.\""""
    type_id = a_type(client, fx)
    assert entry(queue(client, fx), type_id) is not None

    r = client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                   headers=hdr(fx.editor_sub), json={"days": 7})
    assert r.status_code == 200, r.text
    assert entry(queue(client, fx), type_id) is None, (
        "p.71: once you act on an object type in your queue, it disappears"
    )


def test_a_snoozed_type_can_still_be_looked_up(
    client: TestClient, fx: Fixture
) -> None:
    """p.71: "Use the table filters to view all the actions you have already
    selected." Hidden from the queue is not gone."""
    type_id = a_type(client, fx)
    client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
               headers=hdr(fx.editor_sub), json={"days": 7})

    found = entry(queue(client, fx, include_snoozed=True), type_id)
    assert found is not None
    assert found["snoozed_until"] is not None
    # And the flags are still there: a snooze hides a row, it does not change
    # what is true about the type.
    assert found["flags"]


def test_a_snooze_that_has_run_out_brings_the_type_back(
    client: TestClient, fx: Fixture
) -> None:
    """**An expiry rather than a flag**, which is what "for a configurable
    amount of time" means. A queue you can permanently silence one row at a
    time is a queue that quietly stops being a queue."""
    type_id = a_type(client, fx)
    client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
               headers=hdr(fx.editor_sub), json={"days": 7})
    assert entry(queue(client, fx), type_id) is None

    sql("UPDATE object_type_snoozes SET until = now() - interval '1 minute' "
        "WHERE object_type_id = %s", (type_id,))
    assert entry(queue(client, fx), type_id) is not None, (
        "past its expiry the row is ignored, not honoured forever"
    )


def test_snoozing_again_asks_for_longer(client: TestClient, fx: Fixture) -> None:
    """The second press of "remind me later" moves the date rather than
    refusing — which is why the route is a `PUT`."""
    type_id = a_type(client, fx)
    first = client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                       headers=hdr(fx.editor_sub), json={"days": 1})
    assert first.status_code == 200, first.text
    second = client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                        headers=hdr(fx.editor_sub), json={"days": 30})
    assert second.status_code == 200, second.text
    assert second.json()["until"] > first.json()["until"]


def test_a_snooze_is_yours_alone(client: TestClient, fx: Fixture) -> None:
    """**p.71's rule, and the one only two people can check**: "Snoozing is an
    action that will affect only the user that performs it."

    A test with one person cannot tell a per-user snooze from a global one —
    both hide the row from the only reader — so this snoozes as the editor and
    reads the queue as the admin, who should still see it.
    """
    type_id = a_type(client, fx)
    client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
               headers=hdr(fx.editor_sub), json={"days": 7})

    assert entry(queue(client, fx), type_id) is None
    assert entry(queue(client, fx, sub=fx.admin_sub), type_id) is not None, (
        "one editor clearing their queue must not hide a type from the "
        "colleague who would have deleted it"
    )


def test_waking_a_type_brings_it_back_now(client: TestClient, fx: Fixture) -> None:
    type_id = a_type(client, fx)
    client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
               headers=hdr(fx.editor_sub), json={"days": 30})
    assert entry(queue(client, fx), type_id) is None

    r = client.delete(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text
    assert entry(queue(client, fx), type_id) is not None


def test_waking_something_that_was_never_asleep_is_not_a_success(
    client: TestClient, fx: Fixture
) -> None:
    """"It is back" and "it was never away" are different answers, and a
    control reporting success for both is one somebody presses twice (§214)."""
    type_id = a_type(client, fx)
    r = client.delete(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                      headers=hdr(fx.editor_sub))
    assert r.status_code == 404, r.text


# ---- who may see and act on the queue -----------------------------------------
def test_a_viewer_cannot_open_the_queue(client: TestClient, fx: Fixture) -> None:
    """**`editor`, and it is the one read here with that floor.** Every other
    listing says what the ontology *is*; this one says which types somebody
    should consider deleting, and p.71's three buttons are all writes. A viewer
    given the list could act on none of it."""
    r = client.get(f"{wbase(fx)}/ontology-cleanup", headers=hdr(fx.viewer_sub))
    assert r.status_code == 403, r.text


def test_a_viewer_cannot_snooze(client: TestClient, fx: Fixture) -> None:
    type_id = a_type(client, fx)
    r = client.put(f"{wbase(fx)}/object-types/{type_id}/cleanup-snooze",
                   headers=hdr(fx.viewer_sub), json={"days": 7})
    assert r.status_code == 403, r.text


def test_an_outsider_sees_nothing(client: TestClient, fx: Fixture) -> None:
    r = client.get(f"{wbase(fx)}/ontology-cleanup", headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text


def test_the_queue_is_a_page_rather_than_the_whole_ontology(
    client: TestClient, fx: Fixture
) -> None:
    """§256's rule, on a list p.69 says has scale behind it: "the tool may take
    time to find cleanup candidates based on the size of your Ontology".

    **And the cap is applied after ranking.** A `LIMIT` in the statement would
    cut the list before anything was ordered, so the two hundred returned would
    be an arbitrary two hundred rather than p.70's *worst* two hundred — which
    is the difference between a page of a queue and a sample of one. Asserted
    by checking the page is still sorted: an unranked slice of a large ontology
    would almost never come back in priority order.
    """
    rows = queue(client, fx)
    assert len(rows) <= cleanup.MAX_CANDIDATES
    assert [c["priority"] for c in rows] == sorted(c["priority"] for c in rows)


def labelled_flags() -> set[str]:
    """The flags the browser has words for, read out of the TypeScript.

    Crude on purpose, like §323's: a real parse needs a toolchain this suite
    does not have, and what is being checked is that two lists in two languages
    say the same thing. The vacuity guard below is what stops a regex that
    stopped matching from turning this into a check over nothing.
    """
    import re

    # Four levels: tests -> api -> apps -> the repository root.
    root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    src = open(
        os.path.join(root, "apps", "web", "src", "lib", "ontology-cleanup.ts"),
        encoding="utf-8",
    ).read()
    body = src.split("FLAG_LABELS", 1)[1].split("};", 1)[0]
    return set(re.findall(r"^\s{2}(\w+):\s*\{", body, re.MULTILINE))


def test_every_flag_has_words_on_the_screen() -> None:
    """**The drift the type system cannot see** (§315's pattern, §323's shape).

    `FLAG_PRIORITY` is a Python tuple and `FLAG_LABELS` a TypeScript object,
    and nothing but this line connects them. A flag added here and not there
    draws as its own column value — `name_looks_temporary` printed at somebody
    in a list whose buttons delete things.
    """
    labelled = labelled_flags()
    assert labelled, "the labels could not be read; this was about to pass over nothing"
    assert labelled == set(cleanup.FLAG_PRIORITY), (
        "the server's flags and the browser's words for them have drifted: "
        f"only in the server {set(cleanup.FLAG_PRIORITY) - labelled}, "
        f"only in the browser {labelled - set(cleanup.FLAG_PRIORITY)}"
    )


def test_the_unused_window_matches_the_usage_the_flag_reads() -> None:
    """`UNUSED_DAYS` is its own constant and db 0077's `WINDOW_DAYS` is another,
    and they have to agree or the flag says "nobody used it in 30 days" over a
    count taken across a different span.

    Two constants rather than one import, because they answer different
    questions and one moving should be a decision rather than a side effect —
    so this is the line that makes it one.
    """
    from src.services import object_type_usage

    assert cleanup.UNUSED_DAYS == object_type_usage.WINDOW_DAYS


def test_a_healthy_type_is_not_in_the_queue_at_all(
    client: TestClient, fx: Fixture
) -> None:
    """**The direction that stops the queue meaning nothing.**

    Every other test here asks whether a flagged type appears. None asked
    whether an unflagged one stays out — so a queue listing the entire ontology
    would have passed all of them, and this is a screen whose buttons delete
    things. The mutation sweep found exactly that.

    A type is healthy when it has a description, a mapping that synced today,
    and somebody reading it.
    """
    type_id = a_type(client, fx, description="A type somebody documented")
    source_id = give_it_a_source(client, fx, type_id)
    sql("UPDATE object_type_sources SET sync_status = 'ok', "
        "last_synced_at = now() WHERE id = %s", (source_id,))
    # One read through the ordinary route, which is what db 0077 counts.
    assert client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances?application=explorer",
        headers=hdr(fx.viewer_sub),
    ).status_code == 200

    assert entry(queue(client, fx), type_id) is None, (
        "a type with a description, a fresh mapping and a reader is not a "
        "cleanup candidate"
    )


def test_two_types_with_the_same_worst_flag_are_ordered_by_name(
    client: TestClient, fx: Fixture
) -> None:
    """The tie-break, which needs two rows of equal priority to exist.

    p.70 orders by the worst flag; two types whose worst flag is the same would
    otherwise arrive in whatever order the scan produced, and a queue whose rows
    swap places between refreshes is one people stop trusting. A mutant dropping
    the secondary sort survived every other test here, because no two of them
    ever tied.
    """
    tag = uuid.uuid4().hex[:6]
    # Same flags, so the same priority: both are unsourced, undescribed and
    # unused. Only the names differ, and deliberately not in creation order.
    later = a_type(client, fx, description="", display_name=f"zz tie {tag}")
    earlier = a_type(client, fx, description="", display_name=f"aa tie {tag}")

    rows = [c for c in queue(client, fx) if c["id"] in (earlier, later)]
    assert [c["id"] for c in rows] == [earlier, later], (
        [c["display_name"] for c in rows]
    )


def test_the_page_keeps_the_worst_rather_than_the_first_found(
    client: TestClient, fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The cap is applied after ranking**, which is the difference between a
    page of a queue and a sample of one.

    Forced to two rather than seeding two hundred types: what is being checked
    is the order of two operations, and building a workspace big enough to trip
    the real cap would make the test about the fixture. A mutant returning the
    list uncut survived because nothing here comes near two hundred.
    """
    monkeypatch.setattr(cleanup, "MAX_CANDIDATES", 2)
    # One type whose worst flag is the worst there is, created last so that an
    # unranked cut would drop it.
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    worst = a_type(client, fx)
    assert client.post(
        f"{wbase(fx)}/object-types/bulk-status", headers=hdr(fx.editor_sub),
        json={"object_type_ids": [worst], "status": "deprecated",
              "deprecation": {"reason": "Gone", "deadline": yesterday}},
    ).status_code == 200

    rows = queue(client, fx)
    assert len(rows) == 2, len(rows)
    assert entry(rows, worst) is not None, (
        "the cap kept the worst two, not the first two the scan happened to see"
    )
    assert rows[0]["priority"] == 0
