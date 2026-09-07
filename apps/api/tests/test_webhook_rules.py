"""A webhook as an action rule, in p.106's two modes (decision 0012; §260).

`action-types` pages are `a-p.N`; `data-connection` pages are `d-p.N`.

**The failure tests are paired and neither is worth writing alone.** A
writeback that fails leaves the object unchanged and refuses the action; a side
effect that fails leaves the object *changed* and returns success. Each of
those passes against an implementation that got the other mode's semantics, so
only the pair says anything. `data-connection.md` §6 asked for exactly this and
left the direction open — a-p.105-107 answers it, both ways round.
"""
from __future__ import annotations

import io
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
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

SERVER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "webhook_fixture_server.py"
)
TICKETS = b"ticket_id,priority\nT1,low\nT2,low\n"


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
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    conn_routes.configure_secrets_gateway(InMemorySecretsGateway())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("webhook-rules")))
    )
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def connection(client: TestClient, fx: Fixture, target: str) -> str:
    r = client.post(
        f"{pbase(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Target {fx.tag}", "source_type": "rest", "scope": "project",
              "config": {"base_url": target, "allow_insecure_http": True},
              "secret": {}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def ticket_type(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"Ticket{fx.tag}", "display_name": f"Ticket {fx.tag}",
              "properties": [{"api_name": "priority", "data_type": "string"},
                             {"api_name": "note", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def tickets(client: TestClient, fx: Fixture, ticket_type: str) -> list[str]:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Tickets {fx.tag}"},
        files={"file": ("tickets.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type, "dataset_id": r.json()["id"],
              "primary_key_column": "ticket_id",
              "column_mappings": {"priority": "priority"}},
    )
    assert r.status_code == 201, r.text
    assert client.post(
        f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    ).status_code == 200
    listed = client.get(
        f"{wbase(fx)}/object-types/{ticket_type}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"]
    return [i["id"] for i in sorted(listed, key=lambda i: i["primary_key"])]


def make_webhook(client: TestClient, fx: Fixture, connection: str, **over) -> dict:
    payload = {
        "connection_id": connection,
        "api_name": f"hook_{uuid.uuid4().hex[:8]}",
        "display_name": "Modify ticket priority",
        "method": "POST", "path": "echo",
        "inputs": [{"api_name": "priority"}],
        "body": {"priority": "{{{priority}}}"},
    }
    payload.update(over)
    r = client.post(f"{pbase(fx)}/webhooks", headers=hdr(fx.editor_sub), json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def make_action(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "api_name": f"act_{uuid.uuid4().hex[:8]}",
              "display_name": "Retriage", "editable_properties": ["priority"]},
    )
    assert r.status_code == 201, r.text
    return r.json()


def define(client: TestClient, fx: Fixture, action: dict, rules: list[dict],
           parameters=None):
    return client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": parameters if parameters is not None else [
                {"api_name": "priority", "display_name": "Priority",
                 "data_type": "string"},
            ],
            "rules": rules,
            "criteria": [],
        },
    )


def modify_rule() -> dict:
    return {"kind": "modify_object",
            "config": {"property": "priority", "parameter": "priority"}}


def hook_rule(webhook: dict, mode: str, **over) -> dict:
    config = {"webhook": webhook["id"], "mode": mode,
              "inputs": {"priority": {"parameter": "priority"}}}
    config.update(over)
    return {"kind": "webhook", "config": config}


def run(client: TestClient, fx: Fixture, action: dict, instance: str, priority: str):
    return client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instance, "values": {"priority": priority}},
    )


def priority_of(client: TestClient, fx: Fixture, type_id: str, instance: str) -> str:
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances/{instance}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["properties"].get("priority"))


def runs_for(client: TestClient, fx: Fixture, webhook: dict) -> list[dict]:
    r = client.get(
        f"{pbase(fx)}/webhooks/{webhook['id']}/runs", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ---- the two modes, working ------------------------------------------------------
def test_a_side_effect_fires_after_the_object_changed(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.107: "modifications to Foundry objects will occur before side
    effects are applied"."""
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [modify_rule(), hook_rule(hook, "side_effect")]
                  ).status_code == 200

    r = run(client, fx, action, tickets[0], "urgent")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert priority_of(client, fx, ticket_type, tickets[0]) == "urgent"

    sent = runs_for(client, fx, hook)
    assert [item["mode"] for item in sent] == ["side_effect"]
    # The action's parameter reached the webhook's input, which is a-p.107's
    # "each required Webhook input must be set to … an Action parameter".
    assert sent[0]["request_body"]["body"] == {"priority": "urgent"}
    # And the run is linked to the action run, which is what makes the history
    # answerable from the object's side.
    assert sent[0]["action_run_id"]


def test_a_writeback_fires_before_the_object_changed(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.106: "the webhook will be executed before any other rules are
    evaluated".

    Both facts are checked: it ran, and the object still changed. A writeback
    that silently replaced the write would pass a test that only looked at the
    webhook's history.
    """
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [hook_rule(hook, "writeback"), modify_rule()]
                  ).status_code == 200

    assert run(client, fx, action, tickets[1], "high").json()["ok"]
    assert priority_of(client, fx, ticket_type, tickets[1]) == "high"
    assert [item["mode"] for item in runs_for(client, fx, hook)] == ["writeback"]


def test_a_static_value_reaches_the_webhook(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.107's other input source: "a static value". Its own check because a
    rule that only ever read parameters would pass every test above."""
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        modify_rule(),
        hook_rule(hook, "side_effect", inputs={"priority": {"value": "fixed"}}),
    ]).status_code == 200

    run(client, fx, action, tickets[0], "ignored-by-the-hook")
    assert runs_for(client, fx, hook)[0]["request_body"]["body"] == {"priority": "fixed"}


# ---- the pair that answers `data-connection.md` §6 -------------------------------
def test_a_failing_writeback_refuses_the_action_and_changes_nothing(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.106: "if the webhook execution fails, no other changes will be
    made", and the failure is shown to the end user."""
    hook = make_webhook(client, fx, connection, path="boom")
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [hook_rule(hook, "writeback"), modify_rule()]
                  ).status_code == 200
    before = priority_of(client, fx, ticket_type, tickets[0])

    r = run(client, fx, action, tickets[0], "never-applied")
    assert r.status_code == 422, r.text
    # It names the webhook: "the action failed" about an external system is not
    # something the person who clicked can act on.
    assert "Modify ticket priority" in r.json()["detail"]
    assert priority_of(client, fx, ticket_type, tickets[0]) == before
    assert runs_for(client, fx, hook)[0]["ok"] is False


def test_a_failing_side_effect_leaves_the_object_changed(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """The other half, and the reason neither is worth writing alone.

    a-p.106's table: a side effect's failure is **not** shown to the end user
    and the timing is after the objects were modified. Saying the action failed
    here would be a lie about the thing the person was looking at — it did not.
    """
    hook = make_webhook(client, fx, connection, path="boom")
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [modify_rule(), hook_rule(hook, "side_effect")]
                  ).status_code == 200

    r = run(client, fx, action, tickets[1], "applied-anyway")
    assert r.status_code == 200 and r.json()["ok"], r.text
    assert r.json()["error"] is None
    assert priority_of(client, fx, ticket_type, tickets[1]) == "applied-anyway"
    # Invisible to the caller, visible to whoever has to debug it: "no
    # notification" and "no record" are different kinds of quiet, and a-p.107
    # only asks for the first.
    failed = runs_for(client, fx, hook)[0]
    assert failed["ok"] is False and failed["status_code"] == 500
    assert failed["action_run_id"]


def test_a_side_effect_default_is_the_mode_that_cannot_break_an_action(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.114: "By default, the newly added webhook is configured as a side
    effect."

    The default is the *safe* one, which is why it is worth a test: a rule
    saved with no mode at all must not be able to take an action down.
    """
    hook = make_webhook(client, fx, connection, path="boom")
    action = make_action(client, fx, ticket_type)
    rule = hook_rule(hook, "side_effect")
    rule["config"].pop("mode")
    assert define(client, fx, action, [modify_rule(), rule]).status_code == 200

    assert run(client, fx, action, tickets[0], "still-applied").json()["ok"]
    assert runs_for(client, fx, hook)[0]["mode"] == "side_effect"


# ---- a-p.110's outputs -----------------------------------------------------------
def test_a_writebacks_output_can_be_written_into_an_object(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.110: "when the external system returns data that you want to
    immediately write into a Foundry object … you can use its output parameters
    in subsequent rules"."""
    hook = make_webhook(
        client, fx, connection, path="created", body=None, method="GET",
        inputs=[], outputs=[{"api_name": "unique_id", "path": "results.unique_id"}],
    )
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        {"kind": "webhook", "config": {"webhook": hook["id"], "mode": "writeback",
                                       "inputs": {}}},
        # p.111's "Writeback response", spelled as a reserved name in the one
        # namespace every rule kind already reads from.
        {"kind": "modify_object",
         "config": {"property": "priority", "parameter": "webhook.unique_id"}},
    ]).status_code == 200

    assert run(client, fx, action, tickets[0], "overwritten").json()["ok"]
    assert priority_of(client, fx, ticket_type, tickets[0]) == "X1"


def test_a_caller_cannot_forge_a_writeback_output(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """**What makes the reserved name a namespace rather than a hole.**

    The executor is the only thing that may write `webhook.*`, and what enforces
    it is `bind_parameters` refusing every key the caller supplies that is not a
    declared parameter. Without that, anybody who could run the action could
    write any value into any property a rule points at.
    """
    hook = make_webhook(
        client, fx, connection, path="created", body=None, method="GET",
        inputs=[], outputs=[{"api_name": "unique_id", "path": "results.unique_id"}],
    )
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        {"kind": "webhook", "config": {"webhook": hook["id"], "mode": "writeback",
                                       "inputs": {}}},
        {"kind": "modify_object",
         "config": {"property": "priority", "parameter": "webhook.unique_id"}},
    ]).status_code == 200

    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": tickets[1],
              "values": {"webhook.unique_id": "FORGED"}},
    )
    assert r.status_code == 422, r.text
    assert "not a parameter" in r.json()["detail"]
    assert priority_of(client, fx, ticket_type, tickets[1]) != "FORGED"


def test_a_notification_can_read_a_writebacks_output(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.110 names three consumers and this is the second: "use in a
    subsequent notification".

    It is what fixes the *order* of two things in the pre-write block — the
    notification content is rendered there too, and rendering it first would
    substitute an empty string for every webhook output.
    """
    me = client.get("/api/auth/me", headers=hdr(fx.editor_sub)).json()
    hook = make_webhook(
        client, fx, connection, path="created", body=None, method="GET",
        inputs=[], outputs=[{"api_name": "unique_id", "path": "results.unique_id"}],
    )
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [
        {"kind": "webhook", "config": {"webhook": hook["id"], "mode": "writeback",
                                       "inputs": {}}},
        modify_rule(),
        {"kind": "notify", "config": {
            "recipients": {"kind": "static", "user_ids": [me["user_id"]]},
            "subject": f"Filed {fx.tag}",
            "body": "External id {{{webhook.unique_id}}}.",
        }},
    ])
    assert r.status_code == 200, r.text

    assert run(client, fx, action, tickets[0], "filed").json()["ok"]
    inbox = client.get("/api/notifications", headers=hdr(fx.editor_sub)).json()
    latest = inbox["items"][0]
    assert latest["subject"] == f"Filed {fx.tag}"
    assert latest["body"] == "External id X1."


# ---- what may be saved -----------------------------------------------------------
def test_a_second_writeback_is_refused_at_save_time(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    """a-p.106: "you can only configure a single webhook as a writeback".

    At save rather than at run, because at run time the second one is
    discovered *after* the first has already called somebody's production
    system.
    """
    first = make_webhook(client, fx, connection)
    second = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action,
               [hook_rule(first, "writeback"), hook_rule(second, "writeback")])
    assert r.status_code == 422, r.text
    assert "only one writeback" in r.json()["detail"]


def test_two_side_effects_are_fine(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """a-p.107: "you can configure multiple side effect webhooks in a single
    action". The presence half of the refusal above — without it, that check
    would pass against an implementation that refused every second webhook."""
    first = make_webhook(client, fx, connection)
    second = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        modify_rule(), hook_rule(first, "side_effect"), hook_rule(second, "side_effect"),
    ]).status_code == 200
    assert run(client, fx, action, tickets[0], "both").json()["ok"]
    assert runs_for(client, fx, first) and runs_for(client, fx, second)


def test_an_output_cannot_be_read_by_an_earlier_rule(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    """a-p.110's word is **subsequent**, and this is what makes it checkable.

    The validation loop runs in order and adds a writeback's outputs to the
    known names when it reaches that rule — so a rule above it has not seen
    them and is refused. Without the ordering the check would be "does this
    action have a webhook anywhere", which is a different and much weaker
    claim.
    """
    hook = make_webhook(
        client, fx, connection, path="created", body=None, method="GET",
        inputs=[], outputs=[{"api_name": "unique_id"}],
    )
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [
        {"kind": "modify_object",
         "config": {"property": "priority", "parameter": "webhook.unique_id"}},
        {"kind": "webhook", "config": {"webhook": hook["id"], "mode": "writeback",
                                       "inputs": {}}},
    ])
    assert r.status_code == 422, r.text
    assert "webhook.unique_id" in r.json()["detail"]


def test_a_side_effects_outputs_are_not_readable_at_all(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    """Only a writeback's outputs are usable (a-p.110), and the reason is
    structural rather than a restriction: a side effect runs after every rule,
    so there is no subsequent rule for its output to reach."""
    hook = make_webhook(
        client, fx, connection, path="created", body=None, method="GET",
        inputs=[], outputs=[{"api_name": "unique_id"}],
    )
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [
        {"kind": "webhook", "config": {"webhook": hook["id"], "mode": "side_effect",
                                       "inputs": {}}},
        {"kind": "modify_object",
         "config": {"property": "priority", "parameter": "webhook.unique_id"}},
    ])
    assert r.status_code == 422, r.text


def test_a_rule_naming_a_webhook_that_does_not_exist_is_refused(
    client: TestClient, fx: Fixture, ticket_type: str
) -> None:
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [
        {"kind": "webhook", "config": {"webhook": str(uuid.uuid4()), "inputs": {}}},
    ])
    assert r.status_code == 422
    assert "does not have" in r.json()["detail"]


def test_a_required_webhook_input_the_rule_does_not_supply_is_refused(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    """a-p.107: "you must populate all of its required input parameters." At
    save time, because the alternative is a rule that saves and then fails on
    the first click."""
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [hook_rule(hook, "side_effect", inputs={})])
    assert r.status_code == 422, r.text
    assert "'priority'" in r.json()["detail"]


def test_an_optional_webhook_input_may_be_left_out(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    # d-p.229's optional inputs, and the presence half of the refusal above.
    hook = make_webhook(
        client, fx, connection,
        inputs=[{"api_name": "priority", "required": False}],
    )
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action,
                  [hook_rule(hook, "side_effect", inputs={})]).status_code == 200


def test_a_rule_reading_a_parameter_that_does_not_exist_is_refused(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [
        hook_rule(hook, "side_effect", inputs={"priority": {"parameter": "nope"}}),
    ])
    assert r.status_code == 422
    assert "'nope'" in r.json()["detail"]


def test_an_input_needs_exactly_one_source(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    """Both is as wrong as neither, and for the same reason: it leaves the rule
    with no answer to "where does this value come from" that anybody reading it
    could give."""
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    for spec in ({}, {"parameter": "priority", "value": "x"}):
        r = define(client, fx, action,
                   [hook_rule(hook, "side_effect", inputs={"priority": spec})])
        assert r.status_code == 422, (spec, r.text)
        assert "exactly one" in r.json()["detail"]


def test_an_unknown_mode_is_refused(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str
) -> None:
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    r = define(client, fx, action, [hook_rule(hook, "eventually")])
    assert r.status_code == 422
    assert "mode must be" in r.json()["detail"]


def test_an_action_whose_only_rule_sends_data_out_is_refused_as_empty(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """**A limitation, recorded as one rather than discovered later.**

    A webhook changes no object here, so `apply_rules` produces no writes and
    the emptiness refusal fires. That is the same answer §257 settled for a
    notification-only action — its comment says so in as many words — and this
    test exists to keep the two consistent rather than to argue the answer is
    ideal. It is not: a-p.107's "write back to multiple external systems" is a
    perfectly good reason for an action that writes nothing locally.

    What stands in the way is the write path rather than this check. An action
    that reaches it appends a dataset version per execution, so allowing an
    empty one means teaching that path to stage nothing — a change to decision
    0008's shape, not to a rule kind, and not this unit's to make. Pair a
    webhook with a rule that writes something until then.
    """
    hook = make_webhook(client, fx, connection)
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [hook_rule(hook, "side_effect")]).status_code == 200
    r = run(client, fx, action, tickets[0], "outbound-only")
    assert r.status_code == 422, r.text
    assert "at least one value" in r.json()["detail"]
    # And nothing was sent, because the refusal happens before the write and a
    # side effect fires after it.
    assert runs_for(client, fx, hook) == []


def test_an_unsupplied_optional_parameter_is_absent_rather_than_null(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """d-p.229's optional inputs, mapped to a parameter the caller left out.

    **Absent, not null**, and the difference is not pedantry: an API that
    distinguishes "field not provided" from "field explicitly cleared" — and
    most that accept PATCH-shaped bodies do — would read the second as a
    request to erase the value. The rule maps the input, the caller supplies
    nothing, and the key does not appear.

    The earlier optional-input check leaves the input out of the *rule*, which
    never exercises this: a mutant sending `None` for an unsupplied parameter
    survived until this existed.
    """
    hook = make_webhook(
        client, fx, connection,
        inputs=[{"api_name": "note", "required": False},
                {"api_name": "priority"}],
        body={"note": "{{{note}}}", "priority": "{{{priority}}}"},
    )
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        modify_rule(),
        hook_rule(hook, "side_effect", inputs={
            "priority": {"parameter": "priority"},
            "note": {"parameter": "note"},
        }),
    ], parameters=[
        {"api_name": "priority", "display_name": "Priority", "data_type": "string"},
        {"api_name": "note", "display_name": "Note", "data_type": "string"},
    ]).status_code == 200

    # `note` is declared on the action and simply not submitted.
    assert run(client, fx, action, tickets[0], "no-note").json()["ok"]
    body = runs_for(client, fx, hook)[0]["request_body"]["body"]
    # **The key is gone, not null.** The first version of this assertion said
    # `is None or not in`, which is true either way and therefore said nothing
    # — the mutant it was written for survived it. `==` against the whole body
    # is what makes the claim.
    assert body == {"priority": "no-note"}


def test_a_webhook_whose_inputs_changed_after_the_rule_was_written(
    client: TestClient, fx: Fixture, connection: str, ticket_type: str, tickets: list[str]
) -> None:
    """The one path `_validate_definition` cannot close.

    A rule is refused at save time when it does not supply a required input —
    so reaching the run-time failure means the *webhook* changed underneath it,
    which nothing stops: the two are edited on different screens by different
    people. The rule is saved against an optional input, the input is then made
    required, and the call can no longer be built.

    **It has to be a recorded failure rather than a raise**, because this is a
    side effect and a-p.106 says a side effect cannot fail the action. A
    `WebhookError` escaping here would take down an action that had already
    written its object — the exact outcome the mode exists to prevent.
    """
    hook = make_webhook(
        client, fx, connection,
        inputs=[{"api_name": "priority", "required": False}],
    )
    action = make_action(client, fx, ticket_type)
    assert define(client, fx, action, [
        modify_rule(), hook_rule(hook, "side_effect", inputs={}),
    ]).status_code == 200

    r = client.put(
        f"{pbase(fx)}/webhooks/{hook['id']}", headers=hdr(fx.editor_sub),
        json={"connection_id": connection, "display_name": hook["display_name"],
              "method": "POST", "path": "echo",
              "inputs": [{"api_name": "priority", "required": True}],
              "body": {"priority": "{{{priority}}}"}},
    )
    assert r.status_code == 200, r.text

    result = run(client, fx, action, tickets[1], "still-written")
    assert result.status_code == 200 and result.json()["ok"], result.text
    assert priority_of(client, fx, ticket_type, tickets[1]) == "still-written"
    failed = runs_for(client, fx, hook)[0]
    assert failed["ok"] is False
    assert "missing required input" in failed["error"]
