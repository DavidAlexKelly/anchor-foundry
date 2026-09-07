"""Configuring a webhook from the product (`data-connection` p.216-242; §261).

§259 built the resource and §260 the action rule, and left both reachable only
by posting JSON. What is worth a browser is the claim that closes: that a
webhook written **entirely through the form** reaches the far end and comes
back — which no API test can see, because an API test is the JSON.

The far end is `apps/api/tests/webhook_fixture_server.py`, run here in its own
process. It is the API server that makes the outbound call, and both are on
this machine, so a localhost target is a real socket for the code under test.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import uuid

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import WEB_BASE

SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "apps", "api", "tests", "webhook_fixture_server.py",
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


def build(api, name: str) -> Module:
    """A project of its own, so the webhooks table on screen holds this test's
    rows and nobody else's — the trap §122 hit by clicking the first of 2,219
    accumulated objects."""
    return Module(api, name)


def rest_connection(api, mod: Module, target: str, name: str = "Target") -> dict:
    return api.call(
        "POST", f"{mod.base}/connections",
        {
            "name": f"{name} {mod.tag}", "source_type": "rest", "scope": "project",
            # allow_insecure_http because the fixture is plain http on
            # localhost, which is the opt-in that flag exists for.
            "config": {"base_url": target, "allow_insecure_http": True},
            "secret": {},
        },
    )


def panel(page):
    """The webhooks section, as a scope for every button inside it.

    **Never `page.get_by_role` for one of these.** The connections table above
    has its own Test, Edit and Delete on every row, so an unscoped locator
    matches two buttons and Playwright refuses in strict mode — which is the
    right refusal and the reason this helper exists rather than a `.first`.
    """
    return page.get_by_test_id("webhooks-panel")


def open_connections(page, mod: Module) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    expect(page.get_by_test_id("webhooks-panel")).to_be_visible(timeout=30000)


def test_the_panel_says_why_there_is_nothing_to_attach_a_webhook_to(page, api):
    """p.216 ties a webhook to a source, so with no REST source there is
    nothing to make one against.

    **Said, not just disabled.** A New webhook button that does nothing with no
    explanation is §214's control that cannot work — and the reason is not
    guessable, because the project may well have sources, just not of the one
    kind that can carry a webhook.
    """
    mod = build(api, "Webhooks empty")
    open_connections(page, mod)
    expect(page.get_by_test_id("webhooks-need-a-source")).to_be_visible()
    expect(page.get_by_test_id("new-webhook")).to_be_disabled()


def test_only_rest_sources_are_offered(page, api, target):
    """p.220: "Some other source types also support webhooks." Ours support
    one, and offering a Postgres source would be offering a save that fails —
    which the server refuses with that exact sentence."""
    mod = build(api, "Webhooks source picker")
    rest = rest_connection(api, mod, target)
    api.call(
        "POST", f"{mod.base}/connections",
        {"name": f"Database {mod.tag}", "source_type": "postgres", "scope": "project",
         "config": {"host": "db.invalid", "port": 5432, "database": "d", "user": "u"},
         "secret": {}},
    )

    open_connections(page, mod)
    page.get_by_test_id("new-webhook").click()
    picker = page.get_by_test_id("webhook-connection")
    expect(picker).to_be_visible()
    options = picker.locator("option").all_inner_texts()
    assert f"Target {mod.tag}" in options
    assert f"Database {mod.tag}" not in options
    # And the REST one is chosen already, because a form whose first state is
    # valid is a form somebody can save and then refine.
    expect(picker).to_have_value(rest["id"])


def test_a_webhook_typed_in_the_form_reaches_the_far_end(page, api, target):
    """The claim §261 exists for, checked at the far end of the wire rather
    than in the row the form wrote.

    The fixture's `/echo` answers with what it received, so this asserts the
    *request* — a form that saved the right row and sent the wrong request
    would pass a check that only read the database back.
    """
    mod = build(api, "Webhooks round trip")
    rest_connection(api, mod, target)
    open_connections(page, mod)

    page.get_by_test_id("new-webhook").click()
    page.get_by_test_id("webhook-display-name").fill("Modify ticket priority")
    # The api_name was suggested from the name rather than typed, which is the
    # whole point of suggesting it.
    expect(page.get_by_test_id("webhook-api-name")).to_have_value(
        "modify_ticket_priority"
    )
    page.get_by_test_id("webhook-api-name").fill(f"hook_{uuid.uuid4().hex[:8]}")
    # **Not the default.** POST is what a blank form starts on, so a form that
    # ignored this select entirely and always sent POST would pass every
    # assertion below — which is what happened: a mutant hardcoding the method
    # survived until this line chose a different one. §190's rule, that
    # fixtures must collide on everything except the thing under test.
    page.get_by_test_id("webhook-method").select_option("PUT")
    page.get_by_test_id("webhook-path").fill("echo")

    page.get_by_test_id("webhook-inputs-add").click()
    page.get_by_label("Inputs 1 name").fill("priority")
    page.get_by_test_id("webhook-body").fill('{"priority": "{{{priority}}}"}')

    page.get_by_test_id("webhook-save").click()
    expect(page.get_by_role("dialog")).to_have_count(0)

    # p.222's test request, from the row the form just made.
    panel(page).get_by_role("button", name="Test").click()
    page.get_by_label("Test priority").fill("urgent")
    page.get_by_test_id("webhook-test-run").click()
    result = page.get_by_test_id("webhook-test-result")
    expect(result).to_be_visible(timeout=20000)
    expect(result).to_contain_text("Succeeded")
    # What the far end *received*: the reference resolved, and the method and
    # path are the ones the form typed.
    expect(result).to_contain_text('"priority": "urgent"')
    expect(result).to_contain_text('"method": "PUT"')


def test_the_body_says_it_is_not_json_before_a_save(page, api, target):
    """A textarea holding a JSON document is the one field in this form where
    somebody can be wrong in a way the other fields cannot express.

    Both halves: that it is said, and that fixing it takes the message away —
    a message that never clears is a message nobody reads. The Save button is
    the second half of the same claim, because a refusal beside a button that
    still works is a refusal about nothing.
    """
    mod = build(api, "Webhooks bad body")
    rest_connection(api, mod, target)
    open_connections(page, mod)

    page.get_by_test_id("new-webhook").click()
    page.get_by_test_id("webhook-display-name").fill("Broken body")
    page.get_by_test_id("webhook-body").fill("{oops")
    expect(page.get_by_test_id("webhook-body-problem")).to_contain_text("not valid JSON")
    expect(page.get_by_test_id("webhook-save")).to_be_disabled()

    page.get_by_test_id("webhook-body").fill('{"ok": true}')
    expect(page.get_by_test_id("webhook-body-problem")).to_have_count(0)
    expect(page.get_by_test_id("webhook-save")).to_be_enabled()


def test_a_reference_to_something_undeclared_is_named_in_the_form(page, api, target):
    """The refusal, said where the form still is.

    The server refuses this too — an unresolved reference renders as an empty
    string, and an empty string in a path is a request to a different endpoint
    than the one on screen — but that refusal arrives about a form somebody has
    already left.
    """
    mod = build(api, "Webhooks bad reference")
    rest_connection(api, mod, target)
    open_connections(page, mod)

    page.get_by_test_id("new-webhook").click()
    page.get_by_test_id("webhook-display-name").fill("Bad reference")
    page.get_by_test_id("webhook-path").fill("echo/{{{nope}}}")
    said = page.get_by_test_id("webhook-problem")
    expect(said).to_contain_text("nope")
    expect(said).to_contain_text("not an input")

    page.get_by_test_id("webhook-inputs-add").click()
    page.get_by_label("Inputs 1 name").fill("nope")
    expect(page.get_by_test_id("webhook-problem")).to_have_count(0)


def test_an_edit_comes_back_holding_what_was_saved(page, api, target):
    """The round trip in the other direction: a body stored as a JSON document
    has to come back as text somebody can edit.

    Worth its own check because the two representations are different — the
    form holds text so it can hold a half-finished document, and the wire holds
    a parsed one — and a conversion that only works one way is a dialog that
    opens empty.
    """
    mod = build(api, "Webhooks edit")
    connection = rest_connection(api, mod, target)
    api.call(
        "POST", f"{mod.base}/webhooks",
        {"connection_id": connection["id"], "api_name": f"hook_{uuid.uuid4().hex[:8]}",
         "display_name": "Round trip", "method": "PUT", "path": "echo",
         "inputs": [{"api_name": "name"}],
         "body": {"nested": {"who": "{{{name}}}"}}},
    )
    open_connections(page, mod)

    panel(page).get_by_role("button", name="Edit").click()
    expect(page.get_by_test_id("webhook-method")).to_have_value("PUT")
    expect(page.get_by_test_id("webhook-body")).to_contain_text("{{{name}}}")
    expect(page.get_by_label("Inputs 1 name")).to_have_value("name")
    # The api_name is the handle a rule holds, so it is shown and not editable.
    expect(page.get_by_test_id("webhook-api-name")).to_be_disabled()


def test_a_webhook_that_keeps_no_responses_says_so_rather_than_showing_null(
    page, api, target
):
    """p.242's switch, on the screen that reads the history.

    `null` in the response box would read as "the far end sent null", which is
    a fact about the response rather than about the webhook's configuration.
    The two have to be told apart here because telling them apart is the whole
    reason the switch exists.
    """
    mod = build(api, "Webhooks quiet")
    connection = rest_connection(api, mod, target)
    api.call(
        "POST", f"{mod.base}/webhooks",
        {"connection_id": connection["id"], "api_name": f"hook_{uuid.uuid4().hex[:8]}",
         "display_name": "Quiet", "method": "GET", "path": "created",
         "store_responses": False},
    )
    open_connections(page, mod)

    panel(page).get_by_role("button", name="Test").click()
    page.get_by_test_id("webhook-test-run").click()
    result = page.get_by_test_id("webhook-test-result")
    expect(result).to_be_visible(timeout=20000)
    expect(result).to_contain_text("Succeeded")
    expect(result).to_contain_text("responses are not kept")


def test_a_failure_says_which_of_p237s_three_answers_it_got(page, api, target):
    """p.237 captures whether the far end may have changed "to enable debugging
    of write failures", and the third answer is the one worth showing: a 500
    after a POST may well have written, and rendering that as "nothing was
    changed" would be believed."""
    mod = build(api, "Webhooks failure")
    connection = rest_connection(api, mod, target)
    api.call(
        "POST", f"{mod.base}/webhooks",
        {"connection_id": connection["id"], "api_name": f"hook_{uuid.uuid4().hex[:8]}",
         "display_name": "Boom", "method": "POST", "path": "boom"},
    )
    open_connections(page, mod)

    panel(page).get_by_role("button", name="Test").click()
    page.get_by_test_id("webhook-test-run").click()
    result = page.get_by_test_id("webhook-test-result")
    expect(result).to_be_visible(timeout=20000)
    expect(result).to_contain_text("500")
    expect(result).to_contain_text("may have changed")


def test_a_webhook_can_be_deleted(page, api, target):
    mod = build(api, "Webhooks delete")
    connection = rest_connection(api, mod, target)
    api.call(
        "POST", f"{mod.base}/webhooks",
        {"connection_id": connection["id"], "api_name": f"hook_{uuid.uuid4().hex[:8]}",
         "display_name": "Doomed", "method": "POST", "path": "echo"},
    )
    open_connections(page, mod)

    expect(panel(page).get_by_text("Doomed")).to_be_visible()
    panel(page).get_by_role("button", name="Delete").click()
    expect(page.get_by_test_id("webhooks-empty")).to_be_visible(timeout=15000)
