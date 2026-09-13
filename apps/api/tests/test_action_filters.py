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
from src.services import instance_store  # noqa: E402
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


# ---- p.36's third value kind (§334) ---------------------------------------------
def from_object_property(prop: str, name: str, of: str) -> dict:
    return {"property": prop,
            "values": [{"kind": "object_property", "parameter": name,
                        "property": of}]}


def test_a_filter_can_read_a_property_of_an_object_parameter() -> None:
    """p.36's third: "or a property of an Object Reference parameter".

    The whole sentence is now implemented, and this is the half neither of the
    other two can express — "the Teams in the region of the Office you chose"
    compares against a value nobody typed and no parameter holds.
    """
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[
            from_object_property("region", "office", "region")]),
        bound={"office": "o-1"}, property_types={},
        objects={"office": {"region": "uk"}},
    )
    assert (f.property, f.op, f.value) == ("region", "in", ["uk"])


def test_the_property_read_is_the_one_named_rather_than_the_one_filtered() -> None:
    """A filter on `region` may read `home_region`, and reading the *filtered*
    property off the object instead would look identical whenever the two
    happen to share a name — which is most of the time somebody writes one."""
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[
            from_object_property("region", "office", "home_region")]),
        bound={"office": "o-1"}, property_types={},
        objects={"office": {"region": "eu", "home_region": "uk"}},
    )
    assert f.value == ["uk"]


def test_the_three_kinds_mix_inside_one_or() -> None:
    """p.36's OR does not care which kind produced a value, and a `values` list
    that handled only its first entry's kind would pass every single-kind
    test."""
    [f] = filters.resolve(
        a_parameter(dropdown_filters=[{"property": "region", "values": [
            {"kind": "value", "value": "eu"},
            {"kind": "parameter", "parameter": "where"},
            {"kind": "object_property", "parameter": "office",
             "property": "region"},
        ]}]),
        bound={"where": "us", "office": "o-1"}, property_types={},
        objects={"office": {"region": "uk"}},
    )
    assert f.value == ["eu", "us", "uk"]


def test_an_object_parameter_nobody_has_chosen_says_which_box_comes_first() -> None:
    """The same state a plain parameter reference is in, and the same sentence:
    the object has not been chosen, so choose it."""
    with pytest.raises(filters.Unresolved) as caught:
        filters.resolve(
            a_parameter(dropdown_filters=[
                from_object_property("region", "office", "region")]),
            bound={}, property_types={}, objects={},
        )
    assert caught.value.parameter == "office"
    assert caught.value.property is None


def test_a_chosen_object_with_nothing_under_that_property_is_a_different_state() -> None:
    """**Told apart on purpose** (§334). "Choose the Office first" is false to
    somebody who has chosen one, and a control that tells them to do what they
    have already done is §214 in words.

    Filtering on the empty value would be worse: it narrows to whichever Teams
    also have no region, which is a short list for a reason nobody chose.
    """
    for held in ({"office": {"region": None}}, {"office": {"region": ""}},
                 {"office": {}}, {}):
        with pytest.raises(filters.Unresolved) as caught:
            filters.resolve(
                a_parameter(dropdown_filters=[
                    from_object_property("region", "office", "region")]),
                bound={"office": "o-1"}, property_types={}, objects=held,
            )
        assert caught.value.parameter == "office"
        assert caught.value.property == "region", held


def test_an_object_property_filter_is_watched_like_a_parameter_one() -> None:
    """The value changes when the Office does, which is the whole point of it —
    so a form watching only the plain kind narrows once and then stops."""
    assert filters.referenced_parameters(a_parameter(dropdown_filters=[
        from_object_property("region", "office", "region")])) == ["office"]


def test_what_a_filter_reads_off_its_objects_is_named_for_the_caller() -> None:
    """What `object_values_of` loads before `resolve` can run.

    One entry per *parameter*, not per property: two filters reading two
    properties of the same Office are one object to read. And only the third
    kind — a plain parameter reference needs no object at all.
    """
    assert filters.object_parameters_read(a_parameter(dropdown_filters=[
        from_object_property("region", "office", "region"),
        from_object_property("tier", "office", "tier"),
        from_parameter("size", "where"),
        static("code", "x"),
    ])) == ["office"]


def test_a_filter_with_no_property_narrows_nothing_rather_than_everything() -> None:
    """**A document that predates the save-time refusal.**

    `check_filters` will not let one be written, so this is unreachable through
    the API — but `resolve` reads what is *stored*, and an ontology import
    (§326) or a hand-edited row can carry one. Compiling it would produce a
    filter on the empty property, which matches nothing, and a form would go
    blank for a reason nobody could see.

    Tested against the function rather than through the door a caller uses,
    because the door is the one thing that cannot deliver this input.
    """
    got = filters.resolve(
        a_parameter(dropdown_filters=[
            {"property": "", "values": [{"kind": "value", "value": "eu"}]},
            static("region", "eu"),
        ]),
        bound={}, property_types={},
    )
    assert [f.property for f in got] == ["region"]


def test_referenced_parameters_ignores_a_side_whose_kind_is_not_a_parameter() -> None:
    """**The third unit in a row to need this exact check** (§328, §329, here).

    Every side kind this build has either carries a `parameter` key or carries
    nothing, so the guard and "does it have a non-empty name" behave
    identically — until a document carries a kind this build does not have.

    **This test used to use `object_property` as that unknown kind, and §334
    implemented it.** Left as it was, the check would have kept passing while
    testing nothing: `object_property` is now watched on purpose, so the guard
    it was written to defend would have been deleted with the suite green. The
    kind here is p.90's "From a function", which `notifications.RECIPIENT_KINDS`
    names as the one Foundry offers and this platform does not — a kind that
    stays unknown because something real is missing, rather than because nobody
    has got to it yet.
    """
    assert filters.referenced_parameters(a_parameter(dropdown_filters=[{
        "property": "region",
        "values": [{"kind": "function", "parameter": "where",
                    "property": "region"}],
    }])) == []


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
    assert filters.for_reader(p, may_edit=False)["dropdown_filters"] == []


def test_an_editor_still_receives_the_filters() -> None:
    """The other half of "who is asking", at the layer that decides it.

    Without this the whole of `for_reader` could return an empty list and the
    redaction tests would all still pass.
    """
    p = a_parameter(dropdown_filters=[static("region", "eu")])
    assert filters.for_reader(p, may_edit=True)["dropdown_filters"] == [
        static("region", "eu")
    ]


def test_redaction_leaves_everything_else_alone() -> None:
    """A viewer still needs the parameter: its name, its type, and what it
    offers. Only the sentence that produced the offer goes."""
    p = a_parameter(display_name="Team", required=True,
                    dropdown_filters=[static("region", "eu")])
    redacted = filters.for_reader(p, may_edit=False)
    assert redacted["display_name"] == "Team"
    assert redacted["required"] is True
    assert redacted["api_name"] == "team"


def test_a_redacted_parameter_still_says_what_the_form_must_watch() -> None:
    """**§332, and the reason `redact` is not a function any more.**

    The redaction is for people who may not edit the action — which is everyone
    who *runs* it — and the form re-asks its dropdown when a watched value
    changes. §331 sent them no filters and no watch list, so p.36's "inferred
    from another parameter" was dead for exactly them: choose a region and the
    Team dropdown never notices. The names survive the redaction because they
    are not p.40's "property value combination"; they are parameters of an
    action this reader can already read in full.
    """
    p = a_parameter(dropdown_filters=[from_parameter("region", "where")])
    redacted = filters.for_reader(p, may_edit=False)
    assert redacted["dropdown_filters"] == []
    assert redacted["dropdown_watches"] == ["where"]


def test_an_editor_gets_the_same_watch_list() -> None:
    """One source for it, rather than one per role: the browser reads this
    field and never walks the filters, so an editor whose watch list came from
    somewhere else would be a second answer to the same question."""
    p = a_parameter(dropdown_filters=[from_parameter("region", "where")])
    assert filters.for_reader(p, may_edit=True)["dropdown_watches"] == ["where"]


# ---- the save-time refusals ---------------------------------------------------
#: What each *other* object parameter's type offers, for p.36's third kind.
#: `office` holds an Office; `where` is a string parameter and so is absent,
#: which is one of the refusals below.
#:
#: **Deliberately not the same set as the offered type's** (`region`, `tier`).
#: The first version made them identical and a sweep walked straight through
#: it: checking the property against the *filtered* type instead of the *read*
#: one behaved the same, because every name was in both. `site` is in the
#: Office and not in the Team, and `code` the other way round.
OBJECT_PROPERTIES = {"office": {"region", "site"}}


def check(parameter: dict, *, properties=("region", "tier", "code"),
          names=("team", "where", "office"), objects=OBJECT_PROPERTIES):
    filters.check_filters(
        parameter, declared_properties=set(properties),
        parameter_names=set(names), object_properties=objects,
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
    """A document carrying a kind this build lacks is told so rather than
    having the value quietly ignored — which would widen the filter's OR and
    offer exactly what it exists to exclude.

    p.90's "From a function" is the standing example, as it is for a notify
    rule's recipients: Foundry offers it and this platform has no Functions.
    (It was p.36's third kind until §334 built that one.)
    """
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[{
            "property": "region",
            "values": [{"kind": "function", "parameter": "where"}],
        }]))
    assert "function" in str(caught.value)


def test_an_object_property_filter_naming_a_string_parameter_is_refused() -> None:
    """p.36 says an *Object Reference* parameter. Reading a property off a
    string is not a thing that can be done, and the honest place to say so is
    the save rather than an empty dropdown."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[
            from_object_property("region", "where", "region")]))
    assert "not an object parameter with a declared type" in str(caught.value)


def test_an_object_property_filter_naming_an_untyped_parameter_is_refused() -> None:
    """Every object parameter written before §330 is in this state. There is no
    type to check the property against, so there is nothing to check — and
    `notifications.parse_notify`'s rule applies: a caller that has resolved no
    ontology has checked no property."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[
            from_object_property("region", "office", "region")]),
            objects={})
    assert "declared type" in str(caught.value)


def test_an_object_property_filter_reading_an_unknown_property_is_refused() -> None:
    """Checked against the *read* parameter's type, not the offered one — the
    two are different object types and the fixture makes them share property
    names so that confusing them would pass."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[
            from_object_property("region", "office", "no_such_property")]))
    assert "no_such_property" in str(caught.value)
    assert "office" in str(caught.value)


def test_an_object_property_filter_with_no_property_named_is_refused() -> None:
    """Half a rule. Compiled it would read `None` off the object and narrow to
    nothing, which is an empty dropdown for a reason nobody chose."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[{
            "property": "region",
            "values": [{"kind": "object_property", "parameter": "office"}],
        }]))
    assert "which of its properties" in str(caught.value)


def test_an_object_property_filter_reading_itself_is_refused() -> None:
    """The dropdown would read a property of the object it is offering."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[
            from_object_property("region", "team", "region")]))
    assert "itself" in str(caught.value)


def test_the_property_is_checked_against_the_read_type_not_the_filtered_one() -> None:
    """**Two object types, and the check must use the right one.**

    `site` is a property of the Office and not of the Team; `code` is the other
    way round. A version reading the filtered type's properties accepts the
    second and refuses the first, which is exactly backwards — and a fixture
    where both types offered the same names could not see it. A sweep found
    that fixture.
    """
    check(a_parameter(dropdown_filters=[
        from_object_property("region", "office", "site")]))
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_filters=[
            from_object_property("region", "office", "code")]))
    assert "code" in str(caught.value)


def test_a_legal_object_property_filter_is_not_refused() -> None:
    """Otherwise every refusal above passes for a rule that refuses the kind
    outright."""
    check(a_parameter(dropdown_filters=[
        from_object_property("region", "office", "region")]))


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


def test_effective_parameters_redacts_as_well(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**The third door** (§332).

    `effective-parameters` is `viewer`, returns the same `ActionParameterOut`,
    and is the endpoint the form calls most — and §331 left it unredacted while
    closing the other two. p.41 describes Foundry's residual leak as a filter
    visible in a network request; this build claimed not to have one, and did.
    """
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    r = client.post(
        f"{wbase(fx)}/action-types/{setup['action']}/effective-parameters",
        headers=hdr(fx.viewer_sub), json={"values": {}},
    )
    assert r.status_code == 200, r.text
    team = next(p for p in r.json() if p["api_name"] == "team")
    assert team["dropdown_filters"] == []


def test_effective_parameters_still_shows_an_editor_the_filters(
    client: TestClient, fx: Fixture, setup
) -> None:
    """Otherwise the fix above is "send nobody anything", which is a redaction
    the same way an unplugged screen is a permission model."""
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    r = client.post(
        f"{wbase(fx)}/action-types/{setup['action']}/effective-parameters",
        headers=hdr(fx.editor_sub), json={"values": {}},
    )
    assert r.status_code == 200, r.text
    team = next(p for p in r.json() if p["api_name"] == "team")
    assert team["dropdown_filters"] == [static("region", "eu")]


def test_a_viewer_is_told_which_box_the_dropdown_depends_on(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**What §331's redaction took away without replacing** (§332).

    The form re-asks `parameter-choices` when a watched value changes, and it
    learns which values those are from the parameter. Redacted, it learned
    none — so for every reader who cannot edit the action, p.36's "inferred
    from another parameter" was a dropdown that said "choose Region first" and
    then ignored the region.
    """
    define(client, fx, setup, [from_parameter("region", "where")]).raise_for_status()
    as_viewer = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                           headers=hdr(fx.viewer_sub)).json()
    team = next(p for p in as_viewer["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == []
    assert team["dropdown_watches"] == ["where"]


def test_a_static_filter_leaves_the_watch_list_empty(
    client: TestClient, fx: Fixture, setup
) -> None:
    """A form whose filters read nothing asks once, when it opens — so a watch
    list naming everything would be a round trip per keystroke on a screen
    whose dropdown cannot change."""
    define(client, fx, setup, [static("region", "eu")]).raise_for_status()
    as_viewer = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                           headers=hdr(fx.viewer_sub)).json()
    team = next(p for p in as_viewer["parameters"] if p["api_name"] == "team")
    assert team["dropdown_watches"] == []


def test_a_matching_object_past_the_dropdowns_cap_is_still_accepted(
    client: TestClient, fx: Fixture, setup
) -> None:
    """**§256's trap arriving through the back door** (found in §333, fixed
    here).

    §331 answered "is this value allowed" by evaluating the narrowed set at
    `MAX_CHOICES` and searching the result, so an object that matched the filter
    perfectly well but sat past the fiftieth was refused — the answer depended
    on how many the *control* can hold. The dropdown is a control and may
    truncate; the check is a rule and may not.

    The type is loaded with more than a page of matching objects and the last
    one is submitted. Nothing below an API test can see this: it is a fact about
    a limit and a result set.
    """
    tag = uuid.uuid4().hex[:8]
    many = a_type(
        client, fx, f"cap{tag}",
        [(f"o{n:03d}", "eu") for n in range(instance_store.INSTANCE_PAGE_SIZE + 5)],
    )
    r = client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": [
                  {"api_name": "where", "display_name": "Where",
                   "data_type": "string"},
                  {"api_name": "team", "display_name": "Team",
                   "data_type": "object", "object_type_id": many,
                   "dropdown_filters": [static("region", "eu")]},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "where"}}],
              "criteria": []},
    )
    assert r.status_code == 200, r.text

    shown = offered(client, fx, setup)["team"]
    assert shown["truncated"] is True, "the fixture must exceed the control's cap"
    offered_keys = {c["primary_key"] for c in shown["items"]}

    # Paged, because a listing is a page (§256) and this one caps at the same
    # number the dropdown does — the first page is exactly what was offered.
    rows = client.get(
        f"{wbase(fx)}/object-types/{many}/instances", headers=hdr(fx.editor_sub),
        params={"offset": instance_store.INSTANCE_PAGE_SIZE},
    ).json()["items"]
    beyond = next(r for r in rows if r["primary_key"] not in offered_keys)
    accepted = run(client, fx, setup, {"where": "x", "team": beyond["id"]})
    assert accepted.status_code == 200, accepted.text


# ---- p.36's third kind, with objects behind it (§334) ---------------------------
@pytest.fixture(scope="module")
def offices(client: TestClient, fx: Fixture, setup):
    """A second object type whose objects carry a region, so a filter can read
    one off the object somebody chose.

    Two offices in different regions, because with one the filter's value never
    changes and "reads the object" is indistinguishable from "happens to match".
    """
    tag = uuid.uuid4().hex[:8]
    office_type = a_type(client, fx, f"off{tag}", [("hq", "eu"), ("branch", "uk")])
    rows = client.get(f"{wbase(fx)}/object-types/{office_type}/instances",
                      headers=hdr(fx.editor_sub)).json()["items"]
    return {"type": office_type, "ids": {r["primary_key"]: r["id"] for r in rows}}


def define_with_office(client, fx, setup, offices, values, sub=None):
    return client.put(
        f"{wbase(fx)}/action-types/{setup['action']}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": [
                  {"api_name": "where", "display_name": "Where",
                   "data_type": "string"},
                  {"api_name": "office", "display_name": "Office",
                   "data_type": "object", "object_type_id": offices["type"]},
                  {"api_name": "team", "display_name": "Team",
                   "data_type": "object",
                   "object_type_id": setup["team_type"],
                   "dropdown_filters": [{"property": "region", "values": values}]},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "name", "parameter": "where"}}],
              "criteria": []},
    )


def a_read(name="office", of="region"):
    return [{"kind": "object_property", "parameter": name, "property": of}]


def test_the_dropdown_matches_a_property_of_the_chosen_object(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """**p.36's third kind, end to end.** Choose the EU office and the Teams
    offered are the EU ones — a value nobody typed and no parameter holds."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    shown = offered(client, fx, setup, {"office": offices["ids"]["hq"]})["team"]
    assert {c["primary_key"] for c in shown["items"]} == {"alpha"}


def test_choosing_a_different_object_changes_the_dropdown(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """A filter that read the object once and then stopped would pass the test
    above and fail this one."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    shown = offered(client, fx, setup, {"office": offices["ids"]["branch"]})["team"]
    assert {c["primary_key"] for c in shown["items"]} == {"beta"}


def test_before_the_object_is_chosen_the_form_is_told_which_box(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    shown = offered(client, fx, setup)["team"]
    assert shown["items"] == []
    assert shown["waiting_for"] == "office"
    assert shown["waiting_for_property"] is None


def test_an_object_with_nothing_under_that_property_names_the_property(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """**The two empty states, told apart** (§334). The box is filled in, so
    "choose the Office first" would be false; what is missing is the property,
    and the response says which one so the form can say so too."""
    tag = uuid.uuid4().hex[:8]
    blank_type = a_type(client, fx, f"blk{tag}", [("nowhere", "")])
    rows = client.get(f"{wbase(fx)}/object-types/{blank_type}/instances",
                      headers=hdr(fx.editor_sub)).json()["items"]
    define_with_office(
        client, fx, setup, {"type": blank_type}, a_read(),
    ).raise_for_status()
    shown = offered(client, fx, setup, {"office": rows[0]["id"]})["team"]
    assert shown["items"] == []
    assert shown["waiting_for"] == "office"
    assert shown["waiting_for_property"] == "region"


def test_a_submission_outside_the_read_property_is_refused(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """p.34's second sentence with p.36's third kind in it. A dropdown narrowed
    to the EU teams beside a check that accepts a UK one is §214's control that
    looks like it works."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    teams = client.get(
        f"{wbase(fx)}/object-types/{setup['team_type']}/instances",
        headers=hdr(fx.editor_sub)).json()["items"]
    beta = next(t for t in teams if t["primary_key"] == "beta")
    refused = run(client, fx, setup, {
        "where": "x", "office": offices["ids"]["hq"], "team": beta["id"],
    })
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_submission_inside_the_read_property_is_accepted(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """Without this the refusal above passes for a check that refuses
    everything."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    teams = client.get(
        f"{wbase(fx)}/object-types/{setup['team_type']}/instances",
        headers=hdr(fx.editor_sub)).json()["items"]
    alpha = next(t for t in teams if t["primary_key"] == "alpha")
    ok = run(client, fx, setup, {
        "where": "x", "office": offices["ids"]["hq"], "team": alpha["id"],
    })
    assert ok.status_code == 200, ok.text


def test_a_submission_that_does_not_supply_the_read_object_is_refused(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """**Fails closed.** Whether this team is in the set is a question nobody
    can answer without the office."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    teams = client.get(
        f"{wbase(fx)}/object-types/{setup['team_type']}/instances",
        headers=hdr(fx.editor_sub)).json()["items"]
    alpha = next(t for t in teams if t["primary_key"] == "alpha")
    refused = run(client, fx, setup, {"where": "x", "team": alpha["id"]})
    assert refused.status_code == 422, refused.text
    assert "office" in refused.text


def test_a_viewer_is_told_to_watch_the_object_parameter(
    client: TestClient, fx: Fixture, setup, offices
) -> None:
    """§332's rule with p.36's third kind under it: the filter is redacted and
    the parameter it reads is not, because a form told nothing re-asks
    nothing."""
    define_with_office(client, fx, setup, offices, a_read()).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{setup['action']}",
                      headers=hdr(fx.viewer_sub)).json()
    team = next(p for p in read["parameters"] if p["api_name"] == "team")
    assert team["dropdown_filters"] == []
    assert team["dropdown_watches"] == ["office"]
