"""Making the request (decision 0012 §3a; `data-connection` p.233-237).

The third half of a webhook, after "what does the definition mean" and "what is
in the database": the part that needs something on the other end of a socket.
Its own file because it is the only one of the three that can be slow, and
because everything in it is about failure — a function that returns a result
object rather than raising is a function whose callers all have to handle the
same three outcomes.

**Blocking `urllib` inside `anyio.to_thread.run_sync`.** The REST connector
makes its requests the same way and is right to: a sync runs in the worker,
where blocking is the point. A webhook runs inside `async def execute_action`,
and a blocking twenty-second call there does not slow that request — it stops
the event loop, so every other request the process is serving stops with it.
One unreachable host would look like the API going down, and nothing in the
logs would connect the two. Decision 0012 §3a records this because it is
invisible to every test that runs one request at a time, which is every test in
this repo.

**Nothing here raises for an HTTP failure.** A side-effect webhook's failure
must not fail the action (`action-types` p.106), and a writeback's must fail it
with a message naming what went wrong — two different treatments of the same
outcome, which means the outcome has to be a value the caller inspects rather
than an exception one of them has to swallow.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import anyio

from . import egress
from . import webhooks as webhooks_service
from .connectors import RestConnector, _check_url, _join_url

#: Ceiling on what is read back from the far end. A webhook's response is
#: parsed and may be stored (p.242), and neither of those should be able to be
#: a hundred megabytes because somebody pointed one at a download. Ours, not
#: the document's, and the refusal says which.
MAX_RESPONSE_BYTES = 1024 * 1024


def result(
    *, ok: bool, status: int | None = None, error: str | None = None,
    duration_ms: int = 0, request: dict[str, Any] | None = None,
    response: Any = None, outputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One execution's outcome, in the shape `webhook_store.record` stores.

    `system_changed` is computed here rather than passed in, so the one place
    that knows the status is the one place that answers p.237's question — a
    caller that had to work it out would be a second implementation of a
    three-valued rule.
    """
    return {
        "ok": ok,
        "status": status,
        "system_changed": True if ok else webhooks_service.system_changed(status),
        "error": error,
        "duration_ms": duration_ms,
        "request": request,
        "response": response,
        "outputs": outputs or {},
    }


async def perform(
    webhook: dict[str, Any],
    connection: dict[str, Any],
    secret: dict[str, str],
    values: dict[str, Any],
    policies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Render the request, send it, and say what happened.

    Never raises for anything the far end did. It *does* raise
    `webhooks.WebhookError` for a request that could not be built at all — a
    missing required input is a fault in the call, not in the response, and a
    caller has to tell those apart to decide whether to retry.
    """
    built = webhooks_service.render(webhook, values)
    # §263: the source's own allowlist, in scope for the call. **An explicit
    # argument here rather than an ambient scope set by the caller**, because
    # this one has a caller that already holds the connection row and nothing
    # else runs inside it — and an argument that cannot be forgotten is better
    # than a context that can. The connectors get the ambient form because
    # their protocol has no room for a fifth parameter.
    with egress.restricted_to(policies):
        return await anyio.to_thread.run_sync(
            lambda: _send(webhook, connection, secret, built)
        )


def _send(
    webhook: dict[str, Any],
    connection: dict[str, Any],
    secret: dict[str, str],
    built: dict[str, Any],
) -> dict[str, Any]:
    started_auth = time.monotonic()
    # A jsonb column comes back as a dict from some drivers and as text from
    # others, and `routes/connections.py` normalises it at every call site for
    # that reason. Done here rather than asking every caller of `perform` to do
    # it, because a caller that forgot would get `{}.get("base_url")` — an
    # empty base URL, a request to a relative path, and a failure that names
    # the URL rather than the mistake.
    raw_config = connection.get("config") or {}
    config = raw_config if isinstance(raw_config, dict) else json.loads(raw_config)
    url = _join_url(config.get("base_url", ""), built["path"])
    try:
        # The same guard the connector applies to a sync, and the reason
        # decision 0012 §4 keeps a webhook on a connection rather than letting
        # a rule carry a URL: an editor who could name a destination could
        # otherwise name the link-local range and read the task role's
        # credentials out of the response.
        _check_url(url, bool(config.get("allow_insecure_http", False)))
    except egress.EgressRefused as exc:
        # A refused destination is not a failure to reach one: nothing was
        # attempted. Recorded like any other failure, and with p.237's answer
        # for it — the far end cannot have changed, because nothing was sent.
        return result(ok=False, error=str(exc))
    except Exception as exc:
        return result(ok=False, error=str(exc))

    if built["query"]:
        separator = "&" if urllib.parse.urlparse(url).query else "?"
        url = f"{url}{separator}{urllib.parse.urlencode(built['query'])}"

    # The connection's auth **last**, so a webhook header can never replace it.
    # `webhooks.parse` already refuses the reserved names, and this ordering is
    # the second half of that: a guard at save time and a guard at send time,
    # because a row could have been written before the guard existed.
    #
    # Through the connector's own method rather than a second copy of the auth
    # rules. It is private and this reaches past that deliberately: four auth
    # types written out twice is §191's mirror, and the copy that drifts is the
    # one that stops sending a credential without anything failing to compile.
    headers = {"Accept": "application/json"}
    headers.update(built["headers"])
    try:
        # This can reach the network — `oauth2_client_credentials` fetches a
        # token — and it can refuse outright when the connection has no
        # credential stored. Both are failures of *this call*, so they become a
        # result rather than an exception: `perform`'s contract is that a side
        # effect cannot take the action down with it (`action-types` p.106),
        # and a raise here would do exactly that from inside a thread.
        headers.update(RestConnector()._auth_headers(config, secret))
    except Exception as exc:
        return result(
            ok=False, error=f"could not authenticate to the external system: {exc}",
            duration_ms=int((time.monotonic() - started_auth) * 1000), request=None,
        )

    data: bytes | None = None
    if built["body"] is not None:
        data = json.dumps(built["body"]).encode()
        headers.setdefault("Content-Type", "application/json")

    # **What is recorded as the request leaves the headers out.** p.242 stores
    # "inputs passed to the webhook", not the credential that carried them, and
    # the auth header is in this dict by the line above. The path and body are
    # what somebody debugging needs.
    sent = {"method": webhook["method"], "url": url, "body": built["body"]}

    started = time.monotonic()
    request = urllib.request.Request(
        url, data=data, headers=headers, method=webhook["method"]
    )
    try:
        with urllib.request.urlopen(
            request, timeout=int(webhook.get("timeout_seconds") or 20)
        ) as response:
            status = int(response.status)
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        # An HTTP error is a *response*, not a transport failure: it has a
        # status, and p.237's whole question is which statuses mean the far end
        # did not change. Reading the body matters too — an API's refusal
        # usually says why in it, and that sentence is the useful half of the
        # history.
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        elapsed = int((time.monotonic() - started) * 1000)
        return result(
            ok=False, status=int(exc.code),
            error=f"the external system returned HTTP {exc.code}",
            duration_ms=elapsed, request=sent, response=_decode(raw)[0],
        )
    except (urllib.error.URLError, OSError) as exc:
        # Never arrived, so nothing changed — and `result` works that out from
        # the absent status rather than being told.
        return result(
            ok=False, error=f"could not reach the external system: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000), request=sent,
        )

    elapsed = int((time.monotonic() - started) * 1000)
    if len(raw) > MAX_RESPONSE_BYTES:
        return result(
            ok=False, status=status,
            error=f"the response is larger than {MAX_RESPONSE_BYTES} bytes",
            duration_ms=elapsed, request=sent,
        )

    payload, problem = _decode(raw)
    if problem and webhook.get("outputs"):
        # A response that is not JSON is only a failure when something was
        # supposed to be read out of it. A webhook that declares no outputs has
        # no opinion about the body, and failing on one would refuse every
        # write-only endpoint that answers with `OK`.
        return result(
            ok=False, status=status, error=problem,
            duration_ms=elapsed, request=sent,
        )

    return result(
        ok=True, status=status, duration_ms=elapsed, request=sent,
        response=payload,
        outputs=webhooks_service.extract(webhook.get("outputs") or [], payload),
    )


def _decode(raw: bytes) -> tuple[Any, str | None]:
    """The body as JSON, or as text with a reason.

    Returns the *text* rather than nothing when it does not parse, because a
    502 whose body is an HTML error page is a body worth having in the history
    — it is usually the only thing that says which proxy refused.
    """
    text = raw.decode("utf-8", "replace")
    if not text.strip():
        return None, None
    try:
        return json.loads(text), None
    except ValueError:
        return text[:4000], "the external system did not return JSON"
