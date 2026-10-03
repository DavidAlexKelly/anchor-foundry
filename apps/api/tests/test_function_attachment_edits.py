"""Attachments a function creates (§786; decision 0018 option B; `functions`
"Attachments").

> "You can also create and return attachments in functions." … "For
> attachments created in functions to be persisted, the function must make
> an Ontology edit that links the attachment to an object."

A SQL function writes a new file as an attachment property's value: a JSON
object naming its `filename` and its `content` as text, or its `base64`
bytes. The action stores the file, as an upload is stored, and sets the
property to its reference; the function's own run in the helper stores
nothing ("edits are not applied").
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_function_actions import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, wbase,
)
from src.services import function_engine  # noqa: E402


@pytest.fixture
def planes(client, fx) -> dict:
    tag = uuid.uuid4().hex[:6]
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"planes {tag}"},
        files={"file": ("planes.csv", io.BytesIO(b"key,tail,log\nP1,G-AAAA,\nP2,G-BBBB,\n"),
                        "text/csv")})
    assert dataset.status_code == 201, dataset.text
    made = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"plane_{tag}", "display_name": f"Plane {tag}",
        "properties": [{"api_name": "key", "data_type": "string"},
                       {"api_name": "tail", "data_type": "string"},
                       {"api_name": "log", "data_type": "attachment"}],
        "title_property": "key"})
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "key",
              "column_mappings": {"key": "key", "tail": "tail", "log": "log"}})
    assert source.status_code == 201, source.text
    assert client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub)).status_code == 200
    items = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return {"type_id": type_id, "api_name": f"plane_{tag}",
            **{i["primary_key"]: i["id"] for i in items}}


def backed(client, fx, planes, value_sql: str) -> str:
    """An action on a plane whose function sets its log to `value_sql`."""
    p = planes["api_name"]
    made = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [planes["type_id"]],
            "parameters": [{"api_name": "plane", "data_type": "object",
                            "object_type_id": planes["type_id"]}],
            "output": {"kind": "edits", "object_type_ids": [planes["type_id"]]},
            "sql": (f"SELECT '{p}' AS __object_type, __primary_key, 'modify' AS __edit, "
                    f"json_object('log', {value_sql}) AS __properties FROM {p} "
                    "WHERE __primary_key = $plane")}})
    assert made.status_code == 201, made.text
    act = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": planes["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": "Act", "editable_properties": ["tail"]})
    assert act.status_code == 201, act.text
    r = client.put(f"{wbase(fx)}/action-types/{act.json()['id']}/definition",
                   headers=hdr(fx.editor_sub), json={
                       "parameters": [], "criteria": [], "rules": [{"kind": "function", "config": {
                           "function_id": made.json()["id"], "version": "1.0.0",
                           "auto_upgrade": False, "inputs": {"plane": {"subject": True}}}}]})
    assert r.status_code == 200, r.text
    return act.json()["id"]


def run(client, fx, planes, act: str, key: str = "P1"):
    return client.post(
        f"{wbase(fx)}/projects/{fx.project}/actions/{act}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": planes[key], "values": {}})


def log_of(client, fx, planes, key: str = "P1") -> dict | None:
    items = client.get(f"{wbase(fx)}/object-types/{planes['type_id']}/instances",
                       headers=hdr(fx.viewer_sub)).json()["items"]
    return next(i for i in items if i["primary_key"] == key)["properties"].get("log")


def download(client, fx, ref: dict) -> bytes:
    r = client.get(f"{wbase(fx)}/attachments/download", headers=hdr(fx.viewer_sub),
                   params={"key": ref["key"]})
    assert r.status_code == 200, r.text
    return r.content


def test_a_function_writes_a_text_file_onto_its_object(client, fx, planes) -> None:
    act = backed(client, fx, planes,
                 "json_object('filename', 'maintenance-log.txt', 'content', "
                 "'checked ' || tail)")
    r = run(client, fx, planes, act)
    assert r.status_code == 200, r.text
    ref = log_of(client, fx, planes)
    assert (ref["filename"], ref["content_type"], ref["size"]) == (
        "maintenance-log.txt", "text/plain", len("checked G-AAAA"))
    assert download(client, fx, ref) == b"checked G-AAAA"
    # Stored as an upload is, under the workspace's attachments.
    assert "/attachments/" in ref["key"] and ref["key"].endswith("/maintenance-log.txt")
    assert log_of(client, fx, planes, "P2") is None


def test_a_function_writes_bytes_as_base64(client, fx, planes) -> None:
    act = backed(client, fx, planes,
                 "json_object('filename', 'raw.bin', 'base64', base64('\\x00\\x01\\xFF'::BLOB))")
    r = run(client, fx, planes, act)
    assert r.status_code == 200, r.text
    ref = log_of(client, fx, planes)
    assert ref["content_type"] == "application/octet-stream"
    assert download(client, fx, ref) == b"\x00\x01\xff"


def test_running_it_in_the_helper_stores_nothing(client, fx, planes) -> None:
    """functions: "When you run an Ontology edit function in the functions
    helper in Authoring, edits are not applied" - so no file is written,
    and the edit says what it would write."""
    act = backed(client, fx, planes, "json_object('filename', 'a.txt', 'content', 'x')")
    defined = client.get(f"{wbase(fx)}/action-types/{act}", headers=hdr(fx.viewer_sub)).json()
    fn_id = next(r for r in defined["rules"] if r["kind"] == "function")["config"]["function_id"]
    r = client.post(f"{wbase(fx)}/functions/{fn_id}/execute", headers=hdr(fx.editor_sub),
                    json={"values": {"plane": planes["P1"]}})
    assert r.status_code == 200, r.text
    assert r.json()["edits"][0]["properties"]["log"] == {"filename": "a.txt", "content": "x"}
    assert log_of(client, fx, planes) is None


@pytest.mark.parametrize("value_sql, said", [
    ("json_object('content', 'x')", "a new attachment names its filename"),
    ("json_object('filename', 'a.txt')", "a new attachment gives its content or its base64"),
    ("json_object('filename', 'a.txt', 'content', 'x', 'base64', 'eA==')",
     "a new attachment gives its content or its base64"),
    # Valid base64 with a stray character, which a lenient decoder would drop.
    ("json_object('filename', 'a.bin', 'base64', 'eA==!')",
     "a.bin's base64 is not base64"),
    ("json_object('filename', '  ', 'content', 'x')", "a new attachment names its filename"),
    # Not a new file at all: the attachment's own check says what it lacks.
    ("json_object('x', 1)", "attachment is missing key, filename, content_type, size"),
    ("json_object('filename', 'a.txt', 'content', '')", "a.txt is empty"),
])
def test_a_file_that_cannot_be_written_fails_the_action(client, fx, planes, value_sql,
                                                         said) -> None:
    act = backed(client, fx, planes, value_sql)
    r = run(client, fx, planes, act)
    assert r.status_code == 422, r.text
    assert said in r.json()["detail"], r.text
    assert log_of(client, fx, planes) is None


def test_the_20mb_limit(client, fx, planes, monkeypatch) -> None:
    monkeypatch.setattr(function_engine, "MAX_ATTACHMENT_BYTES", 4)
    act = backed(client, fx, planes, "json_object('filename', 'big.txt', 'content', '12345')")
    r = run(client, fx, planes, act)
    assert r.status_code == 422, r.text
    assert "big.txt is larger than the 20 MB a function writes" in r.json()["detail"]


def test_an_inline_edit_stores_the_file_too(client, fx, planes) -> None:
    act = backed(client, fx, planes, "json_object('filename', 'row.txt', 'content', tail)")
    r = client.post(f"{wbase(fx)}/projects/{fx.project}/actions/{act}/execute-batch",
                    headers=hdr(fx.editor_sub),
                    json={"edits": [{"instance_id": planes["P2"], "values": {}}]})
    assert r.status_code == 200, r.text
    ref = log_of(client, fx, planes, "P2")
    assert ref["filename"] == "row.txt"
    assert download(client, fx, ref) == b"G-BBBB"


def test_a_file_named_unsafely_is_stored_under_a_safe_name(client, fx, planes) -> None:
    act = backed(client, fx, planes,
                 "json_object('filename', 'my log/../x.txt', 'content', 'x')")
    assert run(client, fx, planes, act).status_code == 200
    ref = log_of(client, fx, planes)
    assert ref["filename"] == "my_log_._x.txt"
    assert ref["key"].endswith("/my_log_._x.txt")


def test_the_one_type_shape_writes_a_file_too(client, fx, planes) -> None:
    """§773's shape gives a column its JSON as text."""
    p = planes["api_name"]
    made = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [planes["type_id"]],
            "parameters": [{"api_name": "plane", "data_type": "object",
                            "object_type_id": planes["type_id"]}],
            "output": {"kind": "edits", "object_type_id": planes["type_id"]},
            "sql": (f"SELECT __primary_key, json_object('filename', 'w.txt', 'content', "
                    f"'wide') AS log FROM {p} WHERE __primary_key = $plane")}})
    assert made.status_code == 201, made.text
    act = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": planes["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": "Act", "editable_properties": ["tail"]}).json()["id"]
    assert client.put(f"{wbase(fx)}/action-types/{act}/definition",
                      headers=hdr(fx.editor_sub), json={
                          "parameters": [], "criteria": [], "rules": [{"kind": "function",
                          "config": {"function_id": made.json()["id"], "version": "1.0.0",
                                     "auto_upgrade": False,
                                     "inputs": {"plane": {"subject": True}}}}]}).status_code == 200
    r = run(client, fx, planes, act)
    assert r.status_code == 200, r.text
    assert download(client, fx, log_of(client, fx, planes)) == b"wide"


def test_a_file_for_a_property_that_is_not_an_attachment_is_not_stored(
    client, fx, planes, monkeypatch
) -> None:
    from src.services import action_functions

    stored: list[str] = []
    real = action_functions.storage_service.current()

    class Watching:
        def put(self, key, data):
            stored.append(key)
            return real.put(key, data)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(action_functions.storage_service, "current", lambda: Watching())
    p = planes["api_name"]
    made = client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": [planes["type_id"]],
            "parameters": [{"api_name": "plane", "data_type": "object",
                            "object_type_id": planes["type_id"]}],
            "output": {"kind": "edits", "object_type_ids": [planes["type_id"]]},
            "sql": (f"SELECT '{p}' AS __object_type, __primary_key, 'modify' AS __edit, "
                    "json_object('tail', json_object('filename', 't.txt', 'content', 'x')) "
                    f"AS __properties FROM {p} WHERE __primary_key = $plane")}})
    assert made.status_code == 201, made.text
    act = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": planes["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": "Act", "editable_properties": ["tail"]}).json()["id"]
    assert client.put(f"{wbase(fx)}/action-types/{act}/definition",
                      headers=hdr(fx.editor_sub), json={
                          "parameters": [], "criteria": [], "rules": [{"kind": "function",
                          "config": {"function_id": made.json()["id"], "version": "1.0.0",
                                     "auto_upgrade": False,
                                     "inputs": {"plane": {"subject": True}}}}]}).status_code == 200
    r = run(client, fx, planes, act)
    assert r.status_code == 422, r.text
    assert "expected a string" in r.json()["detail"]
    assert stored == []

