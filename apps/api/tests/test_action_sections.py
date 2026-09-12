"""Sections on an action form (§328; db 0081; `action-types` p.122-124).

    "The action form can be customized with sections. These sections provide a
     logical grouping of parameters to organize an action form." (p.122)

    "Sections are also collapsible, can be hidden entirely, and can make use of
     conditional overrides… A section can be hidden at first and only shown
     based on a prior parameter." (p.123)

**The claim that runs through every test here is that a section changes the
form and nothing else.** An action with its sections deleted submits the same
values from the same parameters — so the visibility rules below decide what is
*drawn*, and a hidden section's parameters are still declared, still defaulted
and still validated. A form that quietly dropped them would mean the same
action did different things depending on which boxes were on screen.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_sections as sections  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


# ---- p.123's visibility, decided without a database ---------------------------
NOBODY: dict = {}


def a_section(**over) -> dict:
    return {"hidden": False, "visible_when": None, **over}


def test_a_plain_section_is_drawn() -> None:
    """Every section anybody made before configuring any of this."""
    assert sections.visibility(a_section(), bound={}, user=NOBODY) is True


def test_a_hidden_section_is_never_drawn() -> None:
    """p.123's "can be hidden entirely" — the plain case, which overrides
    whatever a condition would have said."""
    always = {"left": {"kind": "value", "value": 1},
              "operator": "is", "right": {"kind": "value", "value": 1}}
    assert sections.visibility(
        a_section(hidden=True, visible_when=always), bound={}, user=NOBODY
    ) is False


def test_a_condition_decides_when_there_is_one() -> None:
    """p.123: "A section can be hidden at first and only shown based on a prior
    parameter." """
    when_closed = {"left": {"kind": "parameter", "parameter": "status"},
                   "operator": "is", "right": {"kind": "value", "value": "closed"}}
    section = a_section(visible_when=when_closed)
    assert sections.visibility(section, bound={"status": "closed"},
                               user=NOBODY) is True
    assert sections.visibility(section, bound={"status": "open"},
                               user=NOBODY) is False


def test_a_condition_that_cannot_be_read_hides_the_section() -> None:
    """**Both directions of "refuse to guess".**

    `check_criteria` fails an unevaluable criterion closed, and so does this —
    a section shown because its condition was unreadable would put parameters
    in front of somebody on the strength of a broken rule, and p.123's whole
    point is asking for things "under the appropriate circumstances".
    """
    for nonsense in (
        {"left": {"kind": "no_such_side"}, "operator": "is",
         "right": {"kind": "value", "value": 1}},
        {"left": {"kind": "value", "value": 1}, "operator": "no_such_operator",
         "right": {"kind": "value", "value": 1}},
    ):
        assert sections.visibility(
            a_section(visible_when=nonsense), bound={}, user=NOBODY
        ) is False, nonsense


def test_a_broken_condition_does_not_take_the_form_down() -> None:
    """A display decision reading a JSON blob somebody typed. A 500 because a
    section's condition was malformed would take the whole action with it."""
    assert sections.visibility(
        a_section(visible_when={"nothing": "sensible"}), bound={}, user=NOBODY
    ) is False


# **There is no test here for the column count, and there was one.** It read
# `sections.COLUMN_CHOICES == (1, 2)`, which is a test that a constant is
# written the way it is written — and the service check it guarded turned out to
# be unreachable, because `SectionIn.columns` is `Literal[1, 2]` and the table
# carries the same `CHECK`. Both of those are exercised by
# `test_three_columns_are_refused` below, through the door a caller uses.


# ---- the Form tab, against a real action --------------------------------------
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
    """An action with three parameters to arrange."""
    tag = uuid.uuid4().hex[:8]
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"sec_{tag}", "display_name": f"Sectioned {tag}",
              "properties": [
                  {"api_name": "status", "data_type": "string"},
                  {"api_name": "reason", "data_type": "string"},
                  {"api_name": "owner", "data_type": "string"},
              ]},
    )
    assert made.status_code == 201, made.text
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": made.json()["id"], "api_name": f"edit_{tag}",
              "display_name": "Edit",
              "editable_properties": ["status", "reason", "owner"]},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def get_sections(client: TestClient, fx: Fixture, action: str, sub=None):
    r = client.get(f"{wbase(fx)}/action-types/{action}/sections",
                   headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def put_sections(client: TestClient, fx: Fixture, action: str, sections_in, sub=None):
    return client.put(f"{wbase(fx)}/action-types/{action}/sections",
                      headers=hdr(sub or fx.editor_sub),
                      json={"sections": sections_in})


def test_an_action_starts_with_no_sections(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """Which is the shape every action in this platform already has, and the
    one p.122's customisation is optional on top of."""
    assert get_sections(client, fx, action) == []


def test_a_section_holds_the_parameters_put_in_it(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.122's "logical grouping of parameters"."""
    r = put_sections(client, fx, action, [
        {"title": "Why", "description": "What changed and why",
         "parameters": ["status", "reason"]},
    ])
    assert r.status_code == 200, r.text
    [section] = r.json()
    assert section["title"] == "Why"
    assert section["parameters"] == ["status", "reason"]
    # p.123: the description "will always be shown in the section itself, not
    # in a tooltip" — so it travels with the section rather than being a hint
    # on something else.
    assert section["description"] == "What changed and why"


def test_sections_come_back_in_the_order_they_were_written(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.124: "Parameters and sections display in the form based on their order
    in this Form Content section."

    **Named against the alphabet**, so the order returned cannot be the
    accident of sorting by title.
    """
    r = put_sections(client, fx, action, [
        {"title": "Zulu first", "parameters": ["status"]},
        {"title": "Alpha second", "parameters": ["reason"]},
    ])
    assert r.status_code == 200, r.text
    assert [s["title"] for s in r.json()] == ["Zulu first", "Alpha second"]
    assert [s["sort_order"] for s in r.json()] == [0, 1]
    # And it survives the round trip, rather than being the order of the write.
    assert [s["title"] for s in get_sections(client, fx, action)] == [
        "Zulu first", "Alpha second"
    ]


def test_a_parameter_left_out_returns_to_the_form_body(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """**What "moved out of a section" means**, and there is nowhere else for it
    to go.

    The parameter still exists — a section is an arrangement, and an
    arrangement that could delete the thing it arranges would make tidying a
    form a destructive act (db 0081's `ON DELETE SET NULL`).
    """
    put_sections(client, fx, action, [{"title": "All", "parameters":
                                       ["status", "reason", "owner"]}])
    r = put_sections(client, fx, action, [{"title": "Some",
                                           "parameters": ["status"]}])
    assert r.status_code == 200, r.text
    assert r.json()[0]["parameters"] == ["status"]

    definition = client.get(f"{wbase(fx)}/action-types/{action}",
                            headers=hdr(fx.viewer_sub)).json()
    assert {p["api_name"] for p in definition["parameters"]} == {
        "status", "reason", "owner"
    }, "the parameters are still the action's"


def test_deleting_every_section_leaves_the_parameters_alone(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """The same claim at its limit, which is the one p.122 rests on: a form with
    no sections is an action that works exactly as before."""
    put_sections(client, fx, action, [{"title": "All", "parameters":
                                       ["status", "reason", "owner"]}])
    assert put_sections(client, fx, action, []).status_code == 200
    assert get_sections(client, fx, action) == []

    definition = client.get(f"{wbase(fx)}/action-types/{action}",
                            headers=hdr(fx.viewer_sub)).json()
    assert len(definition["parameters"]) == 3


def test_a_parameter_cannot_be_in_two_sections(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.124 offers two ways to put a parameter in a section and neither is "in
    both" — a parameter drawn twice would be one box overwriting the other's
    value as the reader typed."""
    r = put_sections(client, fx, action, [
        {"title": "First", "parameters": ["status"]},
        {"title": "Second", "parameters": ["status"]},
    ])
    assert r.status_code == 422, r.text
    assert "status" in r.text


def test_a_section_cannot_hold_a_parameter_the_action_lacks(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """Refused rather than stored and ignored: a Form tab listing a parameter
    nobody can fill in is §214's control that looks like it works."""
    r = put_sections(client, fx, action, [
        {"title": "Wrong", "parameters": ["no_such_parameter"]},
    ])
    assert r.status_code == 422, r.text
    assert "no_such_parameter" in r.text


def test_two_sections_cannot_share_a_title(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.124's Form tab lists them by name, and two called "Details" is a list
    the builder cannot use."""
    r = put_sections(client, fx, action, [
        {"title": "Details", "parameters": ["status"]},
        {"title": "Details", "parameters": ["reason"]},
    ])
    assert r.status_code == 422, r.text


def test_a_blank_title_is_refused(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """An untitled section is a box the builder cannot point at when they come
    back to it."""
    for blank in ("", "   "):
        r = put_sections(client, fx, action, [{"title": blank}])
        assert r.status_code == 422, (blank, r.text)


def test_three_columns_are_refused(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.123 offers one or two. Three is a layout nothing renders, and storing
    it would put a form in a state the screen has to guess about.

    The refusal is the request model's (`Literal[1, 2]`) with the table's
    `CHECK` behind it. The service used to check a third time and the check
    could not be reached — see the note where it was.
    """
    r = put_sections(client, fx, action, [{"title": "Wide", "columns": 3}])
    assert r.status_code == 422, r.text


def test_nothing_is_written_by_a_refused_form(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """**The form the builder had is the form they still have.**

    p.138's rule about batches applied to a form: a Form tab half-replaced is
    worse than one refused, because the builder cannot see which half took.

    **What keeps that promise is the transaction, not the order of the
    statements** — `user_connection` is one transaction per request, so a
    refusal rolls the delete back wherever it happened. This test said
    "checked before anything is written" and a sweep that moved the delete to
    the very top of `replace_sections` left it green, which is the honest way
    to find out which layer you are actually testing.
    """
    put_sections(client, fx, action, [{"title": "Kept", "parameters": ["status"]}])
    refused = put_sections(client, fx, action, [
        {"title": "New", "parameters": ["status"]},
        {"title": "Also new", "parameters": ["no_such_parameter"]},
    ])
    assert refused.status_code == 422, refused.text
    assert [s["title"] for s in get_sections(client, fx, action)] == ["Kept"], (
        "the form the builder had is the form they still have"
    )


def test_the_hiding_options_survive_the_round_trip(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.123's three switches, which are three different things: whether it may
    be folded, whether it starts folded, and whether it is there at all."""
    condition = {"left": {"kind": "parameter", "parameter": "status"},
                 "operator": "is", "right": {"kind": "value", "value": "closed"}}
    r = put_sections(client, fx, action, [
        {"title": "Conditional", "collapsible": True, "collapsed": True,
         "hidden": False, "visible_when": condition, "parameters": ["reason"]},
    ])
    assert r.status_code == 200, r.text
    [section] = get_sections(client, fx, action)
    assert section["collapsible"] is True
    assert section["collapsed"] is True
    assert section["hidden"] is False
    assert section["visible_when"] == condition


def test_a_viewer_may_read_the_form_but_not_rearrange_it(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """A section is how the form is drawn, and a viewer can already read the
    action's parameters — an arrangement of things they can see is not a new
    thing to see. Changing it is a write."""
    assert get_sections(client, fx, action, sub=fx.viewer_sub) == []
    r = put_sections(client, fx, action, [{"title": "Nope"}], sub=fx.viewer_sub)
    assert r.status_code == 403, r.text


def test_an_outsider_sees_nothing(
    client: TestClient, fx: Fixture, action: str
) -> None:
    r = client.get(f"{wbase(fx)}/action-types/{action}/sections",
                   headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text


# ---- p.123's condition, asked over the wire (§328) ----------------------------
def visible(client: TestClient, fx: Fixture, action: str, values, sub=None):
    r = client.post(f"{wbase(fx)}/action-types/{action}/visible-sections",
                    headers=hdr(sub or fx.viewer_sub), json={"values": values})
    assert r.status_code == 200, r.text
    return r.json()


def when(parameter: str, value) -> dict:
    return {"left": {"kind": "parameter", "parameter": parameter},
            "operator": "is", "right": {"kind": "value", "value": value}}


def test_the_form_asks_the_server_which_sections_to_draw(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """**The endpoint that keeps decision 0007's grammar in one place.**

    The alternative is the browser evaluating `{left, operator, right}` in
    TypeScript, which would be a second reading of the same document — and the
    one it would disagree with is the one the definition editor writes.
    """
    put_sections(client, fx, action, [
        {"title": "Always", "parameters": ["owner"]},
        {"title": "Why", "visible_when": when("status", "closed"),
         "parameters": ["reason"]},
    ]).raise_for_status()
    ids = {s["title"]: s["id"] for s in get_sections(client, fx, action)}

    # Both the positive and the negative, because a call that returned every
    # section would pass the first on its own.
    assert visible(client, fx, action, {"status": "closed"}) == [
        ids["Always"], ids["Why"]
    ]
    assert visible(client, fx, action, {"status": "open"}) == [ids["Always"]]
    # And no values at all, which is the form before anybody types: p.123's
    # "hidden at first".
    assert visible(client, fx, action, {}) == [ids["Always"]]


def test_a_hidden_section_is_never_returned_however_its_condition_reads(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.123's two kinds of hiding do not negotiate: "hidden entirely" wins."""
    put_sections(client, fx, action, [
        {"title": "Gone", "hidden": True, "visible_when": when("status", "closed"),
         "parameters": ["reason"]},
    ]).raise_for_status()
    assert visible(client, fx, action, {"status": "closed"}) == []


def test_an_action_with_no_sections_has_nothing_to_draw(
    client: TestClient, fx: Fixture, action: str
) -> None:
    assert visible(client, fx, action, {"status": "closed"}) == []


def test_a_viewer_may_ask_which_sections_are_drawn(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """Unlike `check`, which is `editor` because p.140 makes criteria a
    permissions mechanism. This says nothing about whether the submission would
    be refused — only where the boxes go."""
    put_sections(client, fx, action, [{"title": "Always"}]).raise_for_status()
    assert len(visible(client, fx, action, {}, sub=fx.viewer_sub)) == 1
    r = client.post(f"{wbase(fx)}/action-types/{action}/visible-sections",
                    headers=hdr(fx.outsider_sub), json={"values": {}})
    assert r.status_code in (403, 404), r.text


def test_a_condition_about_the_current_user_reads_the_caller(
    client: TestClient, fx: Fixture, action: str
) -> None:
    """p.50's other condition template. **The reason this is a round trip and
    not a browser function**: who is asking is not in the form's values at all,
    so a browser-side evaluator would have to be told — and would be told by
    the same browser it is meant to be checking.
    """
    mine = {"left": {"kind": "current_user", "attribute": "id"},
            "operator": "is",
            "right": {"kind": "value", "value": str(fx.viewer)}}
    put_sections(client, fx, action, [
        {"title": "Mine", "visible_when": mine},
    ]).raise_for_status()
    assert len(visible(client, fx, action, {}, sub=fx.viewer_sub)) == 1
    assert visible(client, fx, action, {}, sub=fx.editor_sub) == []
