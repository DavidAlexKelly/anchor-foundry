"""Changing a parameter under specific circumstances (§329; db 0082;
`action-types` p.43-46).

    "While assignees can change the status, managers will have to provide a
     justification. Using overrides, the Justification reason parameter can be
     made **required and visible for managers, while it is hidden and optional
     for the assignee**." (p.43)

    "Every parameter can contain multiple override blocks, however, **if more
     than one is true, only the first one will be executed**." (p.45)

    "The only difference between override conditions and submission criteria
     conditions is that **only parameters which appear above the current
     parameter in the form hierarchy** can be referenced." (p.45)

**The claim every test here is about is the one that separates this from
§328.** A section changes what a form looks like; an override changes what the
action asks for. p.43's justification is *required* for one person and optional
for another, so a submission with no justification must be refused for one and
accepted for the other — and that has to be true of a submission that never
went near a screen, or the rule only exists where somebody drew it.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_overrides as overrides  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


NOBODY: dict = {}


def when(parameter: str, value) -> dict:
    return {"left": {"kind": "parameter", "parameter": parameter},
            "operator": "is", "right": {"kind": "value", "value": value}}


def block(**over) -> dict:
    return {"conditions": [when("status", "closed")], "set_hidden": None,
            "set_required": None, "set_default": None, **over}


def parameter(name: str, **over) -> dict:
    return {"api_name": name, "display_name": name.title(), "data_type": "string",
            "required": False, "default_value": None, "hidden": False,
            "overrides": [], **over}


# ---- p.45's first-match rule, decided without a database ----------------------
def test_a_parameter_with_no_blocks_is_itself() -> None:
    """Every parameter written before §329, and most of them after."""
    p = parameter("status", required=True)
    assert overrides.effective(p, bound={}, user=NOBODY) == dict(p)


def test_a_block_whose_conditions_hold_is_applied() -> None:
    """p.43's example, in one line: required and visible together."""
    p = parameter("justification", hidden=True, overrides=[
        block(set_hidden=False, set_required=True),
    ])
    got = overrides.effective(p, bound={"status": "closed"}, user=NOBODY)
    assert got["hidden"] is False
    assert got["required"] is True


def test_a_block_whose_conditions_do_not_hold_changes_nothing() -> None:
    p = parameter("justification", hidden=True, overrides=[
        block(set_hidden=False, set_required=True),
    ])
    got = overrides.effective(p, bound={"status": "open"}, user=NOBODY)
    assert got["hidden"] is True
    assert got["required"] is False


def test_only_the_first_block_that_holds_is_executed() -> None:
    """p.45 and p.46 say this on two separate pages, which is unusual enough to
    be worth reading as emphasis: "if more than one is true, only the first one
    will be executed". Not a merge — the second block is not consulted at all,
    so the `required` it would have set stays false."""
    p = parameter("justification", overrides=[
        block(set_hidden=True),
        block(set_required=True),
    ])
    got = overrides.effective(p, bound={"status": "closed"}, user=NOBODY)
    assert got["hidden"] is True
    assert got["required"] is False, "the second block was not consulted"


def test_a_later_block_wins_when_the_earlier_one_does_not_hold() -> None:
    """The other half of first-match, and the half a test could forget: "first"
    means first *among those that hold*, not "the first one, if it holds"."""
    p = parameter("justification", overrides=[
        {**block(set_hidden=True), "conditions": [when("status", "open")]},
        block(set_required=True),
    ])
    got = overrides.effective(p, bound={"status": "closed"}, user=NOBODY)
    assert got["hidden"] is False
    assert got["required"] is True


def test_every_condition_in_a_block_has_to_hold() -> None:
    """p.45: "Each block can contain one or multiple conditions." Read as an
    `and`, which is how `check_criteria` reads its own list — one grammar, one
    reading."""
    p = parameter("justification", overrides=[{
        **block(set_required=True),
        "conditions": [when("status", "closed"), when("owner", "me")],
    }])
    assert overrides.effective(
        p, bound={"status": "closed"}, user=NOBODY)["required"] is False
    assert overrides.effective(
        p, bound={"status": "closed", "owner": "me"}, user=NOBODY
    )["required"] is True


def test_a_condition_that_cannot_be_read_leaves_the_parameter_alone() -> None:
    """**The opposite direction from §328's sections, on purpose.**

    A section that cannot decide its condition hides, because showing a box on
    the strength of a broken rule is the worse mistake. An override that cannot
    decide leaves the parameter exactly as configured — the action behaves as
    though nobody had written the block, rather than requiring something of
    somebody because a rule was malformed.
    """
    p = parameter("justification", required=False, overrides=[{
        **block(set_required=True),
        "conditions": [{"left": {"kind": "no_such_side"}, "operator": "is",
                        "right": {"kind": "value", "value": 1}}],
    }])
    assert overrides.effective(p, bound={}, user=NOBODY)["required"] is False


def test_a_broken_block_does_not_take_the_action_down() -> None:
    """An override is resolved on the submit path. A 500 here would refuse an
    action outright for a rule meant only to adjust one field."""
    p = parameter("justification", overrides=[{
        **block(set_required=True), "conditions": [{"nothing": "sensible"}],
    }])
    assert overrides.effective(p, bound={}, user=NOBODY)["required"] is False


def test_a_block_only_changes_what_it_names() -> None:
    """**NULL is "leave alone", not false.**

    p.43's block makes one parameter required *and* visible; a block that only
    hid something would otherwise un-require it as a side effect, and the
    builder would have to restate every field on every block.
    """
    p = parameter("justification", required=True, hidden=True,
                  default_value="none given",
                  overrides=[block(set_hidden=False)])
    got = overrides.effective(p, bound={"status": "closed"}, user=NOBODY)
    assert got["hidden"] is False
    assert got["required"] is True
    assert got["default_value"] == "none given"


def test_a_block_can_change_the_default() -> None:
    p = parameter("justification", default_value="none",
                  overrides=[block(set_default="see the ticket")])
    assert overrides.effective(
        p, bound={"status": "closed"}, user=NOBODY
    )["default_value"] == "see the ticket"


def test_a_block_can_ask_who_is_submitting() -> None:
    """p.43's example is exactly this: a manager and an assignee submitting the
    same form. p.50's second condition template, which p.45 inherits whole."""
    mine = {"left": {"kind": "current_user", "attribute": "id"},
            "operator": "is", "right": {"kind": "value", "value": "u-manager"}}
    p = parameter("justification", overrides=[
        {**block(set_required=True), "conditions": [mine]},
    ])
    assert overrides.effective(
        p, bound={}, user={"id": "u-manager"})["required"] is True
    assert overrides.effective(
        p, bound={}, user={"id": "u-assignee"})["required"] is False


# ---- p.45's form hierarchy ----------------------------------------------------
def test_form_order_is_the_body_then_the_sections() -> None:
    """§328's arrangement, which is what p.45 means by "the form hierarchy"."""
    params = [parameter("a"), parameter("b"), parameter("c")]
    sections = [{"id": "s1", "parameters": ["b"]}]
    assert overrides.form_order(params, sections) == ["a", "c", "b"]


def test_a_hidden_sections_parameter_still_has_a_position() -> None:
    """p.45's rule is about what a condition may *read*. A hidden section's
    parameters are still bound and still submitted (db 0081), so leaving them
    out would make a legal reference unsayable."""
    params = [parameter("a"), parameter("b")]
    sections = [{"id": "s1", "hidden": True, "parameters": ["a"]}]
    assert overrides.form_order(params, sections) == ["b", "a"]


def test_form_order_ignores_a_name_no_parameter_answers_to() -> None:
    """An ontology import or a hand-edited row can leave one behind.
    `replace_sections` cannot, and a save that failed here would be refusing
    the wrong document."""
    assert overrides.form_order(
        [parameter("a")], [{"id": "s1", "parameters": ["gone", "a"]}]
    ) == ["a"]


def test_readable_before_is_strictly_above() -> None:
    order = ["a", "b", "c"]
    assert overrides.readable_before(order, "a") == set()
    assert overrides.readable_before(order, "b") == {"a"}
    assert overrides.readable_before(order, "c") == {"a", "b"}


def test_a_parameter_the_form_does_not_mention_can_read_nothing() -> None:
    assert overrides.readable_before(["a", "b"], "gone") == set()


def test_a_block_reading_a_parameter_below_it_is_refused() -> None:
    """p.45's one difference from a submission criterion.

    Refused at save time, because the two ways of being wrong are
    indistinguishable once the form is open: a condition that reads a parameter
    below it is unevaluable, an unevaluable condition does not hold, and a
    block that never holds looks exactly like one nobody meant to write.
    """
    params = [
        parameter("status", overrides=[
            {**block(set_required=True), "conditions": [when("justification", "x")]},
        ]),
        parameter("justification"),
    ]
    with pytest.raises(ValueError) as caught:
        overrides.check_references(params, [])
    assert "justification" in str(caught.value)
    assert "below it" in str(caught.value)


def test_a_block_reading_itself_is_refused_by_name() -> None:
    """The fixed point the single resolution pass cannot have, and it reads as
    sensible right up until somebody writes one."""
    params = [parameter("status", overrides=[
        {**block(set_default="x"), "conditions": [when("status", "closed")]},
    ])]
    with pytest.raises(ValueError) as caught:
        overrides.check_references(params, [])
    assert "itself" in str(caught.value)


def test_a_block_reading_a_parameter_above_it_is_allowed() -> None:
    params = [
        parameter("status"),
        parameter("justification", overrides=[block(set_required=True)]),
    ]
    overrides.check_references(params, [])  # does not raise


def test_the_form_hierarchy_is_what_decides_above_not_the_declaration() -> None:
    """**The check that makes `form_order` load-bearing rather than decorative.**

    Declared `justification` first and `status` second, but a section puts
    `status` at the top of the form — so a block on `justification` reading
    `status` is legal, and the same document with no sections is not.
    """
    params = [
        parameter("justification", overrides=[block(set_required=True)]),
        parameter("status"),
    ]
    with pytest.raises(ValueError):
        overrides.check_references(params, [])
    overrides.check_references(
        params, [{"id": "s1", "parameters": ["justification"]}]
    )


def test_a_block_reading_a_parameter_that_is_gone_says_so_differently() -> None:
    """p.43's premise is a builder arranging a form, and "below it" and "not a
    parameter at all" are two different things to go and fix."""
    params = [parameter("status", overrides=[
        {**block(set_required=True), "conditions": [when("no_such", "x")]},
    ])]
    with pytest.raises(ValueError) as caught:
        overrides.check_references(params, [])
    assert "not a parameter of this action" in str(caught.value)


# ---- one resolution pass ------------------------------------------------------
def test_resolve_lets_a_block_read_a_default_settled_above_it() -> None:
    """**Why one pass is enough, and what it buys.**

    p.45's "only parameters above" means every value a block may read is
    already known by the time that block is reached — including one the caller
    never typed, because a default filled it in. p.43's example needs exactly
    that: the form asks for a justification because of a status nobody set.
    """
    params = [
        parameter("status", default_value="closed"),
        parameter("justification", overrides=[block(set_required=True)]),
    ]
    resolved = overrides.resolve(
        params, values={}, user=NOBODY, order=["status", "justification"]
    )
    assert resolved[1]["required"] is True


def test_a_submitted_value_beats_the_default_when_a_block_reads_it() -> None:
    params = [
        parameter("status", default_value="closed"),
        parameter("justification", overrides=[block(set_required=True)]),
    ]
    resolved = overrides.resolve(
        params, values={"status": "open"}, user=NOBODY,
        order=["status", "justification"],
    )
    assert resolved[1]["required"] is False


def test_resolve_returns_the_parameters_in_the_order_it_was_given() -> None:
    """Not in form order. A caller reading this list is reading an action's
    parameters, and quietly reordering them would change what the definition
    endpoint returns and which name `bind_parameters` reports first."""
    params = [parameter("b"), parameter("a")]
    resolved = overrides.resolve(
        params, values={}, user=NOBODY, order=["a", "b"])
    assert [p["api_name"] for p in resolved] == ["b", "a"]


# ---- through the API ----------------------------------------------------------
@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client() -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


@pytest.fixture
def action(client: TestClient, fx: Fixture) -> str:
    """p.43's own example: a ticket whose status somebody changes, and a
    justification that is required only under some circumstances."""
    tag = uuid.uuid4().hex[:8]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ovr_{tag}", "display_name": f"Ticket {tag}",
              "properties": [
                  {"api_name": "status", "data_type": "string"},
                  {"api_name": "justification", "data_type": "string"},
              ]},
    )
    assert made.status_code == 201, made.text
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": made.json()["id"], "api_name": f"close_{tag}",
              "display_name": "Close",
              "editable_properties": ["status", "justification"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def define(client: TestClient, fx: Fixture, action: str, parameters, sub=None):
    return client.put(
        f"{wbase(fx)}/action-types/{action}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": parameters,
              "rules": [{"kind": "modify_object",
                         "config": {"property": "status", "parameter": "status"}}],
              "criteria": []},
    )


def read(client: TestClient, fx: Fixture, action: str, sub=None):
    r = client.get(f"{wbase(fx)}/action-types/{action}",
                   headers=hdr(sub or fx.editor_sub))
    assert r.status_code == 200, r.text
    return {p["api_name"]: p for p in r.json()["parameters"]}


JUSTIFY = [
    parameter("status"),
    parameter("justification", hidden=True, overrides=[
        block(set_hidden=False, set_required=True),
    ]),
]


def test_a_block_survives_the_definition_round_trip(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """The blocks travel with the parameter, not as a document of their own —
    unlike §328's sections, because an override is a fact about what the
    parameter *is*."""
    assert define(client, fx, action, JUSTIFY).status_code == 200
    got = read(client, fx, action)["justification"]
    assert len(got["overrides"]) == 1
    [saved] = got["overrides"]
    assert saved["set_required"] is True
    assert saved["set_hidden"] is False
    assert saved["set_default"] is None, "what a block leaves alone stays null"
    assert saved["conditions"] == [when("status", "closed")]
    # And the stored parameter is untouched: an override is a rule about the
    # parameter, not an edit to it.
    assert got["hidden"] is True
    assert got["required"] is False


def test_removing_the_blocks_removes_them(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """A whole-document save. A parameter saved with no `overrides` has none —
    otherwise a builder could never delete the last block."""
    define(client, fx, action, JUSTIFY).raise_for_status()
    define(client, fx, action, [parameter("status"),
                                parameter("justification")]).raise_for_status()
    assert read(client, fx, action)["justification"]["overrides"] == []


def test_a_block_with_no_conditions_is_refused(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.45 offers a block as an "if"/"then" pair. A block with no "if" is the
    parameter's own configuration written twice — and it would silently win
    over every block below it, because the first that holds is the only one
    applied."""
    r = define(client, fx, action, [
        parameter("status"),
        parameter("justification", overrides=[
            {**block(set_required=True), "conditions": []},
        ]),
    ])
    assert r.status_code == 422, r.text


def test_a_block_that_changes_nothing_is_refused(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.45's "then" section "defines the overrides which will be applied". A
    block with none is a condition somebody wrote and then did not finish, and
    storing it would make it shadow the blocks below."""
    r = define(client, fx, action, [
        parameter("status"),
        parameter("justification", overrides=[block()]),
    ])
    assert r.status_code == 422, r.text
    assert "changes nothing" in r.text


def test_a_block_reading_a_parameter_below_it_is_refused_by_the_api(
    client: TestClient, fx: Fixture, action: str
) -> None:
    r = define(client, fx, action, [
        parameter("status", overrides=[
            {**block(set_required=True), "conditions": [when("justification", "x")]},
        ]),
        parameter("justification"),
    ])
    assert r.status_code == 422, r.text
    assert "justification" in r.text


def test_nothing_is_written_by_a_refused_definition(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """`user_connection` is one transaction per request, so a refusal rolls the
    whole rewrite back — the parameters, the rules and the blocks together."""
    define(client, fx, action, JUSTIFY).raise_for_status()
    r = define(client, fx, action, [
        parameter("status"),
        parameter("justification", overrides=[block()]),
    ])
    assert r.status_code == 422, r.text
    assert len(read(client, fx, action)["justification"]["overrides"]) == 1


# ---- the endpoint the form asks ------------------------------------------------
def effective(client: TestClient, fx: Fixture, action: str, values, sub=None):
    r = client.post(f"{wbase(fx)}/action-types/{action}/effective-parameters",
                    headers=hdr(sub or fx.viewer_sub), json={"values": values})
    assert r.status_code == 200, r.text
    return {p["api_name"]: p for p in r.json()}


def test_the_form_is_told_what_to_ask_for(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """**The same `resolve` the executor runs**, which is why this is a round
    trip: get it wrong and the form asks for the wrong things and then refuses
    what somebody sends."""
    define(client, fx, action, JUSTIFY).raise_for_status()

    quiet = effective(client, fx, action, {"status": "open"})["justification"]
    assert quiet["hidden"] is True and quiet["required"] is False

    loud = effective(client, fx, action, {"status": "closed"})["justification"]
    assert loud["hidden"] is False and loud["required"] is True


def test_the_resolved_parameter_does_not_carry_the_rules_that_made_it(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """A screen drawing this needs to know what to ask for. The blocks are the
    *definition*, and a reader of that gets them from the action type."""
    define(client, fx, action, JUSTIFY).raise_for_status()
    assert effective(
        client, fx, action, {"status": "closed"})["justification"]["overrides"] == []


def test_a_viewer_may_ask_what_the_form_would_ask(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """Unlike `check`, which is `editor` because p.140 makes criteria a
    permissions mechanism. This says what a form looks like, not whether a
    submission would be accepted."""
    define(client, fx, action, JUSTIFY).raise_for_status()
    assert effective(client, fx, action, {}, sub=fx.viewer_sub)
    r = client.post(f"{wbase(fx)}/action-types/{action}/effective-parameters",
                    headers=hdr(fx.outsider_sub), json={"values": {}})
    assert r.status_code in (403, 404), r.text
