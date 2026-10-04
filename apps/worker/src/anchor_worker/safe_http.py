"""Outbound HTTP that cannot be steered to the cloud's metadata addresses (§880).

A source's URL, an OAuth token endpoint and a webhook are addresses somebody
typed. The platform refuses the link-local range for them, because that is
where an instance's or a task's metadata is served (`connectors._check_url`).
It checked the URL it was given, and then handed it to `urllib`, which
undid the check twice:

- **It resolved the name again to connect.** A name that answered with a
  public address when it was checked could answer with 169.254.170.2 a moment
  later (§259 recorded the same gap at save time).
- **It followed redirects anywhere.** A server at a checked address could
  answer `302 Location: http://169.254.170.2/...`, and urllib went there, from
  https to plain http, carrying the request's `Authorization` header.

So a request goes out through `open_url`, which connects only to an address
it has itself resolved and checked, and checks every redirect as the first
URL was checked: the scheme, the source's egress policy, and the address. A
redirect to another host leaves the credential behind, as browsers and
`requests` do.

Private ranges stay reachable on purpose: an internal API on a private subnet
is a legitimate source (`connectors._check_url`). So is loopback, for the same
reason and for the tests' own servers.

`apps/api/src/lib/safe_http.py` is the same file for the API.
"""
from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable

REFUSAL = (
    "refusing to reach the link-local address range "
    "(this is where cloud instance metadata lives)"
)

#: AWS's instance metadata over IPv6, which is not in a link-local range.
AWS_METADATA_V6 = ipaddress.ip_address("fd00:ec2::254")

#: Request headers that carry a credential, dropped on a redirect to another host.
CREDENTIAL_HEADERS = ("authorization", "cookie", "proxy-authorization")


class RefusedDestination(OSError):
    """An address the platform will not connect to, whatever asked for it."""


def refused(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    # Unspecified (0.0.0.0, ::) is refused too: connecting to it reaches this
    # host, by a spelling no check for "localhost" would recognise.
    return ip.is_link_local or ip.is_unspecified or ip == AWS_METADATA_V6


def check_host(host: str) -> None:
    """Refuse a name that resolves to a refused address. One that does not
    resolve is left for the request to report."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return
    if any(refused(str(info[4][0])) for info in infos):
        raise RefusedDestination(REFUSAL)


def _connect(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **_):
    """`socket.create_connection`, connecting only to addresses it has
    checked: the name is resolved once, here, and never again for this
    connection."""
    host, port = address
    infos = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    if any(refused(str(info[4][0])) for info in infos):
        raise RefusedDestination(REFUSAL)
    last: OSError | None = None
    for family, kind, proto, _, sockaddr in infos:
        sock = socket.socket(family, kind, proto)
        try:
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            last = exc
            sock.close()
    raise last or OSError(f"could not connect to {host}")


class _HTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._create_connection = _connect


class _HTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_HTTPConnection, req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnection, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, allow_insecure_http: bool,
                 check_destination: Callable[[str, int | None], None] | None) -> None:
        super().__init__()
        self._allow_insecure_http = allow_insecure_http
        self._check_destination = check_destination

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        here = urllib.parse.urlparse(req.full_url)
        there = urllib.parse.urlparse(newurl)
        if there.scheme not in ("http", "https"):
            raise urllib.error.HTTPError(
                newurl, code, f"refusing to follow a redirect to a {there.scheme} URL",
                headers, fp)
        if here.scheme == "https" and there.scheme == "http" and not self._allow_insecure_http:
            raise urllib.error.HTTPError(
                newurl, code, "refusing to follow a redirect from https to plain http",
                headers, fp)
        if self._check_destination is not None:
            port = there.port or (443 if there.scheme == "https" else 80)
            self._check_destination(there.hostname or "", port)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and (here.hostname, here.port) != (there.hostname, there.port):
            for name in list(new.headers):
                if name.lower() in CREDENTIAL_HEADERS:
                    del new.headers[name]
        return new


def open_url(
    request: urllib.request.Request | str,
    *,
    timeout: float,
    allow_insecure_http: bool = False,
    check_destination: Callable[[str, int | None], None] | None = None,
):
    """`urllib.request.urlopen`, held to the rules above. `check_destination`
    is the source's egress policy, asked again of every redirect."""
    opener = urllib.request.build_opener(
        _HTTPHandler, _HTTPSHandler, _Redirects(allow_insecure_http, check_destination))
    return opener.open(request, timeout=timeout)
