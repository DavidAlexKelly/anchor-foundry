"""Who sent a request, through the proxies in front of the API (§955).

A deployed API sits behind CloudFront and a load balancer, so the address it
hears a request from is the load balancer's. Each proxy appends the address
it heard from to X-Forwarded-For; the entry `hops` from the right is the one
the nearest trusted proxy wrote, and everything left of it came from the
sender and proves nothing. `LISTENER_PROXY_HOPS` says how many proxies there
are (one in front of a public load balancer, two behind CloudFront's VPC
origin; `infra/cdk`'s services construct sets it, and its stack check holds
it to the load balancer's scheme). The listener's allowlist read it first
(§850); the audit log's addresses read it too since §955.
"""
from __future__ import annotations

import os

from starlette.requests import Request


def proxy_hops() -> int:
    """How many proxies stand between a sender and this process: none in
    development, where nothing sets it."""
    raw = os.environ.get("LISTENER_PROXY_HOPS", "0")
    return int(raw) if raw.isdigit() else 0


def sender_address(peer: str | None, forwarded_for: str | None, hops: int) -> str | None:
    """The address that sent the request, behind `hops` proxies.

    Each proxy appends the address it heard from to X-Forwarded-For, so the
    entry `hops` from the right is the one the nearest trusted proxy wrote;
    everything to its left came from the sender and proves nothing. With no
    proxies it is the peer itself. Fewer entries than hops is an address
    nobody vouched for."""
    if hops <= 0:
        return peer
    entries = [e.strip() for e in (forwarded_for or "").split(",") if e.strip()]
    return entries[-hops] if len(entries) >= hops else None


def client_address(request: Request) -> str | None:
    """The address to record for this request: the one the proxies vouch
    for, not the load balancer's own (§955)."""
    return sender_address(request.client.host if request.client else None,
                          request.headers.get("x-forwarded-for"), proxy_hops())
