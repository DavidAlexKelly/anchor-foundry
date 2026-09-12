"""Narrowing what an object parameter offers (§331; db 0084;
`action-types` p.33-36, p.40-41).

    "The object dropdown only shows objects where the specified property
     matches any of the provided values. The value can be statically defined by
     the user, inferred from another parameter… **If more than one value is
     provided to compare against, the result will be an OR operation.**" (p.36)

    "Static value filters in object dropdown validations are exposed to all
     users who can view the action type. Use of these filters risks exposing
     property value combinations to users without permissions to view the
     filtered objects." (p.40)

**Two claims run through this file.** p.34's sentence says the dropdown is
narrowed *and* the value is validated, so every test that narrows a list also
asks what happens to a submission that ignores it — a form that offered three
objects and accepted any of a thousand would be §214's control that looks like
it works. And p.40-41's redaction is tested as a fact about who is asking,
because a static filter value is readable by anyone who can read the
definition and Foundry's own example is a filter naming an investigation shown
to people who cannot see a document in it.
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
from src.services import action_filters as filters  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402


def static(prop: str, *values) -> dict:
    return {"property": prop,
            "values": [{"kind": "value", "value": v} for v in values]}


def from_parameter(prop: str, name: str) -> dict:
    return {"property": prop,
            "values": [{"kind": "parameter", "parameter": name}]}


def a_parameter(**over) -> dict:
    return {"api_name": "team", "data_type": "object", "dropdown_filters": [],
            **over}


# ---- p.36's compilation, decided without a database ---------------------------
def test_a_parameter_with_no_filters_narrows_nothing() -> None:
    assert filters.resolve(a_parameter(), bound={}, property_types={}) == ()


def test_a_static_filter_becomes_one_in_over_its_values() -> None:
    """p.36: "If more than one value is provided to compare against, the result
    will be an OR operation." `in` *is* that OR, and it is the operator this
    platform's object sets already have — so p.36 compiles into the narrowing
    that already runs against both stores rather than into a second one."""
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[static("region", "eu", "uk")]),
        bound={}, property_types={"region": "string"},
    )
    assert (f.property, f.op, f.value) == ("region", "in", ["eu", "uk"])


def test_the_declared_type_rides_along() -> None:
    """§221's argument: the decision that a comparison is legal is made once,
    against the ontology the caller resolved, rather than looked up again by
    each store."""
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[static("size", 3)]),
        bound={}, property_types={"size": "integer"},
    )
    assert f.data_type == "integer"


def test_several_filters_stay_several() -> None:
    """Which is p.36's narrowing: values inside one filter are an OR, and the
    filters themselves are an AND — the shape `ObjectSet.filters` already has."""
    got = filters.resolve(
        a_parameter(dropdown_filters=[static("region", "eu"), static("tier", "a")]),
        bound={}, property_types={},
    )
    assert [f.property for f in got] == ["region", "tier"]


def test_a_filter_can_read_another_parameter() -> None:
    """p.36's "inferred from another parameter"."""
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[from_parameter("region", "where")]),
        bound={"where": "uk"}, property_types={},
    )
    assert f.value == ["uk"]


def test_a_filter_reading_an_unsupplied_parameter_is_unresolved() -> None:
    """**Not "skip that value", and not "drop that filter".**

    Either would quietly widen the set, and a wider set is a dropdown offering
    exactly the objects the filter exists to exclude — which the submission
    then refuses. The caller is told which parameter is missing so it can say
    so rather than guess.
    """
    with pytest.raises(filters.Unresolved) as caught:
        filters.resolve(
            a_parameter(dropdown_filters=[from_parameter("region", "where")]),
            bound={}, property_types={},
        )
    assert caught.value.parameter == "where"


def test_an_empty_string_counts_as_unsupplied() -> None:
    """A box somebody cleared is not an answer, and filtering on "" would
    narrow to the objects whose property is empty."""
    with pytest.raises(filters.Unresolved):
        filters.resolve(
            a_parameter(dropdown_filters=[from_parameter("region", "where")]),
            bound={"where": ""}, property_types={},
        )


def test_referenced_parameters_names_what_the_filters_read() -> None:
    """What the form watches and the editor offers. Sorted, so the order of a
    document does not change the answer."""
    assert filters.referenced_parameters(a_parameter(dropdown_filters=[
        from_parameter("region", "where"),
        {"property": "tier", "values": [
            {"kind": "parameter", "parameter": "level"},
            {"kind": "value", "value": "a"},
        ]},
    ])) == ["level", "where"]


def test_a_static_only_filter_reads_no_parameters() -> None:
    assert filters.referenced_parameters(
        a_parameter(dropdown_filters=[static("region", "eu")])
    ) == []


# ---- p.40-41's redaction ------------------------------------------------------
def test_redaction_removes_the_filters_entirely() -> None:
    """**The whole list, not just the static values.**

    A filter reduced to its properties still says "somebody is filtering
    Documents by Investigation Name", and p.40's concern is the combination —
    the example is a value revealing that an investigation exists to people who
    cannot see a document in it.
    """
    p = a_parameter(dropdown_filters=[static("investigation", "Area 51")])
    assert filters.redact(p)["dropdown_filters"] == []


def test_redaction_leaves_everything_else_alone() -> None:
    """A viewer still needs the parameter: its name, its type, and what it
    offers. Only the sentence that produced the offer goes."""
    p = a_parameter(display_name="Team", required=True,
                    dropdown_filters=[static("region", "eu")])
    redacted = filters.redact(p)
    assert redacted["display_name"] == "Team"
    assert redacted["required"] is True
    assert redacted["api_name"] == "team"


# ---- the save-time refusals ---------------------------------------------------
def check(parameter: dict, *, properties=("region", "tier"), names=("team", "where")):
    filters.check_filters(
        parameter, declared_properties=set(properties), parameter_names=set(names)
    )


def test_a_filter_on_an_unknown_property_is_refused() -> None:
    """**The common mistake, and the message says which type is meant.** A
    filter is written against the type the parameter *offers*, not the action's
    own — and for most of this platform's history those were the same thing."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[static("no_such", "x")]))
    assert "no_such" in str(caught.value)
    assert "offers" in str(caught.value)


def test_a_filter_with_no_values_is_refused() -> None:
    """It would narrow to nothing, which is a dropdown that is empty for a
    reason nobody chose."""
    with pytest.raises(ValueError):
        check(a_parameter(dropdown_filters=[{"property": "region", "values": []}]))


def test_a_filter_with_no_property_is_refused() -> None:
    with pytest.raises(ValueError):
        check(a_parameter(dropdown_filters=[{"values": [{"kind": "value", "value": 1}]}]))


def test_a_value_kind_this_build_does_not_have_is_refused_by_name() -> None:
    """p.36's third kind — a property of an object-reference parameter — is not
    implemented, and a document carrying one is told so rather than having the
    value quietly ignored."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[{
            "property": "region",
            "values": [{"kind": "object_property", "parameter": "where",
                        "property": "region"}],
        }]))
    assert "object_property" in str(caught.value)


def test_a_filter_reading_a_parameter_that_is_gone_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[from_parameter("region", "nope")]))
    assert "nope" in str(caught.value)


def test_a_filter_reading_itself_is_refused() -> None:
    """The dropdown would depend on the value it is offering."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[from_parameter("region", "team")]))
    assert "itself" in str(caught.value)


def test_a_legal_filter_is_not_refused() -> None:
    check(a_parameter(dropdown_filters=[
        static("region", "eu"), from_parameter("tier", "where"),
    ]))


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


def a_type(client: TestClient, fx: Fixture, tag: str, rows: list[tuple[str, str]]):
    """A type whose objects carry a `region`, so a filter has something to cut on."""
    made = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"fl_{tag}", "display_name": f"Filter {tag}",
              "title_property": "name",
              "properties": [{"api_name": "code", "data_type": "string"},
                             {"api_name": "name", "data_type": "string"},
                             {"api_name": "region", "data_type": "string"}]},
    )
    assert made.status_code == 201, made.text
    type_id = made.json()["id"]
    csv = "code,name,region\n" + "".join(
        f"{c},{c.title()},{r}\n" for c, r in rows)
    dataset = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Filters {tag}"},
        files={"file": ("f.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert dataset.status_code == 201, dataset.text
    source = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
              "primary_key_column": "code",
              "column_mappings": {"name": "name", "region": "region"}},
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
    tag = uuid.uuid4().hex[:8]
    team_type = a_type(client, fx, f"team{tag}",
                       [("alpha", "eu"), ("beta", "uk"), ("gamma", "us")])
    ticket_type = a_type(client, fx, f"tkt{tag}", [("t1", "eu")])
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
            "teams": {t["primary_key"]: t["id"] for t in teams},
            "ticket": tickets[0]["id"]}


def define(client: TestClient, fx: Fixture, setup, dropdown_filters, sub=None):
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": [
                  {"api_name": "where", "display_name": "Where",
                   "data_type": "string"},
                  {"api_name": "team", "display_name": "Team",
                   "data_type": "object",
                   "object_type_id": setup["team_type"],
                   "dropdown_filters": dropdown_filters},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "where"}}],
              "criteria": []},
    )


def offered(client: TestClient, fx: Fixture, setup, values=None, sub=None):
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


def test_a_static_filter_narrows_the_dropdown(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.34: "the action form will render a dropdown with only objects that
    match the filter"."""
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    keys = {c["primary_key"] for c in offered(client, fx, setup)["team"]["items"]}
    assert keys == {"alpha"}


def test_several_values_are_an_or(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.36 in as many words, and the half a single-value fixture could not
    see: two values admit two objects, not zero."""
    define(client, fx, setup, [static("region", "eu", "uk")]).raise_for_status()
    keys = {c["primary_key"] for c in offered(client, fx, setup)["team"]["items"]}
    assert keys == {"alpha", "beta"}


def test_a_filter_reads_another_parameter(
    client: TestClient, fx: Fixture, setup
) -> None:
    """p.36's "inferred from another parameter", and both values of it: the
    same action offers different objects for different answers."""
    define(client, fx, setup, [from_parameter("region", "where")]).raise_for_status()
    assert {c["primary_key"] for c in offered(
        client, fx, setup, {"where": "uk"})["team"]["items"]} == {"beta"}
    assert {c["primary_key"] for c in offered(
        client, fx, setup, {"where": "us"})["team"]["items"]} == {"gamma"}


def test_an_unresolved_filter_offers_nothing_and_says_which_box_to_fill(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**"Nothing to choose" and "fill in the other box first" are different
    things to tell somebody.**

    Offering every object here would offer exactly the ones the filter exists
    to exclude, and the submission would be refused a moment later.
    """
    define(client, fx, setup, [from_parameter("region", "where")]).raise_for_status()
    offer = offered(client, fx, setup)["team"]
    assert offer["items"] == []
    assert offer["waiting_for"] == "where"


def test_a_value_outside_the_filter_is_refused_at_submit(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**p.34's other sentence, which is what makes the filter a rule.**

    §330 checked the *type*; a dropdown narrowed to one object and a check that
    accepts any object of the type is a control that looks like it works. This
    submission never went near a form.
    """
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    refused = run(client, fx, setup,
                  {"where": "x", "team": setup["teams"]["gamma"]})
    assert refused.status_code == 422, refused.text
    assert "team" in refused.text

    allowed = run(client, fx, setup,
                  {"where": "y", "team": setup["teams"]["alpha"]})
    assert allowed.status_code == 200, allowed.text


def test_a_submission_that_cannot_resolve_the_filter_is_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Fails closed, for the reason the module docstring gives: whether this
    object is in the set is a question nobody can answer, and accepting on an
    unanswered question is how a value the filter exists to exclude gets
    written."""
    define(client, fx, setup, [from_parameter("region", "where")]).raise_for_status()
    refused = run(client, fx, setup, {"team": setup["teams"]["alpha"]})
    assert refused.status_code == 422, refused.text
    assert "where" in refused.text


def test_filters_survive_the_definition_round_trip(
    client: TestClient, fx: Fixture, setup
) -> None:
    define(client, fx, setup, [static("region", "eu", "uk")]).raise_for_status()
    back = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.editor_sub)).json()
    team = next(p for p in back["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == [static("region", "eu", "uk")]


def test_filters_on_a_parameter_with_no_type_are_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    """There is nothing to filter: the parameter does not say what it offers."""
    r = client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "where", "display_name": "Where",
                   "data_type": "string"},
                  {"api_name": "team", "display_name": "Team",
                   "data_type": "object",
                   "dropdown_filters": [static("region", "eu")]},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "where"}}],
              "criteria": []},
    )
    assert r.status_code == 422, r.text
    assert "which object type" in r.text


def test_a_filter_on_a_property_the_offered_type_lacks_is_refused(
    client: TestClient, fx: Fixture, setup
) -> None:
    r = define(client, fx, setup, [static("no_such_property", "eu")])
    assert r.status_code == 422, r.text
    assert "no_such_property" in r.text


# ---- p.40-41, through the API -------------------------------------------------
def test_a_viewer_does_not_receive_the_filter_values(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**p.40's whole concern.** Foundry's example is a filter naming an
    investigation, readable by everyone who can read the action type, revealing
    that the investigation exists to people who cannot see a document in it.

    Both directions in one test: the editor who wrote it still sees it, so this
    is about *who is asking* rather than about a field that stopped being sent.
    """
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()

    as_editor = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                           headers=hdr(fx.editor_sub)).json()
    team = next(p for p in as_editor["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == [static("region", "eu")]

    as_viewer = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                           headers=hdr(fx.viewer_sub)).json()
    team = next(p for p in as_viewer["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == []


def test_the_listing_redacts_too(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The route the Actions table actually calls.**

    A rule that held on the single read and not on the listing would be no rule
    at all — and the listing is the one a screen loads without being asked.
    """
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    listed = client.get(f"{wbase(fx)}/action-types", headers=hdr(fx.viewer_sub)).json()
    mine = next(a for a in listed if a["id"] == setup["action"])
    team = next(p for p in mine["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == []


def test_a_viewer_still_gets_the_narrowed_dropdown(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The redaction costs them nothing.**

    p.41 says Foundry's own form receives the filter as an object set, so
    "users could review the network request containing this object set". This
    platform's form asks for the resulting *objects* and never for the filter,
    so a viewer gets the narrowed list without ever being told what narrowed
    it.
    """
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    keys = {c["primary_key"]
            for c in offered(client, fx, setup, sub=fx.viewer_sub)["team"]["items"]}
    assert keys == {"alpha"}
