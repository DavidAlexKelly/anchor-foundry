"""What a webhook definition means (decision 0012; `data-connection` p.216-242).

The pure half. A wrong answer here is a line, which is why it is separate from
`webhook_store` — the half that needs a row to see — and from the outbound call
itself, which needs a server on the other end.

Three questions, and they are the three a webhook has:

* {@link parse} — is this definition sayable? Refused at *save* time, because
  the alternative is refusing it at click time in front of somebody who did not
  write it (§1.2a's argument, and §129's).
* {@link render} — what request does it make, given these inputs?
* {@link extract} — what comes back out of the response?

**The connection owns the destination and this owns the request.** p.220 draws
that line in its own words: "the source is meant to contain the minimal set of
secrets and connection details required to establish a connection… when
configuring individual webhooks using this source, you will have an opportunity
to add additional request details, including the relative path, query
parameters, headers, and body content." Decision 0012 §4 records why it is kept
rather than letting a rule carry a URL — chiefly that `connectors._check_url`
already refuses the link-local range where cloud instance metadata lives, and a
second path to an outbound request would be a second place to forget it.

**What is deliberately not here** is chaining. p.234's task body is an *array*
of calls with each reading the previous one's response, and p.237's rule that
"only one call is allowed to use an unsafe HTTP method" is a constraint on that
shape. One call has to be right first; the constraint is named in decision 0012
so it is not reinvented from scratch.
"""
from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

from . import templates

#: p.233's methods. The read-only three are separated because p.237 calls them
#: out by name — "by default, only GET, OPTIONS, and HEAD requests are
#: considered safe" — and a caller deciding whether a failure may have changed
#: the far end needs to know which it made.
#:
#: **`SAFE_METHODS` is a subset of `METHODS`, and a test asserts it.** The first
#: version of this file had `HEAD` and `OPTIONS` in the safe list and left them
#: out of the configurable one, which made half of a quoted rule a statement
#: about methods nobody could select — §214's absent control, one level down in
#: a constant rather than in a form. They are configurable: a HEAD or OPTIONS
#: webhook answers with its *status code*, which is a useful thing to ask an
#: external system, and `parse` refuses the output parameters that would have
#: no body to come from.
METHODS = ("GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE")
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

#: p.228's input types, less the ones that need something this platform does
#: not have. Absent rather than accepted-and-ignored (§214): `Attachment`
#: (p.229) needs an action form's uploaded file, and `List`/`Record` are
#: containers whose element constraints are a validator of their own.
INPUT_TYPES = ("string", "integer", "double", "boolean", "date", "timestamp")

#: p.229's output types. `record` is here and absent from the inputs because
#: the direction is what makes it cheap: capturing a JSON object out of a
#: response is a slice, while accepting one *in* is a schema to validate.
OUTPUT_TYPES = ("string", "integer", "double", "boolean", "record")

#: Bounds. Not from the document, which gives none for these — chosen so that a
#: definition cannot be a denial of service against the process that renders
#: it, and written down as ours rather than implied to be Foundry's.
MAX_INPUTS = 50
MAX_OUTPUTS = 50
MAX_HEADERS = 50
MAX_QUERY = 50
MAX_BODY_BYTES = 128 * 1024

#: p.237: `external-system-not-changed-status-codes` "defaults to all status
#: codes from 400 to 431". Everything else that failed is *unknown*, which is
#: the answer a person debugging a write failure needs said out loud.
UNCHANGED_STATUSES = range(400, 432)

#: Headers a webhook may not set, because the connection sets them and a
#: webhook that could override them would be a webhook that could send the
#: connection's credentials somewhere else, or send them nowhere and look
#: broken. p.233 says as much about authorization — "any edits should be done
#: by navigating back to the source".
RESERVED_HEADERS = frozenset({"authorization", "host", "content-length"})

_API_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,62}$")


class WebhookError(ValueError):
    """A webhook that cannot be saved, or a request that cannot be built, in a
    sentence somebody configuring one can act on."""


# ---- what is sayable ------------------------------------------------------------
def parse(config: Any) -> dict[str, Any]:
    """Refuse a webhook definition that could not be executed. Returns it clean.

    Every check has the save-time-not-click-time justification. The two worth
    naming separately:

    * **Every reference must name a declared input.** A template referencing
      something that does not exist renders as an empty string, and an empty
      string in a path is a request to a different endpoint than the one on
      screen — a failure that looks like the far end being wrong.
    * **A reserved header is refused rather than dropped.** Silently ignoring
      `Authorization:` would leave somebody looking at a header they wrote,
      believing it was sent (§214: a control that cannot work is worse than an
      absent one).
    """
    if not isinstance(config, dict):
        raise WebhookError("a webhook needs a configuration object")

    method = str(config.get("method") or "").upper()
    if method not in METHODS:
        raise WebhookError(f"method must be one of {', '.join(METHODS)}")

    inputs = _inputs(config.get("inputs") or [])
    declared = {i["api_name"] for i in inputs}

    path = str(config.get("path") or "")
    query = _pairs(config.get("query") or {}, MAX_QUERY, "query parameter")
    headers = _pairs(config.get("headers") or {}, MAX_HEADERS, "header")
    for name in headers:
        if name.lower() in RESERVED_HEADERS:
            raise WebhookError(
                f"the {name} header is set by the connection and cannot be "
                "overridden here - change it on the source instead"
            )
        if not _HEADER_NAME.match(name):
            raise WebhookError(f"{name!r} is not a valid header name")

    body = config.get("body")
    if body is not None and method in SAFE_METHODS:
        # Not a refusal about HTTP, which permits it, but about intent: a body
        # on a GET is silently dropped by many servers and proxies, so a
        # webhook configured that way would look correct and send nothing.
        raise WebhookError(f"a {method} request cannot carry a body")
    if body is not None and len(json.dumps(body)) > MAX_BODY_BYTES:
        raise WebhookError(f"the body is larger than {MAX_BODY_BYTES} bytes")

    # Every template, in one place, so a reference to something undeclared is
    # the same refusal wherever it was written.
    for where, text in _templates(path, query, headers, body):
        for name in templates.references(text):
            if name not in declared:
                raise WebhookError(
                    f"the {where} references {{{{{{{name}}}}}}}, which is not an "
                    "input of this webhook"
                )

    outputs = _outputs(config.get("outputs") or [])
    if outputs and method == "HEAD":
        raise WebhookError("a HEAD request has no body to read outputs from")

    return {
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body": body,
        "inputs": inputs,
        "outputs": outputs,
        "store_responses": bool(config.get("store_responses", True)),
        "retry_statuses": _statuses(config.get("retry_statuses") or []),
        "timeout_seconds": _timeout(config.get("timeout_seconds", 20)),
    }


def _inputs(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise WebhookError("inputs must be a list")
    if len(raw) > MAX_INPUTS:
        raise WebhookError(f"a webhook may declare at most {MAX_INPUTS} inputs")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise WebhookError("each input must be an object")
        name = str(item.get("api_name") or "")
        if not _API_NAME.match(name):
            raise WebhookError(f"{name!r} is not a valid input name")
        if name in seen:
            raise WebhookError(f"two inputs are both called {name!r}")
        seen.add(name)
        data_type = str(item.get("data_type") or "string")
        if data_type not in INPUT_TYPES:
            raise WebhookError(
                f"input {name!r}: type must be one of {', '.join(INPUT_TYPES)}"
            )
        out.append({
            "api_name": name,
            "data_type": data_type,
            # p.229's "optional parameters represent inputs that may or may not
            # be present". Required is the default, because a webhook whose
            # inputs are all optional is a webhook that can be fired with
            # nothing and will be.
            "required": bool(item.get("required", True)),
        })
    return out


def _outputs(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise WebhookError("outputs must be a list")
    if len(raw) > MAX_OUTPUTS:
        raise WebhookError(f"a webhook may declare at most {MAX_OUTPUTS} outputs")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise WebhookError("each output must be an object")
        name = str(item.get("api_name") or "")
        if not _API_NAME.match(name):
            raise WebhookError(f"{name!r} is not a valid output name")
        if name in seen:
            raise WebhookError(f"two outputs are both called {name!r}")
        seen.add(name)
        data_type = str(item.get("data_type") or "string")
        if data_type not in OUTPUT_TYPES:
            raise WebhookError(
                f"output {name!r}: type must be one of {', '.join(OUTPUT_TYPES)}"
            )
        # p.235's two ways: "capturing top-level fields from a JSON response by
        # name" and a path for more. One field here, because a bare name *is* a
        # one-segment path — two fields would be two ways to say the same thing
        # and a rule about which wins.
        out.append({
            "api_name": name,
            "data_type": data_type,
            "path": str(item.get("path") or name),
        })
    return out


def _pairs(raw: Any, limit: int, what: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise WebhookError(f"{what}s must be an object")
    if len(raw) > limit:
        raise WebhookError(f"a webhook may set at most {limit} {what}s")
    out: dict[str, str] = {}
    for key, value in raw.items():
        name = str(key)
        if not name:
            raise WebhookError(f"a {what} needs a name")
        out[name] = str(value)
    return out


def _statuses(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        raise WebhookError("retry_statuses must be a list")
    out: list[int] = []
    for item in raw:
        try:
            code = int(item)
        except (TypeError, ValueError):
            raise WebhookError(f"{item!r} is not an HTTP status code") from None
        if not 100 <= code <= 599:
            raise WebhookError(f"{code} is not an HTTP status code")
        out.append(code)
    return out


def _timeout(raw: Any) -> int:
    try:
        seconds = int(raw)
    except (TypeError, ValueError):
        raise WebhookError("the timeout must be a whole number of seconds") from None
    if not 1 <= seconds <= 60:
        # The upper bound is the one that matters and it is ours, not the
        # document's: a webhook fires inside a request somebody is waiting on
        # (decision 0012 §3), so a timeout longer than a minute is a way to
        # make an action look hung.
        raise WebhookError("the timeout must be between 1 and 60 seconds")
    return seconds


def _templates(
    path: str, query: dict[str, str], headers: dict[str, str], body: Any
) -> list[tuple[str, str]]:
    """Every string in a definition that may hold a reference, named for the
    refusal message. The body is walked whole, because a reference can be at
    any depth in a JSON document and a check that only read the top level would
    pass the one that matters."""
    found: list[tuple[str, str]] = [("path", path)]
    found += [(f"{k} query parameter", v) for k, v in query.items()]
    found += [(f"{k} header", v) for k, v in headers.items()]
    found += [("body", text) for text in _strings(body)]
    return found


def _strings(node: Any) -> list[str]:
    """Every string anywhere in a decoded JSON value, keys included.

    Keys as well as values, because `{"{{{name}}}": 1}` is a reference too and
    a webhook that resolved it in one position and not the other would be
    right about the common case and silently wrong about the other.
    """
    if isinstance(node, str):
        return [node]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    if isinstance(node, dict):
        return [
            s
            for key, value in node.items()
            for s in ([key] if isinstance(key, str) else []) + _strings(value)
        ]
    return []


# ---- what request it makes -------------------------------------------------------
def render(webhook: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """The concrete request, given the inputs a caller supplied.

    Returns `{path, query, headers, body}` with every reference resolved.
    Raises when a required input is missing, because an unresolved reference
    becomes an empty string and an empty string in a path is a request to a
    different endpoint than the one somebody configured.

    **The body substitutes by value, not by text**, and that is the piece worth
    reading twice. A body is JSON; interpolating into its *source text* would
    let a string containing a quote produce a document that no longer parses,
    and would turn every input into a string on the way. So the body is walked
    as a structure: a string that is exactly one reference becomes the input's
    own value with its own type, and a string that merely contains references
    is interpolated as text, because a number concatenated to a sentence cannot
    be anything but a sentence. p.234's `{{json message }}` is the same
    distinction, spelt with a helper.

    **Path values are percent-encoded and query values are not.** The path is
    assembled into a URL here, so a value holding `/` or `?` would silently
    change the endpoint. Query values are handed to `urlencode` by the caller,
    which does its own encoding — doing it twice is how `%20` becomes `%2520`.
    """
    missing = [
        i["api_name"] for i in webhook.get("inputs", [])
        if i.get("required", True) and values.get(i["api_name"]) is None
    ]
    if missing:
        raise WebhookError(f"missing required input(s): {', '.join(sorted(missing))}")

    return {
        "path": _fill(str(webhook.get("path") or ""), values, encode=True),
        "query": {
            k: _fill(v, values) for k, v in (webhook.get("query") or {}).items()
        },
        "headers": {
            k: _fill(v, values) for k, v in (webhook.get("headers") or {}).items()
        },
        "body": _fill_json(webhook.get("body"), values),
    }


def _fill(text: str, values: dict[str, Any], *, encode: bool = False) -> str:
    def one(match: "re.Match[str]") -> str:
        rendered = _text(values.get(match.group(1)))
        return quote(rendered, safe="") if encode else rendered

    return templates.REFERENCE.sub(one, text or "")


def _fill_json(node: Any, values: dict[str, Any]) -> Any:
    if isinstance(node, str):
        if templates.is_whole_reference(node):
            # The typed substitution: an integer input stays an integer, and a
            # missing optional one becomes JSON null rather than "".
            return values.get(templates.references(node)[0])
        return _fill(node, values)
    if isinstance(node, list):
        return [_fill_json(item, values) for item in node]
    if isinstance(node, dict):
        return {_fill(str(k), values): _fill_json(v, values) for k, v in node.items()}
    return node


def _text(value: Any) -> str:
    """One input value as it reads inside a string.

    `None` is empty rather than "None", and a boolean is lowercase rather than
    Python's `True` — the same two rules `notifications._text` makes, for the
    same reason: these strings are read by another system, and Python's repr is
    a fact about Python.
    """
    if value is None:
        return ""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


# ---- what comes back out ---------------------------------------------------------
def extract(outputs: list[dict[str, Any]], payload: Any) -> dict[str, Any]:
    """p.229's output parameters, read out of a decoded response.

    A path that names nothing yields `None` rather than raising: p.235's
    extraction is a convenience over a response the webhook does not control,
    and an action failing because an optional field was absent this time would
    be a failure about the far end's shape rather than about the request.

    > "If a String output parameter is configured and the Webhook task result
    > is not a string, then the result will be converted to a JSON string."
    > (p.232)

    That sentence is the whole coercion rule, and it is the reason `string` is
    not just `str()`: a dict rendered by `str()` is Python's repr, with single
    quotes, which is not JSON and not what anything downstream can parse.
    """
    found: dict[str, Any] = {}
    for output in outputs:
        value = _at(payload, str(output.get("path") or output["api_name"]))
        found[output["api_name"]] = _coerce(value, str(output.get("data_type") or "string"))
    return found


def _at(payload: Any, path: str) -> Any:
    """Dotted lookup, one segment at a time, stopping at the first miss.

    Deliberately the same shape as `connectors._json_path`, which the REST
    connector already uses to find a records array — a second path language in
    one repo is a second thing to be wrong about, and this one has to survive
    a list where an object was expected without raising.
    """
    node = payload
    for segment in [s for s in (path or "").split(".") if s]:
        if isinstance(node, dict):
            node = node.get(segment)
        elif isinstance(node, list) and segment.isdigit():
            index = int(segment)
            node = node[index] if index < len(node) else None
        else:
            return None
        if node is None:
            return None
    return node


def _coerce(value: Any, data_type: str) -> Any:
    if value is None:
        return None
    if data_type == "record":
        return value if isinstance(value, dict) else None
    if data_type == "boolean":
        return bool(value)
    if data_type in ("integer", "double"):
        try:
            return int(value) if data_type == "integer" else float(value)
        except (TypeError, ValueError):
            # None rather than the raw value: an output declared numeric and
            # used as one downstream must not turn out to be a string because
            # the far end sent "n/a" once.
            return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))
    return str(value)


# ---- what a failure means --------------------------------------------------------
def retryable(status: int | None, retry_statuses: list[int]) -> bool:
    """p.237's `retryable-status-codes`, which "defaults to an empty list".

    Empty by default and not inferred from the status class, which is the
    tempting alternative: 503 is retryable for most APIs and is a permanent
    refusal for some, and guessing would retry a write against the ones where
    it is not safe.
    """
    return status is not None and status in (retry_statuses or [])


def system_changed(status: int | None) -> bool | None:
    """Whether a failed call may have changed the far end (p.237).

    Three-valued, and the third value is the point. A request that never got a
    status did not arrive, so nothing changed. A status in p.237's default
    `external-system-not-changed-status-codes` — "all status codes from 400 to
    431" — is the server saying it refused. Anything else is **unknown**, and
    saying so is more useful than a `False` that would be believed.
    """
    if status is None:
        return False
    if status in UNCHANGED_STATUSES:
        return False
    if 200 <= status < 300:
        return True
    return None
