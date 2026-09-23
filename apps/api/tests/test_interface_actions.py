"""An action type whose subject is an interface (`action-types` p.59-65; db
0101; §451).

> "You can use interface action rules whenever the edits can apply to all the
> object types that implement the interface. In other words, you can use
> interface action rules only to modify the interface shared properties or to
> delete objects." (p.59)

> "Actions created with interface action rules can be applied to objects whose
> object type implements the interface, just like any object-specific action
> type. For a given object, all object-type-specific and interface-based
> actions that can be applied to that object will appear in the action
> dropdown." (p.64)

**The design this file is really about is that there is only one executor.**
An interface action's rules name the interface's shared properties; every
implementation already says which of its own properties those are
(`object_type_interfaces.property_mapping`), so running one against a concrete
object is a *rename* and everything after it — coercion, required and
constraint checks, edit-only, the dataset write, the revert — is the path
object actions already take. A second executor would be a second set of
refusals to keep in step (§292), and p.64's "just like any object-specific
action type" is the page asking for exactly that.

So the tests split in two: the pure rename, which has no database in it, and
the cases where one implementation cannot keep the interface's promise —
which p.59 and p.62 both describe and which can only be found at submission.
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
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import actions as actions_service  # noqa: E402


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


# ---- the rename, with no database in it -------------------------------------
def rule(prop: str, parameter: str, **extra) -> dict:
    return {"kind": "modify_object",
            "config": {"property": prop, "parameter": parameter, **extra}}


def test_a_rule_is_rewritten_into_the_types_own_vocabulary() -> None:
    """p.59's whole mechanism in one line: the interface says
    `last_inspection_date`, this type calls it `surveyed_on`, and the rule that
    reaches the executor says the second."""
    out = actions_service.rules_for_implementation(
        [rule("last_inspection_date", "when")],
        mapping={"last_inspection_date": "surveyed_on"},
        interface_name="Inspectable", type_name="Facility",
    )
    assert out[0]["config"]["property"] == "surveyed_on"
    # The parameter keeps its name: it is the *action's* vocabulary, which is
    # the interface's, and the submitted values are keyed by it.
    assert out[0]["config"]["parameter"] == "when"


def test_the_rules_it_was_given_are_not_changed() -> None:
    """A rename that mutated its input would rewrite the action type itself —
    and `get_action_type` caches nothing, so the damage would be one request's
    and invisible in the next. The executor hands these straight from the read.
    """
    original = [rule("last_inspection_date", "when")]
    actions_service.rules_for_implementation(
        original, mapping={"last_inspection_date": "surveyed_on"},
        interface_name="Inspectable", type_name="Facility",
    )
    assert original[0]["config"]["property"] == "last_inspection_date"


def test_a_rule_naming_another_object_type_is_left_alone() -> None:
    """Its property is already that type's own — the interface has nothing to
    do with it — so translating it would rename a word that was never in the
    interface's vocabulary."""
    other = rule("status", "s", object_type=str(uuid.uuid4()))
    out = actions_service.rules_for_implementation(
        [other], mapping={"status": "renamed"},
        interface_name="Inspectable", type_name="Facility",
    )
    assert out[0]["config"]["property"] == "status"


def test_a_rule_that_is_not_a_modify_is_left_alone() -> None:
    """p.62 allows a delete on an interface, and a delete names no property.
    A rename that tried to translate one would be reading a key that is not
    there."""
    deletion = {"kind": "delete_object", "config": {"object": "target"}}
    out = actions_service.rules_for_implementation(
        [deletion], mapping={},
        interface_name="Inspectable", type_name="Facility",
    )
    assert out == [deletion]


def test_a_property_this_type_maps_nothing_to_is_refused() -> None:
    """**The case p.59's sentence exists to prevent**, and the one that can
    only be caught here.

    An interface's *optional* property may be left unmapped
    (`check_implementation` says so). An action writing one therefore has
    nothing to write on this type — and dropping it silently would make one
    submission change different things depending on which object it ran
    against, which is the opposite of "the edits apply to all the object types
    that implement the interface".
    """
    with pytest.raises(actions_service.InterfaceSubjectError) as excinfo:
        actions_service.rules_for_implementation(
            [rule("inspection_status", "how")],
            mapping={"last_inspection_date": "surveyed_on"},
            interface_name="Inspectable", type_name="Facility",
        )
    # Both names, because neither alone says what to do about it.
    assert "Facility" in str(excinfo.value)
    assert "inspection_status" in str(excinfo.value)


# ---- p.62's primary key, which is about every action type -------------------
def test_writing_the_column_an_object_is_identified_by_is_refused() -> None:
    """p.62: "primary key values cannot be modified by any action type."

    **Not a rule about interfaces**, though p.62 raises it there — an interface
    action is where nobody can see it coming, because each implementation
    decides which of its own columns a shared property is. The refusal names
    the column, since that is the thing the writer has to change.
    """
    with pytest.raises(actions_service.InterfaceSubjectError) as excinfo:
        actions_service.check_primary_key_writes(
            {"code": "new"},
            column_mappings={"code": "facility_code"},
            primary_key_column="facility_code",
            type_name="Facility",
        )
    assert "facility_code" in str(excinfo.value)


def test_writing_any_other_column_is_not() -> None:
    """The half that makes the check a check: a property mapped to an ordinary
    column passes, and one mapped to no column at all (p.113's edit-only) is
    not compared against the key."""
    actions_service.check_primary_key_writes(
        {"status": "open", "note": "edit only"},
        column_mappings={"status": "status_col"},
        primary_key_column="facility_code",
        type_name="Facility",
    )


# ---- the whole path, against the database -----------------------------------
INSPECTABLE = [
    {"api_name": "last_inspection_date", "display_name": "Last inspection",
     "data_type": "string", "required": True},
    {"api_name": "inspection_status", "display_name": "Inspection status",
     "data_type": "string", "required": False},
]

FACILITIES = b"facility_code,surveyed_on,state\nF1,2020-01-01,due\n"
VEHICLES = b"vin,checked_on,state\nV1,2021-06-01,due\n"


def _make_type(client: TestClient, fx: Fixture, api_name: str, props: list[str]) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={
            "api_name": f"{api_name}{fx.tag}",
            "display_name": f"{api_name} {fx.tag}",
            "properties": [{"api_name": p, "data_type": "string"} for p in props],
            "title_property": props[0],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _sync(client: TestClient, fx: Fixture, type_id: str, csv: bytes,
          key: str, mappings: dict[str, str], name: str) -> str:
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"{name} {fx.tag}"},
        files={"file": (f"{name}.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": type_id, "dataset_id": r.json()["id"],
              "primary_key_column": key, "column_mappings": mappings},
    )
    assert r.status_code == 201, r.text
    assert client.post(
        f"{pbase(fx)}/object-type-sources/{r.json()['id']}/sync",
        headers=hdr(fx.editor_sub),
    ).status_code == 200
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
    )
    return r.json()["items"][0]["id"]


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture) -> dict:
    """`ontology` p.60-62's own example: `Inspectable`, implemented by two
    types that call its properties different things.

    **Two implementations and not one**, because the whole claim is that one
    action reaches both — a single implementation would let a rename that did
    nothing pass every assertion.
    """
    r = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.admin_sub),
        json={"api_name": f"Inspectable{fx.tag}", "display_name": "Inspectable",
              "properties": INSPECTABLE},
    )
    assert r.status_code == 201, r.text
    interface_id = r.json()["id"]

    facility = _make_type(client, fx, "Facility", ["facility_code", "surveyed_on", "state"])
    vehicle = _make_type(client, fx, "Vehicle", ["vin", "checked_on", "state"])
    for type_id, mapping in (
        (facility, {"last_inspection_date": "surveyed_on", "inspection_status": "state"}),
        (vehicle, {"last_inspection_date": "checked_on", "inspection_status": "state"}),
    ):
        r = client.put(
            f"{wbase(fx)}/object-types/{type_id}/interfaces", headers=hdr(fx.editor_sub),
            json=[{"interface_id": interface_id, "property_mapping": mapping}],
        )
        assert r.status_code == 200, r.text

    return {
        "interface_id": interface_id,
        "facility": facility,
        "vehicle": vehicle,
        "facility_instance": _sync(
            client, fx, facility, FACILITIES, "facility_code",
            {"surveyed_on": "surveyed_on", "state": "state"}, "Facilities",
        ),
        "vehicle_instance": _sync(
            client, fx, vehicle, VEHICLES, "vin",
            {"checked_on": "checked_on", "state": "state"}, "Vehicles",
        ),
    }


def _interface_action(client: TestClient, fx: Fixture, world: dict,
                      properties: list[str]) -> dict:
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"interface_id": world["interface_id"],
              "api_name": f"inspect_{uuid.uuid4().hex[:8]}",
              "display_name": "Record inspection",
              "editable_properties": properties},
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_an_action_type_can_be_created_on_an_interface(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.59's "under Interfaces, pick the desired interface and rule type",
    through the same endpoint p.30's screen uses.

    The conversion is the one every action gets — one parameter per editable
    property, one `modify_object` rule pairing them — over the *interface's*
    properties, which is p.59's "add the shared properties that you want to
    include in the action".
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    assert action["object_type_id"] is None, action
    assert action["interface_id"] == world["interface_id"], action
    assert action["subject_name"] == "Inspectable", action
    assert [p["api_name"] for p in action["parameters"]] == ["last_inspection_date"]
    assert action["rules"][0]["config"] == {
        "property": "last_inspection_date", "parameter": "last_inspection_date",
    }


def test_an_action_needs_exactly_one_subject(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """Neither is an action with nothing to act on; both is two answers to one
    question. db 0101's CHECK says the same thing, and this is the sentence —
    an integrity error names a constraint, not a mistake."""
    for subject in (
        {},
        {"interface_id": world["interface_id"], "object_type_id": world["facility"]},
    ):
        r = client.post(
            f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"both_{uuid.uuid4().hex[:8]}",
                  "display_name": "Ambiguous",
                  "editable_properties": ["last_inspection_date"], **subject},
        )
        assert r.status_code == 422, r.text
        assert "exactly one" in r.text


def test_a_property_no_implementing_type_shares_is_refused(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.59: "you cannot create any property types that are specific to bugs or
    feature requests". `state` is a real property of both implementations and
    is not the interface's name for it, so naming it here is exactly the
    mistake the sentence describes."""
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"interface_id": world["interface_id"],
              "api_name": f"bad_{uuid.uuid4().hex[:8]}",
              "display_name": "Wrong vocabulary",
              "editable_properties": ["state"]},
    )
    assert r.status_code == 422, r.text
    assert "not properties of this interface" in r.text


def test_one_action_writes_both_implementations(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**p.59's promise, and the only test that can show it.**

    One action, two objects of two types that store the interface's property in
    two differently named columns of two different datasets. Read back off each
    object, because a result saying `ok` is the endpoint agreeing with itself.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    for type_id, instance, prop, said in (
        (world["facility"], world["facility_instance"], "surveyed_on", "2024-03-03"),
        (world["vehicle"], world["vehicle_instance"], "checked_on", "2024-04-04"),
    ):
        r = client.post(
            f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
            json={"instance_id": instance,
                  "values": {"last_inspection_date": said}},
        )
        assert r.status_code == 200, r.text
        got = client.get(
            f"{wbase(fx)}/object-types/{type_id}/instances/{instance}",
            headers=hdr(fx.viewer_sub),
        ).json()["properties"]
        assert got[prop] == said, got


def test_an_object_of_a_type_that_does_not_implement_it_is_not_found(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The subject is looked up among the implementations, so an object of any
    other type is not one this action has. **404 rather than a refusal**: from
    the caller's side it is the same "no such object instance" the object-type
    path raises, and which types were consulted is not something they asked
    about."""
    outsider = _make_type(client, fx, "Outsider", ["code", "state"])
    instance = _sync(
        client, fx, outsider, b"code,state\nO1,due\n", "code",
        {"state": "state"}, "Outsiders",
    )
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instance, "values": {"last_inspection_date": "x"}},
    )
    assert r.status_code == 404, r.text


def test_an_objects_action_list_includes_the_interfaces(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.64: "for a given object, all object-type-specific and interface-based
    actions that can be applied to that object will appear in the action
    dropdown" — *the* dropdown, one list, so the merge is the server's.

    Asserted as a pair, because either half alone passes for a listing that
    dropped the other (§226): the type's own action must still be there.
    """
    interface_action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": world["facility"],
              "api_name": f"own_{uuid.uuid4().hex[:8]}",
              "display_name": "Facility only", "editable_properties": ["state"]},
    )
    assert r.status_code == 201, r.text
    own = r.json()

    listed = client.get(
        f"{wbase(fx)}/action-types?object_type_id={world['facility']}",
        headers=hdr(fx.viewer_sub),
    ).json()
    ids = {a["id"] for a in listed}
    assert own["id"] in ids, listed
    assert interface_action["id"] in ids, listed

    # And not on a type that does not implement it, which is what makes the
    # clause a filter rather than a listing of everything.
    outsider = _make_type(client, fx, "Unrelated", ["code"])
    other = client.get(
        f"{wbase(fx)}/action-types?object_type_id={outsider}",
        headers=hdr(fx.viewer_sub),
    ).json()
    assert interface_action["id"] not in {a["id"] for a in other}, other


def test_an_unmapped_optional_property_is_refused_at_submission(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.59's promise, from the side that breaks it — and the reason the
    refusal is at submission rather than at save time: the action is valid, and
    it is *this object's type* that cannot keep the promise.

    A third implementation that maps only the required property. The action was
    already legal, and stays legal for the two types that do map it.
    """
    partial = _make_type(client, fx, "Kiosk", ["kiosk_code", "seen_on"])
    r = client.put(
        f"{wbase(fx)}/object-types/{partial}/interfaces", headers=hdr(fx.editor_sub),
        json=[{"interface_id": world["interface_id"],
               "property_mapping": {"last_inspection_date": "seen_on"}}],
    )
    assert r.status_code == 200, r.text
    instance = _sync(
        client, fx, partial, b"kiosk_code,seen_on\nK1,2019-01-01\n", "kiosk_code",
        {"seen_on": "seen_on"}, "Kiosks",
    )
    action = _interface_action(client, fx, world, ["inspection_status"])
    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instance, "values": {"inspection_status": "done"}},
    )
    assert r.status_code == 422, r.text
    assert "inspection_status" in r.text


def test_writing_the_property_a_type_is_identified_by_fails_on_submission(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.62's own example, in this platform's terms: "always ensure that the
    action rule does not modify properties that are likely to be used as a
    primary key by some of the object types that implement the interface".

    A fourth type maps the interface's date onto the very column its objects
    are identified by. The action is the same one that works everywhere else,
    and against this object it fails on submission — which is p.62's word.
    """
    keyed = _make_type(client, fx, "Ticket", ["title", "state"])
    r = client.put(
        f"{wbase(fx)}/object-types/{keyed}/interfaces", headers=hdr(fx.editor_sub),
        json=[{"interface_id": world["interface_id"],
               "property_mapping": {"last_inspection_date": "title"}}],
    )
    assert r.status_code == 200, r.text
    instance = _sync(
        client, fx, keyed, b"title,state\nT1,due\n", "title",
        {"title": "title", "state": "state"}, "Tickets",
    )
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": instance, "values": {"last_inspection_date": "renamed"}},
    )
    assert r.status_code == 422, r.text
    assert "primary key" in r.text


def test_an_interface_action_is_not_offered_for_inline_editing(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.135's inline edit writes one type's dataset, and p.59's interface may
    have several.

    **Refused where the grid asks rather than where the batch runs** (§214):
    the Explorer and the Object Table both draw only the actions
    `inline_edit_refusals` calls eligible, so an action offered here and
    refused a click later is a control that looks like it works.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    assert action["inline_edit_refusals"], action
    assert "interface" in " ".join(action["inline_edit_refusals"])


def test_a_batch_of_an_interface_action_is_refused_and_says_why(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The other end of the same sentence: `inline_edit_refusals` decides what
    a *grid* may offer, and this endpoint can be called without one.

    **It is the same check**, and a mutant is how that was established: a
    second guard inside the batch handler survived every test here, because
    `execute_batch` consults the refusals first and never reaches it. The guard
    is gone; this asserts that the endpoint refuses, which is the claim that
    was worth having either way.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute-batch", headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": world["facility_instance"],
                         "values": {"last_inspection_date": "2024-05-05"}}]},
    )
    assert r.status_code == 422, r.text
    assert "interface" in r.text


def test_an_interface_actions_run_can_be_reverted(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.155: the toast is "your only opportunity to revert the action", and an
    interface action's run is a run like any other.

    **The run stores no object type of its own**, so the undo resolves the
    subject the way the apply did. Read back off the object, because a revert
    reporting success is the endpoint agreeing with itself — and the value it
    must restore is the one the *previous* test left, so this one writes its
    own first and puts that back.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    before = client.get(
        f"{wbase(fx)}/object-types/{world['vehicle']}/instances/{world['vehicle_instance']}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["checked_on"]

    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": world["vehicle_instance"],
              "values": {"last_inspection_date": "2099-12-31"}},
    )
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]

    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/runs/{run_id}/undo",
        headers=hdr(fx.editor_sub),
    )
    assert r.status_code == 200, r.text
    after = client.get(
        f"{wbase(fx)}/object-types/{world['vehicle']}/instances/{world['vehicle_instance']}",
        headers=hdr(fx.viewer_sub),
    ).json()["properties"]["checked_on"]
    assert after == before, (before, after)


def test_a_property_inherited_from_a_parent_interface_can_be_written(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """`object-link-types` p.53: "interfaces may extend any number of other
    interfaces", and an inherited property is one every implementation supplies
    just the same — so an action on the child may write it.

    **The child declares nothing of its own**, which is what makes the
    assertion able to fail: an action built from the interface's *own*
    properties would find no property at all here and refuse, and one built
    from the effective shape finds the parent's.
    """
    r = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.admin_sub),
        json={"api_name": f"Serviceable{fx.tag}", "display_name": "Serviceable",
              "properties": [], "extends": [world["interface_id"]]},
    )
    assert r.status_code == 201, r.text
    child = r.json()["id"]
    assert [p["api_name"] for p in r.json()["effective_properties"]] == [
        "last_inspection_date", "inspection_status",
    ], r.json()["effective_properties"]

    r = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"interface_id": child, "api_name": f"child_{uuid.uuid4().hex[:8]}",
              "display_name": "Record inspection (inherited)",
              "editable_properties": ["last_inspection_date"]},
    )
    assert r.status_code == 201, r.text
    assert [p["api_name"] for p in r.json()["parameters"]] == ["last_inspection_date"]


def test_two_interfaces_may_each_have_an_action_of_the_same_name(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """db 0101's two partial unique indexes: **a name is unique within its
    subject**, whichever kind of subject that is.

    The old `UNIQUE (object_type_id, api_name)` could not survive the column
    becoming nullable — Postgres counts every NULL as distinct, so it stopped
    constraining interface actions at all. The check that replaced it has to
    read `interface_id`, and a version that only read the object type would
    make one name usable by one interface in the whole workspace.
    """
    shared = f"shared_{uuid.uuid4().hex[:8]}"
    second = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.admin_sub),
        json={"api_name": f"Auditable{fx.tag}", "display_name": "Auditable",
              "properties": INSPECTABLE},
    )
    assert second.status_code == 201, second.text
    for interface_id in (world["interface_id"], second.json()["id"]):
        r = client.post(
            f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
            json={"interface_id": interface_id, "api_name": shared,
                  "display_name": "Record inspection",
                  "editable_properties": ["last_inspection_date"]},
        )
        assert r.status_code == 201, r.text


def test_a_second_action_of_that_name_on_one_interface_is_refused(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The other half, and the one that makes the rule a rule. **The message
    says which kind of subject it clashed with**, because "already exists on
    this object type" is a sentence about a thing the action does not have.
    """
    name = f"twice_{uuid.uuid4().hex[:8]}"
    body = {"interface_id": world["interface_id"], "api_name": name,
            "display_name": "Record inspection",
            "editable_properties": ["last_inspection_date"]}
    assert client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json=body
    ).status_code == 201
    r = client.post(f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 409, r.text
    assert "interface" in r.text, r.text


def test_the_definition_of_an_interface_action_is_saved_and_checked(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.59's limit on the *edit* path, not just on creation.

    `set_definition` validates the document against the subject's declared
    properties, and for an interface action the subject is the interface — so
    a rule naming a property specific to one implementation is refused with the
    message any unknown property gets, and one naming a shared property is
    saved. Both halves, because a validator that refused everything would pass
    the first assertion on its own.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    refused = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "when", "display_name": "When",
                            "data_type": "string"}],
            # `surveyed_on` is Facility's own name for the interface's
            # property. An interface action may not use it.
            "rules": [{"kind": "modify_object",
                       "config": {"property": "surveyed_on", "parameter": "when"}}],
            "criteria": [],
        },
    )
    assert refused.status_code == 422, refused.text

    ok = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [{"api_name": "when", "display_name": "When",
                            "data_type": "string"}],
            "rules": [{"kind": "modify_object",
                       "config": {"property": "last_inspection_date",
                                  "parameter": "when"}}],
            "criteria": [],
        },
    )
    assert ok.status_code == 200, ok.text
    # And it still runs, which is what saying "saved" is worth.
    r = client.post(
        f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
        json={"instance_id": world["facility_instance"], "values": {"when": "2028-08-08"}},
    )
    assert r.status_code == 200, r.text


def test_a_delete_rule_on_an_interface_reaches_either_implementing_type(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.62's "Delete actions on interfaces", which **already worked** and had
    nothing saying so (§452).

    It falls out of §451's design rather than needing anything: a delete names
    no property, so the rename leaves it alone, and the subject is resolved
    across the implementations like any other. That is the shape a ○ should be
    checked for before it is written — this one was written in the same commit
    that made it untrue.

    Both types, because either alone passes for a path that resolved the
    subject once and kept it: the rows are deleted from two different datasets.
    """
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"interface_id": world["interface_id"],
              "api_name": f"retire_{uuid.uuid4().hex[:8]}",
              "display_name": "Retire",
              "editable_properties": ["last_inspection_date"]},
    ).json()
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={"parameters": [], "rules": [{"kind": "delete_object", "config": {}}],
              "criteria": []},
    )
    assert r.status_code == 200, r.text

    # Two objects of their own, because every other test in this file needs the
    # fixture's to still be there.
    doomed = _make_type(client, fx, "Doomed", ["doomed_code", "retired_on"])
    spare = _make_type(client, fx, "Spare", ["spare_code", "retired_on"])
    for type_id in (doomed, spare):
        assert client.put(
            f"{wbase(fx)}/object-types/{type_id}/interfaces", headers=hdr(fx.editor_sub),
            json=[{"interface_id": world["interface_id"],
                   "property_mapping": {"last_inspection_date": "retired_on"}}],
        ).status_code == 200
    first = _sync(client, fx, doomed, b"doomed_code,retired_on\nD1,\n",
                  "doomed_code", {"retired_on": "retired_on"}, "Doomed")
    second = _sync(client, fx, spare, b"spare_code,retired_on\nS1,\n",
                   "spare_code", {"retired_on": "retired_on"}, "Spare")

    for type_id, instance in ((doomed, first), (spare, second)):
        r = client.post(
            f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
            json={"instance_id": instance, "values": {}},
        )
        assert r.status_code == 200, r.text
        left = client.get(
            f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
        ).json()["items"]
        assert left == [], left


# ---- p.60's Create on an interface (§453) ------------------------------------
def create_rule(**config) -> dict:
    return {"kind": "create_object", "config": config}


IMPLEMENTATIONS = {
    "fac": {"display_name": "Facility",
            "property_mapping": {"last_inspection_date": "surveyed_on"}},
    "veh": {"display_name": "Vehicle",
            "property_mapping": {"last_inspection_date": "checked_on"}},
}


def test_the_chosen_type_becomes_an_ordinary_cross_type_create() -> None:
    """p.60: "an 'Object type' parameter will be automatically generated to
    indicate the object type that should be created".

    The rewrite's whole purpose: after it, the rule is a shape the executor
    already handles — a named `object_type` and that type's own property
    names — so nothing below it had to learn about interfaces.
    """
    out = actions_service.creation_rules_for_interface(
        [create_rule(object_type_parameter="kind", primary_key="key",
                     properties={"last_inspection_date": "when"})],
        bound={"kind": "veh", "key": "V9", "when": "2026-01-01"},
        implementations=IMPLEMENTATIONS, interface_name="Inspectable",
    )
    assert out[0]["config"]["object_type"] == "veh"
    assert out[0]["config"]["properties"] == {"checked_on": "when"}
    # The primary key is a *value* the rule collects and is not renamed.
    assert out[0]["config"]["primary_key"] == "key"
    # And the parameter that chose the type is gone, because the rule no longer
    # has a choice to make.
    assert "object_type_parameter" not in out[0]["config"]


def test_a_create_that_names_a_type_outright_is_left_alone() -> None:
    """p.59 limits what may be *modified* on the subject; a rule creating a
    named type's object is not about the subject at all, so it needs no
    translation and must not get one."""
    rule = create_rule(object_type="other", primary_key="key",
                       properties={"status": "s"})
    out = actions_service.creation_rules_for_interface(
        [rule], bound={}, implementations=IMPLEMENTATIONS,
        interface_name="Inspectable",
    )
    assert out == [rule]


def test_choosing_nothing_is_refused_rather_than_defaulted() -> None:
    """There is no type this could sensibly pick, and picking the first
    implementation would put somebody's row in a table they did not name."""
    with pytest.raises(actions_service.InterfaceSubjectError) as excinfo:
        actions_service.creation_rules_for_interface(
            [create_rule(object_type_parameter="kind", primary_key="key",
                         properties={"last_inspection_date": "when"})],
            bound={"key": "X"}, implementations=IMPLEMENTATIONS,
            interface_name="Inspectable",
        )
    assert "kind" in str(excinfo.value)


def test_choosing_a_type_that_does_not_implement_it_is_refused() -> None:
    """The parameter is a value a caller supplies, so the dropdown offering
    only implementations is a convenience and this is the rule."""
    with pytest.raises(actions_service.InterfaceSubjectError) as excinfo:
        actions_service.creation_rules_for_interface(
            [create_rule(object_type_parameter="kind", primary_key="key",
                         properties={"last_inspection_date": "when"})],
            bound={"kind": "outsider", "key": "X"},
            implementations=IMPLEMENTATIONS, interface_name="Inspectable",
        )
    assert "outsider" in str(excinfo.value)


def test_a_property_the_chosen_type_maps_nothing_to_is_refused() -> None:
    """p.59's promise on the create side: an interface's optional property may
    be unmapped, and a create that silently dropped it would make one
    submission produce different rows depending on the type chosen."""
    with pytest.raises(actions_service.InterfaceSubjectError) as excinfo:
        actions_service.creation_rules_for_interface(
            [create_rule(object_type_parameter="kind", primary_key="key",
                         properties={"inspection_status": "how"})],
            bound={"kind": "fac", "key": "X"},
            implementations=IMPLEMENTATIONS, interface_name="Inspectable",
        )
    assert "Facility" in str(excinfo.value)
    assert "inspection_status" in str(excinfo.value)


def test_one_create_action_makes_an_object_of_whichever_type_was_chosen(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """**p.59's own example, end to end**: "you can use a 'Create a ticket'
    action type to create bugs and feature requests".

    One action, submitted twice, producing a row in two different datasets —
    which is the duplication an interface exists to remove, and the thing a
    rule naming a type outright could not do. Read back off each type, because
    a result saying `ok` is the endpoint agreeing with itself.
    """
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "kind", "display_name": "Object type",
                 "data_type": "object_type", "required": True},
                {"api_name": "key", "display_name": "Key",
                 "data_type": "string", "required": True},
                {"api_name": "when", "display_name": "When",
                 "data_type": "string", "required": True},
            ],
            "rules": [create_rule(object_type_parameter="kind", primary_key="key",
                                  properties={"last_inspection_date": "when"})],
            "criteria": [],
        },
    )
    assert r.status_code == 200, r.text

    for type_id, key, column, said in (
        (world["facility"], "F9", "surveyed_on", "2030-01-01"),
        (world["vehicle"], "V9", "checked_on", "2030-02-02"),
    ):
        r = client.post(
            f"{pbase(fx)}/actions/{action['id']}/execute", headers=hdr(fx.editor_sub),
            json={"instance_id": world["facility_instance"],
                  "values": {"kind": type_id, "key": key, "when": said}},
        )
        assert r.status_code == 200, r.text
        rows = client.get(
            f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
        ).json()["items"]
        made = next((x for x in rows if x["primary_key"] == key), None)
        assert made is not None, rows
        assert made["properties"][column] == said, made


def test_a_create_rule_that_names_no_chooser_and_no_type_is_refused(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """An interface action's own subject is an interface, which has no rows —
    so a create defaulting to "the action's own type" has no type at all. The
    message says which of the two things the rule is missing rather than
    reporting an object type nobody named."""
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "key", "display_name": "Key", "data_type": "string"},
                {"api_name": "when", "display_name": "When", "data_type": "string"},
            ],
            "rules": [create_rule(primary_key="key",
                                  properties={"last_inspection_date": "when"})],
            "criteria": [],
        },
    )
    assert r.status_code == 422, r.text
    assert "object type this workspace does not have" in r.text


def test_the_chooser_has_to_be_an_object_type_parameter(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """A string parameter would collect a type id perfectly well and the form
    would draw a text box for it — which is §214's control that can only be
    satisfied by somebody who already knows a UUID."""
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "kind", "display_name": "Object type",
                 "data_type": "string"},
                {"api_name": "key", "display_name": "Key", "data_type": "string"},
                {"api_name": "when", "display_name": "When", "data_type": "string"},
            ],
            "rules": [create_rule(object_type_parameter="kind", primary_key="key",
                                  properties={"last_inspection_date": "when"})],
            "criteria": [],
        },
    )
    assert r.status_code == 422, r.text
    assert "object_type parameter" in r.text


def test_the_interface_read_carries_the_types_that_implement_it(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """p.60's list, on the wire: "the user will be prompted to pick an object
    type from a list".

    **Tested here rather than beside the other interface reads**, because this
    is the caller that needs it — the picker for an Object type parameter, and
    the only reason the detail grew the field. Asserted as a pair with a type
    that does *not* implement it, since a read returning every object type in
    the workspace would satisfy the first half on its own and offer a picker
    whose extra options can only be refused (§214).
    """
    r = client.get(
        f"{wbase(fx)}/interfaces/{world['interface_id']}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    implementing = {i["object_type_id"] for i in r.json()["implementations"]}
    assert world["facility"] in implementing, implementing
    assert world["vehicle"] in implementing, implementing

    outsider = _make_type(client, fx, "Bystander", ["code"])
    assert outsider not in implementing, implementing
    # And the names come with them, because an id is not something to pick from
    # a list.
    assert all(i["display_name"] for i in r.json()["implementations"])


def test_a_create_cannot_both_name_a_type_and_choose_one(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """Two answers to "what does this make", and the rewrite would honour the
    parameter while the dialog showed the named type — a rule that does
    something other than what it reads as."""
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "kind", "display_name": "Object type",
                 "data_type": "object_type"},
                {"api_name": "key", "display_name": "Key", "data_type": "string"},
                {"api_name": "when", "display_name": "When", "data_type": "string"},
            ],
            "rules": [create_rule(object_type_parameter="kind",
                                  object_type=world["facility"],
                                  primary_key="key",
                                  properties={"last_inspection_date": "when"})],
            "criteria": [],
        },
    )
    assert r.status_code == 422, r.text
    assert "one or the other" in r.text


def test_a_chooser_that_is_not_a_parameter_at_all_is_refused(
    client: TestClient, fx: Fixture, world: dict
) -> None:
    """The name is checked before its type, because the two are different
    mistakes: a parameter that does not exist is a typo, and one of the wrong
    type is a control that would collect the wrong thing. A rule reading a
    name nothing declares would fail at submission with nothing bound, which
    is p.60's choice silently never made."""
    action = _interface_action(client, fx, world, ["last_inspection_date"])
    r = client.put(
        f"{wbase(fx)}/action-types/{action['id']}/definition", headers=hdr(fx.editor_sub),
        json={
            "parameters": [
                {"api_name": "key", "display_name": "Key", "data_type": "string"},
                {"api_name": "when", "display_name": "When", "data_type": "string"},
            ],
            "rules": [create_rule(object_type_parameter="missing", primary_key="key",
                                  properties={"last_inspection_date": "when"})],
            "criteria": [],
        },
    )
    assert r.status_code == 422, r.text
    assert "which is not a parameter" in r.text
