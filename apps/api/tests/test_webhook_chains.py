"""Chained calls in one webhook (§523; db 0112; `data-connection` p.234-237).

    "A single webhook may contain multiple requests. Requests may be chained
     together, with response values from a previous call referenced in
     subsequent calls." (p.234)

Against `webhook_fixture_server.py`, through `test_webhook_calls.py`'s
fixtures, and asserting on what the far end *received*, for that file's
reason: a chain that extracted the right value and sent the wrong one is
wrong in a way no response can show.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_webhook_calls import (  # noqa: E402,F401
    _fresh_identity_cache, base, call, client, connection, fx, make, target,
)
from src.services import webhook_calls  # noqa: E402
from src.services import webhooks as wh  # noqa: E402


def created_step(**over) -> dict:
    step = {"method": "GET", "path": "created",
            "extract": [{"api_name": "unique_id", "path": "results.unique_id"},
                        {"api_name": "count", "path": "count"}]}
    step.update(over)
    return step


def history(client, fx, hook: dict) -> list[dict]:
    r = client.get(f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---- what goes out ---------------------------------------------------------------
def test_a_value_extracted_by_one_call_is_sent_by_the_next(client, fx, connection) -> None:
    """p.235's example: a GET whose response feeds a POST."""
    hook = make(client, fx, connection, steps=[created_step()],
                body={"id": "{{{unique_id}}}", "n": "{{{count}}}", "text": "made {{{unique_id}}}"},
                outputs=[{"api_name": "sent_id", "data_type": "string", "path": "body.id"}])
    assert hook["steps"] == [{"method": "GET", "path": "created", "body": None, "safe": False,
                              "extract": [{"api_name": "unique_id", "path": "results.unique_id"},
                                          {"api_name": "count", "path": "count"}]}]
    run = call(client, fx, hook)
    assert run["ok"] is True, run
    # A whole reference keeps the extracted value's type; one inside a
    # sentence is text.
    assert run["response_body"]["body"] == {"id": "X1", "n": 7, "text": "made X1"}
    assert run["outputs"] == {"sent_id": "X1"}
    # The history keeps each call: what went out, its status and its answer.
    [step] = run["request_body"]["steps"]
    assert (step["method"], step["url"].rsplit("/", 1)[1], step["status"]) == ("GET", "created", 201)
    assert step["response"] == {"results": {"unique_id": "X1"}, "count": 7}
    assert run["request_body"]["method"] == "POST"
    assert run["request_body"]["body"]["id"] == "X1"


def test_each_call_sees_the_inputs_and_what_came_before(client, fx, connection) -> None:
    hook = make(
        client, fx, connection, method="GET", path="echo/{{{segment}}}",
        inputs=[{"api_name": "name"}],
        steps=[
            # A POST that only reads, so p.237 allows the chain's other one.
            {"method": "POST", "path": "echo", "safe": True, "body": {"q": "{{{name}}}"},
             "extract": [{"api_name": "echoed", "path": "body.q"}]},
            {"method": "GET", "path": "echo/{{{echoed}}}",
             "extract": [{"api_name": "segment", "path": "path"}]},
        ])
    run = call(client, fx, hook, {"name": "Ada"})
    assert run["ok"] is True, run
    assert [s["url"].split("/", 3)[3] for s in run["request_body"]["steps"]] == ["echo", "echo/Ada"]
    # The last call's path is the second call's echoed path, percent-encoded
    # as any path value is.
    assert run["response_body"]["path"] == "/echo/%2Fecho%2FAda"


def test_the_source_s_credentials_are_fetched_once_per_chain(
    client, fx, connection, monkeypatch
) -> None:
    """An OAuth grant is itself a request, so a three-call chain asks for
    one token, not three."""
    asked: list[int] = []
    real = webhook_calls._auth

    def counting(config, secret):
        asked.append(1)
        return real(config, secret)

    monkeypatch.setattr(webhook_calls, "_auth", counting)
    hook = make(client, fx, connection, steps=[created_step(), {"method": "GET", "path": "echo"}])
    assert call(client, fx, hook)["ok"] is True
    assert len(asked) == 1


def test_a_whole_response_can_be_extracted(client, fx, connection) -> None:
    hook = make(client, fx, connection,
                steps=[created_step(extract=[{"api_name": "all", "path": "."}])],
                body={"got": "{{{all}}}"})
    run = call(client, fx, hook)
    assert run["response_body"]["body"] == {"got": {"results": {"unique_id": "X1"}, "count": 7}}


# ---- how a chain fails ----------------------------------------------------------
def test_a_failing_call_stops_the_chain_and_says_which(client, fx, connection) -> None:
    hook = make(client, fx, connection, steps=[created_step(), {"method": "GET", "path": "boom"}],
                body={"id": "{{{unique_id}}}"})
    run = call(client, fx, hook)
    assert (run["ok"], run["status_code"], run["error"]) == (
        False, 500, "call 2: the external system returned HTTP 500")
    # Both calls were reads, so the far end cannot have changed.
    assert run["system_changed"] is False
    assert [s["status"] for s in run["request_body"]["steps"]] == [201, 500]
    assert run["response_body"] == {"detail": "boom"}
    # The webhook's own request was never sent.
    assert "method" not in run["request_body"]


def test_a_failure_after_a_change_says_the_change_landed(client, fx, connection) -> None:
    """p.237: the history captures "whether the external system may have been
    changed". An earlier call that could change it and succeeded did."""
    hook = make(client, fx, connection, method="GET", path="refuse",
                steps=[{"method": "POST", "path": "echo", "body": {"a": 1}}])
    run = call(client, fx, hook)
    assert (run["ok"], run["status_code"], run["system_changed"]) == (False, 400, True)
    assert run["error"] == "the external system returned HTTP 400"
    later = make(client, fx, connection, method="GET", path="echo",
                 steps=[{"method": "POST", "path": "echo", "body": {"a": 1}},
                        {"method": "GET", "path": "boom"}])
    assert call(client, fx, later)["system_changed"] is True


def test_a_failing_call_that_may_change_things_is_judged_by_its_status(client, fx, connection) -> None:
    unknown = make(client, fx, connection, method="GET", path="echo",
                   steps=[{"method": "POST", "path": "boom", "body": {}}])
    assert call(client, fx, unknown)["system_changed"] is None
    refused = make(client, fx, connection, method="GET", path="echo",
                   steps=[{"method": "POST", "path": "refuse", "body": {}}])
    assert call(client, fx, refused)["system_changed"] is False
    # Marked safe, a POST that fails cannot have changed anything.
    safe = make(client, fx, connection, method="GET", path="echo",
                steps=[{"method": "POST", "path": "boom", "body": {}, "safe": True}])
    assert call(client, fx, safe)["system_changed"] is False


def test_a_call_that_extracts_needs_json_and_one_that_does_not_does_not(client, fx, connection) -> None:
    hook = make(client, fx, connection,
                steps=[{"method": "GET", "path": "text",
                        "extract": [{"api_name": "x", "path": "a"}]}])
    run = call(client, fx, hook)
    assert (run["ok"], run["error"]) == (False, "call 1: the external system did not return JSON")
    fine = make(client, fx, connection, steps=[{"method": "GET", "path": "text"}])
    assert call(client, fx, fine)["ok"] is True


def test_the_time_limit_is_for_the_whole_chain(client, fx, connection) -> None:
    """p.240: "the maximum duration a Webhook should execute for". Two
    two-second calls do not fit in three seconds, though each would alone."""
    hook = make(client, fx, connection, method="GET", path="echo", timeout_seconds=3,
                steps=[{"method": "GET", "path": "slow"}, {"method": "GET", "path": "slow"}])
    run = call(client, fx, hook)
    assert run["ok"] is False
    assert run["error"].startswith("call 2: could not reach the external system"), run["error"]
    assert 2800 <= run["duration_ms"] < 4500


def test_a_chain_s_bodies_are_not_kept_when_responses_are_not(client, fx, connection) -> None:
    hook = make(client, fx, connection, steps=[created_step()], store_responses=False)
    run = call(client, fx, hook)
    assert run["ok"] is True and run["request_body"] is None and run["response_body"] is None


def test_an_edit_replaces_the_chain(client, fx, connection) -> None:
    hook = make(client, fx, connection, steps=[created_step()])
    body = {k: hook[k] for k in ("connection_id", "display_name", "method", "path", "inputs",
                                 "outputs")}
    r = client.put(f"{base(fx)}/webhooks/{hook['id']}", headers=hdr(fx.editor_sub),
                   json={**body, "steps": []})
    assert r.status_code == 200 and r.json()["steps"] == []


# ---- what a chain may say --------------------------------------------------------
def parse(**over):
    return wh.parse({"method": "POST", **over})


@pytest.mark.parametrize("over, said", [
    ({"steps": [{"method": "PUT"}]},
     "a webhook may make only one call that can change the external system; "
     "mark an earlier call as safe if it only reads"),
    ({"method": "GET", "steps": [{"method": "POST"}, {"method": "DELETE"}]},
     "a webhook may make only one call that can change the external system; "
     "mark an earlier call as safe if it only reads"),
    ({"steps": {"method": "GET"}}, "the calls before the request must be a list"),
    ({"steps": [{"method": "GET"}] * 10}, "a webhook may make at most 9 calls before its request"),
    ({"steps": ["GET"]}, "call 1 must be an object"),
    ({"steps": [{"method": "FETCH"}]},
     "call 1: method must be one of GET, HEAD, OPTIONS, POST, PUT, PATCH, DELETE"),
    ({"steps": [{"method": "GET", "path": 3}]},
     "call 1: the path must be text of at most 2048 characters"),
    ({"steps": [{"method": "GET", "path": "x" * 2049}]},
     "call 1: the path must be text of at most 2048 characters"),
    ({"steps": [{"method": "GET", "body": {}}]}, "call 1: a GET request cannot carry a body"),
    ({"steps": [{"method": "POST", "safe": True, "body": {"x": "y" * 131072}}]},
     "call 1: the body is larger than 131072 bytes"),
    ({"steps": [{"method": "GET", "path": "a/{{{later}}}"},
                {"method": "GET", "extract": [{"api_name": "later", "path": "x"}]}]},
     "call 1: the path references {{{later}}}, which is neither an input nor extracted by an earlier call"),
    ({"steps": [{"method": "GET", "path": "a/{{{own}}}",
                 "extract": [{"api_name": "own", "path": "x"}]}]},
     "call 1: the path references {{{own}}}, which is neither an input nor extracted by an earlier call"),
    ({"steps": [{"method": "POST", "safe": True, "body": {"k": "{{{nope}}}"}}]},
     "call 1: the body references {{{nope}}}, which is neither an input nor extracted by an earlier call"),
    ({"path": "{{{nope}}}", "steps": [{"method": "GET"}]},
     "the path references {{{nope}}}, which is not an input of this webhook"),
    ({"steps": [{"method": "GET", "extract": {"a": "b"}}]}, "call 1: what it extracts must be a list"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": f"v{n}", "path": "x"} for n in range(51)]}]},
     "call 1: a call may extract at most 50 values"),
    ({"steps": [{"method": "GET", "extract": ["a"]}]},
     "call 1: each extracted value must be an object"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": "Bad", "path": "x"}]}]},
     "call 1: 'Bad' is not a valid name for an extracted value"),
    ({"inputs": [{"api_name": "name"}],
      "steps": [{"method": "GET", "extract": [{"api_name": "name", "path": "x"}]}]},
     "call 1: 'name' is already an input or an extracted value"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": "a", "path": "x"},
                                              {"api_name": "a", "path": "y"}]}]},
     "call 1: 'a' is already an input or an extracted value"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": "a", "path": "x"}]},
                {"method": "GET", "extract": [{"api_name": "a", "path": "y"}]}]},
     "call 2: 'a' is already an input or an extracted value"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": "a", "path": " "}]}]},
     "call 1: 'a' needs a path, or \".\" for the whole response"),
    ({"steps": [{"method": "GET", "extract": [{"api_name": "a"}]}]},
     "call 1: 'a' needs a path, or \".\" for the whole response"),
])
def test_a_chain_that_could_not_run_is_refused(over, said) -> None:
    with pytest.raises(wh.WebhookError) as caught:
        parse(**over)
    assert str(caught.value) == said


def test_what_a_chain_may_say() -> None:
    # Nine calls, the most there may be; the method in any case.
    assert len(parse(steps=[{"method": "get"}] * 9)["steps"]) == 9
    # A POST marked safe leaves room for the request's own change.
    [step] = parse(steps=[{"method": "POST", "safe": True, "body": {"a": 1}}])["steps"]
    assert (step["method"], step["safe"], step["body"]) == ("POST", True, {"a": 1})
    # A read-only request lets one step change things.
    assert parse(method="GET", steps=[{"method": "DELETE"}])["steps"][0]["safe"] is False
    # Extracted values are references for later calls and the request, and a
    # path is trimmed.
    parsed = parse(inputs=[{"api_name": "who"}], path="x/{{{b}}}",
                   steps=[{"method": "GET", "path": "{{{who}}}",
                           "extract": [{"api_name": "a", "path": " data.id "}]},
                          {"method": "GET", "path": "{{{a}}}/{{{who}}}",
                           "extract": [{"api_name": "b", "path": "."}]}])
    assert parsed["steps"][0]["extract"] == [{"api_name": "a", "path": "data.id"}]
    assert parse()["steps"] == []


def test_the_browser_allows_as_many_calls_as_the_server() -> None:
    source = open(os.path.join(os.path.dirname(__file__), "..", "..", "web", "src", "lib",
                               "webhook-steps.ts")).read()
    assert f"export const MAX_STEPS = {wh.MAX_STEPS};" in source
