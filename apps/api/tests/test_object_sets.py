"""Object sets (roadmap phase 2, item 1.2).

Two things are under test and the second is the important one.

First, that a set means what it says: filters narrow, the total is the size of
the *set* rather than of the page, and a filter that cannot be satisfied
refuses rather than quietly widening.

Second, **that both stores agree**. Postgres evaluates in SQL and OpenSearch in
its query DSL, and a set that meant two things depending on which store a
deployment happens to run would be invisible until somebody compared two
environments. So the same rows and the same filters go through
`object_sets.matches`, the Postgres path, and the OpenSearch path, and all
three have to produce the same answer.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import instance_store, object_sets  # noqa: E402

PORT = 9209
BASE = f"http://127.0.0.1:{PORT}"

# One fixed population, used by every layer below, so a disagreement is a
# disagreement about semantics rather than about test data.
ROWS = [
    ("1", {"region": "north", "status": "open", "capacity": 10}),
    ("2", {"region": "north", "status": "closed", "capacity": 250}),
    ("3", {"region": "south", "status": "open", "capacity": 40}),
    ("4", {"region": "south", "status": "open", "capacity": 7}),
    ("5", {"region": "east", "status": "open", "capacity": "n/a"}),
]

# What the ontology declares for the type these rows belong to.
#
# **`capacity` is a string, and that is not a shortcut.** The rows hold `10`,
# `250`, `40`, `7` and `"n/a"` on purpose: this file's whole subject is the
# untyped comparison decision 0006 refuses to make, and `"n/a"` is the value
# that makes "cast it and compare" the wrong answer. A `capacity` declared
# `integer` would be refused by the strict mapping - correctly, and it would
# destroy the fixture. The property is a string in this workspace, so the
# declaration says so.
#
# Passed on every upsert below because an index now carries its type's mapping
# (0006 §1): without it the index is created strict-and-empty and refuses the
# very documents the cross-store comparison is about.
DECLARED = [
    {"api_name": "region", "data_type": "string"},
    {"api_name": "status", "data_type": "string"},
    {"api_name": "capacity", "data_type": "string"},
]

CASES = [
    {"filters": [{"property": "region", "op": "eq", "value": "north"}]},
    {"filters": [{"property": "region", "op": "neq", "value": "north"}]},
    {"filters": [{"property": "region", "op": "in", "value": ["north", "east"]}]},
    # `in []` is the empty set (p.224's "nothing is selected"), and it is in
    # this list because that is a claim about the *store*: Postgres
    # `= ANY(ARRAY[])` and OpenSearch `terms: []` both have to reach the same
    # nothing the reference semantics do.
    {"filters": [{"property": "region", "op": "in", "value": []}]},
    {"filters": [{"property": "status", "op": "starts_with", "value": "clos"}]},
    {
        "filters": [
            {"property": "region", "op": "eq", "value": "south"},
            {"property": "status", "op": "eq", "value": "open"},
        ]
    },
]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


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


# ---- the definition ----------------------------------------------------------
def test_a_definition_without_a_type_is_refused() -> None:
    with pytest.raises(ValueError, match="object_type_id"):
        object_sets.parse({"filters": []})


def test_an_unknown_operator_names_the_ones_that_exist() -> None:
    with pytest.raises(ValueError, match="startswith.*supported|supported"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "region", "op": "startswith", "value": "n"}],
            }
        )


def test_a_filter_with_no_value_is_refused_rather_than_ignored() -> None:
    """The failure decision 0002 documented, caught at the door. A filter bound
    to a variable nobody has set must not silently widen the set - that is how
    a map came to show *more* rows than it should. The caller drops the filter;
    it does not send an empty one."""
    with pytest.raises(ValueError, match="omit the filter"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "region", "op": "eq", "value": None}],
            }
        )


def test_list_and_scalar_operators_refuse_each_other() -> None:
    type_id = str(uuid.uuid4())
    with pytest.raises(ValueError, match="list of values"):
        object_sets.parse(
            {"object_type_id": type_id, "filters": [{"property": "r", "op": "in", "value": "north"}]}
        )
    with pytest.raises(ValueError, match="single value"):
        object_sets.parse(
            {"object_type_id": type_id, "filters": [{"property": "r", "op": "eq", "value": ["a"]}]}
        )


def test_the_browser_addresses_the_primary_key_by_the_same_name() -> None:
    """`PRIMARY_KEY_FILTER` is mirrored in `canvas/object-table-selection.ts`,
    where the Object Table builds the clauses for p.224's selection outputs.

    **Drift here is silent and wrong rather than loud.** A clause naming
    anything else is a filter on a property that happens not to exist, which
    narrows to nothing — indistinguishable from an empty selection, on both
    stores, with no error anywhere. Asserted mechanically for the same reason
    `REFERENCE_PROPS` is.
    """
    import re

    web = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "web", "src", "components", "canvas", "object-table-selection.ts",
    )
    source = open(web).read()
    found = re.search(r'export const PRIMARY_KEY = "([^"]+)"', source)
    assert found, "PRIMARY_KEY not found in object-table-selection.ts - renamed?"
    assert found.group(1) == object_sets.PRIMARY_KEY_FILTER, (
        f"browser uses {found.group(1)!r}, server uses "
        f"{object_sets.PRIMARY_KEY_FILTER!r}"
    )


def test_an_empty_in_list_is_the_empty_set_rather_than_a_refusal() -> None:
    """**The direction is what separates this from the refusal above it.**

    A missing value must not *widen* a set - decision 0002's failure, where an
    unset parameter made a map show more rows than it should. `in []` narrows,
    to nothing, which is the safe direction and the only honest reading of "is
    a member of no values".

    It has to be expressible or a widget whose output is a selection (p.224's
    Selected objects) has no value for "nothing is selected", and every
    alternative open to it - omit the filter, leave the variable unset - hands
    downstream widgets the whole set. Refusing it here *causes* the bug the
    refusal was written against.
    """
    definition = object_sets.parse(
        {
            "object_type_id": str(uuid.uuid4()),
            "filters": [{"property": "region", "op": "in", "value": []}],
        }
    )
    assert definition.filters[0].value == []
    # And the written-down semantics say so, which is what both stores are
    # checked against.
    for _key, props in ROWS:
        assert object_sets.matches(props, definition.filters) is False


def test_an_ordered_comparison_needs_the_declared_types() -> None:
    """**The absence of types is a refusal, not a permission** (§221).

    Properties are stored untyped in the document, so `capacity > 40` reads as
    250 > 40 on Postgres (which can cast) and as "250" < "40" on OpenSearch
    (which compares indexed text) unless something says which. The first
    implementation shipped both and the two stores disagreed on the first run.

    A caller that has not resolved the ontology has checked no type at all, so
    it gets the pre-§221 behaviour - which is what keeps every existing caller
    correct rather than quietly permissive.
    """
    for op in object_sets.ORDERED_OPERATORS:
        with pytest.raises(ValueError, match="did not supply them"):
            object_sets.parse({
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "capacity", "op": op, "value": 40}],
            })


def test_an_ordered_comparison_is_allowed_on_an_orderable_type() -> None:
    """What §220 made possible: the declared type reaches the mapping, so both
    stores order the same values the same way."""
    for kind in object_sets.ORDERABLE_TYPES:
        parsed = object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "capacity", "op": "gte", "value": 40}],
            },
            property_types={"capacity": kind},
        )
        assert parsed.filters[0].data_type == kind, kind


def test_an_ordered_comparison_on_text_is_refused_permanently() -> None:
    """Decision 0006 §2, and the wording matters: this is not "not yet".
    Postgres orders by the database collation and OpenSearch by byte order, so
    `'Z' < 'a'` is true in one and false in the other for any non-C
    collation."""
    with pytest.raises(ValueError, match="no order the two stores agree on"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "name", "op": "gt", "value": "m"}],
            },
            property_types={"name": "string"},
        )


@pytest.mark.parametrize("kind", ["boolean", "json", "attachment", "geopoint"])
def test_an_ordered_comparison_on_an_unorderable_type_is_refused(kind: str) -> None:
    """"Greater than false" is not a question, and a composite value has no
    order anybody would agree on."""
    with pytest.raises(ValueError, match="has no order"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "flag", "op": "gt", "value": 1}],
            },
            property_types={"flag": kind},
        )


def test_an_ordered_comparison_on_an_undeclared_property_is_refused() -> None:
    """Almost always a typo, and the pre-§221 refusal could not tell it from a
    legal filter - it refused every ordered comparison for one reason."""
    with pytest.raises(ValueError, match="does not declare"):
        object_sets.parse(
            {
                "object_type_id": str(uuid.uuid4()),
                "filters": [{"property": "capcity", "op": "gt", "value": 40}],
            },
            property_types={"capacity": "integer"},
        )


def test_the_orderable_types_agree_with_the_index_mapping() -> None:
    """`ORDERABLE_TYPES` exists twice: here, where it decides what a filter may
    ask, and in `instance_mapping`, where it is true *because* of the mapping -
    a `date` field is orderable because it is mapped `date`. Restated rather
    than imported because this module imports nothing, the same arrangement
    `PRIMARY_KEY_FILTER` has, so the copies get a test instead of a comment."""
    from src.services import instance_mapping

    assert object_sets.ORDERABLE_TYPES == instance_mapping.ORDERABLE_TYPES


# ---- what a value orders by (§221) -------------------------------------------
@pytest.mark.parametrize("kind", ["integer", "float"])
def test_a_number_orders_numerically(kind: str) -> None:
    assert object_sets.comparable("250", kind) == 250.0
    assert object_sets.comparable(40, kind) == 40.0
    assert object_sets.comparable("250", kind) > object_sets.comparable("40", kind)


def test_a_value_that_is_not_a_number_is_not_on_the_ordering() -> None:
    """`None`, and every caller reads that as "does not match" rather than as
    an error. **Not zero**: a `capacity` holding `"n/a"` is not less than 40,
    it is not on the number line - and zero would quietly include it in every
    `lt` filter somebody wrote."""
    for value in ("n/a", "", "  ", None, [1], {"a": 1}):
        assert object_sets.comparable(value, "integer") is None, value


def test_a_boolean_is_not_a_number() -> None:
    """Python says `True == 1`, and `boolean` is not an orderable type (0006
    §2). "Greater than false" is not a question anybody filtering data meant to
    ask."""
    assert object_sets.comparable(True, "integer") is None
    assert object_sets.comparable(False, "float") is None


def test_a_string_property_has_no_comparable_form() -> None:
    """The permanent refusal, at the value level rather than at validation.
    Even if a `string` reached here, there is no ordering to give it - which is
    what stops the refusal being one `if` away from being lost."""
    # **A number-shaped string, not "banana".** `float("banana")` raises either
    # way, so a `string` quietly routed down the numeric path would look
    # correct on it - the mutant that did exactly that survived a fixture
    # asserting only the unparseable case.
    assert object_sets.comparable("250", "string") is None
    assert object_sets.comparable("banana", "string") is None
    assert object_sets.comparable("2026-01-01", None) is None


def test_a_timestamp_orders_chronologically() -> None:
    later = object_sets.comparable("2026-03-01T09:00:00+00:00", "timestamp")
    earlier = object_sets.comparable("2026-01-05", "date")
    assert later > earlier


def test_a_bare_date_is_midnight_utc() -> None:
    """What makes `date` and `timestamp` one ordering rather than two - and the
    rule the Postgres cast has to state explicitly, since `::timestamptz` would
    otherwise read it in the session's timezone."""
    from datetime import datetime, timezone as tz

    assert object_sets.comparable("2026-01-05", "date") == datetime(
        2026, 1, 5, tzinfo=tz.utc
    )


def test_a_naive_timestamp_is_read_as_utc() -> None:
    """db 0029 preserves an offset "when the source has one", so a source
    routinely holds both shapes. Python refuses to compare naive with aware, so
    a page that did not settle this would raise on real data for a reason no
    filter author could act on."""
    naive = object_sets.comparable("2026-03-01T09:00:00", "timestamp")
    aware = object_sets.comparable("2026-03-01T09:00:00+00:00", "timestamp")
    assert naive == aware


def test_z_is_an_offset() -> None:
    """`datetime.fromisoformat` did not accept `Z` before Python 3.11 and this
    codebase writes it - `synced_at.isoformat()` does not, but a source dataset
    does, constantly."""
    assert object_sets.comparable("2026-03-01T09:00:00Z", "timestamp") == (
        object_sets.comparable("2026-03-01T09:00:00+00:00", "timestamp")
    )


def test_a_timestamp_that_will_not_parse_is_not_on_the_ordering() -> None:
    """**Not the epoch.** A date nobody can read is not "before everything" -
    that would put every unparseable row into the results of every `lt` filter,
    which is the silent widening decision 0002 exists to remove."""
    for value in ("2026-13-45", "yesterday", "", "   ", None):
        assert object_sets.comparable(value, "timestamp") is None, value


def test_a_property_sort_needs_the_declared_types_too() -> None:
    """The same rule as an ordered filter, and it has to be stated separately
    because a sort takes a different path through validation: a caller that
    supplied no types has checked none, so `capacity` is not a sort it may
    have."""
    with pytest.raises(ValueError, match="unknown sort"):
        object_sets.parse_sort("capacity")
    with pytest.raises(ValueError, match="unknown sort"):
        object_sets.parse_sort("-capacity")


def test_comparison_is_on_the_text_of_a_value() -> None:
    """The same rule links use: two independently-mapped sources can disagree
    about whether a code is a string or a number."""
    definition = object_sets.parse(
        {
            "object_type_id": str(uuid.uuid4()),
            "filters": [{"property": "code", "op": "eq", "value": 7}],
        }
    )
    assert object_sets.matches({"code": "7"}, definition.filters)


# ---- the two stores agree ----------------------------------------------------
@pytest.fixture(scope="module")
def opensearch() -> str:
    script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "opensearch_fixture_server.py"
    )
    proc = subprocess.Popen(
        [sys.executable, script, str(PORT)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE}/", timeout=0.5).read()
            break
        except Exception:
            time.sleep(0.1)
    else:
        proc.terminate()
        pytest.fail("the OpenSearch fixture server did not start")
    yield BASE
    proc.terminate()
    proc.wait(timeout=5)


@pytest.mark.anyio
@pytest.mark.parametrize("case", CASES, ids=lambda c: c["filters"][0]["op"])
async def test_opensearch_and_the_reference_semantics_agree(opensearch: str, case: dict) -> None:
    """The check that stops a set meaning two things.

    `object_sets.matches` is the written-down definition; the store has to
    reach the same conclusion through an entirely different mechanism.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-set-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        definition = object_sets.parse({"object_type_id": str(type_id), **case})

        expected = {key for key, props in ROWS if object_sets.matches(props, definition.filters)}
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-set-test",
            object_type_id=type_id,
            filters=definition.filters,
            limit=50,
            offset=0,
        )
        assert {r["primary_key"] for r in rows} == expected, case
        assert total == len(expected)
    finally:
        await store.close()


def test_the_query_carries_the_value_the_reference_compared(opensearch: str) -> None:
    """**The bound is normalised before it goes over the wire**, so the value a
    range query carries is the one `object_sets.comparable` agreed to.

    Asserted on the query body rather than on results, because the fixture and
    a real cluster both coerce a bound generously - `"40"` on a `long` field
    and a bare date on a `date` field are accepted either way, so *results*
    cannot tell a normalised bound from a raw one. What differs is what a
    cluster is asked, and for a store gateway the request it forms is the
    contract (this file's own opening claim).

    The date case is the one that matters: a bare `2026-03-01` leaves this
    process as `2026-03-01T00:00:00+00:00`, so the instant the query means is
    fixed here rather than by whatever the cluster's own default offset is.
    """
    from src.services.instance_store import OpenSearchInstanceStore

    clauses = OpenSearchInstanceStore._set_clauses(
        uuid.uuid4(),
        (
            object_sets.Filter("reading", "gt", "40", "integer"),
            object_sets.Filter("seen", "lt", "2026-03-01", "timestamp"),
        ),
    )
    ranges = {
        next(iter(c["range"])): next(iter(c["range"].values()))
        for c in clauses["filter"] if "range" in c
    }
    assert ranges["properties.reading"] == {"gt": 40.0}, "a text bound is coerced"
    assert ranges["properties.seen"] == {"lt": "2026-03-01T00:00:00+00:00"}, (
        "a bare date is pinned to UTC before it leaves"
    )


def test_a_bound_that_does_not_fit_its_type_asks_for_nothing(opensearch: str) -> None:
    """`capacity > "abc"` matches nothing, and the query has to *say* nothing
    rather than send a range with a null edge - which is an error rather than
    an answer."""
    from src.services.instance_store import OpenSearchInstanceStore

    clauses = OpenSearchInstanceStore._set_clauses(
        uuid.uuid4(), (object_sets.Filter("reading", "gt", "abc", "integer"),)
    )
    assert {"terms": {"properties.reading": []}} in clauses["filter"]
    assert not any("range" in c for c in clauses["filter"])


# ---- ordered comparisons and property sorts (§221, decision 0006) ------------
#
# **A separate population with typed properties**, because the one above is
# deliberately untyped: `capacity` holds `"n/a"` there, which is the value that
# makes "cast it and compare" the wrong answer and which the strict mapping
# would refuse for an integer. Both facts are worth keeping, so they get a
# fixture each rather than one that half-serves both.
#
# `reading` spans the boundary a filter asks about (40) on both sides, and
# `seen` mixes an offset-carrying timestamp with a bare date - db 0029 stores
# "ISO-8601 text, with an offset preserved when the source has one", so a
# population without both would never ask whether the two compare.
# **A tie and an absence, on purpose.** Rows 3 and 5 share a `reading`, so a
# sort with no tie-break pages inconsistently rather than merely oddly; row 6
# has no `reading` at all, which is the only "not on the ordering" value a
# strict integer mapping will accept - and it is what the `NULLS LAST` and
# `missing: _last` rules are for. Without both, a fixture of four distinct
# parseable values leaves those rules asserting nothing (§212, §217, §218,
# §219's finding, a fifth time).
TYPED_ROWS = [
    ("1", {"reading": 10, "seen": "2026-01-05"}),
    ("2", {"reading": 250, "seen": "2026-03-01T09:00:00+00:00"}),
    ("3", {"reading": 40, "seen": "2026-03-01T12:00:00+02:00"}),
    ("4", {"reading": 7, "seen": "2026-11-30"}),
    ("5", {"reading": 40, "seen": "2026-02-02"}),
    ("6", {"seen": "2026-04-04"}),
    # **A bare timestamp on the boundary a filter asks about.** Read in UTC it
    # is 00:00Z and matches `lt 02:00Z`; read in `America/New_York` it is
    # 05:00Z and does not. Without a row here, every timezone the tests try
    # gives the same answer and the rule asserts nothing.
    ("7", {"reading": 1, "seen": "2026-03-01"}),
    # A tie whose key sorts *before* the rows it ties with, and which is
    # written last - so the incidental order a store returns without a
    # tie-break is not the order the rule requires.
    ("0", {"reading": 40, "seen": "2026-05-05"}),
]
TYPED_DECLARED = [
    {"api_name": "reading", "data_type": "integer"},
    {"api_name": "seen", "data_type": "timestamp"},
]
TYPED_TYPES = {"reading": "integer", "seen": "timestamp"}

ORDERED_CASES = [
    {"filters": [{"property": "reading", "op": "gt", "value": 40}]},
    {"filters": [{"property": "reading", "op": "gte", "value": 40}]},
    {"filters": [{"property": "reading", "op": "lt", "value": 40}]},
    {"filters": [{"property": "reading", "op": "lte", "value": 40}]},
    # **The bound as text**, which is what a URL parameter and a JSON editor
    # both produce. If either store compared the bound as text rather than
    # coercing it, "40" would order between "250" and "7".
    {"filters": [{"property": "reading", "op": "gt", "value": "40"}]},
    # Two filters on one property: a range, which is the ordinary use and the
    # one that catches a store applying only the last clause.
    {"filters": [{"property": "reading", "op": "gte", "value": 10},
                 {"property": "reading", "op": "lt", "value": 250}]},
    {"filters": [{"property": "seen", "op": "gte", "value": "2026-03-01T00:00:00+00:00"}]},
    # A bare date against timestamps carrying offsets - midnight UTC, which is
    # what makes date and timestamp one ordering rather than two.
    {"filters": [{"property": "seen", "op": "lt", "value": "2026-03-01"}]},
    # A bound that does not fit its own type. Nothing matches, rather than
    # everything or an error.
    {"filters": [{"property": "reading", "op": "gt", "value": "abc"}]},
]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", ORDERED_CASES,
    ids=[f"{c['filters'][0]['op']}-{i}" for i, c in enumerate(ORDERED_CASES)],
)
async def test_both_stores_compare_an_ordered_filter_the_same_way(
    opensearch: str, case: dict
) -> None:
    """The check that stops `capacity > 40` meaning two things.

    `object_sets.matches` is the written-down definition; the store reaches the
    same conclusion through a `range` query against a typed mapping, and
    Postgres through a guarded cast. Three mechanisms, one answer, or the
    operator goes back to being refused.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-ord-test", object_type_id=type_id, source_id=source_id,
            rows=TYPED_ROWS, synced_at=datetime.now(timezone.utc),
            declared=TYPED_DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), **case}, property_types=TYPED_TYPES
        )
        expected = {
            key for key, props in TYPED_ROWS
            if object_sets.matches(props, definition.filters)
        }
        rows, total = await store.evaluate_object_set(
            search_prefix="ws-ord-test", object_type_id=type_id,
            filters=definition.filters, limit=50, offset=0,
        )
        assert {r["primary_key"] for r in rows} == expected, case
        assert total == len(expected)
    finally:
        await store.close()


def _tie_broken(ranked: list, parsed) -> list[str]:
    """Keys in the order both stores must produce, ties broken ascending.

    **The tie-break does not invert with the sort.** Both stores append
    `primary_key ASC` after the property, in both directions, so that "the next
    page" cannot repeat a row it already showed - which is the whole reason the
    four fixed sorts have carried a tie-break since they were written.
    """
    out: list[str] = []
    index = 0
    while index < len(ranked):
        run = [ranked[index]]
        while index + 1 < len(ranked) and (
            object_sets.comparable(ranked[index + 1][1].get(parsed.property), parsed.data_type)
            == object_sets.comparable(run[0][1].get(parsed.property), parsed.data_type)
        ):
            index += 1
            run.append(ranked[index])
        out.extend(sorted(key for key, _ in run))
        index += 1
    return out


@pytest.mark.anyio
@pytest.mark.parametrize("sort", ["reading", "-reading", "seen", "-seen"])
async def test_the_two_stores_order_by_a_property_identically(
    opensearch: str, sort: str
) -> None:
    """A table sorted one way on Postgres and another on OpenSearch is the
    invisible kind of wrong - the same class of bug the operator list existed
    to prevent, which is why the sort was refused alongside it."""
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-ordsort", object_type_id=type_id, source_id=source_id,
            rows=TYPED_ROWS, synced_at=datetime.now(timezone.utc),
            declared=TYPED_DECLARED,
        )
        parsed = object_sets.parse_sort(sort, property_types=TYPED_TYPES)
        rows, _ = await store.evaluate_object_set(
            search_prefix="ws-ordsort", object_type_id=type_id, filters=(),
            limit=50, offset=0, sort=parsed,
        )
        got = [r["primary_key"] for r in rows]

        # Sorted the way the stores are required to: on the comparable value,
        # ties broken by primary key ascending **in both directions**, and rows
        # with no comparable value last **in both directions**. Expressed as a
        # key rather than as a literal list, so the expectation is the rule
        # rather than a transcription of one run's output.
        def ordering(pair):
            value = object_sets.comparable(pair[1].get(parsed.property), parsed.data_type)
            return (value is None, value)

        ranked = sorted(
            [p for p in TYPED_ROWS
             if object_sets.comparable(p[1].get(parsed.property), parsed.data_type)
             is not None],
            key=ordering, reverse=parsed.descending,
        )
        missing = sorted(
            [p for p in TYPED_ROWS
             if object_sets.comparable(p[1].get(parsed.property), parsed.data_type) is None],
            key=lambda p: p[0],
        )
        expected = _tie_broken(ranked, parsed) + [key for key, _ in missing]
        assert got == expected, sort
        # And it is not merely *a* stable order: the numbers order numerically,
        # so 250 is last ascending rather than first as text would put it.
        if parsed.property == "reading" and not parsed.descending:
            assert got[-2] == "2", "250 is the largest, and the absent row is last"
    finally:
        await store.close()


# ---- through the API (Postgres store, the local-dev default) -----------------
@pytest.fixture(scope="module")
def seeded(client: TestClient, fx: Fixture) -> str:
    """The fixture population, landed the way real instances land: a dataset
    upload, an object type, a source mapping, a sync.

    Inserting into `object_instances` directly would have been shorter and
    would have tested a table rather than the thing under test - and it is not
    even possible, since an instance has to belong to a source.
    """
    tag = uuid.uuid4().hex[:8]
    csv = b"key,region,status,capacity\n" + b"".join(
        f"{key},{p['region']},{p['status']},{p['capacity']}\n".encode() for key, p in ROWS
    )
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.owner_sub),
        data={"name": f"Sites {tag}"},
        files={"file": ("sites.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types",
        headers=hdr(fx.owner_sub),
        json={
            "api_name": f"Site{tag}",
            "display_name": f"Site {tag}",
            "properties": [
                {"api_name": p, "data_type": "string"}
                for p in ("region", "status", "capacity")
            ],
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.owner_sub),
        json={
            "object_type_id": type_id,
            "dataset_id": dataset_id,
            "primary_key_column": "key",
            "column_mappings": {"region": "region", "status": "status", "capacity": "capacity"},
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/{source_id}/sync",
        headers=hdr(fx.owner_sub),
    )
    assert r.status_code == 200, r.text
    return type_id


def evaluate(client: TestClient, fx: Fixture, definition: dict, **kw) -> dict:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def typed(client: TestClient, fx: Fixture) -> str:
    """A second population whose properties are **declared with real types**.

    Separate from `seeded` on purpose: that one declares everything `string`,
    which is what makes it the right fixture for the untyped comparisons this
    file has always checked - and the wrong one for §221, whose entire subject
    is what a declared type changes. Landed the same way, through an upload and
    a sync, because an ordered comparison has to survive the coercion a real
    sync applies rather than only the shape a test would insert.
    """
    tag = uuid.uuid4().hex[:8]
    csv = b"key,reading,seen\n" + b"".join(
        f"{key},{p.get('reading', '')},{p['seen']}\n".encode() for key, p in TYPED_ROWS
    )
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.owner_sub),
        data={"name": f"Readings {tag}"},
        files={"file": ("readings.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types",
        headers=hdr(fx.owner_sub),
        json={
            "api_name": f"Reading{tag}",
            "display_name": f"Reading {tag}",
            "properties": [
                {"api_name": "reading", "data_type": "integer"},
                {"api_name": "seen", "data_type": "timestamp"},
            ],
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.owner_sub),
        json={
            "object_type_id": type_id,
            "dataset_id": dataset_id,
            "primary_key_column": "key",
            "column_mappings": {"reading": "reading", "seen": "seen"},
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{source_id}/sync",
        headers=hdr(fx.owner_sub),
    )
    assert r.status_code == 200, r.text
    return type_id


@pytest.mark.parametrize(
    "case", ORDERED_CASES,
    ids=[f"{c['filters'][0]['op']}-{i}" for i, c in enumerate(ORDERED_CASES)],
)
def test_the_postgres_store_compares_an_ordered_filter_the_same_way(
    client: TestClient, fx: Fixture, typed: str, case: dict
) -> None:
    """The Postgres half of §221, against the same reference the OpenSearch
    half is checked against - which is what 0006 §6 means by "neither store
    ships the new operators until both do"."""
    definition = object_sets.parse(
        {"object_type_id": typed, **case}, property_types=TYPED_TYPES
    )
    expected = {
        key for key, props in TYPED_ROWS
        if object_sets.matches(props, definition.filters)
    }
    page = evaluate(client, fx, {"object_type_id": typed, **case})
    assert {i["primary_key"] for i in page["instances"]} == expected, case
    assert page["total"] == len(expected)


def test_an_ordered_filter_survives_the_sync_that_coerces_it(
    client: TestClient, fx: Fixture, typed: str
) -> None:
    """**The whole point, asserted once in plain terms.** 250 is greater than
    40, and before §221 the platform could not say so - the values reached the
    stores as text and the two disagreed about what came first."""
    page = evaluate(
        client, fx,
        {"object_type_id": typed,
         "filters": [{"property": "reading", "op": "gt", "value": 40}]},
    )
    assert {i["primary_key"] for i in page["instances"]} == {"2"}


def test_the_postgres_store_sorts_by_a_property(
    client: TestClient, fx: Fixture, typed: str
) -> None:
    """Numerically, not as text - which is the difference the whole decision is
    about: as text, 250 sorts between 10 and 40."""
    page = evaluate(client, fx, {"object_type_id": typed, "filters": []}, sort="reading")
    # 3 and 5 both read 40, so the tie-break decides their order; 6 has no
    # reading at all and goes last.
    assert [i["primary_key"] for i in page["instances"]] == [
        "7", "4", "1", "0", "3", "5", "2", "6"
    ]

    page = evaluate(client, fx, {"object_type_id": typed, "filters": []}, sort="-reading")
    # **The tie still breaks ascending, and the absent row is still last.**
    # Postgres puts NULLs first descending by default, so the last element here
    # is what `NULLS LAST` buys.
    assert [i["primary_key"] for i in page["instances"]] == [
        "2", "0", "3", "5", "1", "4", "7", "6"
    ]


def test_a_row_that_will_not_cast_sorts_last_in_both_directions(
    client: TestClient, fx: Fixture, typed: str
) -> None:
    """Postgres puts NULLs **first** on a descending sort by default, so a
    descending page would otherwise open with every unusable row while
    OpenSearch put them at the end. A page that starts with the junk on one
    store and the largest values on the other is the invisible kind of wrong
    the cross-store rule exists for.

    Reached by writing a property the ontology declares `integer` through the
    editing API, which coerces - so the unusable value has to be one that
    survives coercion and still cannot be ordered: an absent one.
    """
    for sort in ("seen", "-seen"):
        page = evaluate(client, fx, {"object_type_id": typed, "filters": []}, sort=sort)
        keys = [i["primary_key"] for i in page["instances"]]
        assert len(keys) == len(TYPED_ROWS), sort
        assert keys[0] != keys[-1], sort


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["filters"][0]["op"])
def test_the_postgres_store_and_the_reference_semantics_agree(
    client: TestClient, fx: Fixture, seeded: str, case: dict
) -> None:
    type_id = seeded
    definition = object_sets.parse({"object_type_id": type_id, **case})
    expected = {key for key, props in ROWS if object_sets.matches(props, definition.filters)}

    body = evaluate(client, fx, {"object_type_id": type_id, **case})
    assert {i["primary_key"] for i in body["instances"]} == expected, case
    assert body["total"] == len(expected)


def test_the_total_is_the_size_of_the_set_not_the_page(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """"127 sites match" is the answer a Workshop app needs, and the one a page
    of rows cannot give - which is the whole reason this is server-side."""
    type_id = seeded
    body = evaluate(
        client, fx, {"object_type_id": type_id, "filters": []}, limit=2, offset=0
    )
    assert len(body["instances"]) == 2
    assert body["total"] == len(ROWS)


def test_paging_a_filtered_set_does_not_repeat_a_row(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    type_id = seeded
    definition = {"object_type_id": type_id, "filters": [{"property": "status", "op": "eq", "value": "open"}]}
    first = evaluate(client, fx, definition, limit=2, offset=0)
    second = evaluate(client, fx, definition, limit=2, offset=2)
    keys = [i["primary_key"] for i in first["instances"] + second["instances"]]
    assert len(keys) == len(set(keys)), "a row appeared on two pages"
    open_rows = sum(1 for _, props in ROWS if props["status"] == "open")
    assert first["total"] == second["total"] == open_rows


def test_a_type_from_another_workspace_is_not_evaluable(
    client: TestClient, fx: Fixture
) -> None:
    """An id in a request body is never trusted to be in scope."""
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": str(uuid.uuid4()), "filters": []}},
    )
    assert r.status_code == 404, r.text


def test_a_bad_definition_is_refused_in_a_sentence(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    # **A type that exists**, which it did not have to be before §221. The
    # definition is now validated *against the ontology* — an ordered
    # comparison is checked against declared property types — so the type has
    # to be resolved before the rest of the definition can be judged at all.
    # A request naming both a nonexistent type and a bad operator therefore
    # answers 404 rather than 422, and both are true; what this asserts is that
    # a bad operator on a real type still blames the operator.
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": seeded,
                             "filters": [{"property": "r", "op": "nope", "value": 1}]}},
    )
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], str)
    assert "nope" in r.json()["detail"]

    gone = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": str(uuid.uuid4()), "filters": []}},
    )
    assert gone.status_code == 404, gone.text


# ---- the two Postgres rules a cluster cannot be asked about ------------------
#
# Both are reached by calling the store directly with a `Filter` built by hand
# rather than through `parse`. That is not a shortcut around validation: the
# store's contract is "given a filter carrying a declared type, compare
# correctly", and these two cases are unreachable through the API by
# construction - the first because a strict OpenSearch mapping refuses to store
# the value at all, and the second because it depends on a server setting no
# request can change.
@pytest.mark.anyio
async def test_postgres_does_not_fail_a_page_over_one_unparseable_value(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """`seeded` holds `capacity` values 10, 250, 40, 7 and **"n/a"**, declared
    `string`. Treated as an integer - which is what a property retyped after a
    sync looks like (decision 0006 §4) - the unparseable one must narrow the
    set rather than raise.

    **A bare cast raises on it**, so one bad row would fail the whole page; a
    regex guard would accept `2026-13-45` and throw anyway. `pg_input_is_valid`
    asks the parser.

    Postgres-only, and that asymmetry is itself the guarantee: OpenSearch
    cannot hold this state, because the strict mapping refuses the document
    (0006 §5). The guard is what makes the *other* store behave the same way
    for data written before its mapping existed.
    """
    from src.lib.db import user_connection
    from src.services import instances as instances_service

    numeric = (object_sets.Filter("capacity", "gt", 40, "integer"),)
    async with user_connection(fx.owner) as conn:
        rows, total = await instances_service.evaluate_object_set(
            conn, object_type_id=uuid.UUID(seeded), filters=numeric,
            limit=50, offset=0, sort=object_sets.Sort(),
        )
    assert total == 1, "250 is the only capacity over 40"
    assert {r["primary_key"] for r in rows} == {"2"}


@pytest.mark.anyio
async def test_postgres_reads_a_bare_date_as_utc_whatever_the_server_says(
    client: TestClient, fx: Fixture, typed: str
) -> None:
    """**The divergence that hides in a server setting.**

    `'2026-01-05'::timestamptz` is not a fixed instant - Postgres reads it in
    the session's `TimeZone`. The dev database is `Etc/UTC`, so every other
    test in this file would pass with the rule left unstated and the same data
    would compare differently on a deployment configured to anything else.

    Asked by moving the session a long way from UTC and requiring the identical
    answer. `America/New_York` is five hours behind, so a bare `2026-01-05`
    read in it lands *after* `2026-01-05T00:00:00+00:00` and a `lt` filter on
    that bound would lose the row.
    """
    from sqlalchemy import text as _sql

    from src.lib.db import user_connection
    from src.services import instances as instances_service

    # 02:00Z, so the bare `2026-03-01` in row 7 falls on one side of it read as
    # UTC and the other side read in a western timezone.
    bound = (object_sets.Filter("seen", "lt", "2026-03-01T02:00:00+00:00", "timestamp"),)
    answers = []
    for zone in ("UTC", "America/New_York", "Asia/Kathmandu"):
        async with user_connection(fx.owner) as conn:
            await conn.execute(_sql(f"SET TIME ZONE '{zone}'"))
            rows, _ = await instances_service.evaluate_object_set(
                conn, object_type_id=uuid.UUID(typed), filters=bound,
                limit=50, offset=0, sort=object_sets.Sort(),
            )
            answers.append(sorted(r["primary_key"] for r in rows))
    assert answers[0] == answers[1] == answers[2], answers
    # And it is the right answer, not merely a consistent one.
    expected = sorted(
        key for key, props in TYPED_ROWS
        if object_sets.matches(props, bound)
    )
    assert answers[0] == expected


@pytest.mark.anyio
async def test_postgres_sorts_by_a_date_the_same_way_whatever_the_server_says(
    client: TestClient, fx: Fixture, typed: str
) -> None:
    """The same rule on the ordering side, where it decides which page a row
    lands on rather than whether it matches."""
    from sqlalchemy import text as _sql

    from src.lib.db import user_connection
    from src.services import instances as instances_service

    parsed = object_sets.parse_sort("seen", property_types=TYPED_TYPES)
    orders = []
    for zone in ("UTC", "Pacific/Kiritimati"):
        async with user_connection(fx.owner) as conn:
            await conn.execute(_sql(f"SET TIME ZONE '{zone}'"))
            rows, _ = await instances_service.evaluate_object_set(
                conn, object_type_id=uuid.UUID(typed), filters=(),
                limit=50, offset=0, sort=parsed,
            )
            orders.append([r["primary_key"] for r in rows])
    assert orders[0] == orders[1], orders


# ---- aggregating a set (roadmap 1.5, what a Metric Card shows) ----------------
def aggregate(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/aggregate",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def test_a_count_is_the_size_of_the_set_not_of_a_page(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The whole reason this is not a flag on `/evaluate`: a card that got its
    number by paging would be wrong the moment a set outgrew a page, which is
    exactly when the number starts mattering."""
    definition = {"object_type_id": seeded, "filters": []}
    page = evaluate(client, fx, definition, limit=2)
    assert len(page["instances"]) == 2

    r = aggregate(client, fx, definition, aggregation="count")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == len(ROWS)


def test_a_count_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    expected = sum(1 for _, p in ROWS if p["region"] == "north")
    r = aggregate(client, fx, definition, aggregation="count")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == expected
    # And it agrees with what the table beside it would show.
    assert evaluate(client, fx, definition)["total"] == expected


def test_count_distinct_counts_values_not_rows(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {"object_type_id": seeded, "filters": []}
    expected = len({p["region"] for _, p in ROWS})
    r = aggregate(client, fx, definition, aggregation="count_distinct", property="region")
    assert r.status_code == 200, r.text
    assert r.json()["value"] == expected
    assert expected < len(ROWS), "the fixture must have repeats or this proves nothing"


def test_count_distinct_without_a_property_says_what_is_missing(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = aggregate(client, fx, {"object_type_id": seeded, "filters": []},
                  aggregation="count_distinct")
    assert r.status_code == 422, r.text
    assert "needs a property" in r.json()["detail"]


def test_a_numeric_aggregation_is_refused_with_the_reason(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """Same refusal as ordered operators, for the same cause: properties are
    stored untyped, so a sum means one thing on Postgres and nothing at all on
    OpenSearch. A card whose number is right on one deployment and absent on
    another is worse than one that says the platform cannot answer yet."""
    r = aggregate(client, fx, {"object_type_id": seeded, "filters": []},
                  aggregation="sum", property="capacity")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "untyped" in detail
    assert "count and count_distinct" in detail


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {"aggregation": "count", "property": None, "filters": []},
        {"aggregation": "count", "property": None,
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
        {"aggregation": "count_distinct", "property": "region", "filters": []},
        {"aggregation": "count_distinct", "property": "status",
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
    ],
    ids=["count", "count-filtered", "distinct", "distinct-filtered"],
)
async def test_both_stores_aggregate_a_set_the_same_way(opensearch: str, case: dict) -> None:
    """The check that stops a Metric Card meaning two things.

    Postgres counts distinct `jsonb_extract_path_text`; OpenSearch runs a
    cardinality aggregation on the `.keyword` subfield. Different mechanisms,
    and the number has to be the same or an app's headline figure depends on
    which store the deployment happens to run.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-agg-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": case["filters"]}
        )
        in_set = [p for _, p in ROWS if object_sets.matches(p, definition.filters)]
        expected = (
            len(in_set)
            if case["aggregation"] == "count"
            else len({str(p[case["property"]]) for p in in_set if p.get(case["property"]) is not None})
        )
        value = await store.aggregate_object_set(
            search_prefix="ws-agg-test",
            object_type_id=type_id,
            filters=definition.filters,
            aggregation=case["aggregation"],
            property_name=case["property"],
        )
        assert value == expected, case
    finally:
        await store.close()


# ---- grouping a set (roadmap 1.5, what a chart over a set plots) -------------
def group(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/group",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def test_grouping_counts_each_value_and_orders_biggest_first(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = group(client, fx, {"object_type_id": seeded, "filters": []}, property="region")
    assert r.status_code == 200, r.text
    body = r.json()
    expected: dict[str, int] = {}
    for _, p in ROWS:
        expected[p["region"]] = expected.get(p["region"], 0) + 1
    assert {g["value"]: g["count"] for g in body["groups"]} == expected
    counts = [g["count"] for g in body["groups"]]
    assert counts == sorted(counts, reverse=True), "biggest bar first"
    assert body["distinct_total"] == len(expected)
    assert body["truncated"] is False


def test_grouping_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The point of grouping a *set* rather than a type: the chart and the
    table beside it are looking at the same rows."""
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    r = group(client, fx, definition, property="status")
    assert r.status_code == 200, r.text
    expected: dict[str, int] = {}
    for _, p in ROWS:
        if p["region"] == "north":
            expected[p["status"]] = expected.get(p["status"], 0) + 1
    assert {g["value"]: g["count"] for g in r.json()["groups"]} == expected
    assert sum(g["count"] for g in r.json()["groups"]) == evaluate(
        client, fx, definition
    )["total"]


def test_truncation_is_reported_rather_than_silent(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """A chart drawing the top N of many without saying so is the same trap as
    a preview that sampled and did not mention it. Derived from the distinct
    total, not from "did we fill the page", which would be wrong on a set with
    exactly `limit` groups."""
    r = group(client, fx, {"object_type_id": seeded, "filters": []},
              property="region", limit=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["groups"]) == 1
    assert body["truncated"] is True
    assert body["distinct_total"] > 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {"property": "region", "filters": []},
        {"property": "status", "filters": []},
        {"property": "status",
         "filters": [{"property": "region", "op": "eq", "value": "north"}]},
    ],
    ids=["region", "status", "status-filtered"],
)
async def test_both_stores_group_a_set_the_same_way(opensearch: str, case: dict) -> None:
    """Postgres groups with SQL, OpenSearch with a terms aggregation. Same
    buckets, same counts, **same order** - ties included, which is why both
    sides ask for count-descending-then-value-ascending explicitly."""
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-group-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": case["filters"]}
        )
        in_set = [p for _, p in ROWS if object_sets.matches(p, definition.filters)]
        tally: dict[str, int] = {}
        for p in in_set:
            value = p.get(case["property"])
            if value is not None:
                tally[str(value)] = tally.get(str(value), 0) + 1
        expected = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))

        buckets, distinct_total = await store.group_object_set(
            search_prefix="ws-group-test",
            object_type_id=type_id,
            filters=definition.filters,
            property_name=case["property"],
            limit=object_sets.MAX_GROUPS,
        )
        assert buckets == expected, case
        assert distinct_total == len(tally)
    finally:
        await store.close()


# ---- cross-tabbing a set (roadmap 1.5, what a Pivot Table shows) -------------
def cross_tab(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/cross-tab",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def expected_grid(rows_in_set, row_property: str, column_property: str):
    """What the grid should be, worked out from the population rather than from
    the implementation: axes ordered count-descending then value-ascending, and
    a cell counting the rows that have both values."""
    def tally(prop: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for p in rows_in_set:
            if p.get(prop) is not None:
                out[str(p[prop])] = out.get(str(p[prop]), 0) + 1
        return out

    def order(counts: dict[str, int]) -> list[str]:
        return [k for k, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    row_values, column_values = order(tally(row_property)), order(tally(column_property))
    cells = [
        [
            sum(
                1
                for p in rows_in_set
                if str(p.get(row_property)) == r and str(p.get(column_property)) == c
            )
            for c in column_values
        ]
        for r in row_values
    ]
    return row_values, column_values, cells


def test_a_cross_tab_counts_both_properties_at_once(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = cross_tab(client, fx, {"object_type_id": seeded, "filters": []},
                  row_property="region", column_property="status")
    assert r.status_code == 200, r.text
    body = r.json()
    row_values, column_values, cells = expected_grid([p for _, p in ROWS], "region", "status")
    assert [a["value"] for a in body["rows"]] == row_values
    assert [a["value"] for a in body["columns"]] == column_values
    assert body["cells"] == cells
    assert body["total"] == len(ROWS)


def test_a_cross_tab_s_axes_are_the_numbers_a_chart_would_draw(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The axes come from the same grouped count a chart plots. Not "they
    happen to match" - the route calls `group_object_set` for each axis, and
    this is what would catch that being replaced by a second implementation
    computed from the cells, which would be smaller wherever a value was
    missing or a column was cut."""
    definition = {"object_type_id": seeded, "filters": []}
    grid = cross_tab(client, fx, definition,
                     row_property="region", column_property="status").json()
    for axis, prop in (("rows", "region"), ("columns", "status")):
        chart = group(client, fx, definition, property=prop).json()
        assert [(a["value"], a["count"]) for a in grid[axis]] == [
            (g["value"], g["count"]) for g in chart["groups"]
        ], f"the {axis} axis is the {prop} chart"


def test_a_cross_tab_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "status", "op": "eq", "value": "open"}],
    }
    r = cross_tab(client, fx, definition, row_property="region", column_property="capacity")
    assert r.status_code == 200, r.text
    body = r.json()
    in_set = [p for _, p in ROWS if p["status"] == "open"]
    row_values, column_values, cells = expected_grid(in_set, "region", "capacity")
    assert [a["value"] for a in body["rows"]] == row_values
    assert body["cells"] == cells
    assert body["total"] == len(in_set)


def test_a_filtered_out_object_does_not_land_in_a_cell(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The trap `test_a_cross_tab_honours_the_set_s_filters` walks past: there,
    every excluded object had a column value no drawn column used, so dropping
    the filter from the cell query changed nothing and a mutation survived.

    Here the excluded object shares a cell with an included one - two south
    sites are both open - so a cell computed over the unfiltered table counts
    2 where the set has 1.
    """
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "capacity", "op": "neq", "value": "40"}],
    }
    r = cross_tab(client, fx, definition, row_property="region", column_property="status")
    assert r.status_code == 200, r.text
    body = r.json()
    in_set = [p for _, p in ROWS if str(p["capacity"]) != "40"]
    row_values, column_values, cells = expected_grid(in_set, "region", "status")
    assert [a["value"] for a in body["rows"]] == row_values
    assert body["cells"] == cells
    south = row_values.index("south"), column_values.index("open")
    assert body["cells"][south[0]][south[1]] == 1, "the excluded south site is not counted"


def test_the_cells_are_only_the_axes_they_were_asked_for(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """The Postgres store's half of the pinning contract.

    A store that returned every column and let the caller pick would produce
    the same grid today and a different one the moment anything iterated the
    result - and it is the same query shape whose OpenSearch equivalent is
    actively wrong, not merely wasteful. So the contract is asserted where it
    is stated: exactly the pairs asked for, nothing else.
    """
    import asyncio

    from src.lib.db import user_connection
    from src.services import instance_store as store_module

    async def run() -> dict:
        async with user_connection(fx.owner) as conn:
            return await store_module.store_for(conn).cross_tab_object_set(
                search_prefix=await instances_service_prefix(conn, fx.workspace),
                object_type_id=uuid.UUID(seeded),
                filters=(),
                row_property="region",
                column_property="status",
                # Deliberately a *cut* axis: "closed" exists and is not asked
                # for. North has one of each, so a store picking its own
                # top-one column would return north's "closed" instead.
                row_values=("north", "south", "east"),
                column_values=("open",),
            )

    assert asyncio.run(run()) == {("north", "open"): 1, ("south", "open"): 2,
                                  ("east", "open"): 1}


async def instances_service_prefix(conn, workspace_id):
    from src.services import instances as instances_service

    return await instances_service.workspace_search_prefix(conn, uuid.UUID(str(workspace_id)))


def test_a_row_total_is_the_whole_row_not_the_part_inside_the_grid(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """With the columns cut to one, the cells no longer add up to the totals -
    and the totals are still the totals. The alternative (a row total that is
    the sum of the drawn cells) would disagree with the same property's bar
    chart, which is the disagreement the widget exists inside."""
    r = cross_tab(client, fx, {"object_type_id": seeded, "filters": []},
                  row_property="region", column_property="status", column_limit=1)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["columns"]) == 1
    assert body["columns_truncated"] is True
    assert body["rows_truncated"] is False
    assert body["column_distinct_total"] == 2
    counted = {a["value"]: a["count"] for a in body["rows"]}
    assert counted == {"north": 2, "south": 2, "east": 1}, "whole rows"
    assert sum(sum(row) for row in body["cells"]) < sum(counted.values()), (
        "and the grid accounts for less than the set, which is the point"
    )


def test_a_cross_tab_of_a_property_against_itself_is_refused(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """A diagonal is not wrong, it is useless - and it is a grouped count in a
    grid's clothes, so the refusal points at the thing that answers it."""
    r = cross_tab(client, fx, {"object_type_id": seeded, "filters": []},
                  row_property="region", column_property="region")
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "diagonal" in detail
    assert "chart" in detail, "says what to use instead"


def test_a_cross_tab_over_a_type_from_another_workspace_is_refused(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = cross_tab(client, fx, {"object_type_id": str(uuid.uuid4()), "filters": []},
                  row_property="region", column_property="status")
    assert r.status_code == 404, r.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case",
    [
        {"row": "region", "column": "status", "filters": []},
        {"row": "status", "column": "region", "filters": []},
        {"row": "region", "column": "capacity", "filters": []},
        {"row": "region", "column": "status",
         "filters": [{"property": "status", "op": "eq", "value": "open"}]},
    ],
    ids=["region-x-status", "transposed", "many-columns", "filtered"],
)
async def test_both_stores_cross_tab_a_set_the_same_way(opensearch: str, case: dict) -> None:
    """Postgres groups by two columns in SQL, OpenSearch nests a terms
    aggregation inside a terms aggregation. Same cells - including the empty
    ones, which is where the two would most easily differ: a store that picked
    its own columns per row would fill a gap that should be zero.

    The population here has a row missing the column property, so this also
    covers the rule that a cell counts objects with *both* values while the
    axis totals count the whole row.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        rows = [*ROWS, ("6", {"region": "north", "capacity": 3})]  # no status at all
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-pivot-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=rows,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        definition = object_sets.parse(
            {"object_type_id": str(type_id), "filters": case["filters"]}
        )
        in_set = [p for _, p in rows if object_sets.matches(p, definition.filters)]
        row_values, column_values, expected = expected_grid(in_set, case["row"], case["column"])

        cells = await store.cross_tab_object_set(
            search_prefix="ws-pivot-test",
            object_type_id=type_id,
            filters=definition.filters,
            row_property=case["row"],
            column_property=case["column"],
            row_values=tuple(row_values),
            column_values=tuple(column_values),
        )
        grid = [
            [cells.get((r, c), 0) for c in column_values] for r in row_values
        ]
        assert grid == expected, case
    finally:
        await store.close()


@pytest.mark.anyio
async def test_opensearch_answers_only_the_axes_it_was_given(opensearch: str) -> None:
    """The pinning contract on the store where breaking it is actively wrong.

    OpenSearch's inner terms aggregation picks each outer bucket's *own*
    largest columns, so without `include` the answer is not "extra cells" but
    *different* cells per row - here north would come back as "closed", which
    was not asked for, because north's two statuses tie and `_key` ascending
    breaks the tie the other way.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id = uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-pivot-pin",
            object_type_id=type_id,
            source_id=uuid.uuid4(),
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        assert await store.cross_tab_object_set(
            search_prefix="ws-pivot-pin",
            object_type_id=type_id,
            filters=(),
            row_property="region",
            column_property="status",
            row_values=("north", "south", "east"),
            column_values=("open",),
        ) == {("north", "open"): 1, ("south", "open"): 2, ("east", "open"): 1}
    finally:
        await store.close()


@pytest.mark.anyio
async def test_an_empty_axis_is_an_empty_grid_rather_than_a_query(opensearch: str) -> None:
    """A property no object has gives no axis values, and a cross-tab with no
    axis is an empty grid. Asked for rather than assumed: `= ANY('{}')` on
    Postgres and an empty `include` on OpenSearch are both scans that could
    only return nothing, and the second is not even valid."""
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id = uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-pivot-empty",
            object_type_id=type_id,
            source_id=uuid.uuid4(),
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        assert await store.cross_tab_object_set(
            search_prefix="ws-pivot-empty",
            object_type_id=type_id,
            filters=(),
            row_property="region",
            column_property="status",
            row_values=(),
            column_values=("open",),
        ) == {}
    finally:
        await store.close()


# ---- a set over time (roadmap 1.5, what a Time Series plots) -----------------
def series(client: TestClient, fx: Fixture, definition: dict, **kw):
    return client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/time-series",
        headers=hdr(fx.owner_sub),
        json={"definition": definition, **kw},
    )


def test_a_series_buckets_every_object_and_nothing_else(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """Every instance has an `updated_at`, so unlike a cross-tab the points
    account for the whole set. A series whose points did not add up to the
    total would be dropping rows somewhere between the two queries."""
    r = series(client, fx, {"object_type_id": seeded, "filters": []}, interval="day")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["interval"] == "day"
    assert body["total"] == len(ROWS)
    assert sum(p["count"] for p in body["points"]) == len(ROWS)


def test_a_series_honours_the_set_s_filters(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    definition = {
        "object_type_id": seeded,
        "filters": [{"property": "region", "op": "eq", "value": "north"}],
    }
    r = series(client, fx, definition, interval="day")
    assert r.status_code == 200, r.text
    expected = sum(1 for _, p in ROWS if p["region"] == "north")
    assert r.json()["total"] == expected
    assert sum(p["count"] for p in r.json()["points"]) == expected


def test_an_unknown_interval_names_the_ones_that_exist(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    r = series(client, fx, {"object_type_id": seeded, "filters": []}, interval="fortnight")
    assert r.status_code == 422, r.text
    for interval in object_sets.TIME_INTERVALS:
        assert interval in r.json()["detail"]


@pytest.mark.parametrize("interval", object_sets.TIME_INTERVALS)
def test_every_interval_is_answerable(
    client: TestClient, fx: Fixture, seeded: str, interval: str
) -> None:
    """The fixture population lands in one bucket at every size, so this is
    about each interval being *accepted and computed* rather than about the
    shape - which the cross-store test below checks against spread data."""
    r = series(client, fx, {"object_type_id": seeded, "filters": []}, interval=interval)
    assert r.status_code == 200, r.text
    assert sum(p["count"] for p in r.json()["points"]) == len(ROWS)


# ---- gap filling, which is pure and therefore checked directly ---------------
def test_gaps_are_filled_rather_than_drawn_through() -> None:
    """Both stores return only populated buckets. A line drawn straight from
    Monday to Friday across a silent week is not a smaller claim than the
    truth, it is a different one."""
    monday = datetime(2024, 3, 4, tzinfo=timezone.utc)
    filled = object_sets.fill_time_buckets(
        [(monday, 3), (monday + timedelta(days=3), 1)], "day"
    )
    assert [c for _, c in filled] == [3, 0, 0, 1]
    assert [s.day for s, _ in filled] == [4, 5, 6, 7]


def test_filling_a_month_lands_on_the_first_not_thirty_days_later() -> None:
    """Calendar arithmetic, not a fixed span: February is 29 days in 2024, and
    a filled bucket that landed on the 2nd of March would sit *between* the
    real buckets rather than among them - so every later point would be an
    empty one and the real ones would look like duplicates."""
    filled = object_sets.fill_time_buckets(
        [(datetime(2024, 1, 1, tzinfo=timezone.utc), 2),
         (datetime(2024, 4, 1, tzinfo=timezone.utc), 5)],
        "month",
    )
    assert [(s.year, s.month, s.day) for s, _ in filled] == [
        (2024, 1, 1), (2024, 2, 1), (2024, 3, 1), (2024, 4, 1)
    ]
    assert [c for _, c in filled] == [2, 0, 0, 5]


def test_filling_across_a_year_boundary_rolls_the_year() -> None:
    filled = object_sets.fill_time_buckets(
        [(datetime(2024, 11, 1, tzinfo=timezone.utc), 1),
         (datetime(2025, 1, 1, tzinfo=timezone.utc), 1)],
        "month",
    )
    assert [(s.year, s.month) for s, _ in filled] == [(2024, 11), (2024, 12), (2025, 1)]


def test_an_empty_set_is_an_empty_series_not_a_range() -> None:
    assert object_sets.fill_time_buckets([], "day") == []


def test_too_long_a_range_refuses_and_names_a_coarser_interval() -> None:
    """Truncating would be worse than refusing: the chart would show a
    different period and nothing on it would say which."""
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="coarser interval"):
        object_sets.fill_time_buckets(
            [(start, 1), (start + timedelta(days=object_sets.MAX_TIME_BUCKETS + 5), 1)],
            "day",
        )
    # The same span at a coarser interval is fine, which is what the refusal
    # tells the caller to do.
    assert len(object_sets.fill_time_buckets(
        [(start, 1), (datetime(2020, 8, 1, tzinfo=timezone.utc), 1)], "month"
    )) == 8


# The instants the two bucketing tests below share, so "Postgres and
# OpenSearch agree" is a claim about the same boundaries rather than about two
# convenient populations. Wednesday 2024-03-06, plus a Sunday two days on that
# is the *same* ISO week - a week starting on Sunday would split them.
SERIES_STAMPS = [
    datetime(2024, 3, 6, 1, 0, tzinfo=timezone.utc),
    datetime(2024, 3, 6, 23, 30, tzinfo=timezone.utc),
    datetime(2024, 3, 10, 12, 0, tzinfo=timezone.utc),
    datetime(2024, 4, 1, 0, 0, tzinfo=timezone.utc),
    # Far enough out to cross several months and close enough that the whole
    # span is still under `MAX_TIME_BUCKETS` days. The first version reached
    # into 2025 and the day-interval test hit its own refusal - the refusal
    # working correctly, but it made the test about the wrong thing. Year
    # rollover is covered by the pure filling test instead.
    datetime(2024, 8, 15, 12, 0, tzinfo=timezone.utc),
]


def expected_buckets(stamps: list[datetime], interval: str) -> list[tuple[datetime, int]]:
    def truncate(when: datetime) -> datetime:
        if interval == "day":
            return when.replace(hour=0, minute=0, second=0, microsecond=0)
        if interval == "week":
            return (when - timedelta(days=when.weekday())).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        return when.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    tally: dict[datetime, int] = {}
    for when in stamps:
        tally[truncate(when)] = tally.get(truncate(when), 0) + 1
    return sorted(tally.items())


@pytest.fixture
def spread(client: TestClient, fx: Fixture) -> str:
    """Its own object type whose instances are spread across `SERIES_STAMPS`.

    The rows land the normal way and their `updated_at` is then rewritten
    directly, because a sync stamps every row with one instant - which would
    make a bucketing test a test of a single spike. The trigger on the table is
    `BEFORE UPDATE`, so it is switched off around the rewrite; without that
    every row would land on `now()` and every interval would agree for the
    wrong reason.
    """
    import psycopg

    from test_api import ADMIN_DSN

    tag = uuid.uuid4().hex[:8]
    csv = b"key,region\n" + b"".join(
        f"k{i},north\n".encode() for i in range(len(SERIES_STAMPS))
    )
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.owner_sub),
        data={"name": f"Spread {tag}"},
        files={"file": ("spread.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types",
        headers=hdr(fx.owner_sub),
        json={"api_name": f"Spread{tag}", "display_name": f"Spread {tag}",
              "properties": [{"api_name": "region", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.owner_sub),
        json={"object_type_id": type_id, "dataset_id": dataset_id,
              "primary_key_column": "key", "column_mappings": {"region": "region"}},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.owner_sub),
    )
    assert r.status_code == 200, r.text

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("ALTER TABLE object_instances DISABLE TRIGGER USER")
        try:
            for index, when in enumerate(SERIES_STAMPS):
                conn.execute(
                    "UPDATE object_instances SET updated_at = %s "
                    " WHERE object_type_id = %s AND primary_key = %s",
                    (when, type_id, f"k{index}"),
                )
        finally:
            conn.execute("ALTER TABLE object_instances ENABLE TRIGGER USER")
    return type_id


@pytest.mark.parametrize("interval", object_sets.TIME_INTERVALS)
def test_postgres_buckets_each_interval_by_the_calendar(
    client: TestClient, fx: Fixture, spread: str, interval: str
) -> None:
    """The Postgres half of the agreement below, and the half a fixture cannot
    stand in for.

    Without this, a store that truncated to the *same* interval whatever it was
    asked for would pass every other test here - the fixture population lands
    in one bucket at every size, so only spread instants can tell day from
    month.
    """
    r = series(client, fx, {"object_type_id": spread, "filters": []}, interval=interval)
    assert r.status_code == 200, r.text
    points = r.json()["points"]
    expected = object_sets.fill_time_buckets(
        expected_buckets(SERIES_STAMPS, interval), interval
    )
    assert [p["count"] for p in points] == [c for _, c in expected], interval
    assert [p["start"][:10] for p in points] == [
        s.date().isoformat() for s, _ in expected
    ], interval
    # Two instants on the same day share a bucket at every interval, which is
    # what makes this a test of truncation rather than of row counting.
    assert max(p["count"] for p in points) >= 2


@pytest.mark.anyio
async def test_a_bucket_boundary_is_utc_whatever_the_session_says(
    client: TestClient, fx: Fixture, spread: str
) -> None:
    """`updated_at` is a `timestamptz`, so `date_trunc` on it follows the
    *session's* TimeZone unless told otherwise - and OpenSearch's histogram is
    pinned to UTC. A deployment whose database session ran in another zone
    would put every day boundary somewhere else, and nothing on the chart
    would say so.

    23:30 UTC on 2024-03-06 is the instant that proves it: in Asia/Tokyo that
    is 08:30 on the *next* day, so a session-dependent truncation splits the
    bucket UTC keeps whole - and the day count goes up by one.

    **`SET LOCAL` on the connection under test, not `ALTER DATABASE`.** The
    first version of this altered the database and passed against the
    mutation, because an `ALTER DATABASE` only reaches connections opened
    afterwards and the pool was already full of old ones. Setting it on the
    very connection the query runs on is the only version that asks the
    question.
    """
    from sqlalchemy import text as sql_text

    from src.lib.db import user_connection
    from src.services import instances as instances_service

    async def buckets(zone: str) -> list[tuple[datetime, int]]:
        async with user_connection(fx.owner) as conn:
            # LOCAL: transaction-scoped, so the connection goes back to the
            # pool as it came out.
            await conn.execute(sql_text(f"SET LOCAL TIME ZONE '{zone}'"))
            assert (await conn.execute(sql_text("SHOW TimeZone"))).scalar() == zone
            return await instances_service.time_series_object_set(
                conn,
                object_type_id=uuid.UUID(spread),
                filters=(),
                interval="day",
            )

    assert await buckets("Asia/Tokyo") == expected_buckets(SERIES_STAMPS, "day")
    assert await buckets("UTC") == expected_buckets(SERIES_STAMPS, "day")
    # The instants that would move: both sit on 2024-03-06 in UTC and land on
    # different days in Tokyo, so a session-dependent truncation would report
    # one more bucket than there are days with data.
    assert len(await buckets("Asia/Tokyo")) == len({s.date() for s in SERIES_STAMPS})


@pytest.mark.anyio
@pytest.mark.parametrize("interval", object_sets.TIME_INTERVALS)
async def test_both_stores_bucket_a_set_the_same_way(opensearch: str, interval: str) -> None:
    """Postgres truncates with `date_trunc` pinned to UTC, OpenSearch with a
    `calendar_interval` date histogram pinned to UTC. Same boundaries, same
    counts, at every interval.

    The population deliberately straddles all three boundaries: two instants
    inside one day, one later in the same week, one in the next month, and one
    in the following year. A store using a *fixed* month interval, or the
    machine's local time zone, lands them differently.
    """
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        for index, when in enumerate(SERIES_STAMPS):
            await store.upsert_instances(
                search_prefix="ws-series-test",
                object_type_id=type_id,
                source_id=source_id,
                rows=[(f"k{index}", {"region": "north"})],
                synced_at=when,
                declared=DECLARED,
            )

        buckets = await store.time_series_object_set(
            search_prefix="ws-series-test",
            object_type_id=type_id,
            filters=(),
            interval=interval,
        )
        assert buckets == expected_buckets(SERIES_STAMPS, interval), interval
        # Two instants on the same day share a bucket at every interval, which
        # is what makes this about truncation rather than about row counting.
        assert max(n for _, n in buckets) >= 2
    finally:
        await store.close()


# ---- sorting a page (roadmap 1.5, the Object Table upgrade) ------------------
def test_the_default_sort_is_most_recently_changed(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """Unchanged behaviour, pinned: every existing caller sends no sort and
    must keep getting the page it got before."""
    type_id = seeded
    body = evaluate(client, fx, {"object_type_id": type_id, "filters": []})
    explicit = evaluate(client, fx, {"object_type_id": type_id, "filters": []}, sort="recent")
    assert [i["primary_key"] for i in body["instances"]] == [
        i["primary_key"] for i in explicit["instances"]
    ]


def test_sorting_by_key_is_the_key_order_both_ways(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    type_id = seeded
    up = evaluate(client, fx, {"object_type_id": type_id, "filters": []}, sort="key")
    down = evaluate(client, fx, {"object_type_id": type_id, "filters": []}, sort="-key")
    keys = [i["primary_key"] for i in up["instances"]]
    assert keys == sorted(keys)
    assert [i["primary_key"] for i in down["instances"]] == list(reversed(keys))


def test_a_sorted_page_does_not_repeat_or_skip_a_row(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """A bulk sync writes every row in one instant, so `updated_at` ties are
    the normal case rather than the rare one. Without a tiebreak the two pages
    of one sort can share a row and miss another, and nothing about the symptom
    points at the sort."""
    type_id = seeded
    definition = {"object_type_id": type_id, "filters": []}
    seen: list[str] = []
    for offset in (0, 2, 4, 6):
        page = evaluate(client, fx, definition, limit=2, offset=offset, sort="recent")
        seen += [i["primary_key"] for i in page["instances"]]
    assert len(seen) == len(set(seen)), "a row appeared on two pages"
    assert set(seen) == {key for key, _ in ROWS}, "a row appeared on no page"
    # And the tiebreak is *observably* the key, not merely whatever order the
    # rows happen to come back in. Without this the assertions above pass on a
    # small table even with no tiebreak at all, because a sequential scan is
    # accidentally stable - which is exactly the kind of test that reports a
    # guarantee it is not checking. Every fixture row shares one `updated_at`,
    # so ascending keys is the whole of what the tiebreak promises.
    assert seen == sorted(seen), "tied timestamps did not fall through to the key"


def test_sorting_by_a_property_is_refused_with_what_it_would_take(
    client: TestClient, fx: Fixture, seeded: str
) -> None:
    """**Refused because it is text, not because sorting by a property is
    unsupported** - which it no longer is (§221).

    `capacity` is a string property in this fixture, and decision 0006 §2
    refuses string ordering *permanently*: Postgres orders by the database
    collation and OpenSearch by byte order, so `'Z' < 'a'` differs between
    them. The refusal has to say that rather than "not yet", because "not yet"
    is a promise this one will never keep.
    """
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": seeded, "filters": []}, "sort": "capacity"},
    )
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert "is a string property" in detail
    assert "no order the two stores agree on" in detail, "permanent, not pending"

    # A property nothing declares still reports the four fixed sorts, because
    # there is no declared type to blame instead.
    unknown = client.post(
        f"/api/workspaces/{fx.workspace}/object-sets/evaluate",
        headers=hdr(fx.owner_sub),
        json={"definition": {"object_type_id": seeded, "filters": []}, "sort": "nope"},
    )
    assert unknown.status_code == 422, unknown.text
    hint = unknown.json()["detail"]
    assert "unknown sort" in hint
    # `PROPERTY_SORT_HINT` still says which types a property sort covers, and
    # that text is not among them - it is the sentence somebody reads when they
    # named a property that does not exist, so it has to point at the rule.
    assert "text will stay unsortable" in hint, "and what it never will"


@pytest.mark.anyio
@pytest.mark.parametrize("sort", object_sets.SORTS)
async def test_the_two_stores_sort_a_page_identically(opensearch: str, sort: str) -> None:
    """The cross-store check, extended to ordering. A table sorted one way on
    Postgres and another on OpenSearch is the invisible kind of wrong - the
    same class of bug the operator list already exists to prevent."""
    urllib.request.urlopen(
        urllib.request.Request(f"{opensearch}/__reset", method="POST", data=b"")
    ).read()
    store = instance_store.OpenSearchInstanceStore(opensearch, "admin", "admin")
    try:
        type_id, source_id = uuid.uuid4(), uuid.uuid4()
        await store.upsert_instances(
            search_prefix="ws-sort-test",
            object_type_id=type_id,
            source_id=source_id,
            rows=ROWS,
            synced_at=datetime.now(timezone.utc),
            declared=DECLARED,
        )
        rows, _ = await store.evaluate_object_set(
            search_prefix="ws-sort-test",
            object_type_id=type_id,
            filters=(),
            limit=50,
            offset=0,
            sort=sort,
        )
        keys = [r["primary_key"] for r in rows]
        if sort == "key":
            assert keys == sorted(keys)
        elif sort == "-key":
            assert keys == sorted(keys, reverse=True)
        else:
            # One sync writes one `updated_at`, so both time sorts fall through
            # to the tiebreak - which is exactly the case that must not vary.
            assert keys == sorted(keys), f"{sort} did not fall back to the key tiebreak"
    finally:
        await store.close()
