"""A parameter added after an action's log was turned on (§792; `action-types`
p.168).

> "By default, action log object types store: … [Optional] Parameter
> values" (p.168)

Saving the definition gives the log a column for each parameter it has none
for, so the next submission stores its value and the entries before it read
as empty.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_action_log import (  # noqa: E402,F401
    _fresh_identity_cache, apply, client, fx, hdr, log_of, objects, pbase, wbase, world,
)

DEFINITION = {
    "rules": [{"kind": "modify_object", "config": {"property": "status", "parameter": "status"}}],
    "criteria": [],
}


def define(client, fx, world, parameters: list[dict]) -> dict:
    r = client.put(f"{wbase(fx)}/action-types/{world['action_id']}/definition",
                   headers=hdr(fx.editor_sub), json={**DEFINITION, "parameters": parameters})
    assert r.status_code == 200, r.text
    return r.json()


def log_source(client, fx, world) -> dict:
    r = client.get(f"{pbase(fx)}/object-type-sources", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return next(s for s in r.json() if s["object_type_id"] == world["log_object_type_id"])


def log_versions(client, fx, world) -> int:
    dataset = log_source(client, fx, world)["dataset_id"]
    r = client.get(f"{pbase(fx)}/datasets/{dataset}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()["current_version"]


STATUS = {"api_name": "status", "display_name": "Status", "data_type": "string"}
NOTE = {"api_name": "note", "display_name": "Note", "data_type": "string", "required": False}


def test_a_new_parameter_gets_its_column_and_its_value_logged(client, fx, world) -> None:
    define(client, fx, world, [STATUS])
    before = apply(client, fx, world, "A1", {"status": "closed"})
    versions = log_versions(client, fx, world)

    define(client, fx, world, [STATUS, NOTE])
    log_type = client.get(f"{wbase(fx)}/object-types/{world['log_object_type_id']}",
                          headers=hdr(fx.viewer_sub)).json()
    assert "param_note" in [p["api_name"] for p in log_type["properties"]]
    # The dataset gained the column as one new version.
    assert log_versions(client, fx, world) == versions + 1

    after = apply(client, fx, world, "A2", {"status": "closed", "note": "duplicate"})
    assert log_of(client, fx, world, after)["param_note"] == "duplicate"
    assert log_of(client, fx, world, before).get("param_note") is None

    # Saved again with nothing new, the log is left as it is.
    now = log_versions(client, fx, world)
    define(client, fx, world, [STATUS, NOTE])
    assert log_versions(client, fx, world) == now


def test_the_entries_survive_a_re_sync_with_the_new_column(client, fx, world) -> None:
    define(client, fx, world, [STATUS, NOTE, {**NOTE, "api_name": "reason",
                                              "display_name": "Reason"}])
    run = apply(client, fx, world, "A3", {"status": "open", "reason": "reopened"})
    source = log_source(client, fx, world)
    r = client.post(f"{pbase(fx)}/object-type-sources/{source['id']}/sync",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert log_of(client, fx, world, run)["param_reason"] == "reopened"


def test_an_object_parameter_gets_no_column(client, fx, world) -> None:
    """Its value is an instance id, which the log does not keep (p.168's
    "property values of object reference parameters" is §586's)."""
    define(client, fx, world, [STATUS, NOTE, {
        "api_name": "other", "display_name": "Other", "data_type": "object",
        "object_type_id": world["type_id"], "required": False}])
    log_type = client.get(f"{wbase(fx)}/object-types/{world['log_object_type_id']}",
                          headers=hdr(fx.viewer_sub)).json()
    assert "param_other" not in [p["api_name"] for p in log_type["properties"]]


def test_a_log_whose_source_is_gone_is_left_alone(client, fx, world) -> None:
    """Its definition still saves: there is no dataset to give a column to."""
    import uuid

    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json={
        "object_type_id": world["type_id"], "api_name": f"act_{uuid.uuid4().hex[:6]}",
        "display_name": f"Act {uuid.uuid4().hex[:4]}", "editable_properties": ["status"]})
    action = {**world, "action_id": r.json()["id"]}
    define(client, fx, action, [STATUS])
    made = client.post(f"{pbase(fx)}/actions/{action['action_id']}/log",
                       headers=hdr(fx.editor_sub))
    assert made.status_code == 201, made.text
    action["log_object_type_id"] = made.json()["log_object_type_id"]
    gone = client.delete(f"{pbase(fx)}/object-type-sources/{log_source(client, fx, action)['id']}",
                         headers=hdr(fx.editor_sub))
    assert gone.status_code == 204, gone.text
    define(client, fx, action, [STATUS, NOTE])


def test_a_column_the_file_already_has_is_kept(tmp_path) -> None:
    import duckdb

    from src.services import dataset_engine

    source = str(tmp_path / "in.parquet")
    duckdb.connect().execute(
        f"COPY (SELECT 'r1' AS action_rid, 'x' AS param_note) TO '{source}' (FORMAT parquet)")
    schema, rows = dataset_engine.add_columns(
        source, ["param_note", "param_new"], str(tmp_path / "out" / "out.parquet"))
    assert [c.name for c in schema] == ["action_rid", "param_note", "param_new"]
    assert rows == 1
    assert duckdb.connect().execute(
        f"SELECT param_note, param_new FROM read_parquet('{tmp_path / 'out' / 'out.parquet'}')"
    ).fetchall() == [("x", None)]
