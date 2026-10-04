"""Outbound HTTP cannot be steered to metadata addresses (§880).

The platform refuses the link-local range for a source's URL, a token
endpoint and a webhook, because that is where a task's metadata is served.
It checked the URL it was given, and then urllib resolved the name again to
connect and followed redirects anywhere. Driven here against real servers on
loopback; the refused addresses are never contacted, because the refusal
comes before the connection.
"""
from __future__ import annotations

import http.server
import os
import socket
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.lib import safe_http  # noqa: E402


class _Server:
    """A loopback server that answers each path from `routes`: a status and
    headers, and remembers every request's headers."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict[str, str]]] = {}
        self.seen: list[dict[str, str]] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                server.seen.append({k.lower(): v for k, v in self.headers.items()})
                status, headers = server.routes.get(self.path, (200, {}))
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            def log_message(self, *args) -> None:
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()


@pytest.fixture()
def no_proxy(monkeypatch) -> None:
    """These requests are to loopback and to names that resolve only here;
    none should be handed to a proxy from the environment."""
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})


@pytest.fixture()
def server(no_proxy):
    s = _Server()
    yield s
    s.close()


def _reason(exc: BaseException) -> BaseException:
    return exc.reason if isinstance(exc, urllib.error.URLError) and not isinstance(
        exc, urllib.error.HTTPError) else exc


@pytest.mark.parametrize("address", [
    "169.254.169.254", "169.254.170.2", "::ffff:169.254.169.254",
    "fd00:ec2::254", "fe80::1%eth0", "0.0.0.0", "::",
])
def test_metadata_addresses_are_refused(address: str) -> None:
    assert safe_http.refused(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.4.12", "192.168.1.1", "8.8.8.8", "::1"])
def test_ordinary_addresses_private_ones_included_are_not(address: str) -> None:
    assert not safe_http.refused(address)


def test_a_redirect_to_the_metadata_address_is_not_followed(server: _Server) -> None:
    server.routes["/start"] = (302, {"Location": "http://169.254.170.2/v2/metadata"})
    with pytest.raises(urllib.error.URLError) as caught:
        safe_http.open_url(f"http://127.0.0.1:{server.port}/start", timeout=5)
    assert isinstance(_reason(caught.value), safe_http.RefusedDestination)


def test_a_name_that_resolves_to_it_at_connect_time_is_refused(no_proxy, monkeypatch) -> None:
    """A name checked when it answered publicly, and answering with the
    metadata address when the request goes out."""
    real = socket.getaddrinfo

    def rebinding(host, *args, **kwargs):
        if host == "rebind.test":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.170.2", 80))]
        return real(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", rebinding)
    with pytest.raises(urllib.error.URLError) as caught:
        safe_http.open_url("http://rebind.test/", timeout=5)
    assert isinstance(_reason(caught.value), safe_http.RefusedDestination)


def test_a_redirect_is_asked_of_the_egress_policy(server: _Server) -> None:
    server.routes["/start"] = (302, {"Location": f"http://localhost:{server.port}/next"})
    asked: list[tuple[str, int | None]] = []

    class Refused(RuntimeError):
        pass

    def policy(host: str, port: int | None) -> None:
        asked.append((host, port))
        raise Refused(f"{host} is not allowed")

    with pytest.raises(Refused):
        safe_http.open_url(f"http://127.0.0.1:{server.port}/start", timeout=5,
                           check_destination=policy)
    assert asked == [("localhost", server.port)]
    assert len(server.seen) == 1  # /next was never requested


def test_a_redirect_to_another_host_leaves_the_credential_behind(server: _Server) -> None:
    server.routes["/start"] = (302, {"Location": f"http://localhost:{server.port}/elsewhere"})
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/start",
                                     headers={"Authorization": "Bearer secret", "X-Kept": "1"})
    with safe_http.open_url(request, timeout=5) as response:
        assert response.status == 200
    first, second = server.seen
    assert first["authorization"] == "Bearer secret"
    assert "authorization" not in second
    assert second["x-kept"] == "1"


def test_a_redirect_on_the_same_host_keeps_it(server: _Server) -> None:
    server.routes["/start"] = (302, {"Location": "/same"})
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}/start",
                                     headers={"Authorization": "Bearer secret"})
    with safe_http.open_url(request, timeout=5):
        pass
    assert [seen["authorization"] for seen in server.seen] == ["Bearer secret"] * 2


def _redirect(allow_insecure_http: bool, start: str, to: str):
    handler = safe_http._Redirects(allow_insecure_http, None)
    return handler.redirect_request(urllib.request.Request(start), None, 302, "Found", {}, to)


def test_https_does_not_become_plain_http_unless_the_source_allows_it() -> None:
    with pytest.raises(urllib.error.HTTPError, match="https to plain http"):
        _redirect(False, "https://api.example.com/a", "http://api.example.com/b")
    assert _redirect(True, "https://api.example.com/a", "http://api.example.com/b") is not None
    assert _redirect(False, "http://api.example.com/a", "https://api.example.com/b") is not None


def test_only_http_and_https_are_followed() -> None:
    with pytest.raises(urllib.error.HTTPError, match="ftp URL"):
        _redirect(True, "http://api.example.com/a", "ftp://files.example.com/x")


def test_an_ordinary_request_still_goes_out(server: _Server) -> None:
    with safe_http.open_url(f"http://127.0.0.1:{server.port}/", timeout=5) as response:
        assert response.read() == b"ok"
