"""Where an object dropdown's objects come from (§333; db 0085;
`action-types` p.34, p.36-37).

    "A Search Around would create a new set by traversing a link on every
     object in the current set. For example, `Github Issue of Current Employee`
     would take the `Employees` in the current set and create a resulting set
     of `Github Issues` linked to those `Employees`." (p.37)

**Two claims, and the file is split along them.** The walk joins up or it does
not, which is decided without a database against a dictionary of link types;
and the objects it reaches are the objects offered *and* the only ones a
submission may name, which needs real instances on both sides of a real link.

p.34's second sentence is the one worth being careful about here. A dropdown
narrowed by a walk beside a check that accepts any object of the type is §214's
control that looks like it works — with the extra insult of having offered the
value it then rejects — so every test that narrows a list also submits.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.services import action_search_arounds as around  # noqa: E402
from src.services import action_filters as filters  # noqa: E402
from src.services import object_sets  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402

EMPLOYEE = "11111111-1111-1111-1111-111111111111"
ISSUE = "22222222-2222-2222-2222-222222222222"
REPO = "33333333-3333-3333-3333-333333333333"
WORKS_ON = "aaaaaaaa-0000-0000-0000-000000000001"
BELONGS_TO = "aaaaaaaa-0000-0000-0000-000000000002"

#: p.37's own example, as this platform's link rows: an issue holds the id of
#: the employee it belongs to, and a repo the issue belongs to.
LINKS = {
    WORKS_ON: {
        "id": WORKS_ON, "display_name": "Raised by",
        "from_object_type_id": ISSUE, "to_object_type_id": EMPLOYEE,
        "from_property": "employee_id", "to_property": "$primary_key",
        "cardinality": "one_to_many",
    },
    BELONGS_TO: {
        "id": BELONGS_TO, "display_name": "In repo",
        "from_object_type_id": ISSUE, "to_object_type_id": REPO,
        "from_property": "repo_id", "to_property": "$primary_key",
        "cardinality": "one_to_many",
    },
}
TYPES = {EMPLOYEE, ISSUE, REPO}


def a_parameter(**over) -> dict:
    return {"api_name": "issue", "data_type": "object",
            "object_type_id": ISSUE, "dropdown_filters": [], **over}


def an_employee_parameter(**over) -> dict:
    return {"api_name": "who", "data_type": "object",
            "object_type_id": EMPLOYEE, **over}


def source(start: dict, *hops: str) -> dict:
    return {"start": start, "hops": [{"link_type_id": h} for h in hops]}


def from_type(type_id: str = EMPLOYEE) -> dict:
    return {"kind": "object_type", "object_type_id": type_id}


def from_parameter(name: str = "who", type_id: str = EMPLOYEE) -> dict:
    return {"kind": "parameter", "object_type_id": type_id, "parameter": name}


def check(parameter, *, parameters=None, types=TYPES):
    return around.check_source(
        parameter,
        object_type_id=parameter.get("object_type_id"),
        link_types=LINKS, object_type_ids=set(types),
        parameters=parameters or [parameter, an_employee_parameter()],
    )


# ---- p.36-37's walk, decided without a database ---------------------------------
def test_no_source_is_p36s_default() -> None:
    """Every parameter written before db 0085, and every one whose panel
    nobody has opened. `None` rather than an empty document, so "the default"
    is a thing the column says rather than a shape a reader has to interpret."""
    assert around.source_of(a_parameter()) is None
    assert around.source_of(a_parameter(dropdown_search_around={})) is None
    assert check(a_parameter()) is None


def test_a_walk_lands_where_the_parameter_holds() -> None:
    """p.37's example, joined up: start at Employees, follow the link an Issue
    holds, arrive at Issues — which is what `issue` is declared to hold."""
    got = check(a_parameter(dropdown_search_around=source(from_type(), WORKS_ON)))
    assert got == {
        "start": {"kind": "object_type", "object_type_id": EMPLOYEE},
        "hops": [{"link_type_id": WORKS_ON, "far_type_id": ISSUE}],
    }


def test_the_landing_type_is_answered_rather_than_trusted() -> None:
    """The same arrangement `derived_properties.parse` uses: the walk decides
    where it lands, and a caller's `far_type_id` comes back replaced by the
    answer. Without this, read-modify-write is impossible — a client would have
    to know which fields to strip before saving."""
    got = check(a_parameter(dropdown_search_around={
        "start": from_type(),
        "hops": [{"link_type_id": WORKS_ON, "far_type_id": ISSUE}],
    }))
    assert got["hops"] == [{"link_type_id": WORKS_ON, "far_type_id": ISSUE}]


def test_a_hop_declaring_the_wrong_landing_is_refused() -> None:
    """Accepted back, never trusted — §156's refusal for a traversal's
    link/landing pair, one document over."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around={
            "start": from_type(),
            "hops": [{"link_type_id": WORKS_ON, "far_type_id": REPO}],
        }))
    assert "declares" in str(caught.value)


def test_a_walk_that_lands_elsewhere_is_refused() -> None:
    """**The refusal the whole check exists for.**

    A walk to Repos on a parameter that holds Issues offers objects the
    parameter cannot hold, and p.34's own validation refuses every one of them
    a moment after somebody picks one.
    """
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(from_type(REPO))))
    assert "lands on a different object type" in str(caught.value)


def test_a_link_that_does_not_touch_the_walk_is_refused() -> None:
    """"Your definition is wrong" and "there are no matches" look identical in
    an empty dropdown, so the first is said out loud."""
    with pytest.raises(ValueError) as caught:
        # Repos and Employees share no link, so this hop cannot be taken.
        check(a_parameter(dropdown_search_around=source(from_type(REPO), WORKS_ON)))
    assert "does not touch" in str(caught.value)


def test_a_link_with_no_join_is_refused() -> None:
    """db 0027 lets a link type be defined and not traversable. There is
    nothing to follow, so there is nothing to offer."""
    unjoinable = {
        **LINKS,
        WORKS_ON: {**LINKS[WORKS_ON], "from_property": "", "to_property": ""},
    }
    with pytest.raises(ValueError) as caught:
        around.check_source(
            a_parameter(dropdown_search_around=source(from_type(), WORKS_ON)),
            object_type_id=ISSUE, link_types=unjoinable,
            object_type_ids=TYPES, parameters=[a_parameter()],
        )
    assert "no join" in str(caught.value)


def test_a_chain_longer_than_the_set_limit_is_refused() -> None:
    """`object_sets.MAX_TRAVERSALS`, not a second number: every hop becomes a
    `Traversal`, and `parse` refuses a deeper set anyway — so a larger cap here
    would be a promise overruled one call down."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(
            from_type(), WORKS_ON, BELONGS_TO, WORKS_ON, BELONGS_TO)))
    assert str(around.MAX_HOPS) in str(caught.value)
    assert around.MAX_HOPS == object_sets.MAX_TRAVERSALS


def test_a_start_this_workspace_does_not_have_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        around.check_source(
            a_parameter(dropdown_search_around=source(from_type(), WORKS_ON)),
            object_type_id=ISSUE, link_types=LINKS,
            object_type_ids={ISSUE, REPO}, parameters=[a_parameter()],
        )
    assert "does not have" in str(caught.value)


def test_a_search_around_on_an_untyped_parameter_is_refused() -> None:
    """A walk needs to know where it is meant to land, and §330's column is the
    only thing that says so."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(object_type_id=None,
                          dropdown_search_around=source(from_type(), WORKS_ON)))
    assert "where it is meant to land" in str(caught.value)


def test_an_unknown_start_kind_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(
            {"kind": "object_set", "object_type_id": EMPLOYEE}, WORKS_ON)))
    assert "object_type or parameter" in str(caught.value)


def test_an_unknown_option_is_refused() -> None:
    """A key nobody validated is a key `build` would read."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around={
            "start": from_type(), "hops": [{"link_type_id": WORKS_ON}],
            "order_by": "name",
        }))
    assert "order_by" in str(caught.value)


def test_the_normalised_document_drops_a_key_nobody_checked() -> None:
    """Rebuilt field by field rather than echoed. A start that carried an extra
    key would be stored and read back by `build`, which is how a setting nobody
    validated ends up deciding something."""
    got = check(a_parameter(dropdown_search_around={
        "start": {**from_type(), "sneaky": "yes"},
        "hops": [{"link_type_id": WORKS_ON}],
    }))
    assert got["start"] == {"kind": "object_type", "object_type_id": EMPLOYEE}


# ---- p.36's parameter start -----------------------------------------------------
def test_a_start_may_read_another_parameter() -> None:
    """p.36: "The starting set could also be set to an ObjectReference…
    parameter", which is what makes p.37's "of Current Employee" writable."""
    got = check(a_parameter(dropdown_search_around=source(
        from_parameter(), WORKS_ON)))
    assert got["start"] == {
        "kind": "parameter", "object_type_id": EMPLOYEE, "parameter": "who",
    }


def test_a_start_reading_itself_is_refused() -> None:
    """The dropdown would walk from the value it is offering."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(
            from_parameter("issue", ISSUE))))
    assert "itself" in str(caught.value)


def test_a_start_reading_a_parameter_that_is_not_declared_is_refused() -> None:
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(
            from_parameter("nobody"), WORKS_ON)))
    assert "nobody" in str(caught.value)


def test_a_start_reading_a_string_parameter_is_refused() -> None:
    """p.36 says an *ObjectReference* parameter. Starting from a string would
    treat whatever somebody typed as an object's key, and the dropdown would be
    empty for every value but one."""
    with pytest.raises(ValueError) as caught:
        check(
            a_parameter(dropdown_search_around=source(from_parameter("note"), WORKS_ON)),
            parameters=[a_parameter(), {"api_name": "note", "data_type": "string"}],
        )
    assert "rather than an object" in str(caught.value)


def test_a_start_walking_from_a_type_the_parameter_does_not_hold_is_refused() -> None:
    """The `who` parameter holds Employees; a start claiming to walk from Repos
    would build a set rooted at an object of the wrong type."""
    with pytest.raises(ValueError) as caught:
        check(a_parameter(dropdown_search_around=source(
            from_parameter("who", REPO), WORKS_ON)))
    assert "different object type than" in str(caught.value)


def test_the_start_parameter_is_what_the_form_watches() -> None:
    """Change the employee and the issues change, so the form re-asks — the
    same list §331's filters contribute to and §332 sends to every reader."""
    assert around.referenced_parameters(a_parameter(
        dropdown_search_around=source(from_parameter(), WORKS_ON))) == ["who"]


def test_a_start_whose_kind_is_not_a_parameter_is_not_watched() -> None:
    """**The seventh time this exact check has been needed** (§328, §329, §331
    twice, §332, and here), and the sweep found it again.

    Every start kind this build has either carries a `parameter` key or carries
    nothing, so the guard and "does it have a non-empty name" behave
    identically — until a document carries a kind this build does not have,
    which p.36's ObjectReference *list* parameter will be the day it arrives or
    an ontology import (§326) brings one. The value below is the only input that
    tells the two apart: an unknown kind that *does* name a parameter.
    """
    assert around.referenced_parameters(a_parameter(dropdown_search_around={
        "start": {"kind": "object_set", "object_type_id": EMPLOYEE,
                  "parameter": "who"},
        "hops": [{"link_type_id": WORKS_ON}],
    })) == []


def test_a_type_start_watches_nothing() -> None:
    """A dropdown that cannot change asks once, when the form opens."""
    assert around.referenced_parameters(a_parameter(
        dropdown_search_around=source(from_type(), WORKS_ON))) == []


def test_the_watch_list_carries_both_the_filters_and_the_start() -> None:
    """Two rules narrow one dropdown and either can move it, so a form told
    about one of them re-asks half the time."""
    p = a_parameter(
        dropdown_filters=[{"property": "state",
                           "values": [{"kind": "parameter", "parameter": "state"}]}],
        dropdown_search_around=source(from_parameter(), WORKS_ON),
    )
    assert filters.for_reader(p, may_edit=False)["dropdown_watches"] == [
        "state", "who",
    ]


def test_a_viewer_does_not_receive_the_walk() -> None:
    """p.40's combination is not only about values: "somebody is offering the
    Documents linked to this Investigation" names two object types and a link,
    and a reader who may not edit the action is told none of them."""
    p = a_parameter(dropdown_search_around=source(from_parameter(), WORKS_ON))
    assert filters.for_reader(p, may_edit=False)["dropdown_search_around"] is None
    assert filters.for_reader(p, may_edit=True)["dropdown_search_around"] is not None


# ---- compiling into an object set -----------------------------------------------
def test_no_source_compiles_to_the_plain_type() -> None:
    built = around.build(
        a_parameter(), object_type_id=uuid.UUID(ISSUE), filters=(),
    )
    assert built.via is None
    assert str(built.object_type_id) == ISSUE


def test_a_hop_becomes_a_traversal_from_the_start() -> None:
    """`Traversal` has been the shape of a hop since §155 and
    `object_set_eval.resolve_traversal` has evaluated one against both stores
    since then. p.37 asks for nothing that is not already there."""
    built = around.build(
        a_parameter(dropdown_search_around=source(from_type(), WORKS_ON)),
        object_type_id=uuid.UUID(ISSUE), filters=(),
    )
    assert str(built.object_type_id) == ISSUE
    assert built.via is not None
    assert str(built.via.link_type_id) == WORKS_ON
    assert str(built.via.base.object_type_id) == EMPLOYEE
    assert built.via.base.via is None


def test_two_hops_nest_in_the_order_they_are_walked() -> None:
    """Issues in a repo, raised by nobody in particular: Repo → Issue is one
    hop, and a second would nest under it. Depth is what
    `object_sets.MAX_TRAVERSALS` counts, so getting the nesting backwards would
    still be three."""
    built = around.build(
        a_parameter(object_type_id=EMPLOYEE, dropdown_search_around={
            "start": from_type(REPO),
            "hops": [{"link_type_id": BELONGS_TO, "far_type_id": ISSUE},
                     {"link_type_id": WORKS_ON, "far_type_id": EMPLOYEE}],
        }),
        object_type_id=uuid.UUID(EMPLOYEE), filters=(),
    )
    assert built.depth == 2
    assert str(built.object_type_id) == EMPLOYEE
    assert str(built.via.base.object_type_id) == ISSUE
    assert str(built.via.base.via.base.object_type_id) == REPO


def test_the_filters_land_on_the_result_rather_than_the_start() -> None:
    """p.34's sentence in its own order: "filters and Search Arounds to limit
    the objects that show up", and what shows up is the far end. A filter on the
    starting set would be filtering Employees by a property of an Issue."""
    narrowing = (object_sets.Filter(property="state", op="in", value=["open"]),)
    built = around.build(
        a_parameter(dropdown_search_around=source(from_type(), WORKS_ON)),
        object_type_id=uuid.UUID(ISSUE), filters=narrowing,
    )
    assert built.filters == narrowing
    assert built.via.base.filters == ()


def test_a_parameter_start_roots_the_set_at_one_object() -> None:
    """p.37's "of Current Employee". §155 built `PRIMARY_KEY_FILTER` for
    exactly this shape — a chain rooted at one object — with the value coming
    off a row being read rather than out of a form."""
    built = around.build(
        a_parameter(dropdown_search_around=source(from_parameter(), WORKS_ON)),
        object_type_id=uuid.UUID(ISSUE), filters=(), start_key="E1",
    )
    [rooted] = built.via.base.filters
    assert (rooted.property, rooted.op, rooted.value) == (
        object_sets.PRIMARY_KEY_FILTER, "eq", "E1",
    )


def test_a_parameter_start_nobody_has_filled_in_is_unresolved() -> None:
    """**The same exception a filter raises**, because the two are the same
    thing to a caller: the dropdown is empty and the form says which box comes
    first. Two exception types would be two `except` clauses, free to drift
    into treating one as empty and the other as an error."""
    for empty in (None, ""):
        with pytest.raises(filters.Unresolved) as caught:
            around.build(
                a_parameter(dropdown_search_around=source(
                    from_parameter(), WORKS_ON)),
                object_type_id=uuid.UUID(ISSUE), filters=(), start_key=empty,
            )
        assert caught.value.parameter == "who"


def test_a_start_with_no_hops_is_just_that_type() -> None:
    """p.36's "changed to any other type" with nothing to walk. `check_source`
    only allows it when that type is the one the parameter holds, so this is
    the default written the long way — and it must still carry the filters."""
    narrowing = (object_sets.Filter(property="state", op="in", value=["open"]),)
    built = around.build(
        a_parameter(dropdown_search_around=source(from_type(ISSUE))),
        object_type_id=uuid.UUID(ISSUE), filters=narrowing,
    )
    assert built.via is None
    assert built.filters == narrowing


# ---- through the API, with objects on both sides of a link ----------------------
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


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """p.37's example, built for real: employees, the issues raised by them,
    and a ticket for the action to act on.

    **Two employees with two issues each**, because a walk that ignored its
    base set would return all four and a fixture with one employee could not
    tell that apart from working.
    """
    import io
    tag = uuid.uuid4().hex[:6]

    def a_type(api_name: str, properties: list[str], *, title: str | None = None):
        made = client.post(
            f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{api_name}_{tag}", "display_name": f"{api_name} {tag}",
                  **({"title_property": title} if title else {}),
                  "properties": [{"api_name": p, "data_type": "string"}
                                 for p in properties]},
        )
        assert made.status_code == 201, made.text
        return made.json()["id"]

    def load(name: str, csv: str, type_id: str, mappings: dict) -> None:
        dataset = client.post(
            f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
            files={"file": (f"{name}.csv", io.BytesIO(csv.encode()), "text/csv")},
            data={"name": f"{name}_{tag}"},
        )
        assert dataset.status_code == 201, dataset.text
        made = client.post(
            f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
            json={"object_type_id": type_id, "dataset_id": dataset.json()["id"],
                  "primary_key_column": "id", "column_mappings": mappings},
        )
        assert made.status_code == 201, made.text
        synced = client.post(
            f"{pbase(fx)}/object-type-sources/{made.json()['id']}/sync",
            headers=hdr(fx.editor_sub), json={},
        )
        assert synced.status_code == 200, synced.text

    employee = a_type("emp", ["name"], title="name")
    issue = a_type("iss", ["employee_id", "title", "state"], title="title")
    ticket = a_type("tkt", ["note"])
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"raised_by_{tag}", "display_name": "Raised by",
              "from_type_id": issue, "to_type_id": employee,
              "cardinality": "one_to_many",
              "from_property": "employee_id", "to_property": "$primary_key"},
    )
    assert link.status_code == 201, link.text

    load("emps", "id,name\nE1,Ada\nE2,Grace\n", employee, {"name": "name"})
    load(
        "isss",
        "id,employee_id,title,state\n"
        "I1,E1,Ada one,open\nI2,E1,Ada two,closed\n"
        "I3,E2,Grace one,open\nI4,E2,Grace two,open\n",
        issue,
        {"employee_id": "employee_id", "title": "title", "state": "state"},
    )
    load("tkts", "id,note\nT1,\n", ticket, {"note": "note"})

    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket, "api_name": f"assign_{tag}",
              "display_name": "Assign", "editable_properties": ["note"]},
    )
    assert action.status_code == 201, action.text

    def ids_of(type_id: str) -> dict[str, str]:
        rows = client.get(f"{wbase(fx)}/object-types/{type_id}/instances",
                          headers=hdr(fx.editor_sub)).json()["items"]
        return {r["primary_key"]: r["id"] for r in rows}

    return {"action": action.json()["id"], "employee": employee, "issue": issue,
            "link": link.json()["id"], "employees": ids_of(employee),
            "issues": ids_of(issue), "ticket": next(iter(ids_of(ticket).values()))}


def define(client, fx, world, *, search_around, dropdown_filters=None, sub=None):
    return client.put(
        f"{wbase(fx)}/action-types/{world['action']}/definition",
        headers=hdr(sub or fx.editor_sub),
        json={"parameters": [
                  {"api_name": "who", "display_name": "Who", "data_type": "object",
                   "object_type_id": world["employee"]},
                  {"api_name": "issue", "display_name": "Issue",
                   "data_type": "object", "object_type_id": world["issue"],
                   "dropdown_filters": dropdown_filters or [],
                   "dropdown_search_around": search_around},
              ],
              "rules": [{"kind": "modify_object",
                         "config": {"property": "note", "parameter": "issue"}}],
              "criteria": []},
    )


def offered(client, fx, world, values=None, sub=None):
    r = client.post(
        f"{wbase(fx)}/action-types/{world['action']}/parameter-choices",
        headers=hdr(sub or fx.viewer_sub), json={"values": values or {}},
    )
    assert r.status_code == 200, r.text
    return {c["parameter"]: c for c in r.json()}


def run(client, fx, world, values, sub=None):
    return client.post(
        f"{pbase(fx)}/actions/{world['action']}/execute",
        headers=hdr(sub or fx.editor_sub),
        json={"instance_id": world["ticket"], "values": values},
    )


def a_walk(world, start_kind="parameter"):
    start = {"kind": start_kind, "object_type_id": world["employee"]}
    if start_kind == "parameter":
        start["parameter"] = "who"
    return {"start": start, "hops": [{"link_type_id": world["link"]}]}


def test_the_dropdown_offers_only_what_the_walk_reaches(client, fx, world) -> None:
    """**p.37's sentence, with objects behind it.** Ada's issues, not Grace's —
    and the second half is what a one-employee fixture could not ask."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    shown = offered(client, fx, world,
                    {"who": world["employees"]["E1"]})["issue"]
    keys = {c["primary_key"] for c in shown["items"]}
    assert keys == {"I1", "I2"}, shown


def test_changing_the_start_changes_what_is_offered(client, fx, world) -> None:
    """A walk that narrowed once and then ignored its base set would pass the
    test above and fail this one."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    keys = {c["primary_key"] for c in
            offered(client, fx, world, {"who": world["employees"]["E2"]})["issue"]["items"]}
    assert keys == {"I3", "I4"}


def test_an_unfilled_start_offers_nothing_and_names_the_box(client, fx, world) -> None:
    """p.37's example before the employee is chosen. Offering every issue would
    offer exactly the ones the walk exists to exclude, and the submission would
    be refused a moment later."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    shown = offered(client, fx, world)["issue"]
    assert shown["items"] == []
    assert shown["waiting_for"] == "who"


def test_a_walk_whose_start_reaches_nothing_offers_nothing(
    client: TestClient, fx: Fixture, world
) -> None:
    """**The silent widening decision 0002 exists to remove**, found by sweep.

    When the set below a hop has no members there is nothing to join against,
    and an unfiltered read of the far type would offer *every* issue — the exact
    opposite of what a walk narrowing to none means, in front of somebody who
    would have no way to tell. The start here names an employee that does not
    exist, which is the state a form is in whenever somebody's chosen object has
    since been deleted.

    Not the same as `waiting_for`: that box is filled in, so nothing is waiting.
    """
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    shown = offered(client, fx, world, {"who": str(uuid.uuid4())})["issue"]
    assert shown["items"] == []
    assert shown["waiting_for"] is None


def test_the_filters_narrow_what_the_walk_reached(client, fx, world) -> None:
    """p.34's "filters **and** Search Arounds": both narrow, and they compose —
    Ada's *open* issues is one of them, not the other."""
    define(
        client, fx, world, search_around=a_walk(world),
        dropdown_filters=[{"property": "state",
                           "values": [{"kind": "value", "value": "open"}]}],
    ).raise_for_status()
    keys = {c["primary_key"] for c in
            offered(client, fx, world, {"who": world["employees"]["E1"]})["issue"]["items"]}
    assert keys == {"I1"}


def test_a_submission_outside_the_walk_is_refused(client, fx, world) -> None:
    """**p.34's second sentence, which is the rule rather than the
    convenience.** A dropdown narrowed to Ada's issues beside a check that
    accepts any issue is §214's control that looks like it works."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    refused = run(client, fx, world, {
        "who": world["employees"]["E1"], "issue": world["issues"]["I3"],
    })
    assert refused.status_code == 422, refused.text
    assert "offers" in refused.text


def test_a_submission_inside_the_walk_is_accepted(client, fx, world) -> None:
    """Without this the refusal above passes for a check that refuses
    everything."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    ok = run(client, fx, world, {
        "who": world["employees"]["E1"], "issue": world["issues"]["I1"],
    })
    assert ok.status_code == 200, ok.text


def test_a_submission_that_does_not_supply_the_start_is_refused(
    client, fx, world
) -> None:
    """**Fails closed.** Whether this issue is in the set is a question nobody
    can answer without the employee, and accepting on an unanswered question is
    how a value the walk exists to exclude gets written."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    refused = run(client, fx, world, {"issue": world["issues"]["I1"]})
    assert refused.status_code == 422, refused.text
    assert "who" in refused.text


def test_a_walk_that_lands_elsewhere_is_refused_at_save_time(
    client, fx, world
) -> None:
    """Through the door a caller actually uses, not only against the function:
    the 422 is what an editor sees, and the message names the mismatch."""
    bad = define(client, fx, world, search_around={
        "start": {"kind": "object_type", "object_type_id": world["employee"]},
        "hops": [],
    })
    assert bad.status_code == 422, bad.text
    assert "lands on a different object type" in bad.text


def test_the_saved_walk_comes_back_with_its_landing_types(
    client, fx, world
) -> None:
    """Read-modify-write: what the editor saved is what it can send again."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{world['action']}",
                      headers=hdr(fx.editor_sub)).json()
    issue = next(p for p in read["parameters"] if p["api_name"] == "issue")
    assert issue["dropdown_search_around"] == {
        "start": {"kind": "parameter", "object_type_id": world["employee"],
                  "parameter": "who"},
        "hops": [{"link_type_id": world["link"], "far_type_id": world["issue"]}],
    }
    again = define(client, fx, world,
                   search_around=issue["dropdown_search_around"])
    assert again.status_code == 200, again.text


def test_a_viewer_is_told_to_watch_the_start(client, fx, world) -> None:
    """§332's rule with §333's second source in it: the walk is redacted and
    the name it reads is not, because a form told nothing re-asks nothing."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    read = client.get(f"{wbase(fx)}/action-types/{world['action']}",
                      headers=hdr(fx.viewer_sub)).json()
    issue = next(p for p in read["parameters"] if p["api_name"] == "issue")
    assert issue["dropdown_search_around"] is None
    assert issue["dropdown_watches"] == ["who"]


def test_a_viewer_still_gets_the_walked_dropdown(client, fx, world) -> None:
    """The redaction costs them nothing: the form asks for the resulting
    objects and never for the walk."""
    define(client, fx, world, search_around=a_walk(world)).raise_for_status()
    keys = {c["primary_key"] for c in offered(
        client, fx, world, {"who": world["employees"]["E1"]}, sub=fx.viewer_sub,
    )["issue"]["items"]}
    assert keys == {"I1", "I2"}
