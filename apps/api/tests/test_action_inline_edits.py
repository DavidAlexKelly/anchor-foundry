"""Inline edits, the server half (Foundry `workshop` p.240-243, `action-types`
p.135-138).

> "Enabling inline editing allows module users to modify cell-level data
> displayed within the Object Table and then save these edits to objects data.
> Editing options are defined via an action configured in the Ontology that must
> meet the following criteria to be compatible with inline edits." (`workshop`
> p.240)

Two things live here, and the first is what makes the second possible.

**Which actions may back an inline edit.** p.240-241 and `action-types`
p.136-137 give a list of requirements, and read together they say one thing: an
eligible action's entire effect is "set these columns on this row". No creates,
no deletes, no links, no second object, no value that is not a single primitive.

**Submitting a hundred of them at once.** p.137: "Inline edits differ in that
they are validated and submitted in bulk"; p.138: "the edits will be submitted
all at once and will succeed if they all pass". That is only expressible because
of the paragraph above - a batch of arbitrary actions could not share a dataset
version, and a batch that wrote as it went could not be all-or-nothing.

The widget that calls this is the next unit. What is checked here is everything
a browser cannot see: that the refusals name real problems, that a batch either
happens or does not, and that an untouched cell keeps its value rather than
losing it.
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
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

# Five rows, because p.242's whole subject is editing several at once and a
# fixture of one cannot tell "the batch wrote every row" from "the batch wrote
# a row".
TICKETS = (
    b"ticket_id,status,priority,site\n"
    b"1,open,low,\"51.5,-0.12\"\n"
    b"2,open,low,\"51.6,-0.12\"\n"
    b"3,open,low,\"51.7,-0.12\"\n"
    b"4,open,low,\"51.8,-0.12\"\n"
    b"5,open,low,\"51.9,-0.12\"\n"
)


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("inline-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def wbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}"


def abase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/actions"


@pytest.fixture(scope="module")
def ticket_type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"InlineTicket{fx.tag}",
            "display_name": f"InlineTicket {fx.tag}",
            "properties": [
                {"api_name": "status", "data_type": "string"},
                {"api_name": "priority", "data_type": "string"},
                # A property whose value is a struct, so "single primitive"
                # has something to refuse.
                {"api_name": "site", "data_type": "geopoint"},
                # No dataset column (p.113), so a synced object carries no key
                # for it at all - which is the one shape p.135's seeding has to
                # read past rather than out of.
                {"api_name": "triage_note", "data_type": "string", "edit_only": True},
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="module")
def instances(client: TestClient, fx: Fixture, ticket_type_id: str) -> dict[str, str]:
    """`ticket_id` → instance id, so a test can name the row it edits.

    By key rather than by index: these tests write to the same five rows, and
    an assertion about "the second one" would depend on the order the store
    happened to return them in.
    """
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"InlineTickets {fx.tag}"},
        files={"file": ("tickets.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": ticket_type_id,
            "dataset_id": dataset_id,
            "primary_key_column": "ticket_id",
            "column_mappings": {
                "status": "status", "priority": "priority", "site": "site",
            },
        },
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]
    assert client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/object-type-sources/{source_id}/sync",
        headers=hdr(fx.editor_sub),
    ).status_code == 200
    r = client.get(
        f"{wbase(fx)}/object-types/{ticket_type_id}/instances",
        headers=hdr(fx.viewer_sub),
    )
    return {i["primary_key"]: i["id"] for i in r.json()["items"]}


def make_action(
    client: TestClient, fx: Fixture, type_id: str, properties: list[str]
) -> dict:
    r = client.post(
        f"{wbase(fx)}/action-types",
        headers=hdr(fx.editor_sub),
        json={
            "object_type_id": type_id,
            "api_name": f"inline_{uuid.uuid4().hex[:8]}",
            "display_name": "Edit ticket",
            "editable_properties": properties,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def define(client: TestClient, fx: Fixture, action_id: str, body: dict) -> dict:
    r = client.put(
        f"{wbase(fx)}/action-types/{action_id}/definition",
        headers=hdr(fx.editor_sub),
        json={"criteria": [], **body},
    )
    assert r.status_code == 200, r.text
    return r.json()


def properties_of(client: TestClient, fx: Fixture, type_id: str, key: str) -> dict:
    r = client.get(
        f"{wbase(fx)}/object-types/{type_id}/instances", headers=hdr(fx.viewer_sub)
    )
    return next(i for i in r.json()["items"] if i["primary_key"] == key)["properties"]


# ---- eligibility (p.240-241, action-types p.136-137) --------------------------
def test_a_plain_property_edit_is_eligible(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The shape p.240 describes: one object, properties from parameters.

    An action created from `editable_properties` is already exactly this, which
    is the point - p.240's criteria are not a new mode to configure, they are a
    description of the ordinary action.
    """
    action = make_action(client, fx, ticket_type_id, ["status", "priority"])
    assert action["inline_edit_refusals"] == []


def test_a_struct_parameter_is_refused_by_name(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """p.241: "Property parameters must be of single, primitive types … not an
    object reference or array."

    A geopoint is this platform's nearest thing to that sentence: two numbers
    in one value, and no cell control that could hold it. **The refusal names
    the parameter**, because an action with six parameters and one bad one is
    otherwise a builder reading a list looking for which.
    """
    action = make_action(client, fx, ticket_type_id, ["status", "site"])
    refusals = action["inline_edit_refusals"]
    assert len(refusals) == 1, refusals
    assert "'site'" in refusals[0]
    assert "geopoint" in refusals[0]
    # The eligible parameter is not mentioned: a refusal list that named every
    # parameter would say nothing about which is the problem.
    assert "'status'" not in refusals[0]


def test_a_hidden_parameter_is_a_column_not_offered_rather_than_a_refusal(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """**This test used to assert the opposite, and the page is why it changed**
    (§324).

    It read `workshop` p.241 — "Parameters' visibility options should not be set
    to 'hidden' (as each parameter will be tied to a visible column with the
    table)" — as a hard rule, and refused the whole action type for it.
    `action-types` p.137 lists visibility among the requirements an action must
    meet only to say it is *allowed*:

        "Visibility status and overrides can be set; however, they will be
         ignored if the inline edit is used in Object Explorer and Object
         Views."

    So refusing was stricter than either page: one hidden parameter took an
    otherwise eligible action out of inline editing entirely. It is safe to
    ignore one, and p.135 says why — "every parameter is optional and defaults
    to the existing value of the object" — so a parameter no column offers is
    submitted unchanged, exactly like a column nobody typed into.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    updated = define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string",
             "hidden": True},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
        ],
    })
    assert updated["inline_edit_refusals"] == [], (
        "visibility is allowed by p.137; it is not an eligibility rule"
    )
    assert updated["inline_edit_hidden_parameters"] == ["status"], (
        "but no surface should offer it as a column"
    )


def test_a_visible_parameter_is_not_named_as_hidden(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The other direction, and what stops the list above meaning nothing.

    Without it, "hidden parameters are named" is satisfied by a server that
    names every parameter — which would leave a table with no columns at all
    and an action that looks eligible.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    updated = define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "note", "display_name": "Note", "data_type": "string",
             "hidden": True},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
        ],
    })
    assert updated["inline_edit_hidden_parameters"] == ["note"]


def test_an_action_that_creates_an_object_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """p.240: "should either use a single 'Modify object' rule"; p.136: "May
    only modify a single object of a single object type."

    Not pedantry: the batch path writes one dataset version made of row
    updates, and a create is an appended row. An action that did both could not
    be submitted a hundred times over into one file.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    updated = define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "new_key", "display_name": "Key", "data_type": "string"},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
            {"kind": "create_object",
             "config": {"primary_key": "new_key", "properties": {"status": "status"}}},
        ],
    })
    assert any("create_object" in r for r in updated["inline_edit_refusals"]), updated[
        "inline_edit_refusals"
    ]


def test_an_action_that_changes_a_second_object_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """p.136's "a single object", from the other direction: a rule that writes
    an object a *parameter* names writes some other row than the one the reader
    typed into."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    updated = define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "other", "display_name": "Other ticket", "data_type": "object"},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status", "object": "other"}},
        ],
    })
    assert any(
        "also changes an object named by a parameter" in r
        for r in updated["inline_edit_refusals"]
    ), updated["inline_edit_refusals"]


def test_an_action_that_changes_nothing_on_its_own_object_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """The case the other refusals do not cover: an action whose every rule is
    legal on its own and none of which writes the row being edited. Without
    this, a table could be pointed at an action that submits happily and
    changes no cell anybody typed in."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    updated = define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "other", "display_name": "Other ticket", "data_type": "object"},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status", "object": "other"}},
        ],
    })
    assert any("has none" in r for r in updated["inline_edit_refusals"]), updated[
        "inline_edit_refusals"
    ]


# ---- the batch (p.242-243, action-types p.137-138) ---------------------------
def test_a_batch_writes_every_row_it_was_given(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.242's staged edits, submitted.

    Read back off the objects rather than off the response: a result saying
    `ok` is the endpoint agreeing with itself.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"status": "triaged"}},
            {"instance_id": instances["2"], "values": {"status": "closed"}},
        ]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert r.json()["rows"] == 2

    assert properties_of(client, fx, ticket_type_id, "1")["status"] == "triaged"
    assert properties_of(client, fx, ticket_type_id, "2")["status"] == "closed"
    # A row nobody edited: the batch wrote what it was given and not the table.
    assert properties_of(client, fx, ticket_type_id, "3")["status"] == "open"


def test_the_whole_batch_lands_in_one_dataset_version(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.138: "the edits will be submitted all at once".

    Asserted as **one version number for the submission**, which is the fact a
    reader of the dataset's history would see. Two edits producing two versions
    would be a history that has to be interpreted (decision 0008's own words),
    and would mean a failure between them left half a submission.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["4"], "values": {"priority": "high"}}]},
    ).json()["dataset_versions"]
    assert len(before) == 1, before
    first = next(iter(before.values()))

    after = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["4"], "values": {"priority": "low"}},
            {"instance_id": instances["5"], "values": {"priority": "high"}},
        ]},
    ).json()["dataset_versions"]
    assert len(after) == 1, after
    # **One** version further on, for two rows. Three rows in two submissions
    # advancing the dataset by two is the claim; by three would mean each row
    # staged its own.
    assert next(iter(after.values())) == first + 1


def test_a_row_that_fails_criteria_stops_the_whole_batch(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.138: "will succeed if they **all** pass parameter and global submission
    criteria for the corresponding object."

    **The load-bearing test of this unit.** Everything else about batching is a
    convenience; this is the guarantee, and the only way to be wrong about it
    is to write as you go. The second edit is the one that fails, so a
    write-as-you-go implementation passes every other test in this file and
    fails only this one - it would have written the first row before finding
    out.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
        ],
        "criteria": [
            {"message": "status must be one this workspace uses",
             "config": {
                 "left": {"kind": "parameter", "parameter": "status"},
                 "operator": "is_included_in",
                 "right": {"kind": "value", "value": ["triaged", "closed"]},
             }},
        ],
    })
    before = properties_of(client, fx, ticket_type_id, "1")["status"]

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"status": "closed"}},
            {"instance_id": instances["2"], "values": {"status": "nonsense"}},
        ]},
    )
    assert r.status_code == 422, r.text
    assert "status must be one this workspace uses" in r.json()["detail"]
    # The first row - valid, and first in the list - is untouched.
    assert properties_of(client, fx, ticket_type_id, "1")["status"] == before


def test_the_same_object_twice_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.138: "Actions will return an error if an inline edit attempts to edit
    the same object twice."

    Two edits of one row are two answers, and merging them would pick one
    silently. Refused before anything is read, so the second is not applied
    over the first by accident of iteration order.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    before = properties_of(client, fx, ticket_type_id, "3")["status"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["3"], "values": {"status": "one"}},
            {"instance_id": instances["3"], "values": {"status": "two"}},
        ]},
    )
    assert r.status_code == 422, r.text
    assert "same object twice" in r.json()["detail"]
    assert properties_of(client, fx, ticket_type_id, "3")["status"] == before


def test_an_untouched_parameter_keeps_the_object_s_value(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """`action-types` p.135: "for action-backed inline edits, every parameter is
    optional and defaults to the existing value of the object, so a user can
    make individual changes to properties one at a time."

    **This is what a cell edit is.** Typing in one column must not clear the
    others, and a batch row carrying one value through an action with two
    parameters would do exactly that without the seeding - `apply_rules` writes
    only what is bound, so the untouched property would be left alone here, but
    the *other* half of p.135 is that a `required` parameter must not refuse
    the row either. Both are asserted.
    """
    action = make_action(client, fx, ticket_type_id, ["status", "priority"])
    define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string",
             "required": True},
            {"api_name": "priority", "display_name": "Priority", "data_type": "string",
             "required": True},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
            {"kind": "modify_object",
             "config": {"property": "priority", "parameter": "priority"}},
        ],
    })
    client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["5"], "values": {
            "status": "seeded", "priority": "urgent"}}]},
    )

    # One column, on an action whose *other* parameter is required.
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["5"], "values": {"status": "changed"}}]},
    )
    assert r.status_code == 200, r.text
    got = properties_of(client, fx, ticket_type_id, "5")
    assert got["status"] == "changed"
    assert got["priority"] == "urgent"


def test_seeding_follows_the_rule_rather_than_the_parameter_s_name(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.241 *recommends* matching names - "For an easier configuration
    experience, action parameter IDs should match the property IDs displayed
    within the table" - which means an action whose names differ is legal and
    has to work.

    **Every other test in this file is blind to this**, because an action built
    from `editable_properties` names each parameter after the property it
    writes, so seeding by name and seeding by rule are the same function. A
    mutant swapping one for the other survived all of them (§232's lesson: a
    fixture that cannot distinguish two implementations is not a check).
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    define(client, fx, action["id"], {
        "parameters": [
            # Named for the reader, not for the column.
            {"api_name": "new_status", "display_name": "New status",
             "data_type": "string"},
            {"api_name": "new_priority", "display_name": "New priority",
             "data_type": "string", "required": True},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "new_status"}},
            {"kind": "modify_object",
             "config": {"property": "priority", "parameter": "new_priority"}},
        ],
    })
    client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["2"], "values": {
            "new_status": "renamed", "new_priority": "keepme"}}]},
    )

    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["2"],
                         "values": {"new_status": "again"}}]},
    )
    assert r.status_code == 200, r.text
    got = properties_of(client, fx, ticket_type_id, "2")
    assert got["status"] == "again"
    # Seeded from `priority` because that is what `new_priority`'s rule writes.
    # Seeding by name would have found no property called `new_priority`, left
    # the required parameter unbound, and refused the row.
    assert got["priority"] == "keepme"


def test_a_property_the_object_has_never_had_is_left_alone(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """The seeding's other edge, and the one that crashes rather than misbehaves.

    An **edit-only** property (p.113) has no dataset column, so an object that
    no action has written carries no value for it at all - the key is simply
    absent from the stored properties. Seeding reads the *rule's* property out
    of that dict, so an untouched parameter for a never-written edit-only
    property is a lookup with nothing behind it.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    define(client, fx, action["id"], {
        "parameters": [
            {"api_name": "status", "display_name": "Status", "data_type": "string"},
            {"api_name": "triage_note", "display_name": "Note", "data_type": "string"},
        ],
        "rules": [
            {"kind": "modify_object",
             "config": {"property": "status", "parameter": "status"}},
            {"kind": "modify_object",
             "config": {"property": "triage_note", "parameter": "triage_note"}},
        ],
    })
    # `triage_note` is not supplied and the object has never carried one.
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["3"],
                         "values": {"status": "noted"}}]},
    )
    assert r.status_code == 200, r.text
    assert properties_of(client, fx, ticket_type_id, "3")["status"] == "noted"


def test_an_ineligible_action_is_refused_at_submission_too(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """The panel offers only eligible actions, and that is not enough: a builder
    can point a table at an action and then change the action. The widget
    configured while it was eligible would go on submitting, so the refusal is
    on the wire as well as in the picker."""
    action = make_action(client, fx, ticket_type_id, ["site"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["1"],
                         "values": {"site": "51.5,-0.12"}}]},
    )
    assert r.status_code == 422, r.text
    assert "cannot back inline edits" in r.json()["detail"]


def test_more_rows_than_the_cap_are_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.242: "up to … 200 rows at a time for actions that are not
    function-backed."

    Refused by the request schema, so two hundred and one rows never become two
    hundred and one reads out of the instance store.
    """
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": str(uuid.uuid4()), "values": {"status": "x"}}
            for _ in range(201)
        ]},
    )
    assert r.status_code == 422, r.text


def test_an_empty_submission_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Nothing on p.242 describes submitting no edits, and a batch that reports
    success for zero rows is one a caller cannot tell from a batch whose staged
    edits were lost on the way."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": []},
    )
    assert r.status_code == 422, r.text


def test_every_row_gets_its_own_run_sharing_one_batch_id(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """db 0063's reason, checked from the outside.

    A run is how this platform answers "who changed this object and to what",
    so a submission of three rows is three runs - each naming its own instance
    and its own values - and one `batch_id` saying they were one press of
    Submit. One run for the batch would answer the question for none of them;
    three unrelated runs would lose that they were submitted together.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"priority": "p1"}},
            {"instance_id": instances["2"], "values": {"priority": "p2"}},
            {"instance_id": instances["3"], "values": {"priority": "p3"}},
        ]},
    )
    assert r.status_code == 200, r.text
    batch_id = r.json()["batch_id"]

    runs = client.get(
        f"{wbase(fx)}/action-types/{action['id']}/runs", headers=hdr(fx.viewer_sub)
    ).json()
    assert len(runs) == 3, runs
    assert {run["batch_id"] for run in runs} == {batch_id}
    assert {run["instance_id"] for run in runs} == {
        instances["1"], instances["2"], instances["3"]
    }
    assert [run["submitted_values"] for run in sorted(
        runs, key=lambda x: x["submitted_values"]["priority"]
    )] == [{"priority": "p1"}, {"priority": "p2"}, {"priority": "p3"}]
    assert {run["status"] for run in runs} == {"succeeded"}


def test_a_single_submission_still_belongs_to_no_batch(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """The other half of db 0063's nullable column, and the one a mutant could
    quietly break: an ordinary `execute` must keep writing `NULL`, or every run
    this platform has ever recorded would start claiming to be part of a
    submission that never happened."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    assert client.post(
        f"{abase(fx)}/{action['id']}/execute",
        headers=hdr(fx.editor_sub),
        json={"instance_id": instances["4"], "values": {"status": "alone"}},
    ).status_code == 200
    runs = client.get(
        f"{wbase(fx)}/action-types/{action['id']}/runs", headers=hdr(fx.viewer_sub)
    ).json()
    assert [run["batch_id"] for run in runs] == [None]


def test_an_object_this_project_cannot_reach_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """A batch is a hundred chances to reach a row the caller may not touch, so
    the per-row lookup is what enforces the boundary rather than the action
    type's own workspace check."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"status": "fine"}},
            {"instance_id": str(uuid.uuid4()), "values": {"status": "nope"}},
        ]},
    )
    assert r.status_code == 404, r.text
    # And the valid row beside it is untouched, for the same reason as the
    # criteria test: validation happens before the first write.
    assert properties_of(client, fx, ticket_type_id, "1")["status"] != "fine"


def test_a_viewer_cannot_submit_a_batch(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """The same floor as `execute`: a batch is a write to project data, and a
    second write path at a lower floor would be a way round the first."""
    action = make_action(client, fx, ticket_type_id, ["status"])
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.viewer_sub),
        json={"edits": [{"instance_id": instances["1"], "values": {"status": "x"}}]},
    )
    assert r.status_code == 403, r.text


# ---- what a bulk edit does to the usage numbers (§324; p.32) ------------------
def usage_of(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/usage",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def by_application(client: TestClient, fx: Fixture, type_id: str) -> dict[str, dict]:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/usage/by-application",
                   headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return {row["application"]: row for row in r.json()}


def test_a_bulk_edit_is_one_write_and_not_one_per_row(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """`ontology-manager` p.32, and a hole §320 left open.

        "Note that one write represents one edit request sent to Object Storage
         v1 (Phonograph). **Many objects edited in bulk at once will only be
         recorded as a single write.**" (p.32)

    This route recorded **no** writes at all until §324 — every number in
    §320's panel came from `execute_action`, so a hundred rows saved from an
    Object Table moved nothing, and the writes column was a figure about one of
    the two write paths while claiming to be about the type.

    Three rows and one write is the assertion that says which rule is in force:
    a per-row count would give three, and is what somebody would write without
    reading the sentence.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = usage_of(client, fx, ticket_type_id)["writes"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"priority": "bulk1"}},
            {"instance_id": instances["2"], "values": {"priority": "bulk2"}},
            {"instance_id": instances["3"], "values": {"priority": "bulk3"}},
        ]},
    )
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert usage_of(client, fx, ticket_type_id)["writes"] == before + 1, (
        "three rows edited at once is one write, not three"
    )


def test_a_bulk_edit_is_counted_against_the_surface_that_sent_it(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.32 lists "direct Object Explorer edit" and a Workshop table as
    different sources of the same kind of write, and §320's panel breaks the
    numbers down by application.

    The two surfaces reach this route identically, so the label is the only
    thing that tells them apart — which is exactly the shape §320's
    `ONTOLOGY_MANAGER` exclusion has, and the reason it is a value the recorder
    recognises rather than a caller that happens not to call.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = by_application(client, fx, ticket_type_id)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"application": "explorer",
              "edits": [{"instance_id": instances["1"],
                         "values": {"priority": "from-the-explorer"}}]},
    )
    assert r.status_code == 200 and r.json()["ok"] is True, r.text

    after = by_application(client, fx, ticket_type_id)
    assert after["explorer"]["writes"] == before.get(
        "explorer", {"writes": 0}
    )["writes"] + 1
    # And it did not land under the other surface's name. Without this the test
    # passes for a route that labels every batch "explorer".
    assert after.get("workshop", {"writes": 0})["writes"] == before.get(
        "workshop", {"writes": 0}
    )["writes"]


def test_an_unlabelled_batch_is_the_object_table(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """The default, which is not an arbitrary choice.

    `execute-batch` exists for `workshop` p.242's staged edits and had exactly
    one caller before §324, so a submission that names no application is that
    caller — and defaulting to `"api"` would move every existing Object Table's
    writes into a column about something else the day this field shipped.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = by_application(client, fx, ticket_type_id)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["2"],
                         "values": {"priority": "unlabelled"}}]},
    )
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    after = by_application(client, fx, ticket_type_id)
    assert after["workshop"]["writes"] == before.get(
        "workshop", {"writes": 0}
    )["writes"] + 1


def test_a_submission_refused_before_it_starts_counts_nothing(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str]
) -> None:
    """p.32 records a write when an application "makes edits", and a submission
    refused for naming the same object twice (p.138) made none.

    **This one cannot reach the counting block at all**, and that is worth
    saying rather than leaving for somebody to discover: the refusal raises
    before the write is attempted, so the whole handler unwinds. It is a real
    claim — nothing is counted — and it is *not* a test of the `if ok:` guard,
    which is what the test below is for.
    """
    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = usage_of(client, fx, ticket_type_id)["writes"]
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [
            {"instance_id": instances["1"], "values": {"priority": "once"}},
            {"instance_id": instances["1"], "values": {"priority": "twice"}},
        ]},
    )
    assert r.status_code == 422, r.text
    assert usage_of(client, fx, ticket_type_id)["writes"] == before, (
        "a submission that wrote nothing is not a write"
    )


def test_a_submission_that_failed_while_writing_counts_nothing(
    client: TestClient, fx: Fixture, ticket_type_id: str, instances: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The `if ok:` guard, and the only way to reach it.**

    The mutation sweep found this: a mutant making the count unconditional
    survived every test in this file, because every refusal here is raised
    *before* the write is attempted and so unwinds the handler long before the
    guard is read. The same defect §320 found in its sixth survivor and §323
    found again — a check placed after a branch nothing in the suite takes.

    So the failure has to happen where p.138 says it can: in the dataset write
    itself, which answers 200 with `ok: false` rather than raising. Forced,
    because provoking a real engine failure needs a broken dataset and what is
    being checked is the guard rather than the engine.
    """
    from src.routes import actions as action_routes
    from src.services.dataset_engine import DatasetEngineError

    def boom(*a, **k):
        raise DatasetEngineError("the write could not be completed")

    action = make_action(client, fx, ticket_type_id, ["priority"])
    before = usage_of(client, fx, ticket_type_id)["writes"]
    monkeypatch.setattr(action_routes.engine, "write_rows", boom)
    r = client.post(
        f"{abase(fx)}/{action['id']}/execute-batch",
        headers=hdr(fx.editor_sub),
        json={"edits": [{"instance_id": instances["1"],
                         "values": {"priority": "doomed"}}]},
    )
    # The submission opened and failed, which is a 200 reporting failure rather
    # than a refusal — so the counting block really was reached this time.
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False, r.json()
    assert usage_of(client, fx, ticket_type_id)["writes"] == before, (
        "p.32 counts a write when an application makes edits, and this made none"
    )


def test_two_projects_behind_one_type_come_back_in_a_stated_order(
    client: TestClient, fx: Fixture
) -> None:
    """**Two projects, which is the only pair that can disagree** (§324).

    A type mapped in one project reads the same however the rows are ordered,
    so the `ORDER BY` was a clause no test could reach — and the Explorer names
    the projects in its refusal, where an order that wandered between reads
    would make the same ambiguity read as a different one each time.

    By name, because that is what the reader sees: an order by id would be
    stable and arbitrary, which is stable in the way a hash is.
    """
    # **Its own object type**, because mapping a second project onto the shared
    # one would leave every other test in this file looking at an ambiguous
    # type. Found exactly that way: the two tests above went red on the first
    # run of this one.
    declared = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"twoproj_{uuid.uuid4().hex[:8]}",
              "display_name": "Two projects",
              "properties": [{"api_name": "status", "data_type": "string"},
                             {"api_name": "priority", "data_type": "string"}]},
    )
    assert declared.status_code == 201, declared.text
    ticket_type_id = declared.json()["id"]

    made = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.editor_sub),
        json={"name": f"AAA tickets {uuid.uuid4().hex[:6]}"},
    )
    assert made.status_code == 201, made.text
    other = made.json()["id"]

    uploaded = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{other}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"OtherTickets {uuid.uuid4().hex[:6]}"},
        files={"file": ("other.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert uploaded.status_code == 201, uploaded.text
    mapped = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{other}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type_id, "dataset_id": uploaded.json()["id"],
              "primary_key_column": "ticket_id",
              "column_mappings": {"status": "status", "priority": "priority"}},
    )
    assert mapped.status_code == 201, mapped.text

    here = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"HereTickets {uuid.uuid4().hex[:6]}"},
        files={"file": ("here.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert here.status_code == 201, here.text
    also = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type_id, "dataset_id": here.json()["id"],
              "primary_key_column": "ticket_id",
              "column_mappings": {"status": "status", "priority": "priority"}},
    )
    assert also.status_code == 201, also.text

    rows = editing_projects(client, fx, ticket_type_id)
    assert len(rows) == 2, rows
    assert [p["name"] for p in rows] == sorted(p["name"] for p in rows), (
        "the Explorer names these in its refusal; an order that wandered "
        "would make one ambiguity read as a different one on every refresh"
    )
    # The new project's name starts with A, so it is first — which is the
    # assertion that fails if the ordering is dropped and the rows arrive in
    # insertion order instead.
    assert rows[0]["id"] == other, rows


# ---- where an edit from the Explorer would land (§324; p.135) ----------------
def editing_projects(client: TestClient, fx: Fixture, type_id: str, sub=None):
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/editing-projects",
                   headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_a_mapped_type_names_the_project_its_edits_would_reach(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """**The Object Explorer is workspace-scoped and a write is not** (§324).

    `action-types` p.135 puts inline edits in the Explorer's results view, but
    an object type is declared in a workspace while the instance behind a row
    comes from a mapping — and a mapping names a dataset in a *project*. So
    before the Explorer can submit anything it has to learn where the write
    would land, which is what this route is for.
    """
    rows = editing_projects(client, fx, ticket_type_id)
    assert [p["id"] for p in rows] == [str(fx.project)], rows
    # Named, not just identified: with more than one the Explorer has to be
    # able to say which, and "editing is unavailable" is not a sentence
    # somebody can act on (§214).
    assert rows[0]["name"]
    assert rows[0]["slug"]


def test_a_type_nothing_maps_names_no_project(
    client: TestClient, fx: Fixture
) -> None:
    """An unsourced type has nowhere for a write to go, and says so by being
    empty rather than by naming a project that could not take one.

    The Explorer reads this as "not editable here", which is the same answer it
    gives for a type with no eligible action — and a different answer from the
    ambiguity below.
    """
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"unmapped_{uuid.uuid4().hex[:8]}",
              "display_name": "Unmapped",
              "properties": [{"api_name": "name", "data_type": "string"}]},
    )
    assert r.status_code == 201, r.text
    assert editing_projects(client, fx, r.json()["id"]) == []


def test_a_type_mapped_twice_in_one_project_still_names_it_once(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """**`DISTINCT` is doing work, and this is what says so.**

    A type may be mapped from several datasets, and two datasets in the same
    project are two sources with one destination. Without the `DISTINCT` the
    Explorer would read two rows as an ambiguity and refuse to edit a type
    whose writes have exactly one place to go.
    """
    second = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/datasets/upload",
        headers=hdr(fx.editor_sub),
        data={"name": f"MoreTickets {uuid.uuid4().hex[:6]}"},
        files={"file": ("more.csv", io.BytesIO(TICKETS), "text/csv")},
    )
    assert second.status_code == 201, second.text
    mapped = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/object-type-sources",
        headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket_type_id, "dataset_id": second.json()["id"],
              "primary_key_column": "ticket_id",
              "column_mappings": {"status": "status", "priority": "priority"}},
    )
    assert mapped.status_code == 201, mapped.text

    rows = editing_projects(client, fx, ticket_type_id)
    assert [p["id"] for p in rows] == [str(fx.project)], (
        "two datasets in one project is one destination, not an ambiguity"
    )


def test_an_outsider_is_told_nothing_about_where_a_type_is_mapped(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """Where a workspace's types are mapped is a fact about that workspace."""
    r = client.get(f"{wbase(fx)}/object-types/{ticket_type_id}/editing-projects",
                   headers=hdr(fx.outsider_sub))
    assert r.status_code in (403, 404), r.text
