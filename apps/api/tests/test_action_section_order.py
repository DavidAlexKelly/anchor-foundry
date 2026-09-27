"""p.124's one Form Content order (§589; db 0123; `action-types` p.124).

> "The Form tab lists the sections with their parameters in a single
>  overview... Parameters and sections display in the form based on their
>  order in this Form Content section." (p.124)

A section says how many of the parameters no section holds come before it,
and nothing means after all of them, which is db 0081's layout. p.45's
"form hierarchy" is this order, so where a section sits decides which
parameters an override may read.
"""
from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_action_sections import (  # noqa: E402
    _fresh_identity_cache, action, client, fx, get_sections, put_sections, wbase,
)
from test_api import hdr  # noqa: E402
from src.services import action_overrides  # noqa: E402

__all__ = ["_fresh_identity_cache", "action", "client", "fx"]

PARAMETERS = [{"api_name": n} for n in ("status", "reason", "owner")]


def test_the_form_order_interleaves_sections_and_loose_parameters() -> None:
    order = action_overrides.form_order
    assert order(PARAMETERS, [{"parameters": ["reason"], "loose_before": 0}]) == [
        "reason", "status", "owner"]
    assert order(PARAMETERS, [{"parameters": ["reason"], "loose_before": 1}]) == [
        "status", "reason", "owner"]
    # Nothing said is db 0081's layout: after all of them.
    assert order(PARAMETERS, [{"parameters": ["reason"]}]) == ["status", "owner", "reason"]
    assert order(PARAMETERS, [{"parameters": ["reason"], "loose_before": 9}]) == [
        "status", "owner", "reason"]
    assert order(PARAMETERS, [
        {"parameters": ["reason"], "loose_before": 0},
        {"parameters": ["owner"], "loose_before": 0},
    ]) == ["reason", "owner", "status"]


def test_an_order_that_backs_up_lists_nothing_twice() -> None:
    """An imported file's sections reach p.45's check before the form's own
    refusal of a section above one before it (§344), so the order it is read
    in must still name each parameter once."""
    four = [{"api_name": n} for n in "abcd"]
    assert action_overrides.form_order(four, [
        {"parameters": ["c"], "loose_before": 2},
        {"parameters": ["d"], "loose_before": 0},
    ]) == ["a", "b", "c", "d"]


def test_a_section_keeps_its_place(client, fx, action) -> None:
    r = put_sections(client, fx, action, [
        {"title": "Why", "parameters": ["reason"], "loose_before": 0},
        {"title": "Who", "parameters": ["owner"]},
    ])
    assert r.status_code == 200, r.text
    got = get_sections(client, fx, action)
    assert [(s["title"], s["loose_before"]) for s in got] == [("Why", 0), ("Who", None)]


@pytest.mark.parametrize("sections", [
    [{"title": "A", "parameters": [], "loose_before": 1},
     {"title": "B", "parameters": [], "loose_before": 0}],
    [{"title": "A", "parameters": []},
     {"title": "B", "parameters": [], "loose_before": 0}],
])
def test_a_section_above_the_one_before_it_is_refused(client, fx, action, sections) -> None:
    r = put_sections(client, fx, action, sections)
    assert r.status_code == 422, r.text
    assert "'B' is placed above a section before it" in r.text
    assert get_sections(client, fx, action) == []


def test_a_negative_place_is_refused(client, fx, action) -> None:
    r = put_sections(client, fx, action, [{"title": "A", "parameters": [], "loose_before": -1}])
    assert r.status_code == 422, r.text


def test_the_place_decides_what_an_override_may_read(client, fx, action) -> None:
    """p.45: "only parameters which appear above the current parameter in the
    form hierarchy can be referenced" - and the hierarchy is p.124's order."""
    definition = client.get(f"{wbase(fx)}/action-types/{action}",
                            headers=hdr(fx.viewer_sub)).json()
    status = next(p for p in definition["parameters"] if p["api_name"] == "status")
    status = {k: status[k] for k in ("api_name", "display_name", "data_type")}
    reading = {**status, "overrides": [{
        "conditions": [{"left": {"kind": "parameter", "parameter": "reason"},
                        "operator": "is", "right": {"kind": "value", "value": "x"}}],
        "set_required": True}]}
    others = [{"api_name": n, "display_name": n, "data_type": "string"}
              for n in ("reason", "owner")]
    rules = [{"kind": r["kind"], "config": r["config"]} for r in definition["rules"]]

    def save():
        return client.put(f"{wbase(fx)}/action-types/{action}/definition",
                          headers=hdr(fx.editor_sub),
                          json={"parameters": [reading, *others], "rules": rules,
                                "criteria": []})

    assert put_sections(client, fx, action, [
        {"title": "Why", "parameters": ["reason"]}]).status_code == 200
    refused = save()
    assert refused.status_code == 422 and "is below it in the form" in refused.text
    assert put_sections(client, fx, action, [
        {"title": "Why", "parameters": ["reason"], "loose_before": 0}]).status_code == 200
    assert save().status_code == 200


def test_an_ontology_export_carries_the_place(client, fx, action) -> None:
    assert put_sections(client, fx, action, [
        {"title": "Why", "parameters": ["reason"], "loose_before": 1},
        {"title": "Who", "parameters": ["owner"]},
    ]).status_code == 200
    name = client.get(f"{wbase(fx)}/action-types/{action}",
                      headers=hdr(fx.viewer_sub)).json()["api_name"]
    document = client.get(f"{wbase(fx)}/ontology-export", headers=hdr(fx.editor_sub)).json()
    [exported] = [a for a in document["action_types"] if a["api_name"] == name]
    by_title = {s["title"]: s for s in exported["sections"]}
    assert by_title["Why"]["loose_before"] == 1
    assert "loose_before" not in by_title["Who"]
