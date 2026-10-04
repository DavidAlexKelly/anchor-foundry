"""A dataset column's type read as a shape, and p.160's Automap all (§735;
`object-link-types` p.149, p.160).

> "Struct properties are created from struct type dataset columns." (p.149)

> "Automapping allows users to map all columns automatically rather than
> manually." (p.160)

The reader is tested on the type sentences DuckDB's `DESCRIBE` writes; the
routes on a JSON Lines upload, whose nested objects arrive as STRUCT columns,
synced through to objects - which is the test that a field automapped from a
column is one the sync then reads.
"""
from __future__ import annotations

import io
import json
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import column_types  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402


# ---- the reader -------------------------------------------------------------
def test_a_struct_column_is_a_struct_with_its_members_as_fields() -> None:
    got = column_types.suggest("STRUCT(street VARCHAR, number BIGINT, since DATE, ok BOOLEAN)")
    assert got == {
        "data_type": "struct",
        "struct_fields": [
            {"api_name": "street", "display_name": "Street", "description": "", "data_type": "string"},
            {"api_name": "number", "display_name": "Number", "description": "", "data_type": "integer"},
            {"api_name": "since", "display_name": "Since", "description": "", "data_type": "date"},
            {"api_name": "ok", "display_name": "Ok", "description": "", "data_type": "boolean"},
        ],
        "skipped_fields": [],
    }


def test_a_member_that_cannot_be_a_field_is_skipped_with_why() -> None:
    got = column_types.suggest(
        'STRUCT(a DOUBLE, "First Name" VARCHAR, n STRUCT(z INTEGER), l INTEGER[], '
        "m MAP(VARCHAR, INTEGER), j JSON, at_time TIMESTAMP WITH TIME ZONE)")
    assert [f["api_name"] for f in got["struct_fields"]] == ["a", "at_time"]
    assert [f["data_type"] for f in got["struct_fields"]] == ["float", "timestamp"]
    reasons = {s["field"]: s["reason"] for s in got["skipped_fields"]}
    assert list(reasons) == ["First Name", "n", "l", "m", "j"]
    assert "is not a name a field can have" in reasons["First Name"]
    assert "depth of one" in reasons["n"]
    assert reasons["l"] == "a struct field cannot be an array"
    assert reasons["m"] == "a struct field cannot hold a MAP"
    assert reasons["j"] == "a struct field cannot hold json"


def test_a_struct_with_no_member_that_can_be_a_field_is_json() -> None:
    got = column_types.suggest('STRUCT("x y" VARCHAR, n STRUCT(z INTEGER))')
    assert got["data_type"] == "json"
    assert "struct_fields" not in got
    assert [s["field"] for s in got["skipped_fields"]] == ["x y", "n"]


def test_a_list_column_is_an_array_of_its_element() -> None:
    assert column_types.suggest("VARCHAR[]") == {"data_type": "array", "array_of": "string"}
    assert column_types.suggest("INTEGER[3]") == {"data_type": "array", "array_of": "integer"}
    got = column_types.suggest("STRUCT(a INTEGER)[]")
    assert (got["data_type"], got["array_of"]) == ("array", "struct")
    assert [f["api_name"] for f in got["struct_fields"]] == ["a"]
    assert column_types.suggest('STRUCT("A" INTEGER)[]') == {
        "data_type": "array", "array_of": "json",
        "skipped_fields": [{"field": "A", "reason": column_types._field_name_problem("A")}],
    }


def test_what_has_no_property_of_its_own_is_json() -> None:
    for text in ("INTEGER[][]", "MAP(VARCHAR, INTEGER)", "UNION(num INTEGER)", "JSON",
                 "MAP(VARCHAR, INTEGER)[]"):
        assert column_types.suggest(text) == {"data_type": "json"}, text


def test_a_scalar_is_read_whole_rather_than_by_the_first_name_in_it() -> None:
    # Before §735 a struct holding an integer was suggested as `integer`.
    assert column_types.suggest("STRUCT(a INTEGER)")["data_type"] == "struct"
    assert column_types.suggest("DECIMAL(10,2)") == {"data_type": "float"}
    assert column_types.suggest("TIMESTAMP WITH TIME ZONE") == {"data_type": "timestamp"}
    assert column_types.suggest("UBIGINT") == {"data_type": "integer"}
    assert column_types.suggest("VARCHAR") == {"data_type": "string"}
    assert column_types.suggest("BLOB") == {"data_type": "string"}


def test_quoted_member_names_unescape() -> None:
    node = column_types.parse('STRUCT("b""q" INTEGER, "c,d" VARCHAR, e DECIMAL(4,1))')
    assert isinstance(node, column_types.Struct)
    assert [name for name, _ in node.members] == ['b"q', "c,d", "e"]
    assert node.members[2][1] == column_types.Scalar("DECIMAL(4,1)")


def test_struct_column_finds_a_struct_or_an_array_of_them() -> None:
    assert column_types.struct_column("STRUCT(a INTEGER)") is not None
    assert column_types.struct_column("STRUCT(a INTEGER)[]") is not None
    assert column_types.struct_column("INTEGER[]") is None
    assert column_types.struct_column("VARCHAR") is None
    assert column_types.struct_column("") is None


# ---- the routes -------------------------------------------------------------
ROWS = [
    {"code": "A1", "name": "Head office",
     "address": {"street": "1 Main St", "number": 1, "First Name": "x"},
     "tags": ["north", "big"], "visits": [{"day": "2024-01-02", "count": 3}]},
    {"code": "B2", "name": "Depot",
     "address": {"street": "9 Side Rd", "number": 9, "First Name": "y"},
     "tags": ["south"], "visits": []},
]


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("struct-automap-storage")))
    )
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture(scope="module")
def sites(client: TestClient, fx: Fixture) -> dict:
    body = "\n".join(json.dumps(r) for r in ROWS).encode()
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub), data={"name": f"Sites {fx.tag}"},
        files={"file": ("sites.jsonl", io.BytesIO(body), "application/json")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/suggest",
        headers=hdr(fx.viewer_sub), json={"dataset_id": dataset_id},
    )
    assert r.status_code == 200, r.text
    return {"dataset_id": dataset_id, "suggestion": r.json()}


def _by_name(suggestion: dict) -> dict:
    return {p["source_column"]: p for p in suggestion["properties"]}


def test_suggest_reads_struct_and_list_columns(sites: dict) -> None:
    props = _by_name(sites["suggestion"])
    assert props["address"]["data_type"] == "struct"
    assert [f["api_name"] for f in props["address"]["struct_fields"]] == ["street", "number"]
    assert [s["field"] for s in props["address"]["skipped_fields"]] == ["First Name"]
    assert (props["tags"]["data_type"], props["tags"]["array_of"]) == ("array", "string")
    assert (props["visits"]["data_type"], props["visits"]["array_of"]) == ("array", "struct")
    assert [f["api_name"] for f in props["visits"]["struct_fields"]] == ["day", "count"]
    assert props["name"]["data_type"] == "string"
    assert props["name"]["skipped_fields"] == []
    assert props["name"]["struct_fields"] is None


@pytest.fixture(scope="module")
def site_type(client: TestClient, fx: Fixture, sites: dict) -> str:
    """The suggestion, created and mapped as the suggest dialog does it."""
    props = sites["suggestion"]["properties"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"Site{fx.tag}", "display_name": f"Site {fx.tag}",
              "properties": [
                  {k: p[k] for k in ("api_name", "data_type", "required", "array_of", "struct_fields")
                   if p.get(k) is not None}
                  for p in props]},
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": sites["dataset_id"],
              "primary_key_column": "code",
              "column_mappings": {p["source_column"]: p["api_name"] for p in props}},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources/{source_id}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"], r.json()
    return type_id


def test_an_automapped_struct_syncs(client: TestClient, fx: Fixture, site_type: str) -> None:
    r = client.get(f"/api/workspaces/{fx.workspace}/object-types/{site_type}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    rows = {i["primary_key"]: i["properties"] for i in r.json()["items"]}
    assert rows["A1"]["address"] == {"street": "1 Main St", "number": 1}
    assert rows["A1"]["tags"] == ["north", "big"]
    assert rows["A1"]["visits"] == [{"day": "2024-01-02", "count": 3}]


def test_automap_names_each_struct_column_a_source_maps(
    client: TestClient, fx: Fixture, site_type: str,
) -> None:
    r = client.get(f"/api/workspaces/{fx.workspace}/object-types/{site_type}/struct-automap",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    got = {row["property"]: row for row in r.json()}
    assert sorted(got) == ["address", "visits"]
    assert got["address"]["column"] == "address"
    assert got["address"]["dataset_name"] == f"Sites {fx.tag}"
    assert [f["api_name"] for f in got["address"]["struct_fields"]] == ["street", "number"]
    assert got["address"]["skipped_fields"][0]["field"] == "First Name"
    assert [f["data_type"] for f in got["visits"]["struct_fields"]] == ["date", "integer"]


def test_automap_is_not_seen_from_outside(client: TestClient, fx: Fixture, site_type: str) -> None:
    r = client.get(f"/api/workspaces/{fx.workspace}/object-types/{site_type}/struct-automap",
                   headers=hdr(fx.outsider_sub))
    assert r.status_code == 404


def test_automap_of_an_unknown_type_is_404(client: TestClient, fx: Fixture) -> None:
    import uuid

    r = client.get(f"/api/workspaces/{fx.workspace}/object-types/{uuid.uuid4()}/struct-automap",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 404
