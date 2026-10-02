"""Value types over arrays and structs (§681; `object-link-types` p.234).

> "Range: … For Array properties, the size of the array is constrained."
> "Array: Uniqueness: All elements of the array must be unique. Nested: A value
>  type constraint can be applied to the elements of the array. For example, a
>  regex constraint could be applied to every string in an array."
> "Struct: Element constraints: A mapping between a struct field identifier and
>  a value type reference, where the struct field identifier indicates the
>  struct component to which the referenced value type should be applied."
> (p.234)

Both base types arrived after the value types did (§245, §346), and until now
a value type over either could carry meaning and nothing else.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_value_types import (  # noqa: E402,F401
    client, fx, make_type, make_value_type, pbase, prop_of, read_type, wbase,
)
from src.services import value_constraints as vc  # noqa: E402

EMAIL = {"base_type": "string", "constraint": {"kind": "regex", "pattern": r"[a-z]+@example\.com"}}
# Fixed rather than random, so an order the code gets wrong cannot pass by luck.
REF = "00000000-0000-4000-8000-00000000000b"
OTHER = "00000000-0000-4000-8000-00000000000a"


# ---- pure ----------------------------------------------------------------------
def test_an_array_range_bounds_its_size() -> None:
    rule = vc.parse({"kind": "range", "minimum": 1, "maximum": 2}, base_type="array")
    assert rule == {"kind": "range", "minimum": 1, "maximum": 2}
    assert vc.violation(rule, "array", ["a"]) is None
    assert vc.violation(rule, "array", ["a", "b"]) is None
    assert vc.violation(rule, "array", []) == "0 items is below the minimum of 1"
    assert vc.violation(rule, "array", ["a", "b", "c"]) == "3 items is above the maximum of 2"
    assert vc.violation(rule, "array", "abc") == "'abc' is not a list"
    with pytest.raises(vc.ConstraintError, match="array size cannot be negative"):
        vc.parse({"kind": "range", "minimum": -1}, base_type="array")
    with pytest.raises(vc.ConstraintError, match="whole number"):
        vc.parse({"kind": "range", "minimum": 1.5}, base_type="array")


def test_unique_refuses_a_repeated_item() -> None:
    rule = vc.parse({"kind": "unique"}, base_type="array")
    assert rule == {"kind": "unique"}
    assert vc.violation(rule, "array", ["a", "b"]) is None
    assert vc.violation(rule, "array", ["a", "b", "a"]) == "'a' appears more than once"
    # A struct item compares by its contents, whatever order its keys arrive in.
    assert vc.violation(rule, "array", [{"x": 1, "y": 2}, {"y": 2, "x": 1}]) is not None
    assert vc.violation(rule, "array", [1, True]) is None
    assert vc.violation(rule, "array", 7) == "7 is not a list"
    with pytest.raises(vc.ConstraintError, match="unique constraint does not apply to a string"):
        vc.parse({"kind": "unique"}, base_type="string")


def test_nested_applies_a_value_type_to_every_item() -> None:
    rule = vc.parse({"kind": "nested", "value_type": REF.upper()}, base_type="array")
    assert rule == {"kind": "nested", "value_type": REF}
    assert vc.references(rule) == [REF]
    held = vc.resolve(rule, {REF: EMAIL})
    assert held["items"] == EMAIL
    assert vc.violation(held, "array", ["ada@example.com"]) is None
    assert vc.violation(held, "array", ["ada@example.com", "nope"]) == (
        r"item 2: 'nope' does not match [a-z]+@example\.com")
    assert vc.violation(held, "array", "ada@example.com") == "'ada@example.com' is not a list"
    # A reference that no longer resolves checks nothing.
    assert vc.resolve(rule, {}) == rule
    assert vc.violation(vc.resolve(rule, {}), "array", ["nope"]) is None
    with pytest.raises(vc.ConstraintError, match="names a value type by id"):
        vc.parse({"kind": "nested", "value_type": "email"}, base_type="array")
    with pytest.raises(vc.ConstraintError, match="does not apply to a struct"):
        vc.parse({"kind": "nested", "value_type": REF}, base_type="struct")


def test_elements_apply_a_value_type_to_each_named_field() -> None:
    rule = vc.parse({"kind": "elements", "fields": {"email": REF, "code": OTHER, "alt": REF}},
                    base_type="struct")
    assert rule == {"kind": "elements", "fields": {"email": REF, "code": OTHER, "alt": REF}}
    assert vc.references(rule) == [OTHER, REF], "each once, in order"
    held = vc.resolve(rule, {REF: EMAIL})
    assert held["resolved"] == {"email": EMAIL, "alt": EMAIL}, "the missing one is left out"
    # Every field is checked, not only the first.
    assert vc.violation(held, "struct", {"email": "ada@example.com", "alt": "nope"}) == (
        r"alt: 'nope' does not match [a-z]+@example\.com")
    assert vc.violation(held, "struct", {"email": "ada@example.com", "code": "x"}) is None
    assert vc.violation(held, "struct", {"email": "nope"}) == (
        r"email: 'nope' does not match [a-z]+@example\.com")
    # An absent field is not a violation, as an absent value is not.
    assert vc.violation(held, "struct", {"code": "x"}) is None
    assert vc.violation(held, "struct", ["email"]) == "['email'] is not a struct"
    for bad, why in (
        ({"kind": "elements", "fields": {}}, "at least one struct field"),
        ({"kind": "elements", "fields": {"Email": REF}}, "not a struct field identifier"),
        ({"kind": "elements", "fields": {"email": "x"}}, "names a value type by id"),
    ):
        with pytest.raises(vc.ConstraintError, match=why):
            vc.parse(bad, base_type="struct")
    with pytest.raises(vc.ConstraintError, match="at most 100 fields"):
        vc.parse({"kind": "elements", "fields": {f"f{i}": REF for i in range(101)}},
                 base_type="struct")
    with pytest.raises(vc.ConstraintError, match="does not apply to a array"):
        vc.parse({"kind": "elements", "fields": {"email": REF}}, base_type="array")


def test_each_says_what_it_does() -> None:
    names = {REF: "email"}
    assert vc.describe({"kind": "unique"}) == "no item twice"
    assert vc.describe({"kind": "nested", "value_type": REF}, names) == "each item is email"
    assert vc.describe({"kind": "nested", "value_type": REF}) == "each item is a deleted value type"
    assert vc.describe({"kind": "elements", "fields": {"work": REF, "home": REF}}, names) == (
        "home is email, work is email")
    assert vc.references(None) == []
    assert vc.references({"kind": "unique"}) == []
    assert vc.resolve({"kind": "unique"}, {REF: EMAIL}) == {"kind": "unique"}


# ---- end to end ------------------------------------------------------------------
def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows([header, *rows])
    return out.getvalue().encode()


def _sync(client: TestClient, fx: Fixture, type_id: str, body: bytes, mapping: dict) -> dict:
    r = client.post(f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
                    data={"name": f"Composite {uuid.uuid4().hex[:6]}"},
                    files={"file": ("rows.csv", io.BytesIO(body), "text/csv")})
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
                    json={"object_type_id": type_id, "dataset_id": r.json()["id"],
                          "primary_key_column": "id", "column_mappings": mapping})
    assert r.status_code == 201, r.text
    r = client.post(f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_an_array_of_emails_is_checked_item_by_item(client: TestClient, fx: Fixture) -> None:
    email = make_value_type(client, fx)
    emails = make_value_type(client, fx, api_name=f"emails_{uuid.uuid4().hex[:6]}",
                             base_type="array",
                             constraint={"kind": "nested", "value_type": email["id"]})
    assert emails["constraint_summary"] == f"each item is {email['api_name']}"
    created = make_type(client, fx, [
        {"api_name": "id", "data_type": "string"},
        {"api_name": "emails", "data_type": "array", "array_of": "string",
         "value_type_id": emails["id"]}])
    # The rule is the referenced type's, beside the reference.
    held = prop_of(read_type(client, fx, created["id"]), "emails")["value_constraint"]
    assert held["items"]["base_type"] == "string"
    result = _sync(client, fx, created["id"], _csv(["id", "emails"], [
        ["1", json.dumps(["ada@example.com"])],
        ["2", json.dumps(["grace@example.com", "not-an-email"])]]),
        {"id": "id", "emails": "emails"})
    assert result["upserted"] == 2
    assert result["constraint_violations"]["emails"]["count"] == 1
    assert "item 2" in result["constraint_violations"]["emails"]["example"]

    # p.230, one level down: a new version of the *item* type reaches the
    # array's properties without the array's value type changing.
    r = client.post(f"{wbase(fx)}/value-types/{email['id']}/versions",
                    headers=hdr(fx.editor_sub),
                    json={"constraint": {"kind": "regex", "pattern": "[a-z]+@other\\.org"}})
    assert r.status_code == 201, r.text
    held = prop_of(read_type(client, fx, created["id"]), "emails")["value_constraint"]
    assert held["items"]["constraint"]["pattern"] == "[a-z]+@other\\.org"
    r = client.get(f"{wbase(fx)}/value-types/{emails['id']}/versions", headers=hdr(fx.viewer_sub))
    assert [v["constraint_summary"] for v in r.json()] == [f"each item is {email['api_name']}"]

    # And the item type cannot be deleted from under it.
    r = client.delete(f"{wbase(fx)}/value-types/{email['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 409, r.text
    assert emails["api_name"] in r.text


def test_an_address_struct_checks_its_named_field(client: TestClient, fx: Fixture) -> None:
    email = make_value_type(client, fx)
    contact = make_value_type(client, fx, api_name=f"contact_{uuid.uuid4().hex[:6]}",
                              base_type="struct",
                              constraint={"kind": "elements", "fields": {"email": email["id"]}})
    fields = [{"api_name": "email", "data_type": "string"},
              {"api_name": "name", "data_type": "string"}]
    created = make_type(client, fx, [
        {"api_name": "id", "data_type": "string"},
        {"api_name": "who", "data_type": "struct", "struct_fields": fields,
         "value_type_id": contact["id"]}])
    result = _sync(client, fx, created["id"], _csv(["id", "who"], [
        ["1", json.dumps({"email": "ada@example.com", "name": "Ada"})],
        ["2", json.dumps({"email": "grace", "name": "Grace"})]]),
        {"id": "id", "who": "who"})
    assert result["constraint_violations"]["who"]["count"] == 1
    assert result["constraint_violations"]["who"]["example"].startswith("email: 'grace'")


def test_an_array_that_must_be_short_and_distinct(client: TestClient, fx: Fixture) -> None:
    tags = make_value_type(client, fx, api_name=f"tags_{uuid.uuid4().hex[:6]}",
                           base_type="array", constraint={"kind": "unique"})
    short = make_value_type(client, fx, api_name=f"short_{uuid.uuid4().hex[:6]}",
                            base_type="array", constraint={"kind": "range", "maximum": 2})
    assert short["constraint_summary"] == "at most 2"
    created = make_type(client, fx, [
        {"api_name": "id", "data_type": "string"},
        {"api_name": "tags", "data_type": "array", "array_of": "string", "value_type_id": tags["id"]},
        {"api_name": "top", "data_type": "array", "array_of": "integer", "value_type_id": short["id"]}])
    result = _sync(client, fx, created["id"], _csv(["id", "tags", "top"], [
        ["1", json.dumps(["a", "b"]), json.dumps([1, 2])],
        ["2", json.dumps(["a", "a"]), json.dumps([1, 2, 3])]]),
        {"id": "id", "tags": "tags", "top": "top"})
    assert result["constraint_violations"]["tags"]["count"] == 1
    assert result["constraint_violations"]["top"]["example"] == "3 items is above the maximum of 2"


def test_a_reference_must_be_a_scalar_value_type_here(client: TestClient, fx: Fixture) -> None:
    def create(constraint: dict, base_type: str = "array"):
        return client.post(f"{wbase(fx)}/value-types", headers=hdr(fx.editor_sub), json={
            "api_name": f"ref_{uuid.uuid4().hex[:6]}", "display_name": "Ref",
            "base_type": base_type, "constraint": constraint})

    r = create({"kind": "nested", "value_type": str(uuid.uuid4())})
    assert r.status_code == 422 and "no value type" in r.text, r.text
    listy = make_value_type(client, fx, api_name=f"listy_{uuid.uuid4().hex[:6]}",
                            base_type="array", constraint={"kind": "unique"})
    r = create({"kind": "nested", "value_type": listy["id"]})
    assert r.status_code == 422 and "is a array value type" in r.text, r.text
    r = create({"kind": "elements", "fields": {"x": listy["id"]}}, "struct")
    assert r.status_code == 422, r.text
    # The same check on a new version.
    r = client.post(f"{wbase(fx)}/value-types/{listy['id']}/versions",
                    headers=hdr(fx.editor_sub),
                    json={"constraint": {"kind": "nested", "value_type": listy["id"]}})
    assert r.status_code == 422, r.text


def test_what_is_applied_must_fit_what_the_property_holds(client: TestClient, fx: Fixture) -> None:
    email = make_value_type(client, fx)
    emails = make_value_type(client, fx, api_name=f"emails_{uuid.uuid4().hex[:6]}",
                             base_type="array",
                             constraint={"kind": "nested", "value_type": email["id"]})
    contact = make_value_type(client, fx, api_name=f"contact_{uuid.uuid4().hex[:6]}",
                              base_type="struct",
                              constraint={"kind": "elements", "fields": {"email": email["id"]}})

    def attempt(prop: dict):
        tag = uuid.uuid4().hex[:6]
        return client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
            "api_name": f"fit_{tag}", "display_name": f"Fit {tag}", "title_property": "id",
            "properties": [{"api_name": "id", "data_type": "string"}, prop]})

    r = attempt({"api_name": "nums", "data_type": "array", "array_of": "integer",
                 "value_type_id": emails["id"]})
    assert r.status_code == 422 and "this array holds integer" in r.text, r.text
    r = attempt({"api_name": "who", "data_type": "struct", "value_type_id": contact["id"],
                 "struct_fields": [{"api_name": "email", "data_type": "integer"}]})
    assert r.status_code == 422 and "'email' is integer" in r.text, r.text
    r = attempt({"api_name": "who", "data_type": "struct", "value_type_id": contact["id"],
                 "struct_fields": [{"api_name": "name", "data_type": "string"}]})
    assert r.status_code == 422 and "has no such field" in r.text, r.text
