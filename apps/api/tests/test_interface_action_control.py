"""p.65's Interface action control (§763; db 0150; Foundry `action-types`
p.65).

> "To restrict access, disable interface actions for specific object types in
> Ontology Manager by selecting its Interfaces tab and establishing control
> over actions inherited from an interface in the Interface action control
> section." (p.65)

The fixture is `test_interface_actions.py`'s: Inspectable, implemented by a
Facility and a Vehicle. Switching an action off for Vehicles must leave
Facilities untouched, which is the whole of "per object type".
"""
from __future__ import annotations

import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_interface_actions import (  # noqa: E402,F401
    _interface_action, client, fx, pbase, wbase, world,
)


def control(client, fx, type_id: str) -> dict[str, bool]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/interface-action-control",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {row["action_type_id"]: row["enabled"] for row in r.json()}


def switch_off(client, fx, type_id: str, ids: list[str]):
    return client.put(f"{wbase(fx)}/object-types/{type_id}/interface-action-control",
                      headers=hdr(fx.editor_sub), json={"disabled": ids})


def listed(client, fx, type_id: str) -> set[str]:
    r = client.get(f"{wbase(fx)}/action-types?object_type_id={type_id}",
                   headers=hdr(fx.viewer_sub))
    return {a["id"] for a in r.json()}


def run(client, fx, action, instance):
    return client.post(f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
                       json={"instance_id": instance,
                             "values": {"last_inspection_date": "2025-05-05"}})


def test_an_action_switched_off_for_one_type_is_off_for_that_type_only(client, fx, world) -> None:
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    assert control(client, fx, world["vehicle"])[action["id"]] is True
    r = switch_off(client, fx, world["vehicle"], [action["id"]])
    assert r.status_code == 200, r.text
    assert {row["action_type_id"]: row["enabled"] for row in r.json()}[action["id"]] is False
    assert control(client, fx, world["facility"])[action["id"]] is True

    # Not among the Vehicle's actions (p.64's merge), still among the Facility's.
    assert action["id"] not in listed(client, fx, world["vehicle"])
    assert action["id"] in listed(client, fx, world["facility"])

    # And refused against a Vehicle, run against a Facility.
    r = run(client, fx, action, world["vehicle_instance"])
    assert r.status_code == 403, r.text
    assert "switched off" in r.text and "p.65" in r.text
    assert run(client, fx, action, world["facility_instance"]).status_code == 200

    # Switched back on, it runs.
    assert switch_off(client, fx, world["vehicle"], []).status_code == 200
    assert run(client, fx, action, world["vehicle_instance"]).status_code == 200
    assert action["id"] in listed(client, fx, world["vehicle"])


def test_only_an_inherited_action_can_be_switched_off(client, fx, world) -> None:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["vehicle"], "api_name": f"own_{uuid.uuid4().hex[:6]}",
        "display_name": "Own", "editable_properties": ["state"]})
    own = r.json()["id"]
    r = switch_off(client, fx, world["vehicle"], [own])
    assert r.status_code == 422, r.text
    assert "interface this object type implements" in r.text
    assert own not in control(client, fx, world["vehicle"])


def test_a_viewer_reads_it_and_cannot_change_it(client, fx, world) -> None:
    r = client.put(f"{wbase(fx)}/object-types/{world['vehicle']}/interface-action-control",
                   headers=hdr(fx.viewer_sub), json={"disabled": []})
    assert r.status_code == 403, r.text


def test_an_action_on_an_interface_the_type_does_not_implement_is_not_its_to_control(
    client, fx, world
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.admin_sub), json={
        "api_name": f"Elsewhere{tag}", "display_name": f"Elsewhere {tag}",
        "properties": [{"api_name": "note", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    elsewhere = r.json()["id"]
    # Implemented by the Facility, so it is *some* type's to control - just
    # not the Vehicle's.
    current = client.get(f"{wbase(fx)}/object-types/{world['facility']}/interfaces",
                         headers=hdr(fx.viewer_sub)).json()
    r = client.put(f"{wbase(fx)}/object-types/{world['facility']}/interfaces",
                   headers=hdr(fx.editor_sub), json=[
        *({"interface_id": i["interface_id"], "property_mapping": i["property_mapping"]}
          for i in current),
        {"interface_id": elsewhere, "property_mapping": {"note": "state"}}])
    assert r.status_code == 200, r.text
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "interface_id": elsewhere, "api_name": f"elsewhere_{tag}",
        "display_name": "Elsewhere", "editable_properties": ["note"]})
    assert r.status_code == 201, r.text
    foreign = r.json()["id"]
    assert foreign not in control(client, fx, world["vehicle"])
    assert foreign in control(client, fx, world["facility"])
    assert switch_off(client, fx, world["vehicle"], [foreign]).status_code == 422
