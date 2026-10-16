"""A SQL model's run that outlasts its request carries on and says so (§969).

The same remedy as a sync's (§967): a run the API is still doing when an
answer would no longer reach the browser answers 202 with the run it carries
on under, and that run then ends as it would have. The wait is set to nothing
rather than the run made slow, so every run here outlasts its request.
"""
from __future__ import annotations

import os
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, hdr  # noqa: E402
from test_export_runs import base, client, fx, storage_root, upload  # noqa: E402,F401 (fixtures)
from src.lib import long_work  # noqa: E402


def a_model(client: TestClient, fx: Fixture, code: str = "SELECT * FROM orders") -> str:
    source = upload(client, fx, "id,email\n1,ada@example.com\n2,grace@example.com\n")
    r = client.post(f"{base(fx)}/models", headers=hdr(fx.editor_sub),
                    json={"name": f"Long {uuid.uuid4().hex[:6]}", "code": code,
                          "inputs": [{"dataset_id": source, "input_alias": "orders"}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def settled(client: TestClient, fx: Fixture, model_id: str, run_id: str) -> dict:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        runs = client.get(f"{base(fx)}/models/{model_id}/runs", headers=hdr(fx.viewer_sub)).json()
        run = next(r for r in runs if r["id"] == run_id)
        if run["status"] not in ("queued", "running"):
            return run
        time.sleep(0.1)
    raise AssertionError(f"run {run_id} still running")


def test_a_run_that_outlasts_its_request_answers_with_its_run(
    client: TestClient, fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(long_work, "ANSWER_WITHIN_S", 0)
    model_id = a_model(client, fx)
    r = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 202, r.text
    assert (r.json()["status"], r.json()["output_dataset"]) == ("running", None)
    run = settled(client, fx, model_id, r.json()["run_id"])
    assert (run["status"], run["rows_produced"]) == ("succeeded", 2)
    model = client.get(f"{base(fx)}/models/{model_id}", headers=hdr(fx.viewer_sub)).json()
    assert model["output_dataset_id"]


def test_one_that_fails_after_answering_says_so_in_its_run(
    client: TestClient, fx: Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(long_work, "ANSWER_WITHIN_S", 0)
    model_id = a_model(client, fx, code="SELECT no_such_column FROM orders")
    r = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 202, r.text
    run = settled(client, fx, model_id, r.json()["run_id"])
    assert run["status"] == "failed" and "no_such_column" in run["error_message"]


def test_a_run_that_finishes_in_time_answers_as_it_always_did(
    client: TestClient, fx: Fixture
) -> None:
    model_id = a_model(client, fx)
    r = client.post(f"{base(fx)}/models/{model_id}/run", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "succeeded" and r.json()["output_dataset"]
