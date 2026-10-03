"""A value type's status (§764; db 0151; Foundry `object-link-types` p.229,
p.253-256).

> "if you make breaking changes to the constraints and your value type has
> consumers, we recommend deprecating the current value type and creating a
> new one instead." (p.229)

The rules are the ones every ontology resource has (`ontology_status`), plus
what deprecating a value type has to mean for p.229's advice to work: what
uses it keeps it, and nothing new takes it.
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_value_types import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, make_type, make_value_type, prop_of, read_type, wbase,
)


def patch(client, fx, vt: dict, **body):
    return client.patch(f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.editor_sub),
                        json={"display_name": vt["display_name"], **body})


def deprecate(client, fx, vt: dict, **note) -> dict:
    r = patch(client, fx, vt, status="deprecated", deprecation=note or None)
    assert r.status_code == 200, r.text
    return r.json()


def editable(detail: dict) -> list[dict]:
    """What the editor sends back (`test_the_editor_can_save_back_what_it_read`)."""
    return [{k: v for k, v in p.items()
             if k not in ("id", "sort_order", "shared_property_api_name", "value_type_api_name",
                          "value_constraint", "effective_value_type_id")}
            for p in detail["properties"]]


def save_type(client, fx, type_id: str, properties: list[dict]):
    return client.patch(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.editor_sub),
                        json={"display_name": "Edited", "properties": properties,
                              "title_property": "name"})


def test_a_new_value_type_is_experimental_and_its_status_is_set_by_the_edit(client, fx) -> None:
    vt = make_value_type(client, fx)
    assert (vt["status"], vt["deprecation"]) == ("experimental", None)
    r = patch(client, fx, vt, status="active")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    # Left out, unchanged - a client from before §764 saving a description.
    r = patch(client, fx, vt, description="Still an email")
    assert (r.json()["status"], r.json()["description"]) == ("active", "Still an email")
    # p.255: `promoted` is for object types only.
    r = patch(client, fx, vt, status="promoted")
    assert r.status_code == 422, r.text
    assert "only to object types" in r.text


def test_an_active_value_type_cannot_be_deleted(client, fx) -> None:
    vt = make_value_type(client, fx)
    assert patch(client, fx, vt, status="active").status_code == 200
    r = client.delete(f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 422, r.text
    assert "cannot be deleted" in r.text and "p.256" in r.text
    deprecate(client, fx, vt)
    r = client.delete(f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 204, r.text


def test_the_deprecation_note_names_a_replacement_and_is_kept_until_undeprecated(
    client, fx
) -> None:
    old = make_value_type(client, fx)
    new = make_value_type(client, fx)
    got = deprecate(client, fx, old, reason="Breaking change", deadline="2027-01-31",
                    replacement_id=new["id"])
    assert got["deprecation"] == {"reason": "Breaking change", "deadline": "2027-01-31",
                                  "replacement_id": new["id"]}
    # Kept by a save that leaves it out while it stays deprecated.
    r = patch(client, fx, old, description="Old")
    assert r.json()["deprecation"]["replacement_id"] == new["id"]
    # Cleared by one that sends null.
    r = patch(client, fx, old, deprecation=None)
    assert (r.json()["status"], r.json()["deprecation"]) == ("deprecated", None)
    deprecate(client, fx, old, reason="Again")
    # And dropped when it stops being deprecated (p.254).
    r = patch(client, fx, old, status="active")
    assert (r.json()["status"], r.json()["deprecation"]) == ("active", None)
    # A note anywhere else is refused.
    r = patch(client, fx, old, deprecation={"reason": "no"})
    assert r.status_code == 422, r.text


def test_the_replacement_is_another_value_type_of_this_workspace(client, fx) -> None:
    vt = make_value_type(client, fx)
    r = patch(client, fx, vt, status="deprecated", deprecation={"replacement_id": vt["id"]})
    assert r.status_code == 422, r.text
    assert "its own replacement" in r.text
    r = patch(client, fx, vt, status="deprecated",
              deprecation={"replacement_id": str(uuid.uuid4())})
    assert r.status_code == 422, r.text
    assert "no value type" in r.text
    r = patch(client, fx, vt, status="deprecated", deprecation={"replacement_id": "nonsense"})
    assert r.status_code == 422, r.text
    assert "no value type" in r.text


def test_a_deprecated_value_type_keeps_its_properties_and_takes_no_new_ones(client, fx) -> None:
    vt = make_value_type(client, fx)
    new = make_value_type(client, fx)
    created = make_type(client, fx, [
        {"api_name": "name", "data_type": "string"},
        {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]},
        {"api_name": "backup", "data_type": "string"}])
    deprecate(client, fx, vt, replacement_id=new["id"])

    # The property that had it keeps it, through an unrelated save.
    props = editable(read_type(client, fx, created["id"]))
    r = save_type(client, fx, created["id"], props)
    assert r.status_code == 200, r.text
    assert prop_of(read_type(client, fx, created["id"]), "email")["value_type_id"] == vt["id"]

    # Another property of the same type does not take it.
    for p in props:
        if p["api_name"] == "backup":
            p["value_type_id"] = vt["id"]
    r = save_type(client, fx, created["id"], props)
    assert r.status_code == 422, r.text
    assert "backup" in r.text and "deprecated" in r.text and new["id"] in r.text

    # Nor does a new object type.
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"c_{uuid.uuid4().hex[:6]}", "display_name": "C",
        "properties": [{"api_name": "name", "data_type": "string"},
                       {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
        "title_property": "name"})
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text

    # Once it is no longer deprecated, it is taken again.
    assert patch(client, fx, vt, status="active").status_code == 200
    assert save_type(client, fx, created["id"], props).status_code == 200


def test_a_property_cannot_switch_to_a_deprecated_value_type(client, fx) -> None:
    """What the property already had is what it keeps - not any value type
    because it had one."""
    vt = make_value_type(client, fx)
    other = make_value_type(client, fx)
    created = make_type(client, fx, [
        {"api_name": "name", "data_type": "string"},
        {"api_name": "email", "data_type": "string", "value_type_id": other["id"]}])
    deprecate(client, fx, vt)
    props = editable(read_type(client, fx, created["id"]))
    for p in props:
        if p["api_name"] == "email":
            p["value_type_id"] = vt["id"]
    r = save_type(client, fx, created["id"], props)
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text


def test_a_property_moved_off_a_deprecated_value_type_cannot_move_back(client, fx) -> None:
    vt = make_value_type(client, fx)
    created = make_type(client, fx, [
        {"api_name": "name", "data_type": "string"},
        {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}])
    deprecate(client, fx, vt)
    props = editable(read_type(client, fx, created["id"]))
    for p in props:
        p["value_type_id"] = None
    assert save_type(client, fx, created["id"], props).status_code == 200
    for p in props:
        if p["api_name"] == "email":
            p["value_type_id"] = vt["id"]
    r = save_type(client, fx, created["id"], props)
    assert r.status_code == 422, r.text


def shared(client, fx, vt_id: str | None, *, data_type: str = "string", sid: str | None = None):
    body = {"display_name": "Contact email", "data_type": data_type, "value_type_id": vt_id}
    if sid is None:
        return client.post(f"{wbase(fx)}/shared-properties", headers=hdr(fx.editor_sub),
                           json={"api_name": f"contact_email_{uuid.uuid4().hex[:6]}", **body})
    return client.patch(f"{wbase(fx)}/shared-properties/{sid}", headers=hdr(fx.editor_sub),
                        json=body)


def test_a_shared_property_is_held_to_the_same_rules(client, fx) -> None:
    vt = make_value_type(client, fx)
    r = shared(client, fx, vt["id"])
    assert r.status_code == 201, r.text
    sp = r.json()
    deprecate(client, fx, vt)
    # Kept by the shared property that had it.
    r = shared(client, fx, vt["id"], sid=sp["id"])
    assert r.status_code == 200, r.text
    assert r.json()["value_type_id"] == vt["id"]
    # Refused to a new one, and to one that had none.
    r = shared(client, fx, vt["id"])
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text
    other = shared(client, fx, None).json()
    r = shared(client, fx, vt["id"], sid=other["id"])
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text
    # Nor to one that had another.
    live = make_value_type(client, fx)
    third = shared(client, fx, live["id"]).json()
    r = shared(client, fx, vt["id"], sid=third["id"])
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text


def test_a_shared_property_takes_a_value_type_of_its_own_base_type_and_workspace(
    client, fx
) -> None:
    vt = make_value_type(client, fx)
    r = shared(client, fx, vt["id"], data_type="integer")
    assert r.status_code == 422, r.text
    assert "is a string, and this shared property is integer" in r.text
    r = shared(client, fx, str(uuid.uuid4()))
    assert r.status_code == 422, r.text
    assert "no value type" in r.text


def test_a_deprecated_value_type_is_not_named_by_a_new_constraint(client, fx) -> None:
    """§681's nested and elements references are uses too: a new one is
    refused, and a version keeps what the current one already names."""
    email = make_value_type(client, fx)
    listy = make_value_type(client, fx, base_type="array",
                            constraint={"kind": "nested", "value_type": email["id"]})
    phone = make_value_type(client, fx, constraint=None)
    pair = make_value_type(client, fx, base_type="struct", constraint={
        "kind": "elements", "fields": {"email": email["id"], "phone": phone["id"]}})
    deprecate(client, fx, email)
    r = client.post(f"{wbase(fx)}/value-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"emails_{uuid.uuid4().hex[:6]}", "display_name": "Emails",
        "base_type": "array", "constraint": {"kind": "nested", "value_type": email["id"]}})
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text
    # A struct naming it in a new version of something that did not name it.
    struct = make_value_type(client, fx, base_type="struct", constraint=None)
    r = client.post(f"{wbase(fx)}/value-types/{struct['id']}/versions",
                    headers=hdr(fx.editor_sub),
                    json={"constraint": {"kind": "elements", "fields": {"email": email["id"]}}})
    assert r.status_code == 422, r.text
    assert "deprecated" in r.text
    # A struct that names it keeps naming it in its next version.
    r = client.post(f"{wbase(fx)}/value-types/{pair['id']}/versions",
                    headers=hdr(fx.editor_sub),
                    json={"constraint": {"kind": "elements", "fields": {"email": email["id"]}}})
    assert r.status_code == 201, r.text
    # Dropped and named again is a new use.
    r = client.post(f"{wbase(fx)}/value-types/{listy['id']}/versions",
                    headers=hdr(fx.editor_sub), json={"constraint": None})
    assert r.status_code == 201, r.text
    r = client.post(f"{wbase(fx)}/value-types/{listy['id']}/versions",
                    headers=hdr(fx.editor_sub),
                    json={"constraint": {"kind": "nested", "value_type": email["id"]}})
    assert r.status_code == 422, r.text
