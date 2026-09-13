"""What an object parameter offers, and what it accepts (§330; db 0083;
`action-types` p.25, p.33-37).

    "Within the parameter configuration view, action editors can specify
     filters and Search Arounds to limit the objects that show up in the
     dropdown across all action interfaces. After configuring the filters, the
     action form will render a dropdown with only objects that match the
     filter. **The value selected is also validated before the action is
     executed.**" (p.34)

    "The resulting multiple choice options will be derived from the set of
     objects that the user has permission to view." (p.33)

**p.33-37 narrows a dropdown this platform did not draw.** An `object`
parameter has been a text box since db 0044, which asks whoever submits the
action to know a uuid — so this unit is the list, and the filters that narrow it
are the next one. The two halves of p.34 are tested together throughout,
because a dropdown offering only the right objects is a convenience and the
refusal is the rule.
"""
from __future__ import annotations

import io
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_choices as choices  # noqa: E402
from src.services import actions as actions_service  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


# ---- reading an object's properties off a row (§334) --------------------------
def test_properties_come_back_decoded_whichever_store_answered() -> None:
    """**Both driver paths, because only one of them runs here.**

    Postgres hands `properties` back already decoded and OpenSearch can hand
    back the text, so the `isinstance(str)` branch is unreachable in this
    suite's configuration — a sweep deleted it with everything green. p.36's
    third kind reads a property *out* of this map, so a store that returned the
    string would make every such filter behave as though the object had
    nothing in it.
    """
    assert choices._properties({"properties": {"region": "eu"}}) == {"region": "eu"}
    assert choices._properties({"properties": '{"region": "eu"}'}) == {"region": "eu"}
    assert choices._properties({"properties": None}) == {}


# ---- which type a parameter holds, decided without a database ----------------
def a_parameter(**over) -> dict:
    return {"api_name": "subject", "data_type": "object", **over}


def test_a_declared_type_is_the_type() -> None:
    assert choices.type_of(a_parameter(object_type_id="t-1")) == "t-1"


def test_a_parameter_nobody_typed_has_no_type() -> None:
    """**And that is the whole reason the column exists.**

    `object_parameter_types` can also produce an answer by reading the action's
    rules, and the first draft of this module used it as a fallback so that
    parameters written before §330 would get a dropdown too. The existing tests
    refused that within a minute: the inference is a guess, documented as one,
    and it is plainly wrong for a link rule — which names the far object
    through the link type rather than through `config.object_type`, so the
    guess falls back to the action's own subject type.

    A wrong guess is survivable where it was born (a notification renders a
    gap). Refusing a submission on one is not, and neither is offering somebody
    a dropdown of the wrong objects.
    """
    assert choices.type_of(a_parameter()) is None
    assert choices.type_of(a_parameter(object_type_id=None)) is None


def test_only_object_parameters_are_asked_about() -> None:
    assert [p["api_name"] for p in choices.object_parameters([
        {"api_name": "note", "data_type": "string"},
        {"api_name": "subject", "data_type": "object"},
        {"api_name": "count", "data_type": "integer"},
    ])] == ["subject"]


def test_the_choice_cap_is_the_stores_own_page_size() -> None:
    """A larger number here would read like a promise and be overruled one call
    down, where `list_for_type` clamps — and the truncation notice would then be
    right for a reason this module did not know."""
    from src.services import instance_store

    assert choices.MAX_CHOICES == instance_store.INSTANCE_PAGE_SIZE


def test_a_declared_type_beats_the_rules_inference() -> None:
    """§257's inference stays for notifications, and now yields to a statement.

    A type somebody *declared* is a claim; one read off a rule is an inference
    from what the action happens to do with the value. When they disagree the
    declaration is the answer, which is what `object_parameter_types`' own
    docstring promised would happen the day this column existed.
    """
    declared = str(uuid.uuid4())
    subject = str(uuid.uuid4())
    types = actions_service.object_parameter_types(
        [],
        default_object_type_id=subject,
        parameters=[a_parameter(object_type_id=declared)],
    )
    assert types["subject"] == declared

    # And a parameter with no column still takes the old answer.
    types = actions_service.object_parameter_types(
        [], default_object_type_id=subject, parameters=[a_parameter()]
    )
    assert types["subject"] == subject


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


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def a_type_with_rows(client: TestClient, fx: Fixture, tag: str, rows: list[str]):
    """An object type backed by a dataset, so it has instances to offer."""
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"ch_{tag}", "display_name": f"Choice {tag}",
              "title_property": "name",
              "properties": [{"api_name": "code", "data_type": "string"},
                             {"api_name": "name", "data_type": "string"}]},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    csv = "code,name\n" + "".join(f"{c},{c.title()} team\n" for c in rows)
    dataset = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Choices {tag}"},
        files={"file": ("c.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    source = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "code",
              "column_mappings": {"name": "name"}},
    )
    assert source.status_code == 201, source.text
    synced = client.post(
        f"{pbase(fx)}/object-type-sources/{source.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    )
    assert synced.status_code == 200, synced.text
    return type_id


@pytest.fixture(scope="module")
def setup(client: TestClient, fx: Fixture):
    """An action over one type, with an `object` parameter naming another.

    Two types, because the whole point of the column is that the parameter's
    type is **not** the action's own — and a fixture where they coincided could
    not tell a working lookup from one that always used the subject type.
    """
    tag = uuid.uuid4().hex[:8]
    team_type = a_type_with_rows(client, fx, f"team{tag}", ["alpha", "beta"])
    ticket_type = a_type_with_rows(client, fx, f"tkt{tag}", ["t1"])
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type, "api_name": f"assign_{tag}",
              "display_name": "Assign", "editable_properties": ["name"]},
    )
    assert action.status_code == 201, action.text
    teams = client.get(f"{wbase(fx)}/object-types/{team_type}/instances",
                       headers=hdr(fx.editor_sub)).json()["items"]
    tickets = client.get(f"{wbase(fx)}/object-types/{ticket_type}/instances",
                         headers=hdr(fx.editor_sub)).json()["items"]
    return {"action": action.json()["id"], "team_type": team_type,
            "ticket_type": ticket_type,
            "teams": {t["primary_key"]: t["id"] for t in teams},
            "ticket": tickets[0]["id"]}


def define(client: TestClient, fx: Fixture, setup, *, typed: bool):
    """The action, with its object parameter typed or not."""
    subject = {"api_name": "team", "display_name": "Team", "data_type": "object"}
    if typed:
        subject["object_type_id"] = setup["team_type"]
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string"},
                  subject,
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "name"}}],
              "criteria": []},
    )


def offered(client: TestClient, fx: Fixture, setup, sub=None, values=None):
    # A POST since §331: p.36's filters may read the values filled in so far,
    # so "what does this parameter offer" is a question *about* a partly
    # completed form rather than about the action alone.
    r = client.post(f"{wbase(fx)}/action-types/{setup['action']}/parameter-choices",
                    headers=hdr(sub or fx.viewer_sub),
                    json={"values": values or {}})
    assert r.status_code == 200, r.text
    return {c["parameter"]: c for c in r.json()}


def run(client: TestClient, fx: Fixture, setup, values, sub=None):
    return client.post(
        f"{pbase(fx)}/actions/{setup['action']}/execute",
        headers=hdr(sub or fx.editor_sub),
        json={"instance_id": setup["ticket"], "values": values},
    )


def test_a_typed_object_parameter_offers_its_objects(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The list p.33-37 assumes and this platform did not have.**

    The objects are of the parameter's *own* type, not the action's — which is
    the whole reason the column exists, and why the fixture uses two types.
    """
    define(client, fx, setup, typed=True).raise_for_status()
    choice = offered(client, fx, setup)["team"]
    assert choice["object_type_id"] == setup["team_type"]
    assert choice["object_type_id"] != setup["ticket_type"]
    assert {c["primary_key"] for c in choice["items"]} == {"alpha", "beta"}
    assert choice["truncated"] is False


def test_a_choice_is_labelled_by_the_types_title_property(
    client: TestClient, fx: Fixture, setup
) -> None:
    """What every other listing here shows. A dropdown of uuids would be the
    text box with extra steps."""
    define(client, fx, setup, typed=True).raise_for_status()
    labels = {c["primary_key"]: c["label"]
              for c in offered(client, fx, setup)["team"]["items"]}
    assert labels["alpha"] == "Alpha team"


def test_an_untyped_object_parameter_is_not_offered_at_all(
    client: TestClient, fx: Fixture, setup
) -> None:
    """It keeps exactly the behaviour it had before §330 — a text box, and no
    p.34 validation to be wrong about. Offering a guessed list would be worse
    than offering none: the reader cannot tell a wrong list from a short one."""
    define(client, fx, setup, typed=False).raise_for_status()
    assert "team" not in offered(client, fx, setup)


def test_a_string_parameter_cannot_name_an_object_type(
    client: TestClient, fx: Fixture, setup
) -> None:
    """A type on a string is a claim nothing reads, and it would sit in the
    document looking like it meant something."""
    r = client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [{"api_name": "name", "display_name": "Name",
                              "data_type": "string",
                              "object_type_id": setup["team_type"]}],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "name"}}],
              "criteria": []},
    )
    assert r.status_code == 422, r.text
    assert "object type" in r.text


def test_the_declared_type_survives_the_definition_round_trip(
    client: TestClient, fx: Fixture, setup
) -> None:
    define(client, fx, setup, typed=True).raise_for_status()
    back = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.editor_sub)).json()
    team = next(p for p in back["parameters"] if p["api_name"] == "team")
    assert team["object_type_id"] == setup["team_type"]
    name = next(p for p in back["parameters"] if p["api_name"] == "name")
    assert name["object_type_id"] is None


# ---- p.34's other half --------------------------------------------------------
def test_an_object_of_the_wrong_type_is_refused_before_anything_runs(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**p.34: "The value selected is also validated before the action is
    executed."**

    The dropdown is a convenience; this is the rule. A submission naming the
    ticket where a team was asked for never went near a form, and is refused
    just the same.
    """
    define(client, fx, setup, typed=True).raise_for_status()
    refused = run(client, fx, setup, {"name": "x", "team": setup["ticket"]})
    assert refused.status_code == 422, refused.text
    assert "team" in refused.text

    # And a real team is accepted, which is what makes the refusal about the
    # type rather than about object parameters in general.
    ok = run(client, fx, setup, {"name": "x", "team": setup["teams"]["alpha"]})
    assert ok.status_code == 200, ok.text


def test_an_object_that_does_not_exist_is_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    define(client, fx, setup, typed=True).raise_for_status()
    refused = run(client, fx, setup, {"name": "x", "team": str(uuid.uuid4())})
    assert refused.status_code == 422, refused.text


def test_an_untyped_object_parameter_accepts_what_it_always_did(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The check that §330 did not quietly narrow every action that came
    before it.**

    Without a declared type there is nothing to validate against that is not a
    guess, so the submission behaves exactly as it did — including one naming
    an object of a type nobody would have chosen.
    """
    define(client, fx, setup, typed=False).raise_for_status()
    ok = run(client, fx, setup, {"name": "y", "team": setup["ticket"]})
    assert ok.status_code == 200, ok.text


def test_a_parameter_left_empty_is_not_validated(
    client: TestClient, fx: Fixture, setup
) -> None:
    """An optional object parameter nobody filled in is not a wrong object."""
    define(client, fx, setup, typed=True).raise_for_status()
    assert run(client, fx, setup, {"name": "z"}).status_code == 200


def test_a_viewer_may_ask_what_a_parameter_offers(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.33: the options are "derived from the set of objects that the user has
    permission to view" — so this is read through the caller's own connection
    and RLS is the whole of that sentence."""
    define(client, fx, setup, typed=True).raise_for_status()
    assert offered(client, fx, setup, sub=fx.viewer_sub)["team"]["items"]
    r = client.post(f"{wbase(fx)}/action-types/{setup['action']}/parameter-choices",
                    headers=hdr(fx.outsider_sub), json={"values": {}})
    assert r.status_code in (403, 404), r.text


def test_a_type_with_more_objects_than_the_control_holds_says_so(
    client: TestClient, fx: Fixture
) -> None:
    """**§256's rule, one control down.**

    A dropdown is not a listing: somebody picks from the rows it happened to
    receive, so a control that quietly held the first fifty of a larger set
    would leave them unable to learn the rest existed. The cap is the store's
    own page size, so this seeds one more object than that.

    Nothing else here could catch it. Every other fixture has two objects, so
    `total > len(rows)` and a hard-coded `False` agree — and a sweep that
    removed the comparison altogether survived the whole file.
    """
    tag = uuid.uuid4().hex[:8]
    many = choices.MAX_CHOICES + 1
    crowded = a_type_with_rows(client, fx, f"many{tag}",
                               [f"c{n:03d}" for n in range(many)])
    ticket = a_type_with_rows(client, fx, f"one{tag}", ["t1"])
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket, "api_name": f"pick_{tag}",
              "display_name": "Pick", "editable_properties": ["name"]},
    )
    assert action.status_code == 201, action.text
    r = client.put(
        f"{wbase(fx)}/action-types/{action.json()['id']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "name", "display_name": "Name",
                   "data_type": "string"},
                  {"api_name": "team", "display_name": "Team",
                   "data_type": "object", "object_type_id": crowded},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "name"}}],
              "criteria": []},
    )
    assert r.status_code == 200, r.text

    offer = client.post(
        f"{wbase(fx)}/action-types/{action.json()['id']}/parameter-choices",
        headers=hdr(fx.viewer_sub), json={"values": {}},
    ).json()[0]
    assert offer["truncated"] is True
    assert len(offer["items"]) == choices.MAX_CHOICES
