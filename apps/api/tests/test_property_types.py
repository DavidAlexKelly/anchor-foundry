"""Richer property types (ROADMAP Objects item 4).

The item guessed that today's properties are "basic scalars". They were worse
than that: `geopoint` and `timestamp` had been in the enum since migration
0003 as labels nothing enforced, so a property declared `geopoint` accepted
the string "banana" from an action and stored whatever a CSV column happened
to hold from a sync. These tests are therefore mostly about the two write
paths *agreeing*, because a type enforced on one and not the other is not a
type.
"""
from __future__ import annotations

import hashlib
import io
import os
import pathlib
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import property_values  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

# lat,lon text in one row and an out-of-range value in another, so both the
# happy path and the refusal are exercised by real synced data.
SITES = b"code,name,location,opened\nA1,Depot,51.5074;-0.1278,2020-03-01\n"
SITES_OK = b"code,name,location,opened\nA1,Depot,\"51.5074,-0.1278\",2020-03-01\nA2,Yard,\"53.48,-2.24\",2021-07-15\n"
SITES_BAD = b"code,name,location,opened\nA1,Depot,banana,2020-03-01\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("property-types")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


# ---- the coercion itself ----------------------------------------------------
def test_a_geopoint_reads_from_both_shapes_it_actually_arrives_in() -> None:
    """A CSV column gives text; a Parquet struct or a JSON body gives a
    mapping. Both are real, so both normalise to the same stored value."""
    expected = {"lat": 51.5074, "lon": -0.1278}
    assert property_values.coerce_property_value("geopoint", "51.5074,-0.1278") == expected
    assert property_values.coerce_property_value(
        "geopoint", {"lat": 51.5074, "lon": -0.1278}
    ) == expected
    assert property_values.coerce_property_value(
        "geopoint", {"Latitude": 51.5074, "Longitude": -0.1278}
    ) == expected
    assert property_values.coerce_property_value("geopoint", [51.5074, -0.1278]) == expected


def test_a_geopoint_refuses_what_is_not_one() -> None:
    for bad in ["banana", "1,2,3", {"lat": 1}, 42, {"lat": "x", "lon": "y"}]:
        with pytest.raises(property_values.PropertyValueError):
            property_values.coerce_property_value("geopoint", bad)


def test_the_lat_lon_order_is_enforced_not_just_documented() -> None:
    """Order is a choice with no right answer (GeoJSON says lon,lat; most UIs
    say lat,lon), so the range check has to catch the transposed case rather
    than leaving it to a comment."""
    with pytest.raises(property_values.PropertyValueError, match="did you send lon,lat"):
        property_values.coerce_property_value("geopoint", "-0.1278,51.5074".replace("-0.1278", "100"))
    assert property_values.coerce_property_value("geopoint", "51.5,-0.1") == {
        "lat": 51.5, "lon": -0.1
    }


def test_temporal_values_parse_and_keep_an_offset_when_there_is_one() -> None:
    assert property_values.coerce_property_value("date", "2026-08-01") == "2026-08-01"
    assert property_values.coerce_property_value(
        "timestamp", "2026-08-01T10:00:00Z"
    ) == "2026-08-01T10:00:00+00:00"
    # No offset in, no offset out - migration 0029's reason for not splitting
    # timestamp into timestamp/timestamptz.
    assert property_values.coerce_property_value(
        "timestamp", "2026-08-01T10:00:00"
    ) == "2026-08-01T10:00:00"
    with pytest.raises(property_values.PropertyValueError):
        property_values.coerce_property_value("timestamp", "not a date")


def test_scalars_coerce_rather_than_merely_check() -> None:
    """The commonest mapping there is: an id column DuckDB reads as BIGINT,
    mapped to a property declared `string`. Refusing that would make the type
    system hostile for no gain - what is worth refusing is the *ambiguous*
    conversion, not the total one."""
    assert property_values.coerce_property_value("string", 1) == "1"
    assert property_values.coerce_property_value("integer", "7") == 7
    assert property_values.coerce_property_value("integer", 3.0) == 3
    assert property_values.coerce_property_value("float", "1.5") == 1.5
    assert property_values.coerce_property_value("boolean", "no") is False
    assert property_values.coerce_property_value("boolean", "TRUE") is True


def test_the_ambiguous_conversions_are_still_refused() -> None:
    for data_type, bad in [
        ("integer", "banana"),
        ("integer", 3.5),          # truncating is quiet data loss
        ("boolean", "maybe"),      # not Python truthiness: "0" would be True
        ("string", {"a": 1}),
        ("string", True),          # a JSON true for a name field is a mistake
    ]:
        with pytest.raises(property_values.PropertyValueError):
            property_values.coerce_property_value(data_type, bad)


def test_json_stays_the_escape_hatch() -> None:
    """Constraining json would leave nowhere to put a value that has no type
    yet, which is the whole reason the label exists."""
    for value in [{"anything": [1, 2]}, "a string", 7]:
        assert property_values.coerce_property_value("json", value) == value


def test_the_flat_form_round_trips_through_a_dataset_column() -> None:
    """Write-back flattens a geopoint into the "lat,lon" text a Parquet
    column can hold; the next sync has to read that back to the same value."""
    point = property_values.coerce_property_value("geopoint", "51.5,-0.12")
    flat = property_values.column_value("geopoint", point)
    assert flat == "51.5,-0.12"
    assert property_values.coerce_property_value("geopoint", flat) == point


def test_an_attachment_survives_a_round_trip_through_a_dataset_column() -> None:
    """Write-back stores the whole reference as JSON text in the column, and
    the next sync reads it back. Storing only the key would lose the filename,
    content type and size - the attachment would degrade a little on every
    sync - and refusing the string on the way back in would mean an attachment
    survived exactly until its source was re-synced."""
    ref = {"key": "workspaces/w/attachments/x/f.txt", "filename": "f.txt",
           "content_type": "text/plain", "size": 3}
    flat = property_values.column_value("attachment", ref)
    assert isinstance(flat, str)
    assert property_values.coerce_property_value("attachment", flat) == ref
    with pytest.raises(property_values.PropertyValueError):
        property_values.coerce_property_value("attachment", "not json at all")


def test_a_bad_value_fails_the_whole_sync_and_says_which_row() -> None:
    rows = [("A1", {"location": "51.5,-0.1"}), ("A2", {"location": "banana"})]
    with pytest.raises(property_values.PropertyValueError) as exc:
        property_values.coerce_rows(rows, {"location": "geopoint"})
    assert "A2" in str(exc.value) and "location" in str(exc.value)


def test_an_unmapped_property_passes_through_untouched() -> None:
    rows = [("A1", {"mystery": {"deep": 1}})]
    assert property_values.coerce_rows(rows, {})[0][1] == {"mystery": {"deep": 1}}


# ---- the two write paths agree ----------------------------------------------
@pytest.fixture()
def site_type(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"site_{tag}", "display_name": f"Site {tag}",
              "properties": [
                  {"api_name": "name", "data_type": "string"},
                  {"api_name": "location", "data_type": "geopoint"},
                  {"api_name": "opened", "data_type": "date"},
              ],
              "title_property": "name"},
    )
    assert r.status_code == 201, r.text
    return {"tag": tag, "id": r.json()["id"]}


def _map_and_sync(client: TestClient, fx: Fixture, type_id: str, csv: bytes) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Sites {tag}"},
        files={"file": ("sites.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": r.json()["id"],
              "primary_key_column": "code",
              "column_mappings": {"name": "name", "location": "location",
                                  "opened": "opened"}},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    r = client.post(f"{pbase(fx)}/object-type-sources/{source_id}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_sync_stores_the_declared_type_not_the_raw_column(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    result = _map_and_sync(client, fx, site_type["id"], SITES_OK)
    assert result["ok"] is True, result["error"]
    assert result["upserted"] == 2

    r = client.get(f"{wbase(fx)}/object-types/{site_type['id']}/instances",
                   headers=hdr(fx.viewer_sub))
    rows = {i["primary_key"]: i["properties"] for i in r.json()["items"]}
    assert rows["A1"]["location"] == {"lat": 51.5074, "lon": -0.1278}
    assert rows["A1"]["opened"] == "2020-03-01"


def test_a_sync_refuses_a_value_that_is_not_the_declared_type(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """Loudly, naming the row - the alternative is a row that arrives looking
    complete with a field silently missing."""
    result = _map_and_sync(client, fx, site_type["id"], SITES_BAD)
    assert result["ok"] is False
    assert "location" in result["error"] and "A1" in result["error"]
    assert result["source"]["sync_status"] == "error"

    r = client.get(f"{wbase(fx)}/object-types/{site_type['id']}/instances",
                   headers=hdr(fx.viewer_sub))
    assert r.json()["total"] == 0, "nothing was written"


def test_write_back_normalises_the_same_way_a_sync_does(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """The point of the shared coercion: a geopoint typed into a form and one
    read from a dataset land in storage identically."""
    _map_and_sync(client, fx, site_type["id"], SITES_OK)
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": site_type["id"], "api_name": f"move_{site_type['tag']}",
              "display_name": "Move site", "editable_properties": ["location"]},
    )
    assert r.status_code == 201, r.text
    action_id = r.json()["id"]

    instances = client.get(f"{wbase(fx)}/object-types/{site_type['id']}/instances",
                           headers=hdr(fx.viewer_sub)).json()["items"]
    target = next(i for i in instances if i["primary_key"] == "A1")

    r = client.post(
        f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": target["id"], "values": {"location": "48.8566,2.3522"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True, r.json()["error"]
    assert r.json()["instance"]["properties"]["location"] == {"lat": 48.8566, "lon": 2.3522}


def test_write_back_refuses_a_value_of_the_wrong_type(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """Before this item every non-scalar label was decorative here: a
    geopoint property accepted the string "banana" without complaint."""
    _map_and_sync(client, fx, site_type["id"], SITES_OK)
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": site_type["id"], "api_name": f"move_{site_type['tag']}",
              "display_name": "Move site", "editable_properties": ["location"]},
    )
    action_id = r.json()["id"]
    instances = client.get(f"{wbase(fx)}/object-types/{site_type['id']}/instances",
                           headers=hdr(fx.viewer_sub)).json()["items"]
    r = client.post(
        f"{pbase(fx)}/actions/{action_id}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instances[0]["id"], "values": {"location": "banana"}},
    )
    assert r.status_code == 422, r.text
    assert "geopoint" in r.json()["detail"]


# ---- attachments -------------------------------------------------------------
def test_an_attachment_uploads_and_downloads(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/attachments", headers=hdr(fx.editor_sub),
        files={"file": ("spec sheet.pdf", io.BytesIO(b"%PDF-1.4 hello"), "application/pdf")},
    )
    assert r.status_code == 201, r.text
    attachment = r.json()
    assert attachment["filename"] == "spec_sheet.pdf", "unsafe characters are replaced"
    assert attachment["size"] == 14
    assert attachment["content_type"] == "application/pdf"

    r = client.get(f"{wbase(fx)}/attachments/download",
                   params={"key": attachment["key"]}, headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.content == b"%PDF-1.4 hello"
    # Never inline, never the uploader's declared type - that is how a stored
    # XSS happens.
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")


def test_a_key_outside_this_workspace_is_a_404(client: TestClient, fx: Fixture) -> None:
    """The stored value is a plain string a caller controls, so the download
    route treats the key as untrusted input rather than a capability."""
    for key in ["other-workspace-/attachments/x/file.pdf",
                "../etc/passwd",
                f"ws-{fx.tag}-/datasets/something/v1/data.parquet"]:
        r = client.get(f"{wbase(fx)}/attachments/download",
                       params={"key": key}, headers=hdr(fx.viewer_sub))
        assert r.status_code == 404, f"{key} -> {r.status_code}"


def test_attachment_upload_needs_editor_and_a_visible_workspace(
    client: TestClient, fx: Fixture
) -> None:
    files = {"file": ("a.txt", io.BytesIO(b"x"), "text/plain")}
    assert client.post(f"{wbase(fx)}/attachments", headers=hdr(fx.viewer_sub),
                       files=files).status_code == 403
    assert client.post(f"{wbase(fx)}/attachments", headers=hdr(fx.outsider_sub),
                       files=files).status_code == 404


def test_an_empty_attachment_is_refused(client: TestClient, fx: Fixture) -> None:
    r = client.post(f"{wbase(fx)}/attachments", headers=hdr(fx.editor_sub),
                    files={"file": ("empty.txt", io.BytesIO(b""), "text/plain")})
    assert r.status_code == 422, r.text


def test_an_attachment_property_stores_the_reference(
    client: TestClient, fx: Fixture
) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"doc_{tag}", "display_name": f"Doc {tag}",
              "properties": [{"api_name": "attachment_file", "data_type": "attachment"}]},
    )
    assert r.status_code == 201, r.text
    assert r.json()["properties"][0]["data_type"] == "attachment"

    upload = client.post(
        f"{wbase(fx)}/attachments", headers=hdr(fx.editor_sub),
        files={"file": ("r.txt", io.BytesIO(b"report"), "text/plain")},
    ).json()
    assert property_values.coerce_property_value("attachment", upload) == upload
    # A fabricated value is refused: it is a reference the platform wrote,
    # not something a user types.
    with pytest.raises(property_values.PropertyValueError):
        property_values.coerce_property_value("attachment", "some-key")
    with pytest.raises(property_values.PropertyValueError):
        property_values.coerce_property_value("attachment", {"key": "k"})


# ---- the fifth mirror --------------------------------------------------------
def test_the_api_and_worker_copies_of_property_values_are_identical() -> None:
    """`property_values.py` is duplicated into the worker, which is the fifth
    such mirror in this build and one more than STATUS's rough edges says
    should exist before someone builds a shared package. The mitigation is
    that this file is pure standard-library Python, so parity is a hash
    comparison rather than a judgement call - unlike the connector registries,
    whose drift can only be caught by asserting behaviour.

    If this fails: copy, do not patch one side. If you are here because you
    need a *sixth* mirror, build the package instead.
    """
    root = pathlib.Path(__file__).resolve().parents[3]
    api = root / "apps/api/src/services/property_values.py"
    worker = root / "apps/worker/src/anchor_worker/property_values.py"
    assert worker.exists(), "the worker's copy is missing"
    assert hashlib.sha256(api.read_bytes()).hexdigest() == \
        hashlib.sha256(worker.read_bytes()).hexdigest(), (
            "the API and worker copies of property_values.py have drifted - "
            "a geopoint would sync differently depending on who ran it"
        )
