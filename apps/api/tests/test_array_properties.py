"""The `array` property type (parity `docs/parity/ontology.md` §1.1; Foundry
`object-link-types` p.86, p.116, p.140; db 0087).

> "Array — valid as title key: Yes. Valid as primary key: No. **Array
>  properties cannot contain null elements.** If the inner type of the Array is
>  not a valid title property, the Array property also cannot be used as the
>  title property." (p.86)

> "**Array properties cannot be empty**: Setting an array property to required
>  ensures the presence of at least one item." (p.116)

**The label is the first one that does not name a type.** `integer` says
everything there is to know about what an `integer` property holds; `array`
says nothing until it says of what. So most of what is checked here is the
*pairing* — a declaration that says both things or neither — and the two write
paths agreeing about what an element may be.
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
from src.services import array_properties, property_values  # noqa: E402
from src.services import ontology as ontology_service  # noqa: E402

ADDRESS = [
    {"api_name": "street", "data_type": "string"},
    {"api_name": "floors", "data_type": "integer"},
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


def parse(array_of, data_type="array", name="tags"):
    return array_properties.parse(
        array_of, data_type=data_type, property_name=name)


# ---- the declaration (p.86) --------------------------------------------------
def test_an_element_type_is_normalised_so_what_is_stored_is_what_was_checked() -> None:
    assert parse("  string  ") == "string"


def test_an_array_that_does_not_say_what_of_is_refused() -> None:
    """Half a declaration. Without this the column takes NULL and every value
    written to the property is refused later by `_coerce_array`, naming a
    missing element type to somebody who is no longer looking at the form."""
    for nothing in (None, "", "   "):
        with pytest.raises(ValueError, match="does not say what of"):
            parse(nothing)


def test_a_non_array_carrying_an_element_type_is_refused_not_ignored() -> None:
    """The other direction, and it is a different mistake: an element type on a
    `string` is a claim nothing reads — db 0083's own argument about an object
    type on a string parameter. Ignoring it would store a property whose
    declaration disagrees with itself."""
    with pytest.raises(ValueError, match="cannot say what it is an array of"):
        parse("string", data_type="string")


def test_a_property_that_is_not_an_array_says_nothing() -> None:
    """The negative control for the two above: without it, a check that refused
    everything would pass both."""
    assert parse(None, data_type="string") is None
    assert parse("", data_type="integer") is None


def test_an_array_of_arrays_is_refused_in_its_own_words() -> None:
    """Foundry's scope is arrays of *base* types (p.86), and one column cannot
    hold a recursive declaration. Its own message rather than "unknown type",
    because it is the first thing somebody tries."""
    with pytest.raises(ValueError, match="array of arrays"):
        parse("array")


def test_a_time_series_element_is_refused() -> None:
    """A time series property's value is already a pointer to a table (decision
    0009, db 0047): the scalar on the instance is a series id. A list of series
    ids is not something p.127 describes, and the thing it could plausibly mean
    — several series on one object — is a different feature with its own
    table."""
    with pytest.raises(ValueError, match="cannot be an array of"):
        parse("time_series")


def test_the_element_types_are_foundrys_list_and_not_this_platforms() -> None:
    """**Checked against the thing it describes**, not a mirror of itself
    (§191). Foundry's scope is "arrays of any base type except Vector and Time
    series"; this platform has no Vector, so exactly two are absent and each
    has to state which side of the line it is on.

    Adding a property type later then fails here until somebody says whether an
    array may hold one.
    """
    assert array_properties.INNER_TYPES < ontology_service.PROPERTY_TYPES
    assert ontology_service.PROPERTY_TYPES - array_properties.INNER_TYPES == {
        "array",        # p.86's scope is base types; one column, no recursion
        "time_series",  # a series id is already a pointer to a table (db 0047)
    }


def test_a_struct_element_needs_nothing_new_to_say() -> None:
    """p.140 names "Struct Array" in as many words, and `struct_fields` already
    describes the *element* rather than the property (db 0064) — which is why
    the array type could carry it without a second column."""
    assert parse("struct") == "struct"


# ---- the value (p.86) --------------------------------------------------------
def coerce(value, array_of="string", fields=None):
    return property_values.coerce_property_value(
        "array", value, array_of=array_of, struct_fields=fields)


def test_every_element_is_coerced_by_the_declared_element_type() -> None:
    """One definition of what a value may be, not a second one for lists: an
    array of integers accepts exactly what an integer accepts."""
    assert coerce(["1", 2, 3.0], "integer") == [1, 2, 3]


def test_a_bad_element_is_refused_naming_its_position_and_its_type() -> None:
    """A list is identified by position and nothing else, so "an integer was
    expected" with no index is a message about a value nobody can find."""
    with pytest.raises(property_values.PropertyValueError,
                       match=r"element 1 \(integer\)"):
        coerce([1, "not a number"], "integer")


def test_a_null_element_is_refused_rather_than_dropped() -> None:
    """p.86, and a refusal rather than a filter: dropping the null would change
    the length of somebody's list without telling them, and positions are the
    only thing identifying an array's elements."""
    with pytest.raises(property_values.PropertyValueError, match="element 1 is null"):
        coerce(["a", None, "c"])


def test_an_empty_array_is_a_value_and_not_an_error() -> None:
    """p.116 makes emptiness a `required` question, and `coerce_property_value`
    is explicit that absence is not a type error. Two rules, two places."""
    assert coerce([]) == []


def test_an_array_value_that_is_not_a_list_is_refused() -> None:
    with pytest.raises(property_values.PropertyValueError, match="must be a list"):
        coerce({"nope": 1})


def test_an_array_cannot_be_read_without_its_element_type() -> None:
    """The mirror of the struct rule: passing the value through would be `json`
    behaviour under an array's name."""
    with pytest.raises(property_values.PropertyValueError,
                       match="without its property's element type"):
        coerce(["a"], None)


def test_an_array_of_structs_reads_each_element_against_the_fields() -> None:
    """p.140's "Struct Array". `struct_fields` describes the element, which is
    what db 0064's column already held — so this needed nothing new."""
    assert coerce(
        [{"street": "Main", "floors": "2"}, {"street": "High"}],
        "struct", ADDRESS,
    ) == [{"street": "Main", "floors": 2}, {"street": "High", "floors": None}]


def test_an_array_survives_a_round_trip_through_a_dataset_column() -> None:
    """The struct's argument (§245) and the attachment's (§39): write-back
    stores the value as JSON text in the column and the next sync reads that
    column back through here. An array that survived only until its source was
    re-synced would not work."""
    value = coerce(["alpha", "beta"])
    flat = property_values.column_value("array", value)
    assert isinstance(flat, str)
    assert coerce(flat) == value


def test_a_whole_syncs_worth_carries_the_element_types_with_the_labels() -> None:
    """`coerce_rows` is the sync path, and the one that would have been
    silently wrong: without the third map every array column in every sync
    would refuse, naming a missing declaration rather than a bad value."""
    rows = [("A1", {"tags": ["x", "y"], "counts": ["1", "2"]})]
    assert property_values.coerce_rows(
        rows,
        {"tags": "array", "counts": "array"},
        None,
        {"tags": "string", "counts": "integer"},
    ) == [("A1", {"tags": ["x", "y"], "counts": [1, 2]})]


# ---- p.116's emptiness rule --------------------------------------------------
def test_an_empty_array_fails_a_required_property() -> None:
    """> "You can use this object type property to validate that there are no
    > objects that have a null value for this property, **or an empty array if
    > it is an array property**." (p.116)

    **`is_missing` already said this**, written with p.116's quote in place and
    unreachable for want of an array property to reach it with. Asserted here
    because a rule nothing can exercise is a rule nothing holds."""
    assert ontology_service.is_missing([]) is True
    assert ontology_service.is_missing(["one"]) is False


# ---- through the API ---------------------------------------------------------
def test_an_object_type_round_trips_an_array_property(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"tagged_{tag}", "display_name": f"Tagged {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "tags", "data_type": "array",
                   "array_of": "string"},
              ],
              "title_property": "code"},
    )
    assert r.status_code == 201, r.text
    detail = client.get(
        f"{wbase(fx)}/object-types/{r.json()['id']}", headers=hdr(fx.editor_sub)
    ).json()
    tags = next(p for p in detail["properties"] if p["api_name"] == "tags")
    assert tags["array_of"] == "string"
    # And every other property answers `None`, so "holds nothing in particular"
    # and "is not an array" stay tellable apart.
    code = next(p for p in detail["properties"] if p["api_name"] == "code")
    assert code["array_of"] is None


def test_an_array_property_with_no_element_type_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"tagged_{tag}", "display_name": f"Tagged {tag}",
              "properties": [{"api_name": "tags", "data_type": "array"}]},
    )
    assert r.status_code == 422, r.text
    assert "does not say what of" in r.text


def test_an_edit_keeps_the_element_type_because_it_travels_with_the_property(
    client: TestClient, fx: Fixture
) -> None:
    """0028: an edit deletes every `object_type_properties` row and writes them
    again, so a field the PATCH body does not carry is written back as the
    column's default. `struct_fields` learned that the hard way (§245) and this
    is the same column one over."""
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"tagged_{tag}", "display_name": f"Tagged {tag}",
              "properties": [{"api_name": "tags", "data_type": "array",
                              "array_of": "integer"}]},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    edited = client.patch(
        f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
        json={"display_name": "Renamed",
              "properties": [{"api_name": "tags", "data_type": "array",
                              "array_of": "integer"}]},
    )
    assert edited.status_code == 200, edited.text
    detail = client.get(f"{wbase(fx)}/object-types/{type_id}",
                        headers=hdr(fx.editor_sub)).json()
    assert detail["properties"][0]["array_of"] == "integer"


def test_an_array_property_travels_through_an_ontology_file(
    client: TestClient, fx: Fixture
) -> None:
    """p.65's round trip (§326). The element type is name-based already — a
    base type's own label, not an id — but it still has to be *carried*, or an
    imported array property is a declaration that says nothing and the import
    refuses it."""
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"exp_{tag}", "display_name": f"Exported {tag}",
              "properties": [{"api_name": "tags", "data_type": "array",
                              "array_of": "string"}]},
    )
    assert made.status_code == 201, made.text

    document = client.get(f"{wbase(fx)}/ontology-export",
                          headers=hdr(fx.editor_sub)).json()
    exported = next(t for t in document["object_types"]
                    if t["api_name"] == f"exp_{tag}")
    assert exported["properties"][0]["array_of"] == "string"

    # And a straight re-import plans no change, which is the assertion that
    # says the exporter and the importer agree about what an array property is.
    planned = client.post(f"{wbase(fx)}/ontology-import/plan",
                          headers=hdr(fx.editor_sub),
                          json={"document": document})
    assert planned.status_code == 200, planned.text
    assert f"exp_{tag}" in planned.json()["sections"]["object_types"]["unchanged"]


def test_an_action_cannot_declare_an_array_parameter(
    client: TestClient, fx: Fixture
) -> None:
    """Storable so the schema and the editor agree, refused at save time where
    the person who typed it is still looking (§245's shape exactly). p.36's
    ObjectReference-list parameter is the ○ that will lift this."""
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"acted_{tag}", "display_name": f"Acted {tag}",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert made.status_code == 201, made.text
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": made.json()["id"], "api_name": f"act_{tag}",
              "display_name": "Act", "editable_properties": ["name"]},
    )
    assert action.status_code == 201, action.text
    refused = client.put(
        f"{wbase(fx)}/action-types/{action.json()['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [{"api_name": "tags", "display_name": "Tags",
                              "data_type": "array"}],
              "rules": [], "criteria": []},
    )
    assert refused.status_code == 422, refused.text
    assert "array parameter" in refused.text


def test_an_action_cannot_make_an_array_property_editable(
    client: TestClient, fx: Fixture
) -> None:
    """The other path into the same refusal (§245): p.30's create screen writes
    one parameter per editable property, so an array property chosen there
    would insert a parameter the definition PUT refuses a moment later — two
    answers to one question, and the one a person meets first would be
    silence."""
    tag = uuid.uuid4().hex[:6]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"acted_{tag}", "display_name": f"Acted {tag}",
              "properties": [{"api_name": "tags", "data_type": "array",
                              "array_of": "string"}]},
    )
    assert made.status_code == 201, made.text
    refused = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": made.json()["id"], "api_name": f"act_{tag}",
              "display_name": "Act", "editable_properties": ["tags"]},
    )
    assert refused.status_code == 422, refused.text
    assert "array parameter" in refused.text
