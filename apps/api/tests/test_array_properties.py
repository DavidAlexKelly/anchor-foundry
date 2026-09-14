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
from src.services import array_properties, property_values, struct_fields  # noqa: E402
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


def test_a_struct_element_is_accepted_as_an_element_type() -> None:
    """p.140 names "Struct Array" in as many words, and `struct_fields`
    describes the *element* rather than the property (db 0064) — which is why
    the array type carries it without a second column."""
    assert parse("struct") == "struct"


def test_an_array_of_structs_may_declare_the_elements_fields() -> None:
    """**§346 said p.140 "needed nothing new" and it was wrong by one line.**

    `struct_fields.parse` read the label alone, so it refused any non-`struct`
    property carrying fields — and an array of structs could not be declared at
    all. The claim came from `array_properties.parse` accepting `"struct"` as
    an element type, which it does; nothing had declared one *through the API*,
    and the test above cannot tell the two apart.

    Found by the browser test that tried to render one (§347), which is the
    layer that had to build the whole thing to ask its question.
    """
    assert struct_fields.parse(
        ADDRESS, data_type="array", property_name="stops", array_of="struct",
    ) == [
        {"api_name": "street", "display_name": "street", "description": "",
         "data_type": "string"},
        {"api_name": "floors", "display_name": "floors", "description": "",
         "data_type": "integer"},
    ]


def test_an_array_of_anything_else_still_cannot_have_struct_fields() -> None:
    """The negative control, and the rule §346 was reaching for: fields on an
    array of strings are a claim nothing reads, exactly as they are on a
    string."""
    with pytest.raises(struct_fields.StructFieldError,
                       match="cannot have struct fields"):
        struct_fields.parse(
            ADDRESS, data_type="array", property_name="tags",
            array_of="string",
        )


def test_an_array_of_structs_needs_at_least_one_field() -> None:
    """p.149's rule reaches the element too: it is the element that is the
    struct, and one with no fields is the same empty promise."""
    with pytest.raises(struct_fields.StructFieldError,
                       match="at least one field"):
        struct_fields.parse(
            None, data_type="array", property_name="stops", array_of="struct",
        )


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


def test_an_object_type_round_trips_an_array_of_structs(
    client: TestClient, fx: Fixture
) -> None:
    """p.140 through the API — the path that was broken, and the reason the
    pure test above is not enough on its own."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"stops_{tag}", "display_name": f"Stops {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "stops", "data_type": "array",
                   "array_of": "struct", "struct_fields": ADDRESS},
              ],
              "title_property": "code"},
    )
    assert r.status_code == 201, r.text
    detail = client.get(
        f"{wbase(fx)}/object-types/{r.json()['id']}", headers=hdr(fx.editor_sub)
    ).json()
    stops = next(p for p in detail["properties"] if p["api_name"] == "stops")
    assert stops["array_of"] == "struct"
    assert [f["api_name"] for f in stops["struct_fields"]] == ["street", "floors"]


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


# ---- the editor's list, against this one (§191) ------------------------------
def test_the_editor_offers_every_element_type_it_can_complete() -> None:
    """§190's drift guard, one type over (§347).

    `array-property.ts` names what the dialog offers as an element type, and a
    mirror goes stale — so it is compared against **the server's** list rather
    than against a second copy of itself, which is the direction that catches
    an addition rather than only a disagreement.

    One is absent and it is the editor's own reason rather than this module's:
    `attachment` needs an upload (§39) and the dialog has nowhere to put one,
    which is also why it is missing from the property dropdown.
    """
    import re

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    source = open(
        os.path.join(root, "web", "src", "lib", "array-property.ts"),
        encoding="utf-8",
    ).read()
    listed = re.search(
        r"export const ELEMENT_TYPES: PropertyDataType\[\] = \[(.*?)\];",
        source, re.S,
    )
    assert listed, "ELEMENT_TYPES not found - has array-property.ts moved?"
    offered = set(re.findall(r'"([a-z_]+)"', listed.group(1)))
    assert offered, "ELEMENT_TYPES parsed as empty"
    assert array_properties.INNER_TYPES - offered == {"attachment"}, (
        "an element type the server accepts and the editor does not offer has "
        "to be named here with a reason"
    )
    assert not offered - array_properties.INNER_TYPES, (
        f"the editor offers element types the server refuses: "
        f"{sorted(offered - array_properties.INNER_TYPES)}"
    )


# ---- through a sync (the wiring, not the functions) --------------------------
#: A list column as a CSV cell: JSON text, which is exactly what `column_value`
#: writes back and `_coerce_array` reads — so this is the same round trip a
#: write-back takes, arriving from the direction a real dataset does.
TAGGED = (
    b"key,tags,counts\n"
    b'T1,"[""alpha"",""beta""]","[""1"",""2""]"\n'
)


def test_a_sync_reads_an_array_column_against_its_element_type(
    client: TestClient, fx: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """**The wiring, which the functions above cannot speak for.**

    `coerce_rows` is tested directly and `field_for` is tested directly; what
    neither says is whether the *route* builds the element-type map and hands
    it over. A sweep found both halves of that unguarded — and the same gap has
    been open for `struct_fields` since §245, because that unit tested
    `coerce_rows` directly too.

    An integer element rather than a string, for the reason the mapping test
    now states: `string` is what an unread declaration falls back to, so an
    array of strings would look identical either way.
    """
    from src.routes import datasets as ds_routes
    from src.services.storage import LocalStorageGateway

    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("array-storage")))
    )
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Tagged {tag}"},
        files={"file": ("tagged.csv", io.BytesIO(TAGGED), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text

    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"synced_{tag}", "display_name": f"Synced {tag}",
              "properties": [
                  {"api_name": "key", "data_type": "string"},
                  {"api_name": "tags", "data_type": "array",
                   "array_of": "string"},
                  {"api_name": "counts", "data_type": "array",
                   "array_of": "integer"},
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
              "column_mappings": {"key": "key", "tags": "tags",
                                  "counts": "counts"}},
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
    held = listed["items"][0]["properties"]
    assert held["tags"] == ["alpha", "beta"]
    # **The integers are the assertion.** The column holds `["1","2"]` as text;
    # an element type that never reached the coercer would leave them strings,
    # which is what the sweep's mutant did.
    assert held["counts"] == [1, 2]


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
