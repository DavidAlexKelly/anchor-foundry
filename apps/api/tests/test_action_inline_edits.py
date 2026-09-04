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


def test_a_hidden_parameter_is_refused(
    client: TestClient, fx: Fixture, ticket_type_id: str
) -> None:
    """p.241: "Parameters' visibility options should not be set to 'hidden' (as
    each parameter will be tied to a visible column with the table)."

    A hidden parameter is one the form fills without showing; a table column is
    the opposite arrangement, and a hidden one has no cell to be typed into.
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
    assert any("hidden" in r for r in updated["inline_edit_refusals"]), updated[
        "inline_edit_refusals"
    ]


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
