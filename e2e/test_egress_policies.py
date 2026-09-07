"""A source's egress policies from the product (`data-connection` p.12, p.37;
decision 0013; §264).

§263 built the rule and enforced it at all four outbound paths, and left it
reachable only by posting JSON. For a *security* control that is worse than the
usual §252 gap: an allowlist nobody can see is one nobody is checking, and
p.37's debugging procedure opens by asking somebody to look at it.

**What is worth a browser here is the round trip that no API test can see**: a
policy typed into the form actually stops a real outbound call. The API suite
asserts the same rule against rows it wrote itself; this asserts it against a
form somebody filled in, with a real socket at the far end.

The far end is the REST connector's own fixture server, in its own process. It
and the API server are both on this machine, so a localhost target is a real
destination for the code under test.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time

import pytest
from playwright.sync_api import expect

from api import Module
from conftest import FIRST_RENDER_MS, TOKENS_FILE, WEB_BASE

SERVER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "apps", "api", "tests", "rest_fixture_server.py",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def target() -> tuple[str, int]:
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
    yield f"http://127.0.0.1:{port}", port
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def viewer_page(browser):
    """A page signed in as the dev workspace's **viewer**.

    Local to this file rather than in `conftest.py` because one test wants it,
    and the console-error check `page` carries is deliberately not copied: what
    is asserted below is which controls exist, and duplicating the fixture's
    other job would make a failure here ambiguous about which claim broke.
    """
    with open(TOKENS_FILE) as handle:
        token = json.load(handle)["viewer@acme.dev.local"]
    context = browser.new_context(viewport={"width": 1500, "height": 1200})
    opened = context.new_page()
    opened.goto(f"{WEB_BASE}/login")
    opened.fill("input[placeholder='Paste an access token']", token)
    opened.get_by_role("button", name="Use token").click()
    opened.wait_for_url(lambda url: "/login" not in url, timeout=FIRST_RENDER_MS)
    yield opened
    context.close()


def build(api, name: str) -> Module:
    """A project per test, so the connections table on screen holds this test's
    rows and nobody else's — §122's trap, and it bites harder here because the
    row a test wants is found by its name."""
    return Module(api, name)


def rest_connection(api, mod: Module, url: str, name: str = "Target") -> dict:
    return api.call(
        "POST", f"{mod.base}/connections",
        {
            "name": f"{name} {mod.tag}", "source_type": "rest", "scope": "project",
            # The opt-in `allow_insecure_http` exists for: plain http on
            # localhost. It is the platform's own protocol control, and decision
            # 0013 §5 is about why it is not a column on a policy.
            "config": {"base_url": url, "allow_insecure_http": True,
                       "resource_path": "records"},
            "secret": {},
        },
    )


def open_networking(page, mod: Module, name: str) -> None:
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=name)
    expect(row).to_be_visible(timeout=30000)
    row.get_by_role("button", name="Networking").click()
    expect(page.get_by_test_id("egress-panel")).to_be_visible()


def test_a_source_with_no_policies_says_it_is_unrestricted(page, api, target):
    """**Decision 0013 §2's sentence, on the screen it is about.**

    An empty allowlist means unrestricted — it has to, because every source
    that already exists is in that state — and an empty table with nothing over
    it reads as the opposite. This is the one control whose off state and on
    state would otherwise look identical, so the state is written out.
    """
    url, _ = target
    mod = build(api, "Egress unrestricted")
    rest_connection(api, mod, url)
    open_networking(page, mod, f"Target {mod.tag}")

    expect(page.get_by_test_id("egress-summary")).to_contain_text("any destination")
    expect(page.get_by_test_id("egress-policies")).to_have_count(0)


def test_the_panel_shows_what_the_source_will_actually_dial(page, api, target):
    """p.37's step 1: "confirm that the correct egress policies are attached to
    the source, and that the host, port, and protocol they allow match the
    system you are connecting to."

    The list of what a source is *allowed* to reach is only useful beside the
    list of what it will *try* to reach, and the second is otherwise spread
    across four fields on a different form.
    """
    url, port = target
    mod = build(api, "Egress destinations")
    rest_connection(api, mod, url)
    open_networking(page, mod, f"Target {mod.tag}")

    destinations = page.get_by_test_id("egress-destinations")
    expect(destinations).to_contain_text(f"127.0.0.1:{port}")
    expect(destinations).to_contain_text("Base URL")


def test_a_policy_typed_in_the_form_stops_a_real_call(page, api, target):
    """**The claim §264 exists for**, and the only one that needs a browser.

    A policy written entirely through the form refuses an outbound call the
    same source made a moment earlier. The API suite makes this assertion
    against rows it wrote itself; here the row came from a person, and the
    refusal is read off the screen rather than out of a response body.

    **Paired, in the order that makes the pair meaningful**: the call succeeds
    first. A refusal on its own passes against a source that could never reach
    anything.
    """
    url, _ = target
    mod = build(api, "Egress stops a call")
    rest_connection(api, mod, url)
    page.goto(f"{WEB_BASE}/{mod.workspace_slug}/{mod.project_slug}/connections")
    row = page.get_by_role("row").filter(has_text=f"Target {mod.tag}")
    expect(row).to_be_visible(timeout=30000)

    row.get_by_role("button", name="Test").click()
    expect(row).to_contain_text("Connected", timeout=30000)

    row.get_by_role("button", name="Networking").click()
    panel = page.get_by_test_id("egress-panel")
    expect(panel).to_be_visible()
    panel.get_by_test_id("egress-host").fill("api.example.com")
    panel.get_by_test_id("egress-port").fill("443")
    panel.get_by_test_id("egress-description").fill("the vendor API")
    panel.get_by_test_id("egress-add").click()
    expect(page.get_by_test_id("egress-policies")).to_contain_text("api.example.com:443")

    page.get_by_role("button", name="Close").click()
    row.get_by_role("button", name="Test").click()
    # Decision 0013 §4: the refusal names what is allowed, so the investigation
    # ends here rather than at DNS and a firewall.
    expect(row).to_contain_text("not allowed to reach", timeout=30000)
    expect(row).to_contain_text("api.example.com:443")


def test_removing_the_last_policy_makes_the_source_unrestricted_again(page, api, target):
    """The switch works in both directions, and the second is the one nobody
    tests. A control that could be turned on and not off would trap every
    source that ever had a policy — and from the product, "off" means somebody
    can find the row and remove it."""
    url, _ = target
    mod = build(api, "Egress removal")
    conn = rest_connection(api, mod, url)
    api.call(
        "POST", f"{mod.base}/connections/{conn['id']}/egress-policies",
        {"host": "api.example.com", "port": 443, "description": "the vendor API"},
    )
    open_networking(page, mod, f"Target {mod.tag}")
    expect(page.get_by_test_id("egress-summary")).to_contain_text("Restricted")

    page.get_by_test_id("egress-policies").get_by_role("button", name="Remove").click()
    expect(page.get_by_test_id("egress-summary")).to_contain_text("any destination")

    page.get_by_role("button", name="Close").click()
    row = page.get_by_role("row").filter(has_text=f"Target {mod.tag}")
    row.get_by_role("button", name="Test").click()
    expect(row).to_contain_text("Connected", timeout=30000)


def test_the_suggestion_fills_the_form_rather_than_saving_it(page, api, target):
    """p.37 asks somebody to *confirm* that the policies match what the source
    dials. A one-click write would let them agree with a suggestion they had not
    read, so Use as a policy fills the boxes and Save is still theirs to press.

    Both halves: the form is filled, **and** nothing was saved by the click.
    """
    url, port = target
    mod = build(api, "Egress suggestion")
    rest_connection(api, mod, url)
    open_networking(page, mod, f"Target {mod.tag}")

    page.get_by_test_id("egress-destinations").get_by_role(
        "button", name="Use as a policy"
    ).click()
    expect(page.get_by_test_id("egress-host")).to_have_value("127.0.0.1")
    expect(page.get_by_test_id("egress-port")).to_have_value(str(port))
    expect(page.get_by_test_id("egress-summary")).to_contain_text("any destination")

    page.get_by_test_id("egress-add").click()
    expect(page.get_by_test_id("egress-policies")).to_contain_text(f"127.0.0.1:{port}")


def test_a_range_is_refused_before_the_form_is_sent(page, api, target):
    """The form says what the server would, without the round trip — and offers
    the alternative, because a range is what somebody writes when they do not
    know the names and a bare refusal leaves them with nothing to write
    instead."""
    url, _ = target
    mod = build(api, "Egress range")
    rest_connection(api, mod, url)
    open_networking(page, mod, f"Target {mod.tag}")

    page.get_by_test_id("egress-host").fill("10.0.0.0/8")
    expect(page.get_by_test_id("egress-problem")).to_contain_text("name each host")
    expect(page.get_by_test_id("egress-add")).to_be_disabled()

    # The presence half: the same form accepts the single host the message
    # points at, so the check above is not a form that refuses everything.
    page.get_by_test_id("egress-host").fill("10.0.0.1")
    expect(page.get_by_test_id("egress-problem")).to_have_count(0)
    expect(page.get_by_test_id("egress-add")).to_be_enabled()


def test_an_aws_bucket_says_a_policy_would_not_restrict_it(page, api, target):
    """**The documented gap, on the screen where somebody would otherwise be
    misled by it.**

    With no custom endpoint, boto3 derives an S3 host from the bucket and region
    when the request is made, so no policy here can refuse the call — the gap
    `S3Connector._client` documents and §263 holds with a test that asserts the
    absence. A panel that let somebody add a policy to an AWS bucket and said
    nothing would be §214's control that cannot work, wearing the interface of
    one that can.
    """
    url, _ = target
    mod = build(api, "Egress s3 caveat")
    api.call(
        "POST", f"{mod.base}/connections",
        {"name": f"Bucket {mod.tag}", "source_type": "s3", "scope": "project",
         "config": {"bucket": "landing", "region": "eu-west-2"}, "secret": {}},
    )
    open_networking(page, mod, f"Bucket {mod.tag}")

    expect(page.get_by_test_id("egress-caveat")).to_contain_text("cannot restrict this source")
    expect(page.get_by_test_id("egress-destinations")).to_have_count(0)


def test_a_viewer_reads_the_policies_and_cannot_change_them(page, api, target, viewer_page):
    """`require_workspace_role` on the routes says a viewer may read and may not
    write, and §263 asserts that at the API. This is the other half: a button a
    viewer's click would 403 is not offered at all.

    The list itself stays visible, because the reason a viewer looks at this
    screen is p.37's — to find out why a call was refused.
    """
    url, _ = target
    mod = build(api, "Egress viewer")
    conn = rest_connection(api, mod, url)
    api.call(
        "POST", f"{mod.base}/connections/{conn['id']}/egress-policies",
        {"host": "api.example.com", "port": 443, "description": "the vendor API"},
    )

    open_networking(viewer_page, mod, f"Target {mod.tag}")
    expect(viewer_page.get_by_test_id("egress-policies")).to_contain_text("api.example.com:443")
    expect(viewer_page.get_by_test_id("egress-host")).to_have_count(0)
    expect(
        viewer_page.get_by_test_id("egress-policies").get_by_role("button", name="Remove")
    ).to_have_count(0)
