"""p.56's logical operators over submission criteria (§643).

> "A logical operator can be used to combine different conditions. Logical
> operators can also be nested to create even more complex logic and can
> require either all, any, or no conditions underneath it to be met to pass."
> (p.56)
>
> "Every condition and logical operator on the root level has its own failure
> message. If conditions of lower levels are not met, the failure message of
> the corresponding root level (parent) is displayed." (p.56)

A group is `{"logic": "all" | "any" | "none", "conditions": [...]}` where a
condition would be, nested up to four deep. The fail-closed rule of
`test_action_criteria` holds inside a group too: a condition nobody can decide
refuses, even under an `any` whose other condition passes.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_action_criteria import USER, check, criterion, param, value  # noqa: E402
from test_action_parameters import (  # noqa: E402,F401
    _fresh_identity_cache, client, definition, fx, make_action, ticket_type_id,
)
from src.services import actions as actions_service  # noqa: E402


def cond(name: str, v: object, operator: str = "is") -> dict:
    return {"left": param(name), "operator": operator, "right": value(v)}


def group(logic: str, *conditions: dict) -> dict:
    return {"logic": logic, "conditions": list(conditions)}


# The aircraft of p.53-56: a flight controller, or anybody at all once the
# aircraft is grounded - and never a decommissioned one.
CONTROLLER = {"left": {"kind": "current_user", "attribute": "group_ids"},
              "operator": "includes", "right": value("g-controllers")}
AIRCRAFT = group("all",
                 group("any", CONTROLLER, cond("status", "grounded")),
                 group("none", cond("fleet", "decommissioned")))


# ---- the three operators --------------------------------------------------------
def test_all_needs_every_condition() -> None:
    both = group("all", cond("a", 1), cond("b", 2))
    assert check(both, {"a": 1, "b": 2})
    assert not check(both, {"a": 1, "b": 3})
    assert not check(both, {"a": 0, "b": 2})


def test_any_needs_one_condition() -> None:
    either = group("any", cond("a", 1), cond("b", 2))
    assert check(either, {"a": 1, "b": 0})
    assert check(either, {"a": 0, "b": 2})
    assert not check(either, {"a": 0, "b": 0})


def test_none_needs_no_condition() -> None:
    neither = group("none", cond("a", 1), cond("b", 2))
    assert check(neither, {"a": 0, "b": 0})
    assert not check(neither, {"a": 1, "b": 0})
    assert not check(neither, {"a": 0, "b": 2})


def test_groups_nest() -> None:
    outsider = {"id": "u-2", "group_ids": ["g-everyone"]}
    assert check(AIRCRAFT, {"status": "flying", "fleet": "active"})
    assert check(AIRCRAFT, {"status": "grounded", "fleet": "active"}, user=outsider)
    assert not check(AIRCRAFT, {"status": "flying", "fleet": "active"}, user=outsider)
    assert not check(AIRCRAFT, {"status": "grounded", "fleet": "decommissioned"})


# ---- p.56's failure message ---------------------------------------------------------
def test_the_root_s_message_is_what_a_refusal_says() -> None:
    with pytest.raises(actions_service.CriteriaRefusal) as caught:
        actions_service.check_criteria(
            {"status": "flying", "fleet": "decommissioned"},
            criteria=[criterion(AIRCRAFT, "Only a controller may move an active aircraft.")],
            user=USER)
    assert caught.value.message == "Only a controller may move an active aircraft."


# ---- failing closed ------------------------------------------------------------------
def test_an_undecidable_condition_refuses_even_under_an_any_that_passes() -> None:
    """The misconfiguration is found the first time, rather than on the day
    the other condition stops passing."""
    broken = {"left": param("a"), "operator": "is_roughly", "right": value(1)}
    with pytest.raises(actions_service.CriteriaRefusal) as caught:
        actions_service.check_criteria(
            {"a": 1}, criteria=[criterion(group("any", cond("a", 1), broken), "nope")], user=USER)
    assert "is_roughly" in str(caught.value)


def test_an_undecidable_condition_under_none_refuses() -> None:
    """p.52's NOT warning: a condition failing for an attribute we cannot
    answer must not become a pass by being negated."""
    unanswerable = {"left": {"kind": "current_user", "attribute": "organization"},
                    "operator": "is", "right": value("acme")}
    assert not check(group("none", unanswerable), {})


def test_an_unknown_logical_operator_refuses() -> None:
    with pytest.raises(actions_service.CriteriaRefusal) as caught:
        actions_service.check_criteria(
            {"a": 1}, criteria=[criterion(group("most", cond("a", 1)), "nope")], user=USER)
    assert "'most'" in str(caught.value)


# ---- refused at save time -----------------------------------------------------------
PARAMETERS = [{"api_name": "status", "display_name": "Status", "data_type": "string"},
              {"api_name": "fleet", "display_name": "Fleet", "data_type": "string"}]


def save(client, fx, ticket_type_id, config: dict):
    action = make_action(client, fx, ticket_type_id, ["status"])
    return definition(client, fx, action["id"], {
        "parameters": PARAMETERS, "rules": [],
        "criteria": [{"message": "Only a controller may move it.", "config": config}]})


def test_a_nested_criterion_is_saved_and_read_back(client: TestClient, fx, ticket_type_id) -> None:
    r = save(client, fx, ticket_type_id, AIRCRAFT)
    assert r.status_code == 200, r.text
    assert r.json()["criteria"][0]["config"] == AIRCRAFT


@pytest.mark.parametrize("config, said", [
    (group("most", cond("status", "x")), "unknown logical operator 'most'"),
    (group("any"), "needs at least one condition"),
    ({"logic": "all", "conditions": "status"}, "needs at least one condition"),
    (group("all", cond("typo", "x")), "'typo', which is not a parameter"),
    (group("all", {"left": param("status"), "operator": "is_roughly", "right": value(1)}),
     "unknown criterion operator 'is_roughly'"),
    (group("all", group("all", group("all", group("all", group("all", cond("status", "x")))))),
     "at most 4 groups deep"),
    (group("any", *[cond("status", str(n)) for n in range(51)]), "at most 50 conditions"),
])
def test_a_group_that_cannot_be_decided_is_refused(
    client: TestClient, fx, ticket_type_id, config, said,
) -> None:
    r = save(client, fx, ticket_type_id, config)
    assert r.status_code == 422, r.text
    assert said in r.text


def test_the_depth_and_count_caps_are_inclusive(client: TestClient, fx, ticket_type_id) -> None:
    deepest = group("all", group("all", group("all", group("all", cond("status", "x")))))
    assert save(client, fx, ticket_type_id, deepest).status_code == 200
    fifty = group("any", *[cond("status", str(n)) for n in range(50)])
    assert save(client, fx, ticket_type_id, fifty).status_code == 200
