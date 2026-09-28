"""Diagnose a connection, step by step (§646; `data-connection` TOC §6).

> "Use this list as a first pass when a source or connection is not working.
> 1. Confirm the source is reachable … run dig, curl, and openssl s_client
> against your source's hostname and port. 2. Check egress configuration …
> 3. Check credentials … 4. Check certificates. PKIX or SSLHandshakeException
> errors indicate that the correct certificates are not configured for the
> source." (TOC §6, *Where to start*)

Foundry hands the reader a terminal on the source's network and the list
above. **A terminal is not offered here**: an editor with a shell on the API's
network could reach anything the API can, which is a much larger grant than
the connection it was opened for. The list is what is taken, run in order
against the one destination the connection's own configuration names:

1. **destination** - the host and port the configuration reaches;
2. **egress** - whether the source's policies allow it (decision 0013), and
   **before** anything touches the network, so a refused destination is never
   probed;
3. **dns** - `dig`'s question;
4. **tcp** - `curl`'s and `netcat`'s: does anything accept a connection;
5. **tls** - `openssl s_client`'s, for a source spoken to over TLS from the
   first byte (HTTPS). A database negotiates TLS inside its own protocol, so
   there it is the credentials step that proves it;
6. **credentials** - the connection's own test, the check TOC §6 lists third.

The first step that fails stops the rest, which are reported as skipped: a
host that does not resolve has no port to try, and saying "connection
refused" beside "does not resolve" would be two answers to one question. Each
failure carries a sentence saying what to do, since the point of the list is
the fix rather than the error.
"""
from __future__ import annotations

import socket
import ssl
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any, Callable

from . import egress

#: TOC §6's order, which is also the order a connection is made in.
STEPS = ("destination", "egress", "dns", "tcp", "tls", "credentials")
#: How long a connection attempt may take before it counts as unanswered.
CONNECT_TIMEOUT_S = 5.0


@dataclass(frozen=True)
class Destination:
    host: str
    port: int
    #: "direct" (TLS from the first byte), "in_protocol" (the driver upgrades
    #: the session), or "none" (plaintext, as configured).
    tls: str
    #: False for AWS's own S3 host, which boto3 derives and no policy scopes.
    scoped: bool = True


@dataclass(frozen=True)
class Step:
    name: str
    #: "ok", "failed", "skipped", or "info" (a fact that is neither).
    status: str
    detail: str
    hint: str | None = None


def destination(source_type: str, config: dict[str, Any]) -> Destination | None:
    """Where a connection's configuration says it connects, or None."""
    if source_type in ("postgres", "mysql"):
        host = str(config.get("host") or "")
        if not host:
            return None
        port = int(config.get("port") or (5432 if source_type == "postgres" else 3306))
        plaintext = (config.get("sslmode") == "disable" if source_type == "postgres"
                     else config.get("ssl_mode") == "disabled")
        return Destination(host, port, "none" if plaintext else "in_protocol")
    if source_type == "rest":
        return _url_destination(str(config.get("base_url") or ""))
    if source_type == "s3":
        if config.get("endpoint_url"):
            return _url_destination(str(config["endpoint_url"]))
        region = str(config.get("region") or "us-east-1")
        return Destination(f"s3.{region}.amazonaws.com", 443, "direct", scoped=False)
    return None


def _url_destination(url: str) -> Destination | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    port = egress.port_for(parsed.scheme, parsed.port)
    return Destination(parsed.hostname, int(port or 0),
                       "direct" if parsed.scheme == "https" else "none")


# The three network probes, as module functions so a test can stand in for the
# network where the network is not the thing under test.
def resolve(host: str, port: int) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})


def reach(host: str, port: int) -> None:
    with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S):
        pass


def handshake(host: str, port: int) -> str:
    context = ssl.create_default_context()
    with socket.create_connection((host, port), timeout=CONNECT_TIMEOUT_S) as raw:
        with context.wrap_socket(raw, server_hostname=host) as tls:
            cipher = tls.cipher()
            return f"{tls.version()}, {cipher[0] if cipher else 'no cipher'}"


def run(
    source_type: str,
    config: dict[str, Any],
    policies: list[dict[str, Any]],
    credentials: Callable[[], None],
) -> list[Step]:
    """TOC §6's list, in order, stopping at the first failure. `credentials`
    is the connection's own test, run under the source's egress policies."""
    steps: list[Step] = []

    def done(step: Step) -> list[Step]:
        steps.append(step)
        if step.status == "failed":
            steps.extend(Step(name, "skipped", f"not tried: {step.name} failed")
                         for name in STEPS[len(steps):])
        return steps

    where = destination(source_type, config)
    if where is None:
        return done(Step("destination", "failed", "the configuration names no host to reach",
                         "Fill in the host or URL and save the connection."))
    steps.append(Step("destination", "ok", f"{where.host}:{where.port}"))

    if not where.scoped:
        steps.append(Step(
            "egress", "info", "an AWS bucket's host is derived when the request is made, "
            "so egress policies do not scope this source"))
    else:
        try:
            egress.check(policies, where.host, where.port)
        except egress.EgressRefused as refused:
            return done(Step("egress", "failed", str(refused),
                             f"Add an egress policy for {where.host}:{where.port} in Networking, "
                             "or correct the host if this is not where the source is."))
        steps.append(Step("egress", "ok", "no policies: unrestricted" if not policies
                          else f"allowed by the source's policies ({len(policies)})"))

    try:
        addresses = resolve(where.host, where.port)
    except (socket.gaierror, UnicodeError) as exc:
        return done(Step("dns", "failed", f"{where.host} does not resolve: {exc}",
                         "Check the host name. A private name needs DNS the platform can see."))
    steps.append(Step("dns", "ok", ", ".join(addresses[:4]) + (" …" if len(addresses) > 4 else "")))

    try:
        reach(where.host, where.port)
    except OSError as exc:
        return done(Step(
            "tcp", "failed", f"nothing accepted a connection on {where.host}:{where.port}: {exc}",
            "Check the port, and that the source's firewall allows the platform's address."))
    steps.append(Step("tcp", "ok", f"{where.host}:{where.port} accepts connections"))

    if where.tls == "direct":
        try:
            steps.append(Step("tls", "ok", handshake(where.host, where.port)))
        except ssl.SSLCertVerificationError as exc:
            return done(Step(
                "tls", "failed",
                f"the certificate was not trusted: {getattr(exc, 'verify_message', None) or exc}",
                "A certificate from a private authority needs that authority trusted by the "
                "platform; an expired or misnamed one needs replacing on the source."))
        except (ssl.SSLError, OSError) as exc:
            return done(Step(
                "tls", "failed", f"the TLS handshake failed: {exc}",
                "The source may not offer a protocol or cipher the platform accepts. "
                "`openssl s_client -connect host:port -tls1_2` shows what it offers."))
    elif where.tls == "in_protocol":
        steps.append(Step("tls", "info", "negotiated inside the database protocol; "
                          "the credentials step proves it"))
    else:
        steps.append(Step("tls", "info", "plaintext, as the connection is configured"))

    try:
        credentials()
    except egress.EgressRefused as refused:
        # A second destination the connector reaches (a token URL, STS), which
        # the configuration's host did not name.
        return done(Step("credentials", "failed", str(refused),
                         "The source reaches another host while connecting; add a policy for it."))
    except KeyError:
        return done(Step("credentials", "failed", "stored credentials are missing",
                         "Update the connection's credentials."))
    except Exception as exc:  # the connector's own sentence, whatever its type
        return done(Step("credentials", "failed", str(exc),
                         "Re-enter the credentials if they may be stale, and check the "
                         "account may read what the connection names."))
    steps.append(Step("credentials", "ok", "the source accepted the connection's credentials"))
    return steps


def as_dicts(steps: list[Step]) -> list[dict[str, Any]]:
    return [asdict(s) for s in steps]
