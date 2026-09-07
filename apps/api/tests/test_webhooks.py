"""What a webhook definition means (decision 0012; §259).

No database and no server: `services/webhooks` is the half where a wrong answer
is a line. The half that needs a row is `test_webhook_store.py`, and the half
that needs something on the other end of a socket is `test_webhook_calls.py`.

`data-connection` page numbers are `p.N`.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.services import templates  # noqa: E402
from src.services import webhooks as wh  # noqa: E402


def definition(**over):
    base = {
        "method": "POST",
        "path": "items",
        "inputs": [{"api_name": "name", "data_type": "string"}],
        "body": {"text": "{{{name}}}"},
    }
    base.update(over)
    return base


# ---- the vocabularies -----------------------------------------------------------
def test_the_safe_methods_are_the_three_p237_names() -> None:
    """"By default, only GET, OPTIONS, and HEAD requests are considered safe."
    (p.237). Asserted as a set rather than by length, so a fourth added here
    without a reason turns this red."""
    assert set(wh.SAFE_METHODS) == {"GET", "HEAD", "OPTIONS"}


def test_every_safe_method_is_also_a_method() -> None:
    """Two lists that have to agree, and nothing else makes them.

    **This test found the defect it was written for, on its first run.** The
    safe list quoted p.237 and named `HEAD` and `OPTIONS`; the configurable
    list did not have them, so two thirds of a quoted rule was a statement
    about methods nobody could select — §214's absent control, in a constant
    rather than in a form.
    """
    assert set(wh.SAFE_METHODS) <= set(wh.METHODS)


def test_the_unchanged_statuses_are_p237s_range() -> None:
    """"This option defaults to all status codes from 400 to 431." (p.237)"""
    assert 400 in wh.UNCHANGED_STATUSES
    assert 431 in wh.UNCHANGED_STATUSES
    assert 432 not in wh.UNCHANGED_STATUSES
    assert 399 not in wh.UNCHANGED_STATUSES


# ---- parse ----------------------------------------------------------------------
def test_a_definition_that_would_run_is_accepted() -> None:
    assert wh.parse(definition())["method"] == "POST"


def test_a_method_the_platform_cannot_send_is_refused() -> None:
    with pytest.raises(wh.WebhookError, match="method must be"):
        wh.parse(definition(method="TRACE"))


def test_the_method_is_read_case_insensitively() -> None:
    # Somebody typing `post` means POST, and a refusal about capitalisation is
    # a refusal about nothing.
    assert wh.parse(definition(method="post"))["method"] == "POST"


def test_a_reference_to_something_undeclared_is_refused_at_save_time() -> None:
    """The alternative is an empty string in a live request: an unresolved
    reference renders as nothing, and nothing in a path is a request to a
    different endpoint than the one on screen."""
    with pytest.raises(wh.WebhookError, match="not an input"):
        wh.parse(definition(path="items/{{{nope}}}"))


def test_a_reference_deep_in_the_body_is_checked_too() -> None:
    # A check that only read the top level would pass the one that matters:
    # bodies nest, and the reference somebody gets wrong is rarely at depth 0.
    with pytest.raises(wh.WebhookError, match="not an input"):
        wh.parse(definition(body={"a": {"b": [{"c": "{{{nope}}}"}]}}))


def test_a_reference_in_a_body_key_is_checked_too() -> None:
    # `{"{{{name}}}": 1}` is a reference, and one resolved in values but not in
    # keys would be right about the common case and silently wrong here.
    with pytest.raises(wh.WebhookError, match="not an input"):
        wh.parse(definition(body={"{{{nope}}}": 1}))


def test_references_in_query_and_headers_are_checked(  ) -> None:
    with pytest.raises(wh.WebhookError, match="not an input"):
        wh.parse(definition(query={"q": "{{{nope}}}"}))
    with pytest.raises(wh.WebhookError, match="not an input"):
        wh.parse(definition(headers={"X-Trace": "{{{nope}}}"}))


def test_two_braces_are_not_a_reference_and_so_are_not_checked() -> None:
    """The count is the whole convention (p.94, `services/templates`).

    A two-brace template is *not* a reference, so it is not an undeclared one
    either — it is literal text that will be sent as typed. This test exists
    because the natural way to get the pattern wrong is to make it tolerant,
    and a tolerant pattern would make this a refusal.
    """
    assert wh.parse(definition(path="items/{{nope}}"))["path"] == "items/{{nope}}"


def test_the_connections_headers_cannot_be_overridden() -> None:
    """p.233: "Authorization details are based on the source configuration. Any
    edits should be done by navigating back to the source."

    Refused rather than dropped: silently ignoring it would leave somebody
    looking at a header they wrote, believing it was sent.
    """
    with pytest.raises(wh.WebhookError, match="set by the connection"):
        wh.parse(definition(headers={"Authorization": "Bearer x"}))


def test_the_reserved_header_check_ignores_case() -> None:
    # HTTP header names are case-insensitive, so a check that was not would be
    # a guard with a one-character bypass.
    with pytest.raises(wh.WebhookError, match="set by the connection"):
        wh.parse(definition(headers={"authorization": "Bearer x"}))


def test_a_body_on_a_read_only_method_is_refused() -> None:
    """Not a rule about HTTP, which permits it, but about intent: many servers
    and proxies drop a GET body, so the webhook would look configured and send
    nothing."""
    with pytest.raises(wh.WebhookError, match="cannot carry a body"):
        wh.parse(definition(method="GET", body={"a": 1}))


def test_a_read_only_method_without_a_body_is_fine() -> None:
    # The presence half of §157: the refusal above is only meaningful if the
    # method itself is allowed.
    assert wh.parse(definition(method="GET", body=None))["method"] == "GET"


def test_two_inputs_with_one_name_are_refused() -> None:
    with pytest.raises(wh.WebhookError, match="both called"):
        wh.parse(definition(inputs=[{"api_name": "a"}, {"api_name": "a"}]))


def test_an_input_type_the_platform_cannot_send_is_refused() -> None:
    """p.229's `Attachment` needs an action form's uploaded file, and this
    platform has nowhere to get one. Absent rather than accepted and ignored
    (§214)."""
    with pytest.raises(wh.WebhookError, match="type must be one of"):
        wh.parse(definition(inputs=[{"api_name": "f", "data_type": "attachment"}]))


def test_an_input_is_required_unless_it_says_otherwise() -> None:
    # p.229's optional inputs exist; the default is the other one, because a
    # webhook whose inputs are all optional can be fired with nothing.
    assert wh.parse(definition())["inputs"][0]["required"] is True
    parsed = wh.parse(definition(inputs=[{"api_name": "name", "required": False}]))
    assert parsed["inputs"][0]["required"] is False


def test_an_output_path_defaults_to_its_name() -> None:
    """p.235's first way — "capturing top-level fields from a JSON response by
    name" — is the one-segment case of the second, so there is one field rather
    than two and no rule about which wins."""
    parsed = wh.parse(definition(outputs=[{"api_name": "unique_id"}]))
    assert parsed["outputs"][0]["path"] == "unique_id"


def test_outputs_on_a_head_request_are_refused() -> None:
    # A HEAD response has no body, so an output declared against one could
    # never be anything but null — a save that configures a lie.
    with pytest.raises(wh.WebhookError, match="no body"):
        wh.parse(definition(method="HEAD", body=None, outputs=[{"api_name": "x"}]))


def test_a_timeout_longer_than_a_minute_is_refused() -> None:
    """Ours, not the document's: a webhook fires inside a request somebody is
    waiting on (decision 0012 §3), so a long timeout is a way to make an action
    look hung."""
    with pytest.raises(wh.WebhookError, match="between 1 and 60"):
        wh.parse(definition(timeout_seconds=120))


def test_a_status_that_is_not_one_is_refused() -> None:
    with pytest.raises(wh.WebhookError, match="not an HTTP status"):
        wh.parse(definition(retry_statuses=[99]))


def test_responses_are_stored_unless_asked_otherwise() -> None:
    """p.242 makes storing the default and turning it off the deliberate act,
    which is the right way round: a webhook you cannot debug is worse than one
    whose responses only its caller can read."""
    assert wh.parse(definition())["store_responses"] is True
    assert wh.parse(definition(store_responses=False))["store_responses"] is False


# ---- render ---------------------------------------------------------------------
def test_a_missing_required_input_stops_the_request() -> None:
    """Rather than sending an empty string, which is a request to a different
    endpoint than the one configured."""
    with pytest.raises(wh.WebhookError, match="missing required input"):
        wh.render(wh.parse(definition(path="items/{{{name}}}")), {})


def test_a_missing_optional_input_leaves_its_field_out_of_the_body() -> None:
    """Not `""`, and — since the mutation round that produced
    `test_an_unsupplied_optional_input_drops_its_key` — not `null` either.

    This test asserted `{"text": None}` when it was written, on the reasoning
    that "null is how JSON says absent". It is not: `{"text": null}` is how
    JSON says *explicitly cleared*, and an API that tells the two apart reads
    it as an instruction to erase. The assertion is the corrected one and the
    docstring is the record of why it moved.
    """
    parsed = wh.parse(definition(inputs=[{"api_name": "name", "required": False}]))
    assert wh.render(parsed, {})["body"] == {}


def test_a_whole_reference_in_a_body_keeps_its_type() -> None:
    """**The piece worth reading twice.** A body is JSON; interpolating into
    its source text would turn every input into a string, and `{"count": "3"}`
    is a different document from `{"count": 3}` — rejected by most servers and
    silently accepted as something else by some."""
    parsed = wh.parse(definition(
        inputs=[{"api_name": "count", "data_type": "integer"}],
        body={"count": "{{{count}}}"},
    ))
    assert wh.render(parsed, {"count": 3})["body"] == {"count": 3}


def test_a_reference_among_other_text_becomes_text() -> None:
    # The other half, and it is what makes the first half a decision rather
    # than an accident: a number concatenated to a sentence is a sentence.
    parsed = wh.parse(definition(
        inputs=[{"api_name": "count", "data_type": "integer"}],
        body={"label": "n={{{count}}}"},
    ))
    assert wh.render(parsed, {"count": 3})["body"] == {"label": "n=3"}


def test_a_reference_in_a_body_key_is_substituted() -> None:
    parsed = wh.parse(definition(body={"{{{name}}}": 1}))
    assert wh.render(parsed, {"name": "k"})["body"] == {"k": 1}


def test_a_path_value_is_percent_encoded() -> None:
    """The path is assembled into a URL, so a value holding `/` would silently
    change which endpoint is called — an input becoming a routing decision."""
    parsed = wh.parse(definition(path="items/{{{name}}}"))
    assert wh.render(parsed, {"name": "a/b?c"})["path"] == "items/a%2Fb%3Fc"


def test_a_query_value_is_not_encoded_here() -> None:
    """Encoded once, by `urlencode` in the caller. Doing it twice is how `%20`
    becomes `%2520`, which is a bug that survives every test that only looks at
    the string this function returns."""
    parsed = wh.parse(definition(query={"q": "{{{name}}}"}))
    assert wh.render(parsed, {"name": "a b"})["query"] == {"q": "a b"}


def test_a_boolean_renders_as_json_not_as_python() -> None:
    parsed = wh.parse(definition(
        inputs=[{"api_name": "flag", "data_type": "boolean"}],
        body={"label": "flag={{{flag}}}"},
    ))
    assert wh.render(parsed, {"flag": True})["body"] == {"label": "flag=true"}


# ---- extract --------------------------------------------------------------------
def test_an_output_is_read_by_its_dotted_path() -> None:
    outputs = wh.parse(definition(
        outputs=[{"api_name": "unique_id", "path": "results.unique_id"}]
    ))["outputs"]
    assert wh.extract(outputs, {"results": {"unique_id": "X1"}}) == {"unique_id": "X1"}


def test_a_path_may_index_a_list() -> None:
    """p.231's "Extract by key … using the Add nested key option" walks into a
    response the webhook does not control, and real ones put the record in an
    array."""
    outputs = wh.parse(definition(
        outputs=[{"api_name": "first", "path": "results.0.id"}]
    ))["outputs"]
    assert wh.extract(outputs, {"results": [{"id": "A"}]}) == {"first": "A"}


def test_a_path_that_names_nothing_is_null_rather_than_an_error() -> None:
    """An action failing because an optional field was absent this time would
    be a failure about the far end's shape rather than about the request."""
    outputs = wh.parse(definition(outputs=[{"api_name": "x", "path": "a.b"}]))["outputs"]
    assert wh.extract(outputs, {"a": 1}) == {"x": None}


def test_a_string_output_of_a_json_object_is_json_not_a_repr() -> None:
    """p.232: "If a String output parameter is configured and the Webhook task
    result is not a string, then the result will be converted to a JSON
    string."

    `str()` on a dict is Python's repr, with single quotes — not JSON, and not
    something anything downstream can parse.
    """
    outputs = wh.parse(definition(outputs=[{"api_name": "x", "path": "a"}]))["outputs"]
    assert wh.extract(outputs, {"a": {"k": "v"}}) == {"x": '{"k":"v"}'}


def test_a_record_output_of_something_that_is_not_one_is_null() -> None:
    outputs = wh.parse(definition(
        outputs=[{"api_name": "x", "path": "a", "data_type": "record"}]
    ))["outputs"]
    assert wh.extract(outputs, {"a": "not a record"}) == {"x": None}


def test_a_numeric_output_of_something_unparseable_is_null() -> None:
    """Not the raw value: an output declared numeric and used as one downstream
    must not turn out to be a string because the far end sent "n/a" once."""
    outputs = wh.parse(definition(
        outputs=[{"api_name": "x", "path": "a", "data_type": "integer"}]
    ))["outputs"]
    assert wh.extract(outputs, {"a": "n/a"}) == {"x": None}


# ---- what a failure means -------------------------------------------------------
def test_nothing_is_retryable_by_default() -> None:
    """p.237: "This option defaults to an empty list." Not inferred from the
    status class, which is the tempting alternative — 503 is retryable for most
    APIs and a permanent refusal for some, and guessing retries a *write*
    against the ones where it is not safe."""
    assert wh.retryable(503, []) is False
    assert wh.retryable(503, [503]) is True


def test_a_request_that_never_got_a_status_changed_nothing() -> None:
    assert wh.system_changed(None) is False


def test_a_refusal_in_p237s_range_changed_nothing() -> None:
    assert wh.system_changed(404) is False
    assert wh.system_changed(431) is False


def test_a_server_error_is_unknown_rather_than_no() -> None:
    """**Three-valued, and the third value is the point.** p.237: "the
    indication of whether the external system may have been changed is captured
    to enable debugging of write failures." A 500 after a POST may well have
    written; a `False` there would be believed."""
    assert wh.system_changed(500) is None
    assert wh.system_changed(432) is None


def test_a_success_changed_the_far_end() -> None:
    assert wh.system_changed(201) is True


# ---- the shared reference syntax ------------------------------------------------
def test_webhooks_use_the_platforms_one_reference_pattern() -> None:
    """§259 moved the pattern to `services/templates` rather than compiling a
    second copy of it here.

    This is the check that says so, and it is deliberately about *identity*
    rather than about behaviour: two `re.compile` calls of the same expression
    would pass every behavioural test in this file and be exactly the mirror
    §191 warns about — free to be identically wrong, with nothing comparing
    either to the thing it describes.
    """
    from src.services import notifications

    assert notifications._REFERENCE is templates.REFERENCE


def test_a_whole_reference_is_told_from_one_among_text() -> None:
    # The distinction the typed body substitution turns on, checked where it
    # is decided rather than only through `render`.
    assert templates.is_whole_reference("{{{a}}}") is True
    assert templates.is_whole_reference("x{{{a}}}") is False
    assert templates.is_whole_reference("{{{a}}}{{{b}}}") is False
    assert templates.is_whole_reference("{{a}}") is False


def test_a_dotted_path_missing_a_middle_key_is_null() -> None:
    """The other way a path can name nothing, and the one a `{"a": 1}` fixture
    cannot reach.

    `a.b` against `{"a": 1}` stops because `1` is not a container — a different
    branch. This one walks into a real dict and finds no `b`, which is the case
    an implementation that raised on a missing key would fail on and the first
    version of this file never exercised. A mutant turning that early return
    into a `raise` survived because of it.
    """
    outputs = wh.parse(definition(outputs=[{"api_name": "x", "path": "a.b"}]))["outputs"]
    assert wh.extract(outputs, {"a": {"c": 1}}) == {"x": None}


def test_an_unsupplied_optional_input_drops_its_key() -> None:
    """d-p.229: optional inputs "may or may not be present".

    **`{"note": null}` is not the same request as `{}`.** Any API that tells
    "not provided" from "explicitly cleared" — most that accept PATCH-shaped
    bodies — reads the first as an instruction to erase the value. So an input
    that was never supplied drops its key.

    This was an *equivalent* mutant before the distinction existed: mapping an
    unsupplied parameter to `None` and not mapping it at all produced the same
    body, because everything downstream treated absent and null alike. The
    mutant could not be killed by a test; it was killed by making the code do
    what its own comment claimed.
    """
    parsed = wh.parse(definition(
        inputs=[{"api_name": "name"}, {"api_name": "note", "required": False}],
        body={"text": "{{{name}}}", "note": "{{{note}}}"},
    ))
    assert wh.render(parsed, {"name": "Ada"})["body"] == {"text": "Ada"}


def test_an_input_supplied_as_null_is_sent_as_null() -> None:
    """The other side, and what makes the sentinel necessary rather than a
    `None` check: `None` is a value a caller can supply, and clearing a field
    on purpose has to remain expressible."""
    parsed = wh.parse(definition(
        inputs=[{"api_name": "name"}, {"api_name": "note", "required": False}],
        body={"text": "{{{name}}}", "note": "{{{note}}}"},
    ))
    assert wh.render(parsed, {"name": "Ada", "note": None})["body"] == {
        "text": "Ada", "note": None
    }


def test_an_absent_input_in_a_list_stays_a_hole() -> None:
    """A list is positional, so dropping an element would shift every element
    after it — the absent value would change what the *others* mean. Null is
    the only answer that leaves the rest alone."""
    parsed = wh.parse(definition(
        inputs=[{"api_name": "note", "required": False}],
        body={"items": ["{{{note}}}", "fixed"]},
    ))
    assert wh.render(parsed, {})["body"] == {"items": [None, "fixed"]}
