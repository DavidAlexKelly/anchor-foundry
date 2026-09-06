"""The `struct` property type (parity `docs/parity/ontology.md` build order
item 7; Foundry `object-link-types` p.149-150, `ontology` p.58-59; db 0064).

> "A struct is an Ontology property base type that allows users to create
> schema-based properties with multiple fields." (`object-link-types` p.149)

**The schema is the whole feature.** A `json` property has accepted the same
*values* since migration 0003; what a struct adds is the property saying what
the value is supposed to contain. So almost every test here is about a claim
being enforced rather than about a value being stored - p.149's four
constraints, the two write paths agreeing about them, and the three places
that decline to carry a struct saying so rather than half-working.
"""
from __future__ import annotations

import os
import pathlib
import re
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import instance_mapping, property_values, struct_fields  # noqa: E402
from src.services import ontology as ontology_service  # noqa: E402

ADDRESS = [
    {"api_name": "street", "data_type": "string"},
    {"api_name": "postal_code", "data_type": "string"},
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


# ---- the declaration (p.149) -------------------------------------------------
def test_a_declaration_is_normalised_so_what_is_stored_is_what_was_checked() -> None:
    """`value_format.parse`'s rule, one property type over: a declaration
    validated and then written from the untouched input would be two things
    that only look like one. A field with no display name gets its own name,
    because a struct field is a thing a person reads."""
    assert struct_fields.parse(
        [{"api_name": "street", "data_type": "string"}],
        data_type="struct", property_name="address",
    ) == [{"api_name": "street", "display_name": "street",
           "description": "", "data_type": "string"}]


def test_the_declared_order_is_kept() -> None:
    """p.154 builds a struct one Add field at a time, so the order is the
    author's statement about the value and not an implementation detail. It is
    also what `_coerce_struct` rebuilds a value in, so losing it here would
    lose it everywhere."""
    parsed = struct_fields.parse(ADDRESS, data_type="struct", property_name="address")
    assert [f["api_name"] for f in parsed] == ["street", "postal_code", "floors"]


def test_a_struct_needs_at_least_one_field() -> None:
    """p.149: "Structs must have at least 1 field." A struct with none is a
    `json` property with a more specific name, and the name would be a claim
    nothing behind it could keep."""
    for empty in (None, []):
        with pytest.raises(struct_fields.StructFieldError, match="at least one field"):
            struct_fields.parse(empty, data_type="struct", property_name="address")


def test_a_struct_field_cannot_itself_be_a_struct_and_says_so() -> None:
    """p.149: "Structs have a depth of one and cannot be nested."

    **Its own message, not "unknown type".** `ontology` p.58's own worked
    example is an address with five fields, and somebody who has read it will
    try nesting one; a refusal that read like a typo would send them looking
    for the right spelling of a thing that does not exist.
    """
    with pytest.raises(struct_fields.StructFieldError, match="cannot be nested"):
        struct_fields.parse(
            [{"api_name": "inner", "data_type": "struct"}],
            data_type="struct", property_name="address",
        )


def test_the_field_types_are_p149s_list_and_not_this_platforms() -> None:
    """p.149 names twelve SQL types and this platform's property types are a
    wider set. The three that are absent are each absent for a *different*
    reason, named in `struct_fields.FIELD_TYPES`, so this asserts the whole
    complement rather than one example: adding a property type later then has
    to state which side of the line it falls on instead of silently landing on
    one.

    §191's rule, applied where it actually bites - the list is checked against
    the thing it describes (`ontology.PROPERTY_TYPES`), not against a mirror of
    itself.
    """
    assert set(struct_fields.FIELD_TYPES) < ontology_service.PROPERTY_TYPES
    assert set(ontology_service.PROPERTY_TYPES) - set(struct_fields.FIELD_TYPES) == {
        "struct",        # p.149: depth of one
        "json",          # the untyped escape hatch, so a field holding one is
                         # nesting with the type system switched off
        "attachment",    # a reference the upload path issues per property
        "time_series",   # `object_type_series` names a property, not a field
    }


def test_a_field_type_outside_that_list_is_refused_naming_the_list() -> None:
    with pytest.raises(struct_fields.StructFieldError, match="expected one of"):
        struct_fields.parse(
            [{"api_name": "blob", "data_type": "json"}],
            data_type="struct", property_name="address",
        )


def test_field_names_follow_the_property_naming_rule_and_are_unique() -> None:
    for bad in (
        [{"api_name": "Street", "data_type": "string"}],
        [{"api_name": "", "data_type": "string"}],
        [{"api_name": "street", "data_type": "string"},
         {"api_name": "street", "data_type": "integer"}],
    ):
        with pytest.raises(struct_fields.StructFieldError):
            struct_fields.parse(bad, data_type="struct", property_name="address")


def test_an_unknown_key_in_a_field_is_refused_rather_than_dropped() -> None:
    """A key nobody reads is a setting somebody thinks they made. The value
    side drops what it does not know (see below) because a *dataset* may
    legitimately carry more than the ontology declares; a declaration is
    written by hand and has no such excuse."""
    with pytest.raises(struct_fields.StructFieldError, match="unknown keys"):
        struct_fields.parse(
            [{"api_name": "street", "data_type": "string", "reducer": "latest"}],
            data_type="struct", property_name="address",
        )


def test_a_non_struct_property_carrying_fields_is_refused_not_ignored() -> None:
    """Silently dropping it would leave somebody looking at a saved definition
    that does not contain what they typed - and looking for the field they
    declared, on a property that could never have had one."""
    with pytest.raises(struct_fields.StructFieldError, match="cannot have struct fields"):
        struct_fields.parse(ADDRESS, data_type="string", property_name="name")
    assert struct_fields.parse(None, data_type="string", property_name="name") is None
    assert struct_fields.parse([], data_type="string", property_name="name") is None


# ---- the value, against the declaration --------------------------------------
def test_each_field_is_coerced_by_its_own_declared_type() -> None:
    """The point of the type. A struct read as `json` would store `"3"` for a
    field declared `integer`, and every reader would then have to guess."""
    assert property_values.coerce_property_value(
        "struct", {"street": "Main", "postal_code": 90210, "floors": "3"},
        struct_fields=ADDRESS,
    ) == {"street": "Main", "postal_code": "90210", "floors": 3}


def test_a_bad_field_value_is_refused_naming_the_field_and_its_type() -> None:
    with pytest.raises(property_values.PropertyValueError) as exc:
        property_values.coerce_property_value(
            "struct", {"floors": "many"}, struct_fields=ADDRESS
        )
    assert "floors" in str(exc.value) and "integer" in str(exc.value)


def test_the_result_holds_the_declared_fields_in_the_declared_order() -> None:
    """Not the order the value happened to arrive in. Two rows of one dataset
    can hold their keys in different orders - JSON objects and Parquet structs
    both allow it - and a stored shape that depended on that would push the
    difference onto every reader."""
    out = property_values.coerce_property_value(
        "struct", {"floors": 2, "street": "Main"}, struct_fields=ADDRESS
    )
    assert list(out) == ["street", "postal_code", "floors"]


def test_a_missing_field_is_none_rather_than_an_error() -> None:
    """`coerce_property_value`'s own rule about absence: `required` is a
    separate concern the ontology already models, and a struct field has no way
    to say it yet."""
    assert property_values.coerce_property_value(
        "struct", {"street": "Main"}, struct_fields=ADDRESS
    ) == {"street": "Main", "postal_code": None, "floors": None}


def test_an_undeclared_key_is_dropped_rather_than_refused() -> None:
    """A struct is a schema over a column the way an object type is a schema
    over a table, and this is the same rule one level down: the sync reads the
    columns the mapping names and ignores the rest. Refusing here would make
    adding a field to a source dataset break every object of that type."""
    assert property_values.coerce_property_value(
        "struct", {"street": "Main", "county": "Greater London"},
        struct_fields=ADDRESS,
    ) == {"street": "Main", "postal_code": None, "floors": None}


def test_a_struct_cannot_be_read_without_its_declaration() -> None:
    """Passing the value through would be `json` behaviour under a struct's
    name - which is exactly the difference this type exists to make."""
    with pytest.raises(property_values.PropertyValueError, match="declared fields"):
        property_values.coerce_property_value("struct", {"street": "Main"})


def test_a_struct_survives_a_round_trip_through_a_dataset_column() -> None:
    """The attachment's argument (§39), for the same reason: write-back stores
    the value as JSON text in the column and the next sync reads that column
    back through here. Accepting only a mapping would mean a struct written by
    an edit survived exactly until its source was re-synced."""
    value = property_values.coerce_property_value(
        "struct", {"street": "Main", "postal_code": "90210", "floors": 3},
        struct_fields=ADDRESS,
    )
    flat = property_values.column_value("struct", value)
    assert isinstance(flat, str)
    assert property_values.coerce_property_value(
        "struct", flat, struct_fields=ADDRESS
    ) == value


def test_a_whole_syncs_worth_carries_the_declarations_with_the_types() -> None:
    """`coerce_rows` is the sync path, and it is the one that would have been
    silently wrong: without the second mapping every struct column in every
    sync would refuse, naming a missing declaration rather than a bad value."""
    rows = [("A1", {"address": {"street": "Main", "floors": "2"}})]
    assert property_values.coerce_rows(
        rows, {"address": "struct"}, {"address": ADDRESS}
    ) == [("A1", {"address": {"street": "Main", "postal_code": None, "floors": 2}})]


def test_the_builder_offers_every_field_type_the_server_accepts() -> None:
    """§190's drift guard, one type over.

    `lib/struct-fields.ts` carries a copy of `FIELD_TYPES` so the dialog can
    draw a dropdown, and a copy is a thing that goes stale — §191's lesson,
    which this repo has now paid for five times. The two lists are compared by
    scanning the file, because there is no import that could do it: one is
    Python and one is TypeScript, and nothing in either build reads the other.

    **Both directions.** A type the server accepts and the dialog does not
    offer is a field nobody can declare through the product; one the dialog
    offers and the server refuses is a dropdown entry whose only outcome is a
    422 after the form is filled in.
    """
    source = (
        pathlib.Path(__file__).resolve().parents[3]
        / "apps/web/src/lib/struct-fields.ts"
    ).read_text()
    match = re.search(
        r"export const FIELD_TYPES: PropertyDataType\[\] = \[(.*?)\];",
        source,
        re.S,
    )
    assert match, "FIELD_TYPES is no longer where this scan looks for it"
    offered = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert offered == set(struct_fields.FIELD_TYPES), (
        "the struct field types the builder offers and the ones the server "
        f"accepts have drifted: {sorted(offered ^ set(struct_fields.FIELD_TYPES))}"
    )


# ---- the stores (decision 0006) ----------------------------------------------
def test_a_struct_is_mapped_but_not_indexed_and_not_orderable() -> None:
    """p.150 lists Object Explorer's struct support with "struct field search
    is under development", and warns in the same breath that a query over an
    array of structs matches its fields independently rather than within one
    entry. So the source has not settled what a field filter means, and 0006 §6
    refuses to ship a comparison on one store before the other."""
    assert instance_mapping.field_for("struct") == {"type": "object", "enabled": False}
    assert "struct" not in instance_mapping.ORDERABLE_TYPES


# ---- the API round trip ------------------------------------------------------
def test_an_object_type_round_trips_a_struct_property(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"facility_{tag}", "display_name": f"Facility {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "address", "data_type": "struct",
                   "struct_fields": ADDRESS},
              ],
              "title_property": "code"},
    )
    assert r.status_code == 201, r.text
    detail = client.get(
        f"{wbase(fx)}/object-types/{r.json()['id']}", headers=hdr(fx.editor_sub)
    ).json()
    address = next(p for p in detail["properties"] if p["api_name"] == "address")
    assert [f["api_name"] for f in address["struct_fields"]] == [
        "street", "postal_code", "floors"
    ]
    # And every other property answers `None` rather than an empty list, so
    # "has no fields" and "is not a struct" stay tellable apart.
    code = next(p for p in detail["properties"] if p["api_name"] == "code")
    assert code["struct_fields"] is None


def test_a_struct_property_with_no_fields_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"facility_{tag}", "display_name": f"Facility {tag}",
              "properties": [{"api_name": "address", "data_type": "struct"}]},
    )
    assert r.status_code == 422, r.text
    assert "at least one field" in r.text


def test_an_edit_keeps_the_fields_because_they_travel_with_the_property(
    client: TestClient, fx: Fixture
) -> None:
    """0028: an edit deletes every `object_type_properties` row for the type
    and re-inserts the list it was given, so property ids do not survive one.
    That is the whole argument for `struct_fields` being a column rather than a
    child table - a child table keyed on the property id would be emptied by
    renaming a *neighbouring* property."""
    tag = uuid.uuid4().hex[:6]
    created = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"facility_{tag}", "display_name": f"Facility {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "address", "data_type": "struct",
                   "struct_fields": ADDRESS},
              ],
              "title_property": "code"},
    ).json()
    detail = client.get(
        f"{wbase(fx)}/object-types/{created['id']}", headers=hdr(fx.editor_sub)
    ).json()
    properties = [
        {k: p[k] for k in ("api_name", "display_name", "data_type", "struct_fields")}
        for p in detail["properties"]
    ]
    properties[0]["display_name"] = "Facility code"   # the *other* property
    r = client.patch(
        f"{wbase(fx)}/object-types/{created['id']}", headers=hdr(fx.editor_sub),
        json={"display_name": detail["display_name"], "properties": properties,
              "title_property": "code", "acknowledge_breaking": True},
    )
    assert r.status_code == 200, r.text
    after = client.get(
        f"{wbase(fx)}/object-types/{created['id']}", headers=hdr(fx.editor_sub)
    ).json()
    address = next(p for p in after["properties"] if p["api_name"] == "address")
    assert [f["api_name"] for f in address["struct_fields"]] == [
        "street", "postal_code", "floors"
    ]


# ---- the three refusals ------------------------------------------------------
def test_a_shared_property_cannot_be_a_struct(client: TestClient, fx: Fixture) -> None:
    """p.178's shared property is one *definition* edited in one place and
    shown everywhere it is attached; a struct's definition is its fields, and
    `shared_properties` has no column for them. Allowing it would mean two
    object types declaring different fields under one borrowed name, which is
    the opposite of the feature."""
    r = client.post(
        f"{wbase(fx)}/shared-properties", headers=hdr(fx.admin_sub),
        json={"api_name": f"addr_{uuid.uuid4().hex[:6]}", "display_name": "Address",
              "data_type": "struct"},
    )
    assert r.status_code == 422, r.text
    assert "shared property" in r.text


def test_an_action_cannot_make_a_struct_property_editable(
    client: TestClient, fx: Fixture
) -> None:
    """p.150 lists Actions among the applications that use structs, so this is
    a gap rather than a scope call - and it is refused *at save time*, where
    the person who typed it is still looking at it, rather than at click time
    in front of somebody who did not.

    Refused rather than offered-and-broken for §237's reason: `inputTypeFor`
    answers "text" for any type it does not name, so an allowed struct
    parameter would render as a box no viewer could ever fill in correctly.
    """
    tag = uuid.uuid4().hex[:6]
    type_id = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"facility_{tag}", "display_name": f"Facility {tag}",
              "properties": [
                  {"api_name": "code", "data_type": "string"},
                  {"api_name": "address", "data_type": "struct",
                   "struct_fields": ADDRESS},
              ],
              "title_property": "code"},
    ).json()["id"]
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": f"move_{tag}",
              "display_name": "Move", "editable_properties": ["address"]},
    )
    assert r.status_code == 422, r.text
    assert "struct" in r.text


def test_an_action_definition_cannot_declare_a_struct_parameter(
    client: TestClient, fx: Fixture
) -> None:
    """The same refusal on the other path. Two ways in, one answer - the shape
    §237 found when the Canvas action form grew a second renderer and the two
    disagreed about which types worked."""
    tag = uuid.uuid4().hex[:6]
    type_id = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"facility_{tag}", "display_name": f"Facility {tag}",
              "properties": [{"api_name": "code", "data_type": "string"}],
              "title_property": "code"},
    ).json()["id"]
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": f"rename_{tag}",
              "display_name": "Rename", "editable_properties": ["code"]},
    ).json()
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [{"api_name": "code", "display_name": "Code",
                              "data_type": "struct"}],
              "rules": [], "criteria": []},
    )
    assert r.status_code == 422, r.text
    assert "struct" in r.text
