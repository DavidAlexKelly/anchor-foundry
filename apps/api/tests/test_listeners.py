"""HTTPS listeners (§516; db 0106; `data-connection` p.249-266).

> "data connection listeners provision a URL endpoint, implement the specific
> message signing or other verification schemes for specific external systems"
> (p.249)

> "Individual event and request payloads are limited to 1 MB in size … Foundry
> rejects events that exceed this limit." (p.262)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sys
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import ADMIN_DSN, Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import connections as connection_routes  # noqa: E402
from src.services import listeners as listener_service  # noqa: E402
from src.services.secrets import InMemorySecretsGateway  # noqa: E402


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def gateway() -> InMemorySecretsGateway:
    return InMemorySecretsGateway()


@pytest.fixture(scope="module")
def client(gateway) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    connection_routes.configure_secrets_gateway(gateway)
    with TestClient(create_app(), raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/listeners"


def make(client, fx, **body) -> dict:
    body.setdefault("display_name", f"Hook {uuid.uuid4().hex[:6]}")
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def started(client, fx, **body) -> dict:
    made = make(client, fx, **body)
    r = client.post(f"{base(fx)}/{made['id']}/start", headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and r.json()["running"] is True
    return r.json()


def path_of(listener: dict) -> str:
    """The endpoint's path, from the URL the API built for it."""
    [active] = [e for e in listener["endpoints"] if e["active"]]
    return "/api/listen/" + active["url"].rsplit("/api/listen/", 1)[1]


def events(client, fx, listener: dict, sub=None) -> list[dict]:
    r = client.get(f"{base(fx)}/{listener['id']}/events", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_new_listener_is_stopped_with_one_endpoint(client, fx) -> None:
    made = make(client, fx)
    assert made["running"] is False and made["verification"] == "none"
    [endpoint] = made["endpoints"]
    assert endpoint["active"] and not endpoint["expired"] and endpoint["expires_at"] is None
    assert endpoint["url"].startswith("http://testserver/api/listen/")
    assert len(endpoint["url"].rsplit("/", 1)[1]) >= 43
    # Stopped: a request is refused, and says why.
    r = client.post(path_of(made), json={"a": 1})
    assert (r.status_code, r.json()["detail"]) == (503, "this listener is stopped")
    assert events(client, fx, made) == []


def test_a_running_listener_keeps_what_it_is_sent(client, fx) -> None:
    listener = started(client, fx)
    r = client.post(path_of(listener), content=b'{"ticket": 7}',
                    headers={"Content-Type": "application/json", "Authorization": "Bearer x",
                             "X-Trace": "abc"})
    assert r.status_code == 200 and r.json()["received"] is True
    [event] = events(client, fx, listener)
    assert (event["content_type"], event["size_bytes"], event["preview"], event["truncated"]) == (
        "application/json", 13, '{"ticket": 7}', False)
    assert event["headers"]["x-trace"] == "abc"
    assert event["headers"]["authorization"] == "[redacted]"
    assert event["id"] == r.json()["event"]
    # The listener says how much it has taken, and when.
    got = client.get(f"{base(fx)}/{listener['id']}", headers=hdr(fx.viewer_sub)).json()
    assert got["events"] == 1 and got["last_event_at"]


def test_events_come_newest_first_and_can_be_limited(client, fx) -> None:
    listener = started(client, fx)
    for n in range(3):
        client.post(path_of(listener), content=f"event {n}".encode())
    assert [e["preview"] for e in events(client, fx, listener)] == ["event 2", "event 1", "event 0"]
    r = client.get(f"{base(fx)}/{listener['id']}/events?limit=1", headers=hdr(fx.viewer_sub))
    assert [e["preview"] for e in r.json()] == ["event 2"]


def test_a_body_that_is_not_text_has_no_preview_and_a_long_one_is_cut(client, fx) -> None:
    listener = started(client, fx)
    client.post(path_of(listener), content=b"\xff\xfe\x00binary")
    long_text = "x" * (listener_service.PREVIEW_CHARS + 5)
    client.post(path_of(listener), content=long_text.encode())
    long_one, binary = events(client, fx, listener)
    assert (binary["preview"], binary["truncated"], binary["size_bytes"]) == (None, False, 9)
    assert long_one["preview"] == "x" * listener_service.PREVIEW_CHARS and long_one["truncated"]
    assert long_one["size_bytes"] == listener_service.PREVIEW_CHARS + 5


def test_a_body_over_a_megabyte_is_refused_either_way_it_arrives(client, fx) -> None:
    listener = started(client, fx)
    at_limit = b"a" * listener_service.MAX_BODY
    assert client.post(path_of(listener), content=at_limit).status_code == 200
    over = at_limit + b"a"
    r = client.post(path_of(listener), content=over)
    assert (r.status_code, r.json()["detail"]) == (413, "a request is at most 1048576 bytes")

    # Without a Content-Length, the stream is read one byte past the limit.
    def chunks():
        yield at_limit
        yield b"b"
    r = client.post(path_of(listener), content=chunks())
    assert r.status_code == 413
    assert [e["size_bytes"] for e in events(client, fx, listener)] == [listener_service.MAX_BODY]


def test_a_token_that_names_nothing_is_a_404(client, fx) -> None:
    r = client.post(f"/api/listen/{'z' * 43}", content=b"x")
    assert (r.status_code, r.json()["detail"]) == (404, "no listener answers here")
    listener = started(client, fx)
    path = path_of(listener)
    assert client.delete(f"{base(fx)}/{listener['id']}", headers=hdr(fx.editor_sub)).status_code == 204
    assert client.post(path, content=b"x").status_code == 404


def test_an_expired_endpoint_answers_nothing(client, fx) -> None:
    listener = started(client, fx)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE listener_endpoints SET expires_at = now() - interval '1 minute'"
                     " WHERE listener_id = %s", (listener["id"],))
    assert client.post(path_of_any(listener), content=b"x").status_code == 404
    got = client.get(f"{base(fx)}/{listener['id']}", headers=hdr(fx.viewer_sub)).json()
    assert got["endpoints"][0]["expired"] is True and got["endpoints"][0]["active"] is False


def path_of_any(listener: dict) -> str:
    return "/api/listen/" + listener["endpoints"][0]["url"].rsplit("/api/listen/", 1)[1]


def test_a_header_secret_is_checked_and_not_kept(client, fx, gateway) -> None:
    listener = started(client, fx, verification="header_secret",
                       verification_header="X-Hook-Token", secret="s3cret")
    assert "s3cret" not in json.dumps(listener) and "secret_arn" not in listener
    for given, status in (("s3cret", 200), ("s3cre", 401), ("s3crett", 401), (None, 401)):
        headers = {"X-Hook-Token": given} if given is not None else {}
        r = client.post(path_of(listener), content=b"{}", headers=headers)
        assert r.status_code == status, given
    assert client.post(path_of(listener), content=b"{}", headers={"X-Hook-Token": "no"}).json() \
        == {"detail": "the request did not verify"}
    [event] = events(client, fx, listener)
    assert event["headers"]["x-hook-token"] == "[redacted]"


def test_an_hmac_signature_is_over_the_body(client, fx) -> None:
    listener = started(client, fx, verification="hmac_sha256",
                       verification_header="X-Signature", secret="key")
    body = b'{"push": true}'
    sig = hmac.new(b"key", body, hashlib.sha256).hexdigest()
    for given, status in ((sig, 200), (f"sha256={sig}", 200), (sig.upper(), 200),
                          (f"SHA256={sig}", 200),
                          (hmac.new(b"key", body + b" ", hashlib.sha256).hexdigest(), 401),
                          (hmac.new(b"other", body, hashlib.sha256).hexdigest(), 401), ("", 401)):
        r = client.post(path_of(listener), content=body, headers={"X-Signature": given})
        assert r.status_code == status, given


def test_basic_authentication_is_a_username_and_password(client, fx) -> None:
    listener = started(client, fx, verification="basic", secret="hook:pa:ss")

    def auth(value: str) -> dict:
        return {"Authorization": value}
    good = base64.b64encode(b"hook:pa:ss").decode()
    cases = ((auth(f"Basic {good}"), 200), (auth(f"basic {good}"), 200),
             (auth(f"Basic {base64.b64encode(b'hook:pa:sx').decode()}"), 401),
             (auth("Basic !!notbase64"), 401), (auth(f"Bearer {good}"), 401), ({}, 401),
             (auth(f"Basic {base64.b64encode(bytes([0xff, 0xfe])).decode()}"), 401))
    for headers, status in cases:
        assert client.post(path_of(listener), content=b"x", headers=headers).status_code == status, headers


def test_a_configuration_that_cannot_verify_is_refused(client, fx) -> None:
    for body, message in (
        ({"verification": "magic"}, "verification must be one of none, basic, header_secret, hmac_sha256, not 'magic'"),
        ({"verification": "none", "secret": "x"}, "a listener that verifies nothing has no header or secret"),
        ({"verification": "none", "verification_header": "X-A"}, "a listener that verifies nothing has no header or secret"),
        ({"verification": "header_secret", "verification_header": "X-A"}, "header_secret verification needs a secret"),
        ({"verification": "hmac_sha256", "secret": "k"}, "hmac_sha256 verification needs the header it arrives in"),
        ({"verification": "basic", "secret": "a:b", "verification_header": "X-A"},
         "basic verification reads the Authorization header, so it takes no other"),
        ({"verification": "basic", "secret": "nocolon"}, "basic verification's secret is username:password"),
    ):
        r = client.post(base(fx), headers=hdr(fx.editor_sub), json={"display_name": "Bad", **body})
        assert r.status_code == 422, (body, r.text)
        assert r.json()["detail"] == message, body


def test_changing_the_verification_takes_effect_and_forgets_an_old_secret(client, fx, gateway) -> None:
    listener = started(client, fx)
    assert client.post(path_of(listener), content=b"x").status_code == 200
    r = client.put(f"{base(fx)}/{listener['id']}/verification", headers=hdr(fx.editor_sub),
                   json={"verification": "header_secret", "verification_header": "X-T", "secret": "t"})
    assert r.status_code == 200 and r.json()["verification"] == "header_secret"
    assert client.post(path_of(listener), content=b"x").status_code == 401
    assert client.post(path_of(listener), content=b"x", headers={"X-T": "t"}).status_code == 200
    kept = [arn for arn in gateway._store if listener["id"] in arn]
    assert len(kept) == 1
    r = client.put(f"{base(fx)}/{listener['id']}/verification", headers=hdr(fx.editor_sub),
                   json={"verification": "none"})
    assert r.status_code == 200 and r.json()["verification_header"] is None
    assert kept[0] not in gateway._store
    assert client.post(path_of(listener), content=b"x").status_code == 200
    r = client.put(f"{base(fx)}/{listener['id']}/verification", headers=hdr(fx.editor_sub),
                   json={"verification": "basic", "secret": "nocolon"})
    assert r.status_code == 422


def test_deleting_a_listener_deletes_its_secret(client, fx, gateway) -> None:
    listener = make(client, fx, verification="header_secret", verification_header="X-T", secret="t")
    assert any(listener["id"] in arn for arn in gateway._store)
    client.delete(f"{base(fx)}/{listener['id']}", headers=hdr(fx.editor_sub))
    assert not any(listener["id"] in arn for arn in gateway._store)


def test_stopping_and_renaming(client, fx) -> None:
    listener = started(client, fx)
    r = client.post(f"{base(fx)}/{listener['id']}/stop", headers=hdr(fx.editor_sub))
    assert r.json()["running"] is False
    assert client.post(path_of(listener), content=b"x").status_code == 503
    r = client.patch(f"{base(fx)}/{listener['id']}", headers=hdr(fx.editor_sub),
                     json={"display_name": "  Tickets  "})
    assert r.json()["display_name"] == "Tickets"


def test_listing_is_by_name_and_reading_is_a_viewer_s(client, fx) -> None:
    tag = uuid.uuid4().hex[:6]
    # Byte order puts "Zulu" first; a reader expects "alpha" first.
    make(client, fx, display_name=f"Zulu {tag}")
    make(client, fx, display_name=f"alpha {tag}")
    r = client.get(base(fx), headers=hdr(fx.viewer_sub))
    mine = [x["display_name"] for x in r.json() if x["display_name"].endswith(tag)]
    assert mine == [f"alpha {tag}", f"Zulu {tag}"]
    assert make(client, fx, display_name=f"  Padded {tag}  ")["display_name"] == f"Padded {tag}"


def test_managing_a_listener_is_an_editor_s(client, fx) -> None:
    listener = make(client, fx)
    lid = listener["id"]
    for method, path, body in (("post", "", {"display_name": "x"}), ("post", f"/{lid}/start", None),
                               ("post", f"/{lid}/stop", None), ("patch", f"/{lid}", {"display_name": "x"}),
                               ("put", f"/{lid}/verification", {"verification": "none"}),
                               ("delete", f"/{lid}", None)):
        kwargs = {"headers": hdr(fx.viewer_sub)}
        if body is not None:
            kwargs["json"] = body
        assert getattr(client, method)(f"{base(fx)}{path}", **kwargs).status_code == 403, (method, path)
    assert client.get(base(fx), headers=hdr(fx.outsider_sub)).status_code in (403, 404)


def test_a_listener_belongs_to_its_project(client, fx) -> None:
    listener = make(client, fx)
    other = client.post(f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.editor_sub),
                        json={"name": f"Elsewhere {uuid.uuid4().hex[:6]}"}).json()
    elsewhere = f"/api/workspaces/{fx.workspace}/projects/{other['id']}/listeners/{listener['id']}"
    assert client.get(elsewhere, headers=hdr(fx.editor_sub)).status_code == 404
    assert client.get(f"{elsewhere}/events", headers=hdr(fx.editor_sub)).status_code == 404
    assert client.post(f"{elsewhere}/start", headers=hdr(fx.editor_sub)).status_code == 404
    assert client.delete(elsewhere, headers=hdr(fx.editor_sub)).status_code == 404
    assert client.get(f"{base(fx)}/{uuid.uuid4()}", headers=hdr(fx.viewer_sub)).status_code == 404


def test_a_body_is_read_only_until_it_is_too_big() -> None:
    """`read_capped` stops pulling at the first chunk past the limit, so a
    sender cannot make the server hold more than one chunk over it."""
    import asyncio

    pulled: list[int] = []

    async def chunks():
        for n in range(5):
            pulled.append(n)
            yield b"x" * 4

    assert asyncio.run(listener_service.read_capped(chunks(), 6)) == b"x" * 8
    assert pulled == [0, 1]
    pulled.clear()
    assert asyncio.run(listener_service.read_capped(chunks(), 100)) == b"x" * 20
    assert pulled == [0, 1, 2, 3, 4]
    pulled.clear()
    # Exactly at the limit is not past it.
    assert asyncio.run(listener_service.read_capped(chunks(), 8)) == b"x" * 12


# ---- endpoint rotation (§517; p.258-259) ---------------------------------------

def rotate(client, fx, listener: dict, expire_old_at: str | None):
    return client.post(f"{base(fx)}/{listener['id']}/endpoints/rotate", headers=hdr(fx.editor_sub),
                       json={"expire_old_at": expire_old_at})


def soon(hours: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def test_rotating_with_an_expiry_keeps_both_addresses_working(client, fx) -> None:
    """p.258: "Generate a new endpoint, and add an expiration date for the old
    endpoint. You should now have two usable endpoints.\""""
    listener = started(client, fx)
    old_path = path_of(listener)
    r = rotate(client, fx, listener, soon(24))
    assert r.status_code == 200, r.text
    after = r.json()
    active = [e for e in after["endpoints"] if e["active"]]
    retiring = [e for e in after["endpoints"] if not e["active"]]
    assert len(active) == 1 and len(retiring) == 1
    assert retiring[0]["expires_at"] and not retiring[0]["expired"]
    # The active one is listed first.
    assert after["endpoints"][0]["active"] is True
    new_path = path_of(after)
    assert new_path != old_path
    assert client.post(old_path, content=b"old").status_code == 200
    assert client.post(new_path, content=b"new").status_code == 200
    # A third is refused until the retiring one is gone.
    r = rotate(client, fx, after, soon(1))
    assert r.status_code == 409
    assert r.json()["detail"] == "a listener has at most 2 endpoints; delete the one being retired first"


def test_rotating_without_an_expiry_retires_the_old_address_now(client, fx) -> None:
    listener = started(client, fx)
    old_path = path_of(listener)
    after = rotate(client, fx, listener, None).json()
    assert len(after["endpoints"]) == 1 and after["endpoints"][0]["active"]
    assert client.post(old_path, content=b"x").status_code == 404
    assert client.post(path_of(after), content=b"x").status_code == 200


def test_an_expiry_in_the_past_is_refused(client, fx) -> None:
    listener = started(client, fx)
    r = rotate(client, fx, listener, soon(-1))
    assert (r.status_code, r.json()["detail"]) == (409, "the old endpoint's expiry has to be in the future")
    assert len(client.get(f"{base(fx)}/{listener['id']}", headers=hdr(fx.viewer_sub)).json()["endpoints"]) == 1


def test_a_retiring_endpoint_can_be_extended_until_it_expires(client, fx) -> None:
    """p.259: "you can extend the expiration if more time is needed … Once an
    endpoint is expired, you can no longer modify the expiration date.\""""
    listener = started(client, fx)
    after = rotate(client, fx, listener, soon(1)).json()
    [active] = [e for e in after["endpoints"] if e["active"]]
    [retiring] = [e for e in after["endpoints"] if not e["active"]]
    url = f"{base(fx)}/{listener['id']}/endpoints"
    r = client.put(f"{url}/{retiring['id']}", headers=hdr(fx.editor_sub), json={"expires_at": soon(48)})
    assert r.status_code == 200, r.text
    [extended] = [e for e in r.json()["endpoints"] if e["id"] == retiring["id"]]
    assert extended["expires_at"] > retiring["expires_at"]
    for endpoint_id, at, message in (
        (active["id"], soon(5), "the active endpoint does not expire; rotate to retire it"),
        (retiring["id"], soon(-1), "an endpoint's expiry has to be in the future"),
    ):
        r = client.put(f"{url}/{endpoint_id}", headers=hdr(fx.editor_sub), json={"expires_at": at})
        assert (r.status_code, r.json()["detail"]) == (409, message)
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute("UPDATE listener_endpoints SET expires_at = now() - interval '1 second' WHERE id = %s",
                     (retiring["id"],))
    r = client.put(f"{url}/{retiring['id']}", headers=hdr(fx.editor_sub), json={"expires_at": soon(5)})
    assert (r.status_code, r.json()["detail"]) == (
        409, "an expired endpoint cannot be extended; delete it and rotate again")
    assert client.put(f"{url}/{uuid.uuid4()}", headers=hdr(fx.editor_sub),
                      json={"expires_at": soon(5)}).status_code == 404


def test_only_the_retired_endpoint_can_be_deleted(client, fx) -> None:
    listener = started(client, fx)
    after = rotate(client, fx, listener, soon(1)).json()
    [active] = [e for e in after["endpoints"] if e["active"]]
    [retiring] = [e for e in after["endpoints"] if not e["active"]]
    url = f"{base(fx)}/{listener['id']}/endpoints"
    r = client.delete(f"{url}/{active['id']}", headers=hdr(fx.editor_sub))
    assert (r.status_code, r.json()["detail"]) == (409, "the active endpoint cannot be deleted; rotate to replace it")
    r = client.delete(f"{url}/{retiring['id']}", headers=hdr(fx.editor_sub))
    assert r.status_code == 200 and [e["id"] for e in r.json()["endpoints"]] == [active["id"]]
    assert client.delete(f"{url}/{uuid.uuid4()}", headers=hdr(fx.editor_sub)).status_code == 404
    # And rotating is possible again.
    assert rotate(client, fx, r.json(), None).status_code == 200


def test_rotation_is_an_editor_s(client, fx) -> None:
    listener = make(client, fx)
    r = client.post(f"{base(fx)}/{listener['id']}/endpoints/rotate", headers=hdr(fx.viewer_sub),
                    json={"expire_old_at": None})
    assert r.status_code == 403
    eid = listener["endpoints"][0]["id"]
    assert client.put(f"{base(fx)}/{listener['id']}/endpoints/{eid}", headers=hdr(fx.viewer_sub),
                      json={"expires_at": soon(1)}).status_code == 403
    assert client.delete(f"{base(fx)}/{listener['id']}/endpoints/{eid}",
                         headers=hdr(fx.viewer_sub)).status_code == 403
