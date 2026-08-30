"""Submission criteria (decision 0007; Foundry `action-types` p.49-56, p.140).

> "Submission criteria (formerly known as validations) are the conditions that
> determine whether an action can be submitted... Actions can only be submitted
> if **all** the submission criteria are met." (p.49, p.50)

Two halves, deliberately split by what they need:

* the **evaluator** is a pure function over conditions, so most of this file is
  ordinary unit tests with no database and no HTTP - which is what makes it
  cheap enough to cover every operator p.54 and p.55 list;
* the **placement** of the check is the part a unit test cannot see, and it is
  the acceptance test decision 0007 names: a refused action must create no
  dataset version, because "refused" and "refused after writing half of it"
  look identical from the caller.

**The fail-closed rule is the one to hold on to.** A condition the executor
cannot decide fails rather than passes. p.52 makes the same argument about NOT
conditions against group membership: a condition that passes because an
attribute is missing "grant[s] more access than intended".
"""
from __future__ import annotations

import io
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
from src.routes import datasets as ds_routes  # noqa: E402
from src.services import actions as actions_service  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

USER = {"id": "u-1", "group_ids": ["g-controllers", "g-everyone"]}


def criterion(config: dict, message: str = "nope") -> dict:
    return {"message": message, "config": config, "sort_order": 0}


def param(name: str) -> dict:
    return {"kind": "parameter", "parameter": name}


def value(v: object) -> dict:
    return {"kind": "value", "value": v}


def check(config: dict, bound: dict, *, user: dict = USER) -> bool:
    """True if the action may be submitted."""
    try:
        actions_service.check_criteria(bound, criteria=[criterion(config)], user=user)
        return True
    except actions_service.CriteriaRefusal:
        return False


# ---- the operators p.54 and p.55 list -----------------------------------------
def test_is_and_is_not() -> None:
    assert check({"left": param("status"), "operator": "is", "right": value("open")},
                 {"status": "open"})
    assert not check({"left": param("status"), "operator": "is", "right": value("open")},
                     {"status": "closed"})
    assert check({"left": param("status"), "operator": "is_not", "right": value("open")},
                 {"status": "closed"})
    assert not check({"left": param("status"), "operator": "is_not", "right": value("open")},
                     {"status": "open"})


def test_matches_is_a_regex_and_a_bad_one_refuses() -> None:
    """p.54's `matches`. A pattern that does not compile is a misconfiguration,
    and a misconfigured check that governs writes must not pass."""
    assert check({"left": param("code"), "operator": "matches", "right": value("^A")},
                 {"code": "A-12"})
    assert not check({"left": param("code"), "operator": "matches", "right": value("^A")},
                     {"code": "B-12"})
    assert not check({"left": param("code"), "operator": "matches", "right": value("^[A")},
                     {"code": "A-12"})


def test_ordering_is_numbers_only() -> None:
    assert check({"left": param("n"), "operator": "is_less_than", "right": value(10)}, {"n": 4})
    assert not check({"left": param("n"), "operator": "is_less_than", "right": value(10)}, {"n": 40})
    # **The boundary, which is the whole difference between the two
    # operators.** Without these two lines `is_less_than` can be `<=` and
    # `is_greater_than_or_equals` can be `>`, and every other assertion here
    # still passes - found by mutation, not by reading.
    assert not check({"left": param("n"), "operator": "is_less_than", "right": value(10)},
                     {"n": 10})
    assert check({"left": param("n"), "operator": "is_greater_than_or_equals", "right": value(2)},
                 {"n": 2})
    assert not check({"left": param("n"), "operator": "is_greater_than_or_equals", "right": value(2)},
                     {"n": 1})

    # **Dates are refused rather than compared.** They arrive as ISO-8601 text
    # whose ordering is lexicographic only when the offsets match, and a check
    # that is right in London and wrong in New York is worse than one that
    # refuses - especially this check.
    assert not check(
        {"left": param("d"), "operator": "is_less_than", "right": value("2026-01-01")},
        {"d": "2025-01-01"},
    )
    # And a boolean has no ordering, however happily Python compares it.
    assert not check({"left": param("b"), "operator": "is_less_than", "right": value(1)},
                     {"b": False})


def test_includes_and_is_included_in() -> None:
    """p.55: `includes` puts the list on the left, `is_included_in` on the
    right. Both are in Foundry's table and they are not the same check."""
    assert check({"left": param("names"), "operator": "includes", "right": value("Ada")},
                 {"names": ["Ada", "Grace"]})
    assert not check({"left": param("names"), "operator": "includes", "right": value("Alan")},
                     {"names": ["Ada", "Grace"]})
    assert check({"left": param("name"), "operator": "is_included_in", "right": value(["Ada", "Grace"])},
                 {"name": "Ada"})
    assert not check({"left": param("name"), "operator": "is_included_in", "right": value(["Ada"])},
                     {"name": "Alan"})
    # A list operator against a non-list is unevaluable, not false-y.
    assert not check({"left": param("name"), "operator": "includes", "right": value("Ada")},
                     {"name": "Ada"})


def test_no_value_checks_emptiness() -> None:
    """p.55: "No value checks whether the first value is empty (or null)."
    A property of the right-hand side rather than an operator of its own, which
    is why `is` against no value reads as "is empty"."""
    none = {"kind": "none"}
    assert check({"left": param("note"), "operator": "is", "right": none}, {})
    assert check({"left": param("note"), "operator": "is", "right": none}, {"note": ""})
    assert not check({"left": param("note"), "operator": "is", "right": none}, {"note": "hi"})
    assert check({"left": param("note"), "operator": "is_not", "right": none}, {"note": "hi"})
    assert not check({"left": param("note"), "operator": "is_not", "right": none}, {})

    # **Zero is a value and False is a value.** Writing this as `not left` is
    # the shorter version and the wrong one - it would make "priority is 0" and
    # "approved is false" read as *unanswered*, which in a check that governs
    # writes means refusing a submission somebody did make. The same trap §125
    # hit rendering `0` as "∅".
    assert not check({"left": param("n"), "operator": "is", "right": none}, {"n": 0})
    assert not check({"left": param("ok"), "operator": "is", "right": none}, {"ok": False})
    # An operator that cannot mean anything against no value refuses.
    assert not check({"left": param("n"), "operator": "is_less_than", "right": none}, {"n": 1})


def test_a_condition_can_compare_two_parameters() -> None:
    """p.55: the right side "can either be based on an existing parameter, a
    static value, or no value"."""
    config = {"left": param("new_status"), "operator": "is_not", "right": param("old_status")}
    assert check(config, {"new_status": "closed", "old_status": "open"})
    assert not check(config, {"new_status": "open", "old_status": "open"})


# ---- the current-user template (p.50, p.140) ----------------------------------
def test_a_criterion_can_require_a_group() -> None:
    """p.140: "Simple submission criteria can require a specific user ID or
    group ID". This is how an action gets its own permission, distinct from the
    role that lets somebody edit the action *type*."""
    config = {
        "left": {"kind": "current_user", "attribute": "group_ids"},
        "operator": "includes",
        "right": value("g-controllers"),
    }
    assert check(config, {})
    assert not check(config, {}, user={"id": "u-2", "group_ids": ["g-everyone"]})


def test_a_criterion_can_require_a_user_id() -> None:
    config = {
        "left": {"kind": "current_user", "attribute": "id"},
        "operator": "is",
        "right": value("u-1"),
    }
    assert check(config, {})
    assert not check(config, {}, user={"id": "u-2", "group_ids": []})


def test_an_attribute_we_cannot_answer_refuses() -> None:
    """Foundry has multipass attributes we have no equivalent for. Returning
    nothing for one would make `is_not` pass and hand out access; p.52 warns
    about exactly this shape."""
    config = {
        "left": {"kind": "current_user", "attribute": "organisation"},
        "operator": "is_not",
        "right": value("acme"),
    }
    assert not check(config, {})


# ---- combination and refusal --------------------------------------------------
def test_every_criterion_must_pass() -> None:
    """p.50: "Actions can only be submitted if all the submission criteria are
    met." The stored list is an implicit ALL."""
    passing = criterion({"left": param("a"), "operator": "is", "right": value(1)}, "a must be 1")
    failing = criterion({"left": param("b"), "operator": "is", "right": value(2)}, "b must be 2")
    actions_service.check_criteria({"a": 1}, criteria=[passing], user=USER)
    with pytest.raises(actions_service.CriteriaRefusal):
        actions_service.check_criteria({"a": 1, "b": 9}, criteria=[passing, failing], user=USER)


def test_the_refusal_carries_the_criterion_s_own_message() -> None:
    """p.56: the failure message "informs the user about why they are blocked
    from submitting an Action". A refusal that said "condition 2 failed" would
    be the greyed-out button with no explanation."""
    failing = criterion(
        {"left": param("status"), "operator": "is", "right": value("open")},
        "Only open tickets can be closed.",
    )
    with pytest.raises(actions_service.CriteriaRefusal) as caught:
        actions_service.check_criteria({"status": "closed"}, criteria=[failing], user=USER)
    assert caught.value.message == "Only open tickets can be closed."


def test_an_unknown_operator_refuses_and_says_so() -> None:
    failing = criterion(
        {"left": param("a"), "operator": "is_roughly", "right": value(1)}, "nope"
    )
    with pytest.raises(actions_service.CriteriaRefusal) as caught:
        actions_service.check_criteria({"a": 1}, criteria=[failing], user=USER)
    # The message stays first - it is what the user is told - and the reason
    # follows, because a criterion nobody can evaluate is a bug in the action
    # and somebody has to be able to find it.
    assert str(caught.value).startswith("nope")
    assert "is_roughly" in str(caught.value)


def test_no_criteria_means_no_refusal() -> None:
    actions_service.check_criteria({"anything": 1}, criteria=[], user=USER)


# ---- where the check sits (the acceptance test) --------------------------------
TICKETS = b"ticket_id,status\n1,open\n2,open\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("criteria-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict[str, str]:
    """An object type, a dataset behind it, one instance, and an action."""
    base = f"/api/workspaces/{fx.workspace}"
    project = f"{base}/projects/{fx.project}"
    r = client.post(
        f"{base}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"CritTicket{fx.tag}", "display_name": f"CritTicket {fx.tag}",
            "properties": [{"api_name": "status", "data_type": "string"}],
        },
    )
    type_id = r.json()["id"]
    r = client.post(
        f"{project}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"CritTickets {fx.tag}"},
        files={"file": ("tickets.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    dataset_id = r.json()["id"]
    r = client.post(
        f"{project}/object-type-sources", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id, "dataset_id": dataset_id,
            "primary_key_column": "ticket_id", "column_mappings": {"status": "status"},
        },
    )
    source_id = r.json()["id"]
    client.post(f"{project}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub))
    instances = client.get(
        f"{base}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
    ).json()["items"]
    r = client.post(
        f"{base}/action-types", headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id, "api_name": f"close_{uuid.uuid4().hex[:8]}",
            "display_name": "Close ticket", "editable_properties": ["status"],
        },
    )
    return {
        "type_id": type_id, "dataset_id": dataset_id, "action_id": r.json()["id"],
        "instance_id": instances[0]["id"], "base": base, "project": project,
    }


def _add_criterion(action_id: str, config: str, message: str) -> None:
    """Straight into the database: there is no criterion editor yet, and the
    check that matters is what the *executor* does with one."""
    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO action_criteria (action_type_id, message, config) "
            "VALUES (%s, %s, %s::jsonb)",
            (action_id, message, config),
        )


def _version(client: TestClient, fx: Fixture, world: dict[str, str]) -> int:
    r = client.get(
        f"{world['project']}/datasets/{world['dataset_id']}", headers=hdr(fx.viewer_sub)
    )
    return int(r.json()["current_version"])


def test_a_failed_criterion_refuses_the_action_and_writes_nothing(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """**Decision 0007's acceptance test.** The refusal is visible; the absence
    of a dataset version is the part that needs asserting, because our
    write-back appends one per write and a check placed after the first rule
    would leave one behind while still returning an error."""
    _add_criterion(
        world["action_id"],
        '{"left": {"kind": "parameter", "parameter": "status"},'
        ' "operator": "is_not", "right": {"kind": "value", "value": "closed"}}',
        "Tickets cannot be closed from here.",
    )
    before = _version(client, fx, world)

    r = client.post(
        f"{world['project']}/actions/{world['action_id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": world["instance_id"], "values": {"status": "closed"}},
    )
    assert r.status_code == 422, r.text
    assert "Tickets cannot be closed from here." in r.text

    assert _version(client, fx, world) == before
    # And no run was opened, so the history does not carry an attempt that
    # never touched anything.
    runs = client.get(
        f"{world['base']}/action-types/{world['action_id']}/runs", headers=hdr(fx.viewer_sub)
    ).json()
    assert runs == []


def test_the_same_action_still_runs_when_the_criterion_holds(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """The other half. Without it, a criterion that refused *everything* would
    pass the test above."""
    before = _version(client, fx, world)
    r = client.post(
        f"{world['project']}/actions/{world['action_id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": world["instance_id"], "values": {"status": "triaged"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["instance"]["properties"]["status"] == "triaged"
    assert _version(client, fx, world) == before + 1


def test_the_criteria_are_on_the_wire(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """A form cannot grey out a button for a rule it cannot see. The editor and
    the form both arrive later; the API is what they will read."""
    r = client.get(
        f"{world['base']}/action-types/{world['action_id']}", headers=hdr(fx.viewer_sub)
    )
    criteria = r.json()["criteria"]
    assert [c["message"] for c in criteria] == ["Tickets cannot be closed from here."]
    assert criteria[0]["config"]["operator"] == "is_not"


# ---- asking before submitting (Workshop p.513) ------------------------------
def _check(client: TestClient, fx: Fixture, world: dict[str, str], values: dict) -> dict:
    r = client.post(
        f"{world['project']}/actions/{world['action_id']}/check",
        headers=hdr(fx.editor_sub), json={"values": values},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_a_submission_can_be_asked_about_before_it_is_made(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """Workshop p.513 lets a builder disable or hide an Inline Action form
    "when submission criteria are not met", which needs the answer before
    anything is written.

    **The point is that it is the same check.** The alternative is a browser
    evaluating p.54-55's operators in another language, free to disagree with
    the one that governs writes — so the assertions here are that the endpoint
    agrees with `execute` in both directions.
    """
    refused = _check(client, fx, world, {"status": "closed"})
    assert refused["ok"] is False
    assert refused["error"] == "Tickets cannot be closed from here."

    allowed = _check(client, fx, world, {"status": "triaged"})
    assert allowed == {"ok": True, "error": None}


def test_asking_writes_nothing(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """**Asking is not submitting.** A check that appended a dataset version, or
    opened a run, would make a disabled form more expensive than a working
    one — and a widget that asks on every object change would fill the history
    with attempts nobody made."""
    def runs() -> int:
        return len(client.get(
            f"{world['base']}/action-types/{world['action_id']}/runs",
            headers=hdr(fx.viewer_sub),
        ).json())

    # **Counted, not compared to zero.** `world` is module-scoped and an
    # earlier test in this file submits the action successfully, so `== []`
    # held only where it happened to sit - which is the claim's neighbour
    # passing for it rather than the claim.
    before_version, before_runs = _version(client, fx, world), runs()
    _check(client, fx, world, {"status": "closed"})
    _check(client, fx, world, {"status": "triaged"})
    assert _version(client, fx, world) == before_version
    assert runs() == before_runs


def test_a_refusal_is_an_answer_rather_than_an_error(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """200 with `ok: false`, not 422. A 4xx would make "this action is not
    available" indistinguishable from "the question could not be asked", and
    the widget has to tell those apart to decide between disabling a form and
    reporting that something is broken."""
    r = client.post(
        f"{world['project']}/actions/{world['action_id']}/check",
        headers=hdr(fx.editor_sub), json={"values": {"status": "closed"}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False


def test_a_value_the_parameters_refuse_is_reported_too(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """A binding failure is also a reason the submission would not go through,
    and saying so here is more use than saying nothing until Submit."""
    answer = _check(client, fx, world, {"not_a_parameter": "x"})
    assert answer["ok"] is False
    assert answer["error"]


def test_checking_needs_the_role_that_could_submit(
    client: TestClient, fx: Fixture, world: dict[str, str]
) -> None:
    """p.140 makes criteria a permissions mechanism, so a caller who may not run
    the action has no business learning which criterion would stop them."""
    r = client.post(
        f"{world['project']}/actions/{world['action_id']}/check",
        headers=hdr(fx.viewer_sub), json={"values": {"status": "triaged"}},
    )
    assert r.status_code in (403, 404), r.text
