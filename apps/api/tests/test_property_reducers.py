"""Property reducers (parity `docs/parity/ontology.md`; Foundry
`object-link-types` p.131-133 **[Beta]**; db 0088).

> "A property reducer enables you to transform an array property into a single
>  value in the array for display and interface implementation purposes.
>  **Reduction does not change the underlying property type or property data
>  stored**; instead, it provides access to the reduced value in the array when
>  reading the property value." (p.131)

> "You can also configure **multiple reducers** using different struct fields
>  to handle tie-breaking scenarios." (p.133)

Three things are being checked here and they fail in different ways:

* **the declaration**, where every refusal is p.132's two tables or p.133's
  sentence about struct fields, and the interesting ones are the mismatches
  rather than the typos — `latest` on a string array is somebody who meant
  `last`, and a list of every operation in the platform would not tell them so;
* **the reduction itself**, where the whole risk is that the comparison is the
  wrong *kind*: `latest` means later in time and `last` means later in the
  alphabet, and an array of ISO timestamps compared as text answers the first
  question with the second one's method. The tests that would catch that are
  the ones where text order and real order disagree, so those are the ones
  written;
* **the read path**, because a reducer that parses and reduces perfectly is
  still nothing until a route hands the array to it — which is exactly the gap
  §346's sweep found twice over, in `coerce_rows` and `field_for`.
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
from src.services import array_properties, property_reducers  # noqa: E402

INSPECTION = [
    {"api_name": "on", "data_type": "date"},
    {"api_name": "score", "data_type": "integer"},
    {"api_name": "where", "data_type": "geopoint"},
]


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


def parse(reducers, *, data_type="array", array_of="date", fields=None,
          name="inspections"):
    return property_reducers.parse(
        reducers, data_type=data_type, array_of=array_of,
        struct_fields=fields, property_name=name,
    )


def refusal(reducers, **kw) -> str:
    with pytest.raises(property_reducers.ReducerError) as caught:
        parse(reducers, **kw)
    return str(caught.value)


# ---- the declaration ---------------------------------------------------------
def test_a_reducer_is_normalised_so_what_is_stored_is_what_was_checked() -> None:
    """`value_format`'s rule, one column over: a declaration validated and then
    written from the untouched input is two things that only look like one.
    `field` comes back present and null on a non-struct array, so a reader
    never has to tell "absent" from "not applicable"."""
    assert parse([{"operation": "latest"}]) == [
        {"operation": "latest", "field": None}
    ]


def test_every_category_has_p132s_own_words() -> None:
    """p.132's table, category by category. **The words are per category on
    purpose** — one max/min pair over everything would have made `latest` and
    `last` the same operation, which is the bug the reduction tests below are
    built around."""
    assert property_reducers.OPERATIONS["integer"] == ("highest", "lowest")
    assert property_reducers.OPERATIONS["float"] == ("highest", "lowest")
    assert property_reducers.OPERATIONS["date"] == ("latest", "earliest")
    assert property_reducers.OPERATIONS["timestamp"] == ("latest", "earliest")
    assert property_reducers.OPERATIONS["string"] == ("first", "last")
    assert property_reducers.OPERATIONS["boolean"] == ("true_first", "false_first")


def test_a_property_that_is_not_an_array_says_nothing() -> None:
    assert parse(None, data_type="string", array_of=None) is None
    # `[]` is "no reducers", not a mistake — `struct_fields`' rule, for its
    # reason: a client echoing a stored null back as an empty list means the
    # same thing.
    assert parse([], data_type="string", array_of=None) is None


def test_an_array_that_declares_none_is_an_ordinary_array() -> None:
    assert parse(None) is None
    assert parse([]) is None


def test_a_non_array_carrying_reducers_is_refused_not_ignored() -> None:
    """`array_properties`' both-directions rule. Silently dropping it would
    leave somebody looking at a saved definition that does not contain what
    they typed — the failure §157, §160 and §163 each had to fix."""
    said = refusal([{"operation": "latest"}], data_type="string", array_of=None)
    assert "is a string" in said and "p.131" in said


def test_an_operation_that_does_not_fit_the_element_type_says_which_do() -> None:
    """**The mistake that actually happens**, and it is not a typo: `latest` is
    a real operation, and somebody reducing a string array meant `last`. A
    refusal listing every operation in the platform would leave them to work
    that out."""
    said = refusal([{"operation": "latest"}], array_of="string")
    assert "'latest'" in said
    assert "first or last" in said
    # And not the whole vocabulary, which is the other refusal's job.
    assert "true_first" not in said


def test_an_operation_nobody_has_is_a_different_sentence() -> None:
    said = refusal([{"operation": "biggest"}])
    assert "no operation I know" in said
    assert "highest" in said and "true_first" in said


@pytest.mark.parametrize("element,because", [
    ("attachment", "reference to a stored blob"),
    ("geopoint", "two coordinates with no agreed precedence"),
    ("json", "untyped escape hatch"),
])
def test_an_element_type_p132_cannot_order_is_refused_in_its_own_words(
    element: str, because: str,
) -> None:
    """p.132's unsupported table. **A sentence each**, because the reasons are
    different — an attachment is a reference to a blob, a geopoint is two
    numbers with no precedence between them, and a `json` value has no declared
    shape at all — and a shared "not supported" would read as an oversight.

    The expected phrases are written out here rather than read off
    `UNREDUCIBLE`, which would make this a test of `in` rather than of what any
    of the sentences say."""
    said = refusal([{"operation": "latest"}], array_of=element)
    assert element in said
    assert "cannot be reduced" in said
    assert because in said


def test_p132s_unsupported_list_is_read_in_full() -> None:
    """The guard on the test above: parametrised cases pass by being absent. If
    a fourth element type is refused, its sentence needs a case of its own."""
    assert sorted(property_reducers.UNREDUCIBLE) == [
        "attachment", "geopoint", "json"
    ]


def test_every_element_type_0087_allows_has_a_decision_here() -> None:
    """**The guard against the list this one mirrors** (§191): 0087 decides
    what an array may hold, and this module decides which of those can be
    reduced. An element type added there with nothing said about it here would
    otherwise fall through to "which has no reducer operations", a sentence
    with no page behind it.

    `struct` is neither: p.133 reduces a struct array **by a field**, so its
    decision is the field's rather than the element's.
    """
    decided = set(property_reducers.OPERATIONS) | set(property_reducers.UNREDUCIBLE)
    assert set(array_properties.INNER_TYPES) - {"struct"} == decided


def test_the_editor_offers_exactly_the_operations_the_server_takes() -> None:
    """§190's drift guard, one declaration over (§349).

    `property-reducer.ts` names what the Reduce dialog offers per base type,
    and a mirror goes stale — so it is compared against **this module's** table
    rather than against a second copy of itself, which is the direction that
    catches an addition rather than only a disagreement.

    Nothing is left out in either direction here, unlike `array-property.ts`'s
    element types: an operation is a word in a dropdown, so there is no version
    of one the dialog cannot complete and no reason for it to offer one the
    server refuses.
    """
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "web", "src", "lib", "property-reducer.ts"),
        encoding="utf-8",
    ).read()
    listed = re.search(
        r"export const OPERATIONS: Record<string, string\[\]> = \{(.*?)\n\};",
        source, re.S,
    )
    assert listed, "OPERATIONS not found - has property-reducer.ts moved?"
    offered = {
        base: tuple(re.findall(r'"([a-z_]+)"', ops))
        for base, ops in re.findall(r"(\w+): \[(.*?)\]", listed.group(1))
    }
    assert offered, "OPERATIONS parsed as empty"
    assert offered == property_reducers.OPERATIONS, (
        "the editor's reducer table and the server's disagree: "
        f"editor {offered}, server {property_reducers.OPERATIONS}"
    )


def test_every_operation_the_editor_offers_has_words_to_show() -> None:
    """The other half of the table, and the half a drift guard on `OPERATIONS`
    alone would miss: a dropdown whose label map is short by one renders that
    row as `true_first`, which is the API's spelling and nobody's sentence."""
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "web", "src", "lib", "property-reducer.ts"),
        encoding="utf-8",
    ).read()
    listed = re.search(
        r"export const OPERATION_LABELS: Record<string, string> = \{(.*?)\n\};",
        source, re.S,
    )
    assert listed, "OPERATION_LABELS not found"
    labelled = set(re.findall(r"^\s*(\w+):", listed.group(1), re.M))
    assert labelled == set(property_reducers.ALL_OPERATIONS), (
        f"labelled {sorted(labelled)}, "
        f"server has {sorted(property_reducers.ALL_OPERATIONS)}"
    )


# ---- p.133's struct arrays ---------------------------------------------------
def test_a_struct_array_reduces_by_a_field_and_says_so_when_it_does_not() -> None:
    """> "Reducers function on struct arrays based on a specific field within
    > the struct, **not the struct itself**." (p.133)"""
    said = refusal([{"operation": "latest"}], array_of="struct", fields=INSPECTION)
    assert "which struct field" in said and "p.133" in said


def test_a_struct_arrays_operation_is_the_fields_and_not_the_elements() -> None:
    """The distinction p.132's last row makes: "Depends on the base type of the
    struct field". Reducing by `on` takes a date's operations and reducing by
    `score` takes an integer's, in the same property."""
    assert parse([{"operation": "latest", "field": "on"}],
                 array_of="struct", fields=INSPECTION) == [
        {"operation": "latest", "field": "on"}
    ]
    assert parse([{"operation": "highest", "field": "score"}],
                 array_of="struct", fields=INSPECTION) == [
        {"operation": "highest", "field": "score"}
    ]
    # And the mismatch is caught against the *field*, which is the assertion
    # that fails if the element type were consulted instead.
    said = refusal([{"operation": "latest", "field": "score"}],
                   array_of="struct", fields=INSPECTION)
    assert "highest or lowest" in said


def test_a_field_that_is_not_declared_is_refused_naming_what_is() -> None:
    said = refusal([{"operation": "latest", "field": "when"}],
                   array_of="struct", fields=INSPECTION)
    assert "'when'" in said and "on" in said and "score" in said


def test_a_field_p132_cannot_order_is_refused_like_an_element_would_be() -> None:
    """The geopoint field is in `INSPECTION` for exactly this: p.132's
    unsupported list reaches inside a struct, and a declaration that named it
    would produce a column that is blank on every row."""
    said = refusal([{"operation": "first", "field": "where"}],
                   array_of="struct", fields=INSPECTION)
    assert "'where'" in said and "geopoint" in said


def test_a_field_on_an_array_that_has_no_fields_is_refused() -> None:
    """The other direction, which is the pairing again: an array of dates has
    no fields, so a reducer naming one is a claim nothing reads."""
    said = refusal([{"operation": "latest", "field": "on"}], array_of="date")
    assert "array of date" in said and "p.133" in said


def test_a_second_reducer_over_the_same_basis_cannot_break_a_tie() -> None:
    """p.133 gives multiple reducers exactly one job — "to handle tie-breaking
    scenarios" — and two elements tied on a basis are tied on it whichever
    operation asks. Stored, the second would be a declaration that provably
    does nothing (§213); refused, it is the one sentence that says why.

    Both shapes: the same struct field twice, and any second reducer on a
    non-struct array, where the element itself is the only basis there is."""
    said = refusal([{"operation": "latest", "field": "on"},
                    {"operation": "earliest", "field": "on"}],
                   array_of="struct", fields=INSPECTION)
    assert "'on' again" in said

    said = refusal([{"operation": "latest"}, {"operation": "earliest"}])
    assert "the element again" in said


def test_two_reducers_over_different_fields_are_p133s_own_example() -> None:
    assert parse([{"operation": "latest", "field": "on"},
                  {"operation": "highest", "field": "score"}],
                 array_of="struct", fields=INSPECTION) == [
        {"operation": "latest", "field": "on"},
        {"operation": "highest", "field": "score"},
    ]


def test_a_reducer_list_that_is_not_a_list_is_refused() -> None:
    assert "must be a list" in refusal({"operation": "latest"})
    assert "not an object" in refusal(["latest"])
    assert "unknown keys" in refusal([{"operation": "latest", "sort": "asc"}])


# ---- the reduction -----------------------------------------------------------
def reduce(value, reducers):
    return property_reducers.reduce(value, reducers)


LATEST = [{"operation": "latest", "field": None}]
EARLIEST = [{"operation": "earliest", "field": None}]


def test_latest_and_earliest_pick_the_ends_of_a_date_array() -> None:
    dates = ["2024-01-05", "2024-03-09", "2023-11-02"]
    assert reduce(dates, LATEST) == "2024-03-09"
    assert reduce(dates, EARLIEST) == "2023-11-02"


def test_latest_is_about_time_and_not_about_text() -> None:
    """**The negative control for the whole vocabulary decision.** Both values
    are ISO-8601 and the one that sorts *later as text* is the one that happened
    *earlier*: `23:00+05:00` is 18:00 UTC and `20:00+00:00` is 20:00 UTC. A
    `max()` over the strings — the obvious implementation, and the one every
    other ordering in this platform uses — answers with the first.

    Migration 0029 is why both shapes can be in one array: one timestamp type,
    with the offset preserved when the value has one.
    """
    stamps = ["2024-03-01T23:00:00+05:00", "2024-03-01T20:00:00+00:00"]
    assert reduce(stamps, LATEST) == "2024-03-01T20:00:00+00:00"
    assert reduce(stamps, EARLIEST) == "2024-03-01T23:00:00+05:00"
    # And a naive value is read as UTC rather than crashing the read — Python
    # refuses to compare an aware datetime with a naive one at all.
    mixed = ["2024-03-01T20:00:00+00:00", "2024-03-01T21:00:00"]
    assert reduce(mixed, LATEST) == "2024-03-01T21:00:00"


def test_highest_is_about_number_and_not_about_text() -> None:
    """The same control one category over: `"9"` sorts above `"10"` as text and
    is the smaller number. The array holds strings because a synced column
    can — `property_values` coerces on the way in, and a property retyped after
    the fact leaves what was already there."""
    assert reduce([1, 10, 9], [{"operation": "highest"}]) == 10
    assert reduce(["1", "10", "9"], [{"operation": "highest"}]) == "10"
    assert reduce([1, 10, 9], [{"operation": "lowest"}]) == 1


def test_first_and_last_are_lexicographic_because_p132_says_so() -> None:
    assert reduce(["pear", "apple", "fig"], [{"operation": "first"}]) == "apple"
    assert reduce(["pear", "apple", "fig"], [{"operation": "last"}]) == "pear"


def test_true_first_and_false_first_prefer_their_own_value() -> None:
    assert reduce([False, True, False], [{"operation": "true_first"}]) is True
    assert reduce([True, False, True], [{"operation": "false_first"}]) is False
    # And when the array holds only one of them, that is the answer rather than
    # nothing: p.131 reduces to "a single value **in** the array".
    assert reduce([False, False], [{"operation": "true_first"}]) is False


def test_a_struct_array_reduces_to_the_element_and_not_to_the_field() -> None:
    """p.131's own words: "a single value **in** the array". Reducing a list of
    inspections by their date answers with the whole inspection — a caller
    given only the date could never get back to the score."""
    stops = [
        {"on": "2024-01-05", "score": 3},
        {"on": "2024-03-09", "score": 7},
    ]
    assert reduce(stops, [{"operation": "latest", "field": "on"}]) == {
        "on": "2024-03-09", "score": 7,
    }


def test_the_second_reducer_breaks_the_tie_the_first_one_left() -> None:
    """p.133's whole reason for a list. Two inspections on the same day, and
    the date reducer cannot choose between them."""
    stops = [
        {"on": "2024-03-09", "score": 3},
        {"on": "2024-03-09", "score": 7},
        {"on": "2024-01-05", "score": 9},
    ]
    reducers = [{"operation": "latest", "field": "on"},
                {"operation": "highest", "field": "score"}]
    assert reduce(stops, reducers) == {"on": "2024-03-09", "score": 7}
    # The negative control: the first reducer still decides. Score 9 is the
    # highest in the array and belongs to the wrong day.
    assert reduce(stops, reducers)["score"] != 9


def test_an_element_missing_the_field_cannot_be_the_latest_anything() -> None:
    """The case that actually happens on a struct array, and the reason
    `reduce` refuses rather than raises: a read path that threw would turn one
    incomplete element into a blank page."""
    stops = [{"score": 7}, {"on": "2024-01-05", "score": 3}]
    assert reduce(stops, [{"operation": "latest", "field": "on"}]) == {
        "on": "2024-01-05", "score": 3,
    }


def test_a_reducer_nothing_is_eligible_for_says_nothing() -> None:
    """Rather than picking whichever element the store happened to return
    first, which would look like an answer."""
    assert reduce([{"score": 7}, {"score": 3}],
                  [{"operation": "latest", "field": "on"}]) is None
    # Values that cannot be read as what the operation compares are the same
    # case — a property retyped after the fact, not a crash.
    assert reduce(["not a date"], LATEST) is None


def test_there_is_nothing_to_reduce_without_an_array_or_a_reducer() -> None:
    assert reduce([], LATEST) is None
    assert reduce(None, LATEST) is None
    assert reduce("2024-01-05", LATEST) is None
    assert reduce(["2024-01-05"], []) is None
    assert reduce(["2024-01-05"], None) is None


def test_reduce_all_leaves_out_what_has_no_answer() -> None:
    """`name in reduced` is the question a caller has, and a null would be
    indistinguishable from an element whose value is null."""
    values = {"dates": ["2024-01-05", "2024-03-09"], "empty": [], "plain": "x"}
    assert property_reducers.reduce_all(
        values, {"dates": LATEST, "empty": LATEST, "plain": LATEST}
    ) == {"dates": "2024-03-09"}
    assert property_reducers.reduce_all(values, {}) == {}
    assert property_reducers.reduce_all(values, None) == {}


# ---- through the API ---------------------------------------------------------
def make_type(client: TestClient, fx: Fixture, tag: str, properties) -> str:
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"insp_{tag}", "display_name": f"Inspected {tag}",
              "properties": properties, "title_property": "code"},
    )
    assert made.status_code == 201, made.text
    return made.json()["id"]


DATED = [
    {"api_name": "code", "data_type": "string"},
    {"api_name": "dates", "data_type": "array", "array_of": "date",
     "reducers": [{"operation": "latest"}]},
]


def test_an_object_type_round_trips_a_reducer(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    type_id = make_type(client, fx, tag, DATED)
    detail = client.get(f"{wbase(fx)}/object-types/{type_id}",
                        headers=hdr(fx.editor_sub)).json()
    dates = next(p for p in detail["properties"] if p["api_name"] == "dates")
    assert dates["reducers"] == [{"operation": "latest", "field": None}]
    # And every other property answers null, so "declares none" and "could not
    # have any" stay tellable apart.
    code = next(p for p in detail["properties"] if p["api_name"] == "code")
    assert code["reducers"] is None


def test_an_edit_keeps_the_reducer_because_it_travels_with_the_property(
    client: TestClient, fx: Fixture
) -> None:
    """0028 deletes every property row on an edit and writes them again, so a
    column the PATCH body does not carry comes back as its default.
    `struct_fields` learned that in §245 and `array_of` in §346; this is the
    same column one more over."""
    tag = uuid.uuid4().hex[:6]
    type_id = make_type(client, fx, tag, DATED)
    edited = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": "Renamed", "properties": DATED},
    )
    assert edited.status_code == 200, edited.text
    detail = client.get(f"{wbase(fx)}/object-types/{type_id}",
                        headers=hdr(fx.editor_sub)).json()
    dates = next(p for p in detail["properties"] if p["api_name"] == "dates")
    assert dates["reducers"] == [{"operation": "latest", "field": None}]


def test_a_restored_version_brings_its_reducers_back(
    client: TestClient, fx: Fixture
) -> None:
    """db 0028: a version snapshot has to record what the type *was*, and a
    column missing from `jsonb_build_object` is one the restore silently drops
    — the type comes back looking right and reducing nothing.

    **Found by a sweep, and it is the one survivor the suite had.** Every other
    path this column travels was already guarded; the snapshot is the one that
    only fails on a restore, which no test had asked for. The same shape is
    open one column over for `array_of` and `struct_fields`, whose units tested
    the save and the export and not this.
    """
    tag = uuid.uuid4().hex[:6]
    type_id = make_type(client, fx, tag, DATED)
    without = [DATED[0], {k: v for k, v in DATED[1].items() if k != "reducers"}]
    edited = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": f"Inspected {tag}", "properties": without},
    )
    assert edited.status_code == 200, edited.text
    detail = client.get(f"{wbase(fx)}/object-types/{type_id}",
                        headers=hdr(fx.editor_sub)).json()
    # The premise: the edit really did take it away, so the restore below has
    # something to bring back.
    assert next(p for p in detail["properties"]
                if p["api_name"] == "dates")["reducers"] is None

    versions = client.get(f"{wbase(fx)}/object-types/{type_id}/versions",
                          headers=hdr(fx.editor_sub)).json()
    first = min(v["version_number"] for v in versions)
    restored = client.post(
        f"{wbase(fx)}/object-types/{type_id}/versions/{first}/restore",
        headers=hdr(fx.editor_sub), json={"acknowledge_breaking": True},
    )
    assert restored.status_code == 200, restored.text
    dates = next(p for p in restored.json()["properties"]
                 if p["api_name"] == "dates")
    assert dates["reducers"] == [{"operation": "latest", "field": None}]
    # And the element type with it, which is the same hole one column over and
    # has been open since §346 — a restored array that forgot what it is a list
    # of is a declaration the server would refuse if anybody saved it.
    assert dates["array_of"] == "date"


def test_a_reducer_the_element_type_cannot_take_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"bad_{tag}", "display_name": f"Bad {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "tags", "data_type": "array",
                   "array_of": "string",
                   "reducers": [{"operation": "latest"}]},
              ]},
    )
    assert r.status_code == 422, r.text
    assert "first or last" in r.text


def test_a_reducer_travels_through_an_ontology_file(
    client: TestClient, fx: Fixture
) -> None:
    """p.65's round trip (§326). Nothing here needs resolving against the
    workspace it lands in — an operation is a word and a struct field is
    declared in the same property — but it still has to be *carried*, or an
    exported type re-imports as one that reduces nothing."""
    tag = uuid.uuid4().hex[:6]
    make_type(client, fx, tag, DATED)
    document = client.get(f"{wbase(fx)}/ontology-export",
                          headers=hdr(fx.editor_sub)).json()
    exported = next(t for t in document["object_types"]
                    if t["api_name"] == f"insp_{tag}")
    dates = next(p for p in exported["properties"] if p["api_name"] == "dates")
    assert dates["reducers"] == [{"operation": "latest", "field": None}]

    planned = client.post(f"{wbase(fx)}/ontology-import/plan",
                          headers=hdr(fx.editor_sub), json={"document": document})
    assert planned.status_code == 200, planned.text
    assert f"insp_{tag}" in planned.json()["sections"]["object_types"]["unchanged"]


#: Two arrays, one reduced and one not, in a workspace where the reduced one's
#: text order and date order disagree — "2024-01-05" sorts last as text and
#: "2024-03-09" is the later date, so a route that reduced by the wrong
#: comparison would be visible in the assertion rather than in a comment.
INSPECTED = (
    b"key,dates,tags\n"
    b'I1,"[""2024-03-09"",""2024-01-05""]","[""beta"",""alpha""]"\n'
)


def test_a_reducer_reaches_a_page_of_instances(
    client: TestClient, fx: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """**The wiring, which the pure tests cannot speak for.** `reduce` is
    tested directly and `parse` is tested directly; what neither says is
    whether the *route* reads the declarations and hands the array over. That
    is exactly the gap §346's sweep found twice, in `coerce_rows` and
    `field_for`, and it is why p.131's sentence is about a table.

    Three claims in one read, because they are one read: the reduced value is
    there, **the full array is still there beside it** (p.131 keeps it
    accessible and has applications show it on hover), and a property with no
    reducer is absent from `reduced` rather than present as null.
    """
    from src.routes import datasets as ds_routes
    from src.services.storage import LocalStorageGateway

    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("reducer-storage")))
    )
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Inspected {tag}"},
        files={"file": ("inspected.csv", io.BytesIO(INSPECTED), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text

    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"read_{tag}", "display_name": f"Read {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "dates", "data_type": "array",
                   "array_of": "date",
                   "reducers": [{"operation": "latest"}]},
                  {"api_name": "tags", "data_type": "array",
                   "array_of": "string"},
              ],
              "title_property": "key"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]

    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "dates": "dates",
                                  "tags": "tags"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/"
        f"{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert synced.status_code == 200, synced.text

    listed = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                        headers=hdr(fx.viewer_sub)).json()
    item = listed["items"][0]
    assert item["reduced"] == {"dates": "2024-03-09"}
    # p.131: reduction "does not change the underlying property type or
    # property data stored". Both arrives, and this is the assertion that fails
    # if a later change decides to substitute the reduced value instead.
    assert item["properties"]["dates"] == ["2024-03-09", "2024-01-05"]
    assert item["properties"]["tags"] == ["beta", "alpha"]

    # The single-object read answers the same way — p.131's reduced value is
    # for "a table or application", and the object's own page is the other one.
    single = client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances/{item['id']}",
        headers=hdr(fx.viewer_sub),
    ).json()
    assert single["reduced"] == {"dates": "2024-03-09"}


def test_an_object_type_with_no_reducers_reduces_nothing(
    client: TestClient, fx: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """The negative control the test above needs to mean anything: a `reduced`
    that answered on every property would satisfy every assertion up there."""
    from src.routes import datasets as ds_routes
    from src.services.storage import LocalStorageGateway

    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("plain-storage")))
    )
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Plain {tag}"},
        files={"file": ("plain.csv", io.BytesIO(INSPECTED), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"plain_{tag}", "display_name": f"Plain {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "dates", "data_type": "array",
                   "array_of": "date"},
              ],
              "title_property": "key"},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "dates": "dates"}},
    )
    assert source.status_code == 201, source.text
    client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/"
        f"{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    listed = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                        headers=hdr(fx.viewer_sub)).json()
    assert listed["items"][0]["reduced"] == {}


# ---- p.132's interface sentence (§350) ---------------------------------------
def test_what_a_property_presents_to_an_interface() -> None:
    """> "Array properties require non-array types to satisfactorily implement
    > interface properties." (p.132)

    **The element type, because `reduce` answers with an element.** p.131 says
    "a single value *in* the array", so a reduced list of dates is a date —
    and a reduced list of *structs* is a struct, not the field it reduced by,
    which is the distinction p.133 draws and the one an implementation would
    otherwise get wrong in the direction that looks right.
    """
    presents = property_reducers.implements_as
    assert presents({"data_type": "string"}) == "string"
    assert presents({"data_type": "array", "array_of": "date",
                     "reducers": [{"operation": "latest", "field": None}]}) == "date"
    # p.133's struct array reduces *by* a field and answers with the element,
    # so what it presents is `struct` — which is itself not an interface type.
    assert presents({"data_type": "array", "array_of": "struct",
                     "reducers": [{"operation": "latest", "field": "on"}]}) == "struct"


def test_an_array_with_no_reducer_presents_as_an_array() -> None:
    """p.132's sentence doing its work rather than a fallback: there is no
    single value, so there is nothing a non-array interface property could be
    satisfied by. **This is the assertion the whole feature turns on** — if an
    unreduced array presented its element type, every array would silently
    satisfy an interface it cannot answer for.
    """
    presents = property_reducers.implements_as
    assert presents({"data_type": "array", "array_of": "date"}) == "array"
    assert presents({"data_type": "array", "array_of": "date",
                     "reducers": []}) == "array"
    assert presents({"data_type": "array", "array_of": "date",
                     "reducers": None}) == "array"


def test_a_reduced_array_implements_an_interface_property(
    client: TestClient, fx: Fixture
) -> None:
    """p.132 end to end, which is the wiring the pure test above cannot speak
    for: whether `set_implementations` builds its map through `implements_as`
    at all.

    The same object type twice — refused, then accepted after a reducer is
    added and nothing else changes. **That order is the test**: asserting only
    that the reduced one is accepted would pass against a build that never
    compared base types.
    """
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Inspectable{tag}", "display_name": f"Inspectable {tag}",
              "properties": [{"api_name": "last_checked", "data_type": "date"}]},
    )
    assert made.status_code == 201, made.text
    interface_id = made.json()["id"]

    unreduced = [
        {"api_name": "code", "data_type": "string"},
        {"api_name": "checks", "data_type": "array", "array_of": "date"},
    ]
    typed = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"insp_{tag}", "display_name": f"Inspected {tag}",
              "properties": unreduced, "title_property": "code"},
    )
    assert typed.status_code == 201, typed.text
    type_id = typed.json()["id"]

    def implement():
        return client.put(
            f"{wbase(fx)}/object-types/{type_id}/interfaces",
            headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface_id,
                   "property_mapping": {"last_checked": "checks"}}],
        )

    refused = implement()
    assert refused.status_code == 422, refused.text
    # The message names p.132 and the fix, because the fix is not "map a
    # different property" the way every other mismatch's is.
    assert "no reducer" in refused.text and "p.132" in refused.text, refused.text

    reduced = [
        {"api_name": "code", "data_type": "string"},
        {"api_name": "checks", "data_type": "array", "array_of": "date",
         "reducers": [{"operation": "latest"}]},
    ]
    edited = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": f"Inspected {tag}", "properties": reduced},
    )
    assert edited.status_code == 200, edited.text

    accepted = implement()
    assert accepted.status_code == 200, accepted.text
    held = client.get(f"{wbase(fx)}/object-types/{type_id}/interfaces",
                      headers=hdr(fx.viewer_sub)).json()
    assert [e["property_mapping"] for e in held] == [{"last_checked": "checks"}], held


def test_a_reduced_array_still_has_to_reduce_to_the_right_type(
    client: TestClient, fx: Fixture
) -> None:
    """The negative control the test above needs: a build that stopped checking
    base types once a reducer was present would satisfy every assertion up
    there. An array of *strings* reduces to a string, and a `date` interface
    property is still not satisfied by it.
    """
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": f"Dated{tag}", "display_name": f"Dated {tag}",
              "properties": [{"api_name": "last_checked", "data_type": "date"}]},
    )
    assert made.status_code == 201, made.text
    typed = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"tags_{tag}", "display_name": f"Tagged {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "tags", "data_type": "array",
                   "array_of": "string",
                   "reducers": [{"operation": "first"}]},
              ],
              "title_property": "code"},
    )
    assert typed.status_code == 201, typed.text
    r = client.put(
        f"{wbase(fx)}/object-types/{typed.json()['id']}/interfaces",
        headers=hdr(fx.editor_sub),
        json=[{"interface_id": made.json()["id"],
               "property_mapping": {"last_checked": "tags"}}],
    )
    assert r.status_code == 422, r.text
    # The *ordinary* mismatch message, not p.132's — this one is answered by
    # mapping a different property, and saying "no reducer" would be wrong.
    assert "base types must match" in r.text, r.text
    assert "no reducer" not in r.text, r.text
