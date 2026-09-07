"""Which destinations a source may reach (decision 0013; `data-connection` p.12).

    "For Foundry worker sources, networking is configured via egress policies.
     They define at a granular level how each target system can be reached from
     Foundry, and which egress destinations are permitted." (p.12)

The pure half: given a source's policies and a host and port, may the call go
out? A wrong answer here is a line, which is why it is separate from the store
that reads the rows and from the four call sites that make the requests.

**Empty means unrestricted**, and decision 0013 §2 is the argument. The short
version: Foundry's model is closed because p.49 makes policies step 6 of
*setting up a source*, so a Foundry source never exists without them — and this
platform has sources that already exist, whose authors were never asked. There
is no migration that fixes that, because a REST source's `base_url` and its
OAuth `token_url` may be different hosts and an S3 source's destinations
include STS (p.184). A migration that guessed would produce policies that are
*almost* right, which is worse than none because it looks configured.

**A host and a port, not a URL.** Three of this platform's four outbound paths
have a URL and the fourth — a database connection — has never had one. Taking
the lower of the two shapes is what lets `connectors._check_url` become a
caller of this rather than its home.
"""
from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from typing import Any, Iterator

#: A hostname, as db 0068's CHECK spells it. Lowercase because a hostname is
#: case-insensitive and a policy for `API.example.com` that missed
#: `api.example.com` would be a guard with a one-keystroke bypass.
_HOST = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

#: p.103 pushes towards names rather than addresses — "use this ad-hoc domain
#: instead of `10.0.0.1`" — and decision 0013 declines CIDR ranges outright.
#: This is what refuses one: a range is what somebody writes when they do not
#: know the names, and it invites the allowlist to be widened until it means
#: nothing.
_LOOKS_LIKE_A_RANGE = re.compile(r"/\d{1,3}$")


class EgressError(ValueError):
    """A policy that cannot be saved, in a sentence somebody configuring a
    source can act on."""


class EgressRefused(RuntimeError):
    """A destination this source's policies do not permit.

    **Its own class, not a `ConnectorOperationError`.** A refused destination is
    not a failure to reach one — nothing was attempted — and the four call sites
    report the two differently: "could not reach X" sends somebody to check DNS,
    a firewall and the far end's health, which is exactly the investigation
    decision 0013 §4 exists to prevent.
    """


def parse(config: Any) -> dict[str, Any]:
    """Refuse a policy that could not do what its author meant. Returns it clean.

    The host is lowercased rather than refused for case, because a person
    typing `API.example.com` means the host — the two differ only in a
    convention nobody should have to know.
    """
    if not isinstance(config, dict):
        raise EgressError("a policy needs a host")
    host = str(config.get("host") or "").strip().lower()
    if not host:
        raise EgressError("a policy needs a host")
    if _LOOKS_LIKE_A_RANGE.search(host):
        raise EgressError(
            "an egress policy names one destination, not a range - name each "
            "host you need to reach, or the domain they share"
        )
    if len(host) > 253 or not _HOST.match(host):
        raise EgressError(f"{host!r} is not a hostname or an address")

    port = config.get("port")
    if port is not None and port != "":
        try:
            port = int(port)
        except (TypeError, ValueError):
            raise EgressError(f"{config.get('port')!r} is not a port") from None
        if not 1 <= port <= 65535:
            raise EgressError(f"{port} is not a port")
    else:
        # p.12 says nothing about ports, and a person who names a host and no
        # port has said nothing about ports. Reading that silence as a
        # restriction would refuse the call they were trying to allow.
        port = None

    return {
        "host": host,
        "port": port,
        "description": str(config.get("description") or "")[:500],
    }


def permitted(
    policies: list[dict[str, Any]], host: str, port: int | None
) -> dict[str, Any] | None:
    """The policy that allows this destination, or None.

    Returns the *policy* rather than a boolean, because decision 0013 §4 wants
    a refusal to name what was consulted and an approval to be auditable — and
    a caller that had a boolean would have to search the list again to say
    which.

    **An empty list is not a refusal**, and this function does not decide that:
    see {@link check}. Asked about a destination with no policies at all, there
    is nothing that allows it, and the answer is None either way.

    A policy with no port allows any port on its host. A policy with a port
    allows only that one — which is the whole reason the column exists.
    """
    wanted = (host or "").strip().lower()
    for policy in policies:
        if str(policy.get("host", "")).lower() != wanted:
            continue
        allowed = policy.get("port")
        if allowed is None or (port is not None and int(allowed) == int(port)):
            return policy
    return None


def check(policies: list[dict[str, Any]], host: str, port: int | None) -> None:
    """Refuse a destination this source may not reach. Raises {@link EgressRefused}.

    **The one place "empty means unrestricted" is decided.** Callers ask this
    rather than `permitted`, so there is exactly one expression of decision
    0013 §2 and no call site that can forget it.
    """
    if not policies:
        return
    if permitted(policies, host, port) is not None:
        return
    raise EgressRefused(describe(policies, host, port))


def describe(
    policies: list[dict[str, Any]], host: str, port: int | None
) -> str:
    """The refusal, in the words decision 0013 §4 asks for.

    Names what was *wanted* and what is *allowed*, because a message with only
    the first sends somebody to check DNS and a firewall before they think to
    look at a list in the platform.
    """
    where = f"{host}:{port}" if port is not None else str(host)
    allowed = ", ".join(sorted(label(p) for p in policies))
    return (
        f"this source is not allowed to reach {where}; its egress policies "
        f"allow {allowed}"
    )


def label(policy: dict[str, Any]) -> str:
    """One policy as it reads in a sentence and in a list."""
    host = str(policy.get("host", ""))
    port = policy.get("port")
    where = f"{host}:{port}" if port is not None else host
    description = str(policy.get("description") or "").strip()
    return f"{where} ({description})" if description else where


def port_for(scheme: str, explicit: int | None) -> int | None:
    """The port a URL means, given its scheme and whatever it stated.

    **Filled in rather than left None**, and that is the point of the function:
    `https://api.example.com/x` and `https://api.example.com:443/x` are the same
    destination, and a policy naming port 443 has to allow both. Reading the
    first as "no port" would make every port-scoped policy fail against the
    ordinary way people write URLs.

    An unknown scheme yields None, which `check` reads as "no port stated" and
    a port-scoped policy therefore refuses — the safe direction for a scheme
    this function has never heard of.
    """
    if explicit is not None:
        return explicit
    return {"http": 80, "https": 443}.get((scheme or "").lower())


# ---- how the policies reach the guard --------------------------------------------
#: The source whose call is being made, for the duration of one operation.
#:
#: **A context variable rather than an argument**, and the reason is the
#: `SourceConnector` protocol: its methods take `(config, secret)` and are
#: implemented four times over. Threading a fifth parameter through all of them
#: would touch every connector to serve two, and the database connectors' hosts
#: never pass through a URL guard at all — so there is no one function to add it
#: to. What every path *does* share is that somebody resolved a connection
#: before making the call, which is exactly the scope a context variable has.
#:
#: **It fails open, and that is written down rather than hoped about.** A call
#: site that forgets `restricted_to` sees an empty list, and an empty list is
#: "unrestricted" by decision 0013 §2 — so a forgotten one leaves the platform
#: exactly as it was before this feature, rather than refusing traffic nobody
#: asked it to refuse. For an opt-in control that is the right failure, but it
#: means a missing call site is silent: there is a test per path asserting the
#: policies actually reach the guard, and adding an outbound path means adding
#: one of those.
_policies: contextvars.ContextVar[list[dict[str, Any]]] = contextvars.ContextVar(
    "egress_policies", default=[]
)


@contextmanager
def restricted_to(policies: list[dict[str, Any]] | None) -> Iterator[None]:
    """Run this block as a call from a source with these policies.

    Reset on the way out rather than left set, because the same worker thread
    serves the next operation and a leaked allowlist would refuse a *different*
    source's destinations — a failure that looks like the second source being
    misconfigured.
    """
    token = _policies.set(list(policies or []))
    try:
        yield
    finally:
        _policies.reset(token)


def current() -> list[dict[str, Any]]:
    """The policies in force right now, empty when nothing set any."""
    return _policies.get()


def check_current(host: str, port: int | None) -> None:
    """{@link check} against whatever `restricted_to` is in scope.

    The form every call site uses, so none of them has to know where the
    policies came from — and so that adding a fifth outbound path is one line
    rather than a signature change.
    """
    check(current(), host, port)
