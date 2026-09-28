"""What an implementing property presents to an interface (§675;
`object-link-types` p.131, p.169-170).

> "A property reducer enables you to transform an array property into a
>  single value in the array for display and interface implementation
>  purposes." (p.131)
>
> "When you configure both a struct main field and a property reducer, the
>  transformation: Applies the configured property reducer, fetching the most
>  recent location based on its date. Extracts the configured main field and
>  returns its value as a string." (p.170)
>
> "Interface actions that edit a property implemented through a property
>  reducer or struct main field will return an error when called on objects of
>  that type." (p.170)

Three types implement one interface's `street`: a site's address struct
(its main field), a route's struct array of stops (the latest stop's main
field), and a list of street names (the first). Read through the interface,
each answers a street - not a struct, not a list.
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
from test_interface_sets import _map_and_sync, _upload, client, fx, wbase  # noqa: E402,F401
from src.services import property_reducers  # noqa: E402

ADDRESS = [{"api_name": "street", "data_type": "string", "main": True},
           {"api_name": "on", "data_type": "date"}]


def field(api_name: str, data_type: str, main: bool = False) -> dict:
    return {"api_name": api_name, "display_name": api_name, "description": "", "data_type": data_type,
            **({"main": True} if main else {})}


# ---- pure --------------------------------------------------------------------------
def test_a_struct_presents_its_one_main_field() -> None:
    one = {"data_type": "struct", "struct_fields": [field("street", "string", True), field("on", "date")]}
    two = {"data_type": "struct", "struct_fields": [field("street", "string", True), field("on", "date", True)]}
    none = {"data_type": "struct", "struct_fields": [field("street", "string"), field("on", "date")]}
    assert [property_reducers.implements_as(p) for p in (one, two, none)] == ["string", "struct", "struct"]
    assert property_reducers.present(one, {"street": "12 Main St", "on": "2024-01-01"}) == "12 Main St"
    assert property_reducers.present(two, {"street": "A"}) == {"street": "A"}
    assert property_reducers.present(one, "not a struct") == "not a struct"
    assert [property_reducers.presented_through(p) for p in (one, two, none)] == [
        "a struct main field", None, None]


def test_a_reduced_struct_array_presents_its_element_s_main_field() -> None:
    stops = {"data_type": "array", "array_of": "struct",
             "struct_fields": [field("street", "string", True), field("on", "date")],
             "reducers": [{"operation": "latest", "field": "on"}]}
    value = [{"street": "Old Rd", "on": "2024-01-01"}, {"street": "New St", "on": "2024-06-01"}]
    assert property_reducers.implements_as(stops) == "string"
    assert property_reducers.present(stops, value) == "New St"
    assert property_reducers.presented_through(stops) == "a property reducer and a struct main field"
    # Unreduced, a struct array presents an array, main field or not.
    unreduced = {**stops, "reducers": None}
    assert property_reducers.implements_as(unreduced) == "array"
    assert property_reducers.presented_through(unreduced) is None
    assert property_reducers.present(unreduced, value) == value
    # Reduced with no main field, it presents the element.
    plain = {**stops, "struct_fields": [field("street", "string"), field("on", "date")]}
    assert property_reducers.present(plain, value) == {"street": "New St", "on": "2024-06-01"}
    assert property_reducers.presented_through(plain) == "a property reducer"


def test_a_reduced_array_presents_its_element_and_anything_else_itself() -> None:
    names = {"data_type": "array", "array_of": "string", "reducers": [{"operation": "first"}]}
    assert property_reducers.present(names, ["b", "a"]) == "a"
    assert property_reducers.presented_through(names) == "a property reducer"
    plain = {"data_type": "string"}
    assert property_reducers.present(plain, "x") == "x"
    assert property_reducers.presented_through(plain) is None


# ---- end to end ----------------------------------------------------------------------
def _csv(header: list[str], rows: list[list[str]]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def _type(client: TestClient, fx: Fixture, api_name: str, prop: dict) -> str:
    r = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": api_name, "display_name": api_name.replace("_", " "),
        "properties": [{"api_name": "id", "data_type": "string"}, prop], "title_property": "id"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _implement(client: TestClient, fx: Fixture, type_id: str, interface_id: str, target: str):
    return client.put(f"{wbase(fx)}/object-types/{type_id}/interfaces", headers=hdr(fx.editor_sub),
                      json=[{"interface_id": interface_id, "property_mapping": {"street": target}}])


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json={
        "api_name": f"Addressed{tag}", "display_name": f"Addressed {tag}",
        "properties": [{"api_name": "street", "display_name": "Street", "data_type": "string"}]})
    assert r.status_code == 201, r.text
    interface_id = r.json()["id"]
    site = _type(client, fx, f"site_{tag}", {"api_name": "address", "data_type": "struct",
                                             "struct_fields": ADDRESS})
    route = _type(client, fx, f"route_{tag}", {"api_name": "stops", "data_type": "array", "array_of": "struct",
                                               "struct_fields": ADDRESS,
                                               "reducers": [{"operation": "latest", "field": "on"}]})
    names = _type(client, fx, f"names_{tag}", {"api_name": "streets", "data_type": "array",
                                               "array_of": "string", "reducers": [{"operation": "first"}]})
    for type_id, target in ((site, "address"), (route, "stops"), (names, "streets")):
        r = _implement(client, fx, type_id, interface_id, target)
        assert r.status_code == 200, r.text
    for type_id, column, value in (
        (site, "address", json.dumps({"street": "12 Main St", "on": "2024-01-01"})),
        (route, "stops", json.dumps([{"street": "Old Rd", "on": "2024-01-01"},
                                     {"street": "New St", "on": "2024-06-01"}])),
        (names, "streets", json.dumps(["Zeta Way", "Alpha Ave"])),
    ):
        dataset = _upload(client, fx, f"{column} {tag}", _csv(["id", column], [[f"{column}-1", value]]))
        _map_and_sync(client, fx, type_id, dataset, "id", {"id": "id", column: column})
    return {"tag": tag, "interface_id": interface_id, "site": site, "route": route, "names": names}


def test_each_implementation_presents_a_street(client: TestClient, fx: Fixture, world: dict) -> None:
    r = client.post(f"{wbase(fx)}/interfaces/{world['interface_id']}/evaluate",
                    headers=hdr(fx.viewer_sub), json={})
    assert r.status_code == 200, r.text
    streets = {row["primary_key"]: row["properties"].get("street") for row in r.json()["instances"]}
    assert streets == {"address-1": "12 Main St", "stops-1": "New St", "streets-1": "Alpha Ave"}


def test_two_main_fields_present_no_one_value(client: TestClient, fx: Fixture, world: dict) -> None:
    tag = uuid.uuid4().hex[:6]
    both = _type(client, fx, f"both_{tag}", {"api_name": "address", "data_type": "struct", "struct_fields": [
        {"api_name": "street", "data_type": "string", "main": True},
        {"api_name": "town", "data_type": "string", "main": True}]})
    r = _implement(client, fx, both, world["interface_id"], "address")
    assert r.status_code == 422, r.text
    assert "base types must match" in r.text


def test_an_interface_action_cannot_write_through_a_presented_value(
    client: TestClient, fx: Fixture, world: dict,
) -> None:
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "interface_id": world["interface_id"], "api_name": f"move_{uuid.uuid4().hex[:8]}",
        "display_name": "Move", "editable_properties": ["street"]})
    assert r.status_code == 201, r.text
    action = r.json()
    for type_id, through in ((world["site"], "a struct main field"),
                             (world["route"], "a property reducer and a struct main field"),
                             (world["names"], "a property reducer")):
        listed = client.get(f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub))
        instance = listed.json()["items"][0]["id"]
        r = client.post(f"{wbase(fx)}/projects/{fx.project}/actions/{action['id']}/execute",
                        headers=hdr(fx.editor_sub), json={"instance_id": instance, "values": {"street": "X"}})
        assert r.status_code == 422, r.text
        assert through in r.json()["detail"] and "p.170" in r.json()["detail"], r.json()["detail"]
