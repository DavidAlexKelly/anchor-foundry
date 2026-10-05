"""Attachments in functions (§785; decision 0018 option B; `functions`
"Attachments").

> "Attachments can be passed into functions as inputs from actions, or
> accessed as properties on objects." … "A read method is provided on
> attachments to read their raw data." … "we recommend only interacting with
> attachments under 20MB."

A SQL function reads one with `read_attachment(...)`, given an attachment
parameter or an attachment property's value, and gets its bytes as a BLOB;
`decode(...)` makes text of them.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_api import hdr  # noqa: E402
from test_function_actions import (  # noqa: E402,F401
    _fresh_identity_cache, action, client, define, fx, held, rule, run, tickets, wbase,
)
from src.services import function_engine  # noqa: E402


def upload(client, fx, name: str, data: bytes, ctype: str = "text/plain") -> dict:
    r = client.post(f"{wbase(fx)}/attachments", headers=hdr(fx.editor_sub),
                    files={"file": (name, io.BytesIO(data), ctype)})
    assert r.status_code == 201, r.text
    return r.json()


def function(client, fx, sql: str, parameters: list[dict], output=None, inputs=None):
    return client.post(f"{wbase(fx)}/functions", headers=hdr(fx.editor_sub), json={
        "api_name": f"fn_{uuid.uuid4().hex[:6]}", "display_name": "F", "version": {
            "version": "1.0.0", "inputs": inputs or [], "parameters": parameters,
            "output": output or {"kind": "value", "data_type": "string"}, "sql": sql}})


def call(client, fx, fn_id: str, values: dict):
    return client.post(f"{wbase(fx)}/functions/{fn_id}/execute", headers=hdr(fx.editor_sub),
                       json={"values": values})


FILE = {"api_name": "file", "data_type": "attachment"}


def test_an_attachment_parameter_is_read_as_its_bytes(client, fx) -> None:
    fn = function(client, fx, "SELECT decode(read_attachment($file))", [FILE])
    assert fn.status_code == 201, fn.text
    ref = upload(client, fx, "note.txt", b"hello, file")
    r = call(client, fx, fn.json()["id"], {"file": ref})
    assert r.status_code == 200, r.text
    assert r.json()["value"] == "hello, file"
    # Its size, as bytes rather than characters.
    fn = function(client, fx, "SELECT octet_length(read_attachment($file))::INTEGER",
                  [FILE], output={"kind": "value", "data_type": "integer"})
    assert call(client, fx, fn.json()["id"], {"file": upload(
        client, fx, "é.txt", "é".encode())}).json()["value"] == 2


def test_nothing_reads_as_nothing(client, fx) -> None:
    fn = function(client, fx, "SELECT coalesce(decode(read_attachment($file)), 'none')",
                  [{**FILE, "required": False}])
    assert fn.status_code == 201, fn.text
    assert call(client, fx, fn.json()["id"], {}).json()["value"] == "none"


def test_an_attachment_property_is_read_from_its_object(client, fx) -> None:
    ref = upload(client, fx, "log.txt", b"engine checked")
    tag = uuid.uuid4().hex[:6]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["key", "log"])
    writer.writerow(["P1", json.dumps(ref)])
    writer.writerow(["P2", ""])
    dataset = client.post(
        f"{wbase(fx)}/projects/{fx.project}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"planes {tag}"},
        files={"file": ("planes.csv", io.BytesIO(out.getvalue().encode()), "text/csv")})
    assert dataset.status_code == 201, dataset.text
    made = client.post(f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub), json={
        "api_name": f"plane_{tag}", "display_name": f"Plane {tag}",
        "properties": [{"api_name": "key", "data_type": "string"},
                       {"api_name": "log", "data_type": "attachment"}],
        "title_property": "key"})
    assert made.status_code == 201, made.text
    source = client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": made.json()["id"], "dataset_id": dataset.json()["id"],
              "primary_key_column": "key", "column_mappings": {"key": "key", "log": "log"}})
    assert source.status_code == 201, source.text
    assert client.post(
        f"{wbase(fx)}/projects/{fx.project}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub)).status_code == 200
    fn = function(client, fx,
                  f"SELECT __primary_key, decode(read_attachment(log)) AS text "
                  f"FROM plane_{tag} ORDER BY 1",
                  [], output={"kind": "table"}, inputs=[made.json()["id"]])
    assert fn.status_code == 201, fn.text
    r = call(client, fx, fn.json()["id"], {})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] == [["P1", "engine checked"], ["P2", None]]


@pytest.mark.parametrize("value, said", [
    ({"key": "workspaces/elsewhere/attachments/x/f.txt", "filename": "f.txt",
      "content_type": "text/plain", "size": 1},
     "read_attachment reads this workspace's attachments only"),
])
def test_an_attachment_from_elsewhere_is_refused(client, fx, value, said) -> None:
    fn = function(client, fx, "SELECT decode(read_attachment($file))", [FILE])
    r = call(client, fx, fn.json()["id"], {"file": value})
    assert r.status_code == 422, r.text
    # The sentence itself, not DuckDB's report of a Python exception.
    assert r.json()["detail"] == said


def test_a_key_typed_into_the_sql_is_held_to_the_same_rule(client, fx) -> None:
    """The function reads what its caller may: a key written into the query
    is checked as a parameter's is, so no query reads another tenant's bytes."""
    fn = function(client, fx,
                  "SELECT decode(read_attachment('workspaces/other/datasets/d/data.parquet'))",
                  [])
    assert fn.status_code == 201, fn.text
    r = call(client, fx, fn.json()["id"], {})
    assert r.status_code == 422, r.text
    assert "read_attachment reads this workspace's attachments only" in r.text


def test_an_attachment_that_is_gone_is_said(client, fx) -> None:
    ref = upload(client, fx, "a.txt", b"x")
    fn = function(client, fx, "SELECT decode(read_attachment($file))", [FILE])
    gone = {**ref, "key": ref["key"].rsplit("/", 2)[0] + f"/{uuid.uuid4()}/a.txt"}
    r = call(client, fx, fn.json()["id"], {"file": gone})
    assert r.status_code == 422, r.text
    assert "no attachment a.txt" in r.text


def test_the_20mb_limit(client, fx, monkeypatch) -> None:
    assert function_engine.MAX_ATTACHMENT_BYTES == 20 * 1024 * 1024
    monkeypatch.setattr(function_engine, "MAX_ATTACHMENT_BYTES", 4)
    fn = function(client, fx, "SELECT decode(read_attachment($file))", [FILE])
    r = call(client, fx, fn.json()["id"], {"file": upload(client, fx, "big.txt", b"12345")})
    assert r.status_code == 422, r.text
    assert "big.txt is larger than the 20 MB a function reads" in r.text


def test_an_attachment_parameter_from_an_action(client, fx, tickets) -> None:
    """ "passed into functions as inputs from actions": the action's
    attachment parameter feeds the function, which writes its text."""
    t = tickets["api_name"]
    fn = function(client, fx,
                  f"SELECT __primary_key, decode(read_attachment($file)) AS title FROM {t} "
                  "WHERE __primary_key = $ticket",
                  [{"api_name": "ticket", "data_type": "object",
                    "object_type_id": tickets["type_id"]}, FILE],
                  output={"kind": "edits", "object_type_id": tickets["type_id"]},
                  inputs=[tickets["type_id"]])
    assert fn.status_code == 201, fn.text
    act = action(client, fx, tickets)
    r = define(client, fx, act, [rule(fn.json(), inputs={
        "ticket": {"subject": True}, "file": {"parameter": "file"}})],
        [{"api_name": "file", "display_name": "File", "data_type": "attachment"}])
    assert r.status_code == 200, r.text
    ref = upload(client, fx, "title.txt", b"From the file")
    r = run(client, fx, act, tickets["T1"], {"file": ref})
    assert r.status_code == 200, r.text
    assert held(client, fx, tickets["type_id"])["T1"]["title"] == "From the file"


def test_a_bare_key_is_a_reference_too_and_a_number_is_not(client, fx) -> None:
    fn = function(client, fx, "SELECT decode(read_attachment($file))", [FILE])
    ref = upload(client, fx, "k.txt", b"by key")
    assert call(client, fx, fn.json()["id"], {"file": ref["key"]}).json()["value"] == "by key"
    r = call(client, fx, fn.json()["id"], {"file": 5})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "file: 5 is not a attachment"


def test_one_call_reads_at_most_100mb(client, fx, monkeypatch) -> None:
    assert function_engine.MAX_ATTACHMENT_TOTAL == 100 * 1024 * 1024
    monkeypatch.setattr(function_engine, "MAX_ATTACHMENT_TOTAL", 6)
    fn = function(client, fx, "SELECT decode(read_attachment($a)) || decode(read_attachment($b))",
                  [{**FILE, "api_name": "a"}, {**FILE, "api_name": "b"}])
    a, b = upload(client, fx, "a.txt", b"1234"), upload(client, fx, "b.txt", b"5678")
    r = call(client, fx, fn.json()["id"], {"a": a, "b": b})
    assert r.status_code == 422, r.text
    assert r.json()["detail"] == "the function read more than 100 MB of attachments"
