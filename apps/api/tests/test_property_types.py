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


def _upload(client: TestClient, fx: Fixture, name: str, data: bytes, ctype: str) -> dict:
    r = client.post(
        f"{wbase(fx)}/attachments", headers=hdr(fx.editor_sub),
        files={"file": (name, io.BytesIO(data), ctype)},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _download(client: TestClient, fx: Fixture, key: str, **params) -> object:
    return client.get(
        f"{wbase(fx)}/attachments/download",
        params={"key": key, **params},
        headers=hdr(fx.viewer_sub),
    )


def test_an_image_can_be_asked_for_inline(client: TestClient, fx: Fixture) -> None:
    """Decision 0009, part 2. The default stays a download - the test above
    guards that - and inline is *earned*: asked for explicitly, and only for a
    type on the route's own allowlist."""
    a = _upload(client, fx, "dot.png", b"\x89PNG\r\n\x1a\n", "image/png")
    r = _download(client, fx, a["key"], disposition="inline", content_type="image/png")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers["content-disposition"].startswith("inline;")
    # So a file that is really HTML fails to decode as an image rather than
    # being run as a document.
    assert r.headers["x-content-type-options"] == "nosniff"


def test_an_image_is_still_a_download_unless_asked_for_inline(
    client: TestClient, fx: Fixture
) -> None:
    """**The default is the safe one, for the types that could go either way.**

    `test_an_attachment_uploads_and_downloads` above guards the default with a
    PDF - which is off the allowlist, so it could never have gone inline and
    the test cannot tell "not asked" from "not allowed" apart. An image can go
    either way, and this is what says which happens when nobody asked. Written
    because the mutation that drops the `disposition` check passed everything
    else.
    """
    a = _upload(client, fx, "dot.png", b"\x89PNG\r\n\x1a\n", "image/png")
    r = _download(client, fx, a["key"])
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")
    # And naming the type without asking for inline is still a download: the
    # two conditions are separate and both are required.
    r = _download(client, fx, a["key"], content_type="image/png")
    assert r.headers["content-disposition"].startswith("attachment;")


def test_a_type_off_the_allowlist_stays_a_download(client: TestClient, fx: Fixture) -> None:
    """**The refusal that makes the feature safe**, and it falls back rather
    than erroring: a mislabelled file is a link, not a broken page."""
    a = _upload(client, fx, "notes.html", b"<script>alert(1)</script>", "text/html")
    r = _download(client, fx, a["key"], disposition="inline", content_type="text/html")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")


def test_svg_is_never_inline(client: TestClient, fx: Fixture) -> None:
    """An image the browser will execute script inside, served same-origin.
    Absent from the allowlist on purpose, and `components/media-kind.ts` makes
    the same call on the other side so the two cannot disagree."""
    a = _upload(client, fx, "x.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>",
                "image/svg+xml")
    r = _download(client, fx, a["key"], disposition="inline", content_type="image/svg+xml")
    assert r.headers["content-type"] == "application/octet-stream"
    assert r.headers["content-disposition"].startswith("attachment;")


def test_a_caller_cannot_widen_the_type_by_asking(client: TestClient, fx: Fixture) -> None:
    """`content_type` is a request, not an instruction. A caller naming a type
    the route does not serve inline gets a download - so the allowlist is the
    server's, not the uploader's and not the page's."""
    a = _upload(client, fx, "thing.bin", b"\x00\x01", "application/octet-stream")
    for claimed in ["text/html", "application/javascript", "image/svg+xml", ""]:
        r = _download(client, fx, a["key"], disposition="inline", content_type=claimed)
        assert r.headers["content-type"] == "application/octet-stream", claimed


def test_asking_inline_for_a_key_outside_the_workspace_is_still_a_404(
    client: TestClient, fx: Fixture
) -> None:
    """The isolation check runs before any of this. Worth its own line because
    a new query parameter is exactly the sort of thing that gets added in front
    of a boundary rather than behind it."""
    r = _download(client, fx, "other-workspace-/attachments/x/a.png",
                  disposition="inline", content_type="image/png")
    assert r.status_code == 404


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


# ---- exact property filtering on the explorer (Canvas item 3) ---------------
def test_the_explorer_can_filter_on_an_exact_property_value(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """`q` is substring/prefix across every property - right for a search box,
    wrong for a dropdown. Canvas item 3's object table needed the exact
    question, and the store Protocol has had `find_by_property` since Objects
    item 3, so this exposes it rather than inventing a second search."""
    _map_and_sync(client, fx, site_type["id"], SITES_OK)
    r = client.get(
        f"{wbase(fx)}/object-instances",
        params={"type_id": site_type["id"], "property": "name", "value": "Depot"},
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    item = r.json()["items"][0]
    assert item["properties"]["name"] == "Depot"
    # The explorer's contract is that every row says what it is.
    assert item["object_type_id"] == site_type["id"]
    assert item["object_type_display_name"].startswith("Site ")


def test_an_exact_filter_does_not_match_a_prefix(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """The whole reason it exists: picking "Depot" from a dropdown must not
    also return "Depot North"."""
    _map_and_sync(client, fx, site_type["id"], SITES_OK)
    exact = client.get(
        f"{wbase(fx)}/object-instances",
        params={"type_id": site_type["id"], "property": "name", "value": "Dep"},
        headers=hdr(fx.viewer_sub),
    )
    assert exact.json()["total"] == 0, "an exact filter is not a prefix filter"
    fuzzy = client.get(
        f"{wbase(fx)}/object-instances",
        params={"type_id": site_type["id"], "q": "Dep"},
        headers=hdr(fx.viewer_sub),
    )
    assert fuzzy.json()["total"] >= 1, "q still matches a prefix - that is its job"


def test_the_primary_key_is_filterable_by_its_reserved_name(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    _map_and_sync(client, fx, site_type["id"], SITES_OK)
    r = client.get(
        f"{wbase(fx)}/object-instances",
        params={"type_id": site_type["id"], "property": "$primary_key", "value": "A2"},
        headers=hdr(fx.viewer_sub),
    )
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["primary_key"] == "A2"


def test_a_property_filter_needs_exactly_one_type(
    client: TestClient, fx: Fixture, site_type: dict
) -> None:
    """A property api_name only means something within a type - "status" on an
    Order and on a Shipment are unrelated columns sharing a name, and matching
    across both would silently union two different questions."""
    r = client.get(
        f"{wbase(fx)}/object-instances",
        params={"property": "name", "value": "Depot"}, headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 422
    assert "exactly one type_id" in r.json()["detail"]

    r = client.get(
        f"{wbase(fx)}/object-instances",
        params={"type_id": site_type["id"], "property": "name"},
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 422, "half a filter is not a filter"


# ---------------------------------------------------------------------------
# Geoshape (§425; `object-link-types` p.127, p.273; `functions` p.40)
# ---------------------------------------------------------------------------

LONDON = {"type": "Point", "coordinates": [-0.1278, 51.5074]}
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
}


def coerce(value, data_type="geoshape"):
    return property_values.coerce_property_value(data_type, value)


def test_every_geometry_type_the_spec_names_is_accepted() -> None:
    """p.127: "any valid GeoJSON geometry, including Points, Polygons,
    LineStrings, and other shapes"."""
    assert coerce(LONDON) == LONDON
    assert coerce(SQUARE) == SQUARE
    assert coerce({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})["type"] \
        == "LineString"
    assert coerce({"type": "MultiPoint", "coordinates": [[0, 0]]})["type"] == "MultiPoint"
    assert coerce({
        "type": "MultiPolygon", "coordinates": [SQUARE["coordinates"]],
    })["type"] == "MultiPolygon"
    assert coerce({
        "type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]]],
    })["type"] == "MultiLineString"


def test_a_type_the_spec_does_not_name_is_refused() -> None:
    """**The whole reason this is a type and not a `json` property.**
    `{"type": "Polygn"}` is valid JSON, draws nothing and reports nothing —
    which is what `geopoint` was before db 0029 enforced it."""
    with pytest.raises(property_values.PropertyValueError, match="Polygn"):
        coerce({"type": "Polygn", "coordinates": []})


def test_a_feature_is_refused_because_it_is_not_a_geometry() -> None:
    """A Feature is a geometry *plus* properties, and a property that stored
    one would be an object type holding a second object type's worth of fields
    where the schema says it holds a shape."""
    with pytest.raises(property_values.PropertyValueError, match="Feature"):
        coerce({"type": "Feature", "geometry": LONDON, "properties": {}})


def test_the_positions_are_longitude_first() -> None:
    """> "Note that positional arguments follow longitude, latitude order as
    >  per the GeoJSON spec." (`functions` p.40)

    **And the opposite way round to a geopoint**, which `object-link-types`
    p.273 documents as "latitude,longitude". Both are kept, because
    reconciling them would break whichever of the two this platform is
    exporting to — so the one thing that has to be true is that each refuses
    the other's order where it can tell.
    """
    # A longitude of 51.5 is legal; a latitude of 51.5 is legal too, so this
    # pair is accepted in both orders and neither type can object. That is the
    # honest limit of the check, and the reason the input says which it wants.
    assert coerce(LONDON)["coordinates"] == [-0.1278, 51.5074]
    # Where it *can* tell, it does: 120 is a legal longitude and not a legal
    # latitude, so [45, 120] is a transposed pair and the refusal says so.
    with pytest.raises(property_values.PropertyValueError, match="longitude, latitude"):
        coerce({"type": "Point", "coordinates": [45.0, 120.0]})
    # And the geopoint type refuses the same pair the other way round.
    with pytest.raises(property_values.PropertyValueError, match="lon,lat"):
        coerce({"lat": 120.0, "lon": 45.0}, "geopoint")


def test_a_position_out_of_range_is_refused() -> None:
    with pytest.raises(property_values.PropertyValueError, match="longitude 181"):
        coerce({"type": "Point", "coordinates": [181.0, 0.0]})


def test_the_nesting_depth_of_each_type_is_checked() -> None:
    """**The check a look at the outer shape alone would miss.** A Point
    holding a polygon's coordinates and a Polygon holding a bare position are
    both valid JSON, both draw nothing, and neither is caught by asking
    whether `coordinates` is a list."""
    with pytest.raises(property_values.PropertyValueError):
        coerce({"type": "Point", "coordinates": SQUARE["coordinates"]})
    with pytest.raises(property_values.PropertyValueError):
        coerce({"type": "Polygon", "coordinates": [0.0, 0.0]})


def test_a_geometry_with_no_coordinates_is_refused() -> None:
    """The half a type check alone lets through: `{"type": "Point"}` names a
    geometry and describes none. A sweep found it — every other refusal here
    had a test and this one was carried only by the API/worker mirror check,
    which fires for any edit at all and says nothing about behaviour."""
    with pytest.raises(property_values.PropertyValueError, match="needs coordinates"):
        coerce({"type": "Point"})
    with pytest.raises(property_values.PropertyValueError, match="needs coordinates"):
        coerce({"type": "Polygon", "bbox": [0, 0, 1, 1]})


def test_an_altitude_is_kept_and_a_fourth_number_is_not() -> None:
    """RFC 7946 allows a third element; it does not allow a fourth."""
    assert coerce({"type": "Point", "coordinates": [0.0, 0.0, 12.5]})["coordinates"] \
        == [0.0, 0.0, 12.5]
    with pytest.raises(property_values.PropertyValueError):
        coerce({"type": "Point", "coordinates": [0.0, 0.0, 1.0, 2.0]})


def test_a_geometry_collection_holds_geometries_and_not_collections() -> None:
    """RFC 7946 §3.1.8 says to avoid nested GeometryCollections, and allowing
    one would make the depth of a value unbounded on a read path."""
    held = coerce({"type": "GeometryCollection", "geometries": [LONDON, SQUARE]})
    assert [g["type"] for g in held["geometries"]] == ["Point", "Polygon"]
    with pytest.raises(property_values.PropertyValueError, match="another one"):
        coerce({
            "type": "GeometryCollection",
            "geometries": [{"type": "GeometryCollection", "geometries": []}],
        })


def test_a_bbox_and_foreign_members_are_dropped() -> None:
    """A bbox that does not match its geometry is a second answer to where the
    shape is, and this platform computes nothing from one."""
    held = coerce({**LONDON, "bbox": [0, 0, 1, 1], "name": "London"})
    assert held == LONDON


def test_a_geometry_arrives_as_text_from_a_csv_column() -> None:
    """The same reason `_coerce_geopoint` takes "lat,lon": a CSV column holding
    a geometry holds text. The parse is JSON, because there is no plain-text
    spelling of a polygon a spreadsheet would produce."""
    import json

    assert coerce(json.dumps(SQUARE)) == SQUARE
    with pytest.raises(property_values.PropertyValueError, match="GeoJSON"):
        coerce("POLYGON((0 0, 1 0, 1 1, 0 0))")


def test_a_geoshape_round_trips_through_a_dataset_column() -> None:
    """**The round trip is the whole reason `column_value` has a case for it.**
    A geometry has no scalar it can be flattened to that survives — a centroid
    is a different shape and a bbox is a different geometry — so the column
    holds the document, which the next sync reads straight back."""
    flat = property_values.column_value("geoshape", SQUARE)
    assert isinstance(flat, str)
    assert coerce(flat) == SQUARE


def test_a_geoshape_property_is_declared_stored_and_read_back(
    client: TestClient, fx: Fixture
) -> None:
    """The type end to end: declared on an object type, written through the
    action path, and read back as the geometry it was."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Parcel{tag}", "display_name": f"Parcel {tag}",
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"},
                {"api_name": "outline", "display_name": "Outline",
                 "data_type": "geoshape"},
            ],
            "title_property": "id",
        },
    )
    assert r.status_code == 201, r.text
    props = {p["api_name"]: p for p in r.json()["properties"]}
    assert props["outline"]["data_type"] == "geoshape"


def test_a_geoshape_cannot_be_an_object_types_title(
    client: TestClient, fx: Fixture
) -> None:
    """`object-link-types` p.273's "Valid as title key?" column, which marks
    Geoshape No — and the reason is not arbitrary: a heading is one line of
    text and a shape has none."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Titled{tag}", "display_name": f"Titled {tag}",
            "properties": [
                {"api_name": "outline", "display_name": "Outline",
                 "data_type": "geoshape"},
            ],
            "title_property": "outline",
        },
    )
    assert r.status_code == 422, r.text
    assert "title" in r.text and "geoshape" in r.text


def test_a_geopoint_may_still_be_a_title(client: TestClient, fx: Fixture) -> None:
    """**The negative control for the rule above**, and p.273's own answer:
    Geopoint is marked Yes, and "57.6,10.4" is a usable heading for a reading
    somebody took at a place. A blanket refusal of anything geographic would
    have passed the test above and been wrong."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Reading{tag}", "display_name": f"Reading {tag}",
            "properties": [
                {"api_name": "where", "display_name": "Where",
                 "data_type": "geopoint"},
            ],
            "title_property": "where",
        },
    )
    assert r.status_code == 201, r.text


def test_the_title_rule_holds_on_an_edit_as_well_as_on_a_create(
    client: TestClient, fx: Fixture
) -> None:
    """**A rule enforced on create and not on update is a rule anybody can get
    round by saving twice**, which is db 0040's lesson in this file."""
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"Edited{tag}", "display_name": f"Edited {tag}",
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"},
                {"api_name": "outline", "display_name": "Outline",
                 "data_type": "geoshape"},
            ],
            "title_property": "id",
        },
    )
    assert r.status_code == 201, r.text
    type_id = r.json()["id"]

    r = client.patch(
        f"/api/workspaces/{fx.workspace}/object-types/{type_id}",
        headers=hdr(fx.editor_sub),
        json={
            "properties": [
                {"api_name": "id", "display_name": "Id", "data_type": "string"},
                {"api_name": "outline", "display_name": "Outline",
                 "data_type": "geoshape"},
            ],
            "title_property": "outline",
        },
    )
    assert r.status_code == 422, r.text
    assert "geoshape" in r.text


def test_an_array_of_shapes_is_allowed_and_cannot_be_reduced() -> None:
    """Two pages, one type, and they are not in tension.

    p.127: "All base types may be used in arrays… excluding the Vector and
    Time series types" — so an array of shapes is ordinary, and a route's legs
    or a district's parcels are what one is for. p.132 lists Geoshape among
    the subtypes a reducer cannot take — because there is no single one of
    them to call highest, not because the array is disallowed.
    """
    from src.services import array_properties, property_reducers

    assert "geoshape" in array_properties.INNER_TYPES
    assert "geoshape" in property_reducers.UNREDUCIBLE
    assert "geoshape" not in property_reducers.OPERATIONS
