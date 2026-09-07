"""Webhooks end to end, against a real socket (decision 0012; §259).

`test_webhooks.py` is what a definition *means*; this is what actually goes out
and what comes back. Against `webhook_fixture_server.py` in its own process,
for `test_rest_connector.py`'s reason: a patched `urlopen` tests the patch's
shape rather than the request.

**Most of these assert on what the server received**, not on what it answered,
and that is the whole point of the fixture echoing. A webhook that sent
`{"count": "3"}` where `{"count": 3}` was configured is wrong in a way no
assertion about a response can see.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

SERVER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "webhook_fixture_server.py"
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def target() -> str:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, SERVER, str(port)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.25)
    else:  # pragma: no cover - environment guard
        proc.terminate()
        pytest.skip("fixture server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def connection(client: TestClient, fx: Fixture, target: str) -> str:
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={
            "name": f"Target {fx.tag}", "source_type": "rest", "scope": "project",
            # allow_insecure_http because the fixture is plain http on
            # localhost, which is the opt-in that flag exists for.
            "config": {"base_url": target, "allow_insecure_http": True},
            "secret": {},
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make(client: TestClient, fx: Fixture, connection: str, **over) -> dict:
    payload = {
        "connection_id": connection,
        "api_name": f"hook_{uuid.uuid4().hex[:8]}",
        "display_name": "Modify ticket priority",
        "method": "POST",
        "path": "echo",
    }
    payload.update(over)
    r = client.post(f"{base(fx)}/webhooks", headers=hdr(fx.editor_sub), json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def call(client: TestClient, fx: Fixture, hook: dict, values=None, sub=None) -> dict:
    r = client.post(
        f"{base(fx)}/webhooks/{hook['id']}/test",
        headers=hdr(sub or fx.editor_sub), json={"values": values or {}},
    )
    assert r.status_code == 200, r.text
    return r.json()


# ---- the request that goes out ---------------------------------------------------
def test_the_configured_request_is_what_arrives(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """The claim everything else rests on, asserted against what the server
    saw rather than what it said."""
    hook = make(
        client, fx, connection,
        method="PUT",
        query={"tenant": "acme"},
        headers={"X-Trace": "abc"},
        body={"text": "{{{name}}}"},
        inputs=[{"api_name": "name"}],
    )
    run = call(client, fx, hook, {"name": "Ada"})
    assert run["ok"], run
    echoed = run["response_body"]
    assert echoed["method"] == "PUT"
    assert echoed["query"] == {"tenant": "acme"}
    assert echoed["headers"]["x-trace"] == "abc"
    assert echoed["body"] == {"text": "Ada"}


def test_a_whole_reference_arrives_with_its_own_type(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """**The one that a response-only assertion cannot see.** `{"count": "3"}`
    is a different document from `{"count": 3}` — most servers reject it and
    some accept it as something else — and both look identical in a webhook
    whose far end just says 200."""
    hook = make(
        client, fx, connection,
        body={"count": "{{{count}}}", "label": "n={{{count}}}"},
        inputs=[{"api_name": "count", "data_type": "integer"}],
    )
    run = call(client, fx, hook, {"count": 3})
    assert run["response_body"]["body"] == {"count": 3, "label": "n=3"}


def test_a_path_reference_is_encoded_before_it_becomes_a_url(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """A value holding `/` would otherwise be a routing decision: the request
    would arrive at a different endpoint than the one configured, and the
    webhook would look like it worked."""
    hook = make(
        client, fx, connection, path="echo/{{{id}}}",
        inputs=[{"api_name": "id"}],
    )
    run = call(client, fx, hook, {"id": "a/b"})
    # One segment, not two. The server reports the raw path it was asked for.
    assert run["response_body"]["path"] == "/echo/a%2Fb"


def test_a_missing_required_input_never_reaches_the_network(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """A fault in the call rather than in the response, so it is a 4xx and
    leaves no row: recording it would put a failure in the history for a
    request that was never made."""
    hook = make(
        client, fx, connection, body={"t": "{{{name}}}"},
        inputs=[{"api_name": "name"}],
    )
    r = client.post(
        f"{base(fx)}/webhooks/{hook['id']}/test",
        headers=hdr(fx.editor_sub), json={"values": {}},
    )
    assert r.status_code == 422, r.text
    assert "missing required input" in r.json()["detail"]

    runs = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub)
    ).json()
    assert runs["total"] == 0


def test_the_connections_credential_is_sent_and_is_not_recorded(
    client: TestClient, fx: Fixture, target: str
) -> None:
    """Two halves of p.242, and neither is worth checking without the other.

    The credential has to *arrive*, or the webhook is broken; and it must not
    be in the history, or the history is a place credentials leak to. A test
    for either alone passes against an implementation that sends nothing, or
    against one that stores everything.
    """
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={
            "name": f"Secured {fx.tag}", "source_type": "rest", "scope": "project",
            "config": {"base_url": target, "allow_insecure_http": True,
                       "auth_type": "api_key_header", "auth_header_name": "X-API-Key"},
            "secret": {"api_key": "s3cret"},
        },
    )
    assert r.status_code == 201, r.text
    hook = make(client, fx, r.json()["id"], method="GET", path="secured", body=None)

    run = call(client, fx, hook)
    assert run["ok"], run          # it arrived, so the far end accepted it
    assert "s3cret" not in str(run["request_body"])
    assert "s3cret" not in str(run)


def test_a_webhook_header_cannot_replace_the_connections(
    client: TestClient, fx: Fixture, target: str
) -> None:
    """p.233: "Authorization details are based on the source configuration."

    `parse` refuses the reserved names at save time; this is the send-time half,
    because a row could have been written before that guard existed. The
    reserved header is set on the *connection* here and the webhook's own
    headers go on first, so the only way the credential survives is the
    ordering being right.
    """
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={
            "name": f"Bearer {fx.tag}", "source_type": "rest", "scope": "project",
            "config": {"base_url": target, "allow_insecure_http": True,
                       "auth_type": "bearer"},
            "secret": {"api_key": "t0ken"},
        },
    )
    assert r.status_code == 201, r.text
    hook = make(client, fx, r.json()["id"], method="GET", path="echo", body=None)
    run = call(client, fx, hook)
    assert run["response_body"]["headers"]["authorization"] == "Bearer t0ken"


# ---- what comes back --------------------------------------------------------------
def test_outputs_are_read_out_of_the_response(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """p.229's example, and its own words: "when you create a new record in an
    external system, the system may return an ID for the new record"."""
    hook = make(
        client, fx, connection, path="created",
        outputs=[{"api_name": "unique_id", "path": "results.unique_id"},
                 {"api_name": "count", "data_type": "integer"}],
    )
    run = call(client, fx, hook)
    assert run["outputs"] == {"unique_id": "X1", "count": 7}
    assert run["status_code"] == 201


def test_a_response_with_no_body_is_a_success(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    # 204 is what a write-only endpoint answers with, and a webhook that
    # treated an empty body as a parse failure would refuse every one of them.
    hook = make(client, fx, connection, path="empty")
    run = call(client, fx, hook)
    assert run["ok"] and run["status_code"] == 204


def test_a_non_json_response_is_only_a_failure_when_something_reads_it(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """Both directions, because the asymmetry *is* the rule: a webhook with no
    outputs has no opinion about the body, and failing on one would refuse
    every endpoint that answers `OK`."""
    quiet = make(client, fx, connection, path="text")
    assert call(client, fx, quiet)["ok"] is True

    reading = make(
        client, fx, connection, path="text", outputs=[{"api_name": "x"}]
    )
    failed = call(client, fx, reading)
    assert failed["ok"] is False
    assert "did not return JSON" in failed["error"]


def test_a_response_larger_than_the_cap_is_refused(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """Ours rather than the document's: a response is parsed and may be stored,
    and neither should be able to be a hundred megabytes because somebody
    pointed a webhook at a download."""
    hook = make(client, fx, connection, path="huge")
    run = call(client, fx, hook)
    assert run["ok"] is False
    assert "larger than" in run["error"]


def test_a_timeout_is_a_failure_that_reached_nothing(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    hook = make(client, fx, connection, path="slow", timeout_seconds=1)
    run = call(client, fx, hook)
    assert run["ok"] is False
    assert run["status_code"] is None
    # Nothing came back, so nothing changed — and that is worked out from the
    # absent status rather than from the shape of the error.
    assert run["system_changed"] is False


# ---- p.237's three-valued question ------------------------------------------------
def test_a_refusal_says_the_far_end_did_not_change(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    hook = make(client, fx, connection, path="refuse")
    run = call(client, fx, hook)
    assert run["ok"] is False and run["status_code"] == 400
    assert run["system_changed"] is False
    # The refusal's own body is kept, because it is usually the only thing that
    # says why.
    assert run["response_body"] == {"detail": "no"}


def test_a_server_error_says_unknown_rather_than_no(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """p.237: the indication exists "to enable debugging of write failures". A
    500 after a POST may well have written, and a `false` there would be
    believed."""
    hook = make(client, fx, connection, path="boom")
    run = call(client, fx, hook)
    assert run["ok"] is False and run["status_code"] == 500
    assert run["system_changed"] is None


def test_a_success_says_the_far_end_changed(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    # The third value, without which the other two are a boolean with a hole.
    assert call(client, fx, make(client, fx, connection))["system_changed"] is True


# ---- the history (p.242) -----------------------------------------------------------
def test_a_run_is_recorded_with_what_was_sent(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    hook = make(client, fx, connection, body={"a": 1})
    call(client, fx, hook)
    page = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub)
    ).json()
    assert page["total"] == 1
    assert page["items"][0]["mode"] == "test"
    assert page["items"][0]["request_body"]["body"] == {"a": 1}


def test_store_responses_off_keeps_the_status_and_drops_the_bodies(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """p.242: "This option may be disabled entirely for a webhook that is known
    to return sensitive information."

    The status, the timing and p.237's answer are kept either way — those are
    what a person debugging needs and none of them is the sensitive part.
    Asserted together, because a version that dropped everything would pass a
    test that only checked the bodies were gone.
    """
    hook = make(client, fx, connection, path="created", store_responses=False)
    call(client, fx, hook)
    item = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub)
    ).json()["items"][0]
    assert item["request_body"] is None
    assert item["response_body"] is None
    assert item["ok"] is True and item["status_code"] == 201
    assert item["duration_ms"] is not None


def test_outputs_are_kept_even_when_responses_are_not(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """The extracted values are what the platform was asked for; the response
    is what it had to read to get them. Turning off storage of the second must
    not lose the first, or `store_responses` would silently be a switch that
    disables output parameters."""
    hook = make(
        client, fx, connection, path="created", store_responses=False,
        outputs=[{"api_name": "unique_id", "path": "results.unique_id"}],
    )
    call(client, fx, hook)
    item = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub)
    ).json()["items"][0]
    assert item["response_body"] is None
    assert item["outputs"] == {"unique_id": "X1"}


def test_a_history_is_yours(
    client: TestClient, fx: Fixture, connection: str
) -> None:
    """p.242: "the full response will only be visible to the user who called
    the webhook".

    db 0067's policy rather than a handler, so a project admin reading somebody
    else's test responses is not something this API can express. The admin can
    see the *webhook* — this is not about the definition — and sees no runs.
    """
    hook = make(client, fx, connection)
    call(client, fx, hook)

    mine = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.editor_sub)
    ).json()
    theirs = client.get(
        f"{base(fx)}/webhooks/{hook['id']}/runs", headers=hdr(fx.admin_sub)
    ).json()
    assert mine["total"] == 1
    assert theirs["total"] == 0
    # And the webhook itself is not hidden from them, which is what makes the
    # empty page a statement about the *history* rather than about access.
    assert client.get(
        f"{base(fx)}/webhooks/{hook['id']}", headers=hdr(fx.admin_sub)
    ).status_code == 200


def test_runs_for_a_webhook_that_does_not_exist_are_a_404(
    client: TestClient, fx: Fixture
) -> None:
    # "No runs" and "no such webhook" are different answers, and only one of
    # them means somebody typed the wrong id.
    r = client.get(
        f"{base(fx)}/webhooks/{uuid.uuid4()}/runs", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 404
