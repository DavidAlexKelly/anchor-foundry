"""Egress policies as rows, and as a control on a real call (§263).

`test_egress.py` is what a set of policies *means*; this is whether the four
outbound paths actually consult them. Against a real socket, for
`test_rest_connector.py`'s reason: a patched `urlopen` tests the patch.

**The tests are paired throughout.** `data-connection.md` asks for "a source
configured for `host-a` cannot reach `host-b`, and the refusal names the
policy" — and the refusal alone passes against an implementation that refuses
everything, so every refusal here has an allowed call beside it.

`data-connection` pages are `p.N`.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.parse
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as conn_routes  # noqa: E402
from src.services import egress  # noqa: E402
from src.services.connectors import S3Connector  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402

#: The REST connector's own fixture, because this suite tests a *source*
#: reaching out — and the connector reads an array of records, which is what
#: `/records` serves. The webhook fixture answers a different shape.
SERVER = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "rest_fixture_server.py"
)


#: The platform's own Postgres, standing in for a customer's database. The
#: database path needs a *real* driver connecting to a *real* socket for the
#: same reason the REST path does — and it needs no fixture of its own, because
#: what is being asserted is which host the connector was allowed to dial, not
#: what it found there.
DB = urllib.parse.urlparse(os.environ["TEST_ADMIN_DSN"])


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _serve() -> tuple[str, int, subprocess.Popen]:
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
    return f"http://127.0.0.1:{port}", port, proc


@pytest.fixture(scope="module")
def target() -> tuple[str, int]:
    url, port, proc = _serve()
    yield url, port
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="module")
def token_target() -> tuple[str, int]:
    """A second server on a second port, so one source has **two**
    destinations.

    p.12's own example is a source that does exactly this — "retrieve
    credentials from an internet-hosted system, and use said credentials to
    authenticate with an on-premise system" — and one server could not tell the
    two checks apart: a policy naming its host and port would permit both, so a
    missing guard on the token endpoint would look identical to a present one.
    """
    url, port, proc = _serve()
    yield url, port
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


def rest_connection(client: TestClient, fx: Fixture, url: str, **over) -> str:
    payload = {
        "name": f"Target {uuid.uuid4().hex[:6]}", "source_type": "rest",
        "scope": "project", "secret": {},
        "config": {"base_url": url, "allow_insecure_http": True,
                   "resource_path": "records"},
    }
    payload.update(over)
    r = client.post(f"{base(fx)}/connections", headers=hdr(fx.editor_sub), json=payload)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def allow(client: TestClient, fx: Fixture, cid: str, **policy):
    return client.post(
        f"{base(fx)}/connections/{cid}/egress-policies",
        headers=hdr(fx.editor_sub), json=policy,
    )


def policies(client: TestClient, fx: Fixture, cid: str) -> list[dict]:
    r = client.get(
        f"{base(fx)}/connections/{cid}/egress-policies", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    return r.json()


def probe(client: TestClient, fx: Fixture, cid: str) -> dict:
    r = client.post(f"{base(fx)}/connections/{cid}/test", headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    return r.json()


# ---- the rows --------------------------------------------------------------------
def test_a_source_starts_with_no_policies(
    client: TestClient, fx: Fixture, target
) -> None:
    """Decision 0013 §2. An empty list is the state every existing source is
    already in, which is the whole reason it has to mean unrestricted."""
    url, _ = target
    assert policies(client, fx, rest_connection(client, fx, url)) == []


def test_a_policy_round_trips(client: TestClient, fx: Fixture, target) -> None:
    url, _ = target
    cid = rest_connection(client, fx, url)
    r = allow(client, fx, cid, host="API.Example.com", port=443,
              description="the vendor API")
    assert r.status_code == 201, r.text
    # Lowercased on the way in, because the comparison is case-insensitive and
    # storing it as typed would make the list disagree with itself on screen.
    assert r.json()["host"] == "api.example.com"
    assert [p["host"] for p in policies(client, fx, cid)] == ["api.example.com"]


def test_a_range_is_refused_with_the_alternative(
    client: TestClient, fx: Fixture, target
) -> None:
    url, _ = target
    r = allow(client, fx, rest_connection(client, fx, url), host="10.0.0.0/8")
    assert r.status_code == 422, r.text
    assert "name each host" in r.json()["detail"]


def test_the_same_destination_twice_is_refused_with_a_sentence(
    client: TestClient, fx: Fixture, target
) -> None:
    """db 0068's unique constraint refuses it too; this turns that into a
    sentence rather than a 500 quoting a constraint name — the same fix §259
    had to make for a connection a webhook was using."""
    url, _ = target
    cid = rest_connection(client, fx, url)
    assert allow(client, fx, cid, host="api.example.com", port=443).status_code == 201
    clash = allow(client, fx, cid, host="api.example.com", port=443)
    assert clash.status_code == 409
    assert "already allows api.example.com:443" in clash.json()["detail"]


def test_the_same_host_on_another_port_is_a_different_destination(
    client: TestClient, fx: Fixture, target
) -> None:
    # The presence half of the refusal above: without it, that check passes
    # against an implementation that refuses every second policy for a host.
    url, _ = target
    cid = rest_connection(client, fx, url)
    assert allow(client, fx, cid, host="api.example.com", port=443).status_code == 201
    assert allow(client, fx, cid, host="api.example.com", port=8443).status_code == 201


def test_a_policy_can_be_removed(client: TestClient, fx: Fixture, target) -> None:
    url, _ = target
    cid = rest_connection(client, fx, url)
    made = allow(client, fx, cid, host="api.example.com").json()
    assert client.delete(
        f"{base(fx)}/connections/{cid}/egress-policies/{made['id']}",
        headers=hdr(fx.editor_sub),
    ).status_code == 204
    assert policies(client, fx, cid) == []


def test_a_source_may_not_name_more_destinations_than_anybody_will_read(
    client: TestClient, fx: Fixture, target
) -> None:
    """`egress_store.MAX_POLICIES`, which is ours and not the document's.

    The ceiling is the kind of line that is easy to write and never exercised,
    and one that never fires is one that could be off by a factor of ten
    without anybody noticing. Both halves: the fiftieth is accepted, and the
    fifty-first is refused with the number in the sentence.
    """
    url, _ = target
    cid = rest_connection(client, fx, url)
    for n in range(50):
        r = allow(client, fx, cid, host=f"h{n}.example.com")
        assert r.status_code == 201, f"policy {n}: {r.text}"

    over = allow(client, fx, cid, host="one-too-many.example.com")
    assert over.status_code == 409, over.text
    assert "at most 50 destinations" in over.json()["detail"]
    assert len(policies(client, fx, cid)) == 50


def test_a_viewer_may_read_and_may_not_write(
    client: TestClient, fx: Fixture, target
) -> None:
    url, _ = target
    cid = rest_connection(client, fx, url)
    assert client.get(
        f"{base(fx)}/connections/{cid}/egress-policies", headers=hdr(fx.viewer_sub)
    ).status_code == 200
    r = client.post(
        f"{base(fx)}/connections/{cid}/egress-policies", headers=hdr(fx.viewer_sub),
        json={"host": "api.example.com"},
    )
    assert r.status_code == 403


def test_a_stranger_sees_nothing(client: TestClient, fx: Fixture, target) -> None:
    url, _ = target
    cid = rest_connection(client, fx, url)
    r = client.get(
        f"{base(fx)}/connections/{cid}/egress-policies", headers=hdr(fx.outsider_sub)
    )
    assert r.status_code == 404


def test_policies_for_a_source_in_another_project_are_a_404(
    client: TestClient, fx: Fixture
) -> None:
    """"No policies" and "no such source" are different answers, and only one
    of them means unrestricted — so a source this project cannot see must not
    read as an empty list."""
    r = client.get(
        f"{base(fx)}/connections/{uuid.uuid4()}/egress-policies",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 404


# ---- the control, on a real call -------------------------------------------------
def test_a_source_with_no_policies_reaches_the_far_end(
    client: TestClient, fx: Fixture, target
) -> None:
    """**The presence half, and it is not a formality.** Without it every
    refusal below passes against an implementation that refuses everything —
    which is exactly what closed-by-default would have been."""
    url, _ = target
    assert probe(client, fx, rest_connection(client, fx, url))["ok"] is True


def test_a_policy_for_the_host_it_uses_still_reaches_it(
    client: TestClient, fx: Fixture, target
) -> None:
    url, port = target
    cid = rest_connection(client, fx, url)
    assert allow(client, fx, cid, host="127.0.0.1", port=port).status_code == 201
    assert probe(client, fx, cid)["ok"] is True


def test_a_policy_for_another_host_refuses_the_call(
    client: TestClient, fx: Fixture, target
) -> None:
    """`data-connection.md`'s acceptance test, in its own words: "a source
    configured for `host-a` cannot reach `host-b`, and the refusal names the
    policy"."""
    url, _ = target
    cid = rest_connection(client, fx, url)
    assert allow(client, fx, cid, host="api.example.com", port=443,
                 description="the vendor API").status_code == 201

    result = probe(client, fx, cid)
    assert result["ok"] is False
    assert "not allowed to reach 127.0.0.1" in result["error"]
    # Names what is allowed, and the description with it — "could not reach X"
    # sends somebody to check DNS and a firewall first.
    assert "api.example.com:443" in result["error"]
    assert "the vendor API" in result["error"]


def test_a_policy_on_the_wrong_port_refuses_the_same_host(
    client: TestClient, fx: Fixture, target
) -> None:
    """The port half. p.37 names it — egress policies "allowlist the specific
    hosts, ports, and protocols a source is permitted to connect to" — and
    decision 0013 had it marked as inferred until that page was read, which is
    why it gets a test that fails if the column is ignored rather than one that
    trusts the column exists for a reason."""
    url, port = target
    cid = rest_connection(client, fx, url)
    assert allow(client, fx, cid, host="127.0.0.1", port=port + 1).status_code == 201
    assert probe(client, fx, cid)["ok"] is False


def test_removing_the_last_policy_makes_the_source_unrestricted_again(
    client: TestClient, fx: Fixture, target
) -> None:
    """The switch works in both directions, and the second is the one nobody
    tests: a control that could be turned on and not off would trap every
    source that ever had a policy."""
    url, _ = target
    cid = rest_connection(client, fx, url)
    made = allow(client, fx, cid, host="api.example.com").json()
    assert probe(client, fx, cid)["ok"] is False

    client.delete(
        f"{base(fx)}/connections/{cid}/egress-policies/{made['id']}",
        headers=hdr(fx.editor_sub),
    )
    assert probe(client, fx, cid)["ok"] is True


def test_discovery_is_guarded_too(client: TestClient, fx: Fixture, target) -> None:
    """A second operation on the same source. The guard is in `_check_url`, and
    "the guard is in a shared function" is not the same claim as "every path
    reaches it" — decision 0013's enforcement table exists because two of the
    four did not."""
    url, _ = target
    cid = rest_connection(client, fx, url)
    allow(client, fx, cid, host="api.example.com")
    r = client.post(f"{base(fx)}/connections/{cid}/discover", headers=hdr(fx.editor_sub))
    assert r.status_code in (422, 502), r.text
    assert "not allowed to reach" in r.text


# ---- the two paths decision 0013's table found unchecked --------------------------
def db_connection(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Warehouse {uuid.uuid4().hex[:6]}", "source_type": "postgres",
              "scope": "project", "secret": {"password": DB.password},
              "config": {"host": DB.hostname, "port": DB.port or 5432,
                         "database": (DB.path or "/platform").lstrip("/"),
                         "user": DB.username}},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_database_source_with_a_policy_for_its_host_still_connects(
    client: TestClient, fx: Fixture
) -> None:
    """**A destination that is a host and a port, never a URL.**

    Decision 0013's enforcement table exists because this path had no check at
    all: `_check_url` guarded every REST call and there was nothing on the
    database connectors, so an allowlist on a Postgres source was a control
    that did nothing. The presence half first — this really does dial the
    socket, so a refusal below is a refusal and not a broken fixture.
    """
    cid = db_connection(client, fx)
    assert allow(client, fx, cid, host=DB.hostname,
                 port=DB.port or 5432).status_code == 201
    assert probe(client, fx, cid)["ok"] is True


def test_a_database_source_may_not_reach_a_host_it_has_no_policy_for(
    client: TestClient, fx: Fixture
) -> None:
    cid = db_connection(client, fx)
    assert allow(client, fx, cid, host="warehouse.example.com", port=5432,
                 description="the analytics warehouse").status_code == 201

    result = probe(client, fx, cid)
    assert result["ok"] is False
    assert f"not allowed to reach {DB.hostname}:{DB.port or 5432}" in result["error"]
    assert "warehouse.example.com:5432" in result["error"]


def test_a_policy_for_the_data_host_alone_does_not_permit_the_token_endpoint(
    client: TestClient, fx: Fixture, target, token_target
) -> None:
    """**p.12's two-destination source, and the half an allowlist would miss.**

    `token_url` is fetched by `_auth_headers` on the way to the data call, and
    it is a separate host reached with the same source's credentials — so a
    policy covering `base_url` and nothing else must not carry it. This is the
    other path decision 0013's table found unchecked; `validate_config` looked
    at `token_url` when the source was saved, which is not a send-time guard.
    """
    url, port = target
    token_url, _ = token_target
    cid = rest_connection(
        client, fx, url,
        config={"base_url": url, "allow_insecure_http": True,
                "resource_path": "oauth-data",
                "auth_type": "oauth2_client_credentials",
                "token_url": f"{token_url}/oauth-token"},
        secret={"client_id": "the-client", "client_secret": "the-secret"},
    )
    assert allow(client, fx, cid, host="127.0.0.1", port=port).status_code == 201

    result = probe(client, fx, cid)
    assert result["ok"] is False
    # The *token* port, not the data port: the data destination was permitted
    # and the call still stopped, which is the only shape that says the second
    # guard is the one that fired.
    assert f"not allowed to reach 127.0.0.1:{token_target[1]}" in result["error"]


def test_a_policy_for_both_destinations_lets_the_two_hop_source_through(
    client: TestClient, fx: Fixture, target, token_target
) -> None:
    """The presence half. Without it the refusal above passes against an
    implementation that simply cannot mint a token — and "the credential hop
    never worked" and "the credential hop was refused" are the two answers this
    pair exists to tell apart."""
    url, port = target
    token_url, token_port = token_target
    cid = rest_connection(
        client, fx, url,
        config={"base_url": url, "allow_insecure_http": True,
                "resource_path": "oauth-data",
                "auth_type": "oauth2_client_credentials",
                "token_url": f"{token_url}/oauth-token"},
        secret={"client_id": "the-client", "client_secret": "the-secret"},
    )
    assert allow(client, fx, cid, host="127.0.0.1", port=port).status_code == 201
    assert allow(client, fx, cid, host="127.0.0.1", port=token_port).status_code == 201
    assert probe(client, fx, cid)["ok"] is True


# ---- object storage, and the half of it that cannot be scoped ---------------------
#: `_client` builds a boto3 client and sends nothing, so both halves below are
#: settled before any socket exists. That is the point: the guard is at the
#: chokepoint every S3 operation goes through, not at each of them.
S3_SECRET = {"access_key_id": "ak", "secret_access_key": "sk"}


def test_a_custom_object_store_endpoint_is_a_destination_like_any_other(
    client: TestClient, fx: Fixture
) -> None:
    config = {"bucket": "landing", "region": "eu-west-2",
              "endpoint_url": "https://minio.internal:9000"}
    with egress.restricted_to([{"host": "minio.internal", "port": 9000}]):
        assert S3Connector()._client(config, S3_SECRET) is not None
    with egress.restricted_to([{"host": "elsewhere.example.com", "port": None}]):
        with pytest.raises(egress.EgressRefused) as refused:
            S3Connector()._client(config, S3_SECRET)
    assert "minio.internal:9000" in str(refused.value)


def test_an_aws_bucket_is_not_scoped_by_a_policy_and_this_is_deliberate(
    client: TestClient, fx: Fixture
) -> None:
    """**The documented gap, asserted rather than assumed** (`_client`'s own
    comment; `data-connection.md`'s row).

    With no `endpoint_url` boto3 derives the host from the bucket and region at
    request time, and p.184's troubleshooting page lists the destinations an S3
    sync reaches that nobody expected — STS among them. None of them pass
    through this function, so a policy naming one host cannot refuse the call.

    That is a limitation, and it is written down as one. This test is here so
    the limitation cannot quietly become a *claim*: if somebody later makes
    this path raise, they have to come here and decide whether the allowlist
    now honestly covers an AWS source, or whether it only looks like it does.
    """
    config = {"bucket": "landing", "region": "eu-west-2"}
    with egress.restricted_to([{"host": "nothing-like-s3.example.com", "port": None}]):
        assert S3Connector()._client(config, S3_SECRET) is not None


def test_the_platforms_own_guard_is_not_overridable_by_a_policy(
    client: TestClient, fx: Fixture
) -> None:
    """**Two controls, and a source's cannot switch the platform's off.**

    `_check_url` refuses the link-local range because that is where cloud
    instance metadata lives, and an allowlist naming it would otherwise read as
    permission. The connection cannot even be *saved* pointing there, which is
    the check doing its job one layer earlier — and is why this asserts on the
    create rather than on a call.
    """
    r = client.post(
        f"{base(fx)}/connections", headers=hdr(fx.editor_sub),
        json={"name": f"Metadata {uuid.uuid4().hex[:6]}", "source_type": "rest",
              "scope": "project", "secret": {},
              "config": {"base_url": "http://169.254.169.254/latest",
                         "allow_insecure_http": True}},
    )
    assert r.status_code == 422
    assert "link-local" in r.json()["detail"]
