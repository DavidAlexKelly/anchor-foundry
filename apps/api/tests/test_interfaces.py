"""Interfaces (parity `docs/parity/ontology.md` §1.2, build order item 9's
fourth; Foundry `object-link-types` p.4, p.53; `ontology` p.60-62; db 0065).

> "An interface is an Ontology type that describes the shape of an object type
> and its capabilities." (`object-link-types` p.4)

> "You can implement an interface on multiple object types, and interfaces may
> extend any number of other interfaces." (p.53)

**The `[?]` on this row was about the screens, not the concept.** There is no
reference section in `object-link-types` for creating or editing an interface -
p.4 defines one and then points at a page this PDF does not carry, and every
other mention is the Gaia/Gotham integration, which is out of scope. What
`ontology` p.60-62 gives is the model in full, including the worked example
this file's fixture is named after: `Inspectable` with `lastInspectionDate` and
`inspectionStatus`, implemented by Vehicle, Equipment and Facility.

Most of what matters here is a **refusal**, because an interface is a promise
and a promise nothing enforces is worse than none. The pure half of that is
tested without a database, which is where a wrong answer is a line rather than
a fixture.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.services import interfaces as interfaces_service  # noqa: E402
from src.services import ontology as ontology_service  # noqa: E402


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


INSPECTABLE = [
    {"api_name": "last_inspection_date", "display_name": "Last inspected",
     "data_type": "date"},
    {"api_name": "inspection_status", "display_name": "Inspection status",
     "data_type": "string"},
]


def make_interface(client: TestClient, fx: Fixture, **over) -> dict:
    tag = uuid.uuid4().hex[:6]
    body = {
        "api_name": f"Inspectable{tag}",
        "display_name": f"Inspectable {tag}",
        "properties": INSPECTABLE,
        **over,
    }
    r = client.post(f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_type(client: TestClient, fx: Fixture, properties: list[dict]) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"vehicle_{tag}", "display_name": f"Vehicle {tag}",
              "properties": [{"api_name": "id", "display_name": "Id",
                              "data_type": "string"}, *properties],
              "title_property": "id"},
    )
    assert r.status_code == 201, r.text
    return r.json()


def implement(client: TestClient, fx: Fixture, type_id: str, entries: list[dict]):
    return client.put(
        f"{wbase(fx)}/object-types/{type_id}/interfaces",
        headers=hdr(fx.editor_sub), json=entries,
    )


# ---- the shape, without a database --------------------------------------------
def test_an_interface_inherits_every_ancestors_properties() -> None:
    """p.53: "interfaces may extend any number of other interfaces", and p.62's
    "extend interfaces for multi-level abstraction".

    Two parents and a grandparent, because one of each would pass against an
    implementation that only followed the first edge.
    """
    own = {
        "child": [{"api_name": "own", "data_type": "string", "required": True}],
        "p1": [{"api_name": "from_p1", "data_type": "date", "required": True}],
        "p2": [{"api_name": "from_p2", "data_type": "integer", "required": True}],
        "grand": [{"api_name": "from_grand", "data_type": "boolean", "required": True}],
    }
    extends = {"child": ["p1", "p2"], "p1": ["grand"]}
    assert [
        p["api_name"]
        for p in interfaces_service.effective_properties(
            "child", own=own, extends=extends
        )
    ] == ["own", "from_p1", "from_grand", "from_p2"]


def test_two_ancestors_may_agree_about_a_property() -> None:
    """The diamond, which is what "any number of other interfaces" makes
    ordinary: two parents both declaring `status` as a string is one property
    and nothing to decide."""
    own = {
        "child": [],
        "p1": [{"api_name": "status", "data_type": "string", "required": True}],
        "p2": [{"api_name": "status", "data_type": "string", "required": True}],
    }
    resolved = interfaces_service.effective_properties(
        "child", own=own, extends={"child": ["p1", "p2"]}
    )
    assert [p["api_name"] for p in resolved] == ["status"]


def test_two_ancestors_that_disagree_are_refused_before_anything_implements() -> None:
    """**A contradiction, not a winner.** No object type could satisfy both, so
    the refusal belongs where the hierarchy is declared - refusing it at the
    moment somebody tries to implement it would be one screen too late, and the
    person who typed the extension is not the person who would meet it."""
    own = {
        "child": [],
        "p1": [{"api_name": "status", "data_type": "string", "required": True}],
        "p2": [{"api_name": "status", "data_type": "integer", "required": True}],
    }
    with pytest.raises(interfaces_service.InterfaceError, match="different base types"):
        interfaces_service.effective_properties(
            "child", own=own, extends={"child": ["p1", "p2"]}
        )


def test_a_circle_of_extensions_is_refused_and_names_the_circle() -> None:
    """p.53 says nothing about cycles because a cycle is not an abstraction:
    `A extends B extends A` has no shape, and the walk that resolves it would
    not terminate. Named in the order followed, which is what makes it
    fixable."""
    with pytest.raises(interfaces_service.InterfaceError, match="in a circle"):
        interfaces_service.effective_properties(
            "a", own={"a": [], "b": []}, extends={"a": ["b"], "b": ["a"]}
        )


def test_an_implementation_must_supply_every_required_property() -> None:
    with pytest.raises(interfaces_service.InterfaceError, match="maps nothing to it"):
        interfaces_service.check_implementation(
            interface_name="Inspectable",
            required=[{"api_name": "checked", "data_type": "date", "required": True}],
            property_types={"id": "string"},
            mapping={},
        )


def test_an_optional_property_may_be_left_unmapped() -> None:
    """The reason `required` is a column rather than an assumption: p.62's
    "design interfaces around capabilities" needs a capability with one
    mandatory field and two optional ones, which is an ordinary thing."""
    interfaces_service.check_implementation(
        interface_name="Inspectable",
        required=[{"api_name": "notes", "data_type": "string", "required": False}],
        property_types={"id": "string"},
        mapping={},
    )


def test_base_types_must_match_and_the_refusal_names_both() -> None:
    """p.181's rule about shared properties, one resource over. A refusal that
    said only "does not match" would make somebody go and look."""
    with pytest.raises(interfaces_service.InterfaceError) as exc:
        interfaces_service.check_implementation(
            interface_name="Inspectable",
            required=[{"api_name": "checked", "data_type": "date", "required": True}],
            property_types={"when": "string"},
            mapping={"checked": "when"},
        )
    assert "date" in str(exc.value) and "string" in str(exc.value)


def test_a_mapping_to_a_property_that_does_not_exist_is_refused() -> None:
    """The shape of a rename that happened somewhere else."""
    with pytest.raises(interfaces_service.InterfaceError, match="does not have"):
        interfaces_service.check_implementation(
            interface_name="Inspectable",
            required=[{"api_name": "checked", "data_type": "date", "required": True}],
            property_types={"id": "string"},
            mapping={"checked": "gone"},
        )


def test_a_mapping_for_a_property_the_interface_never_declared_is_refused() -> None:
    """Otherwise a typo in an interface property name is stored as a mapping
    nothing reads, and the implementation looks configured."""
    with pytest.raises(interfaces_service.InterfaceError, match="does not declare"):
        interfaces_service.check_implementation(
            interface_name="Inspectable",
            required=[{"api_name": "checked", "data_type": "date", "required": True}],
            property_types={"id": "string"},
            mapping={"chekced": "id"},
        )


def test_an_interface_property_must_have_a_real_base_type() -> None:
    """The vocabulary is the ontology's, so an interface cannot promise a type
    no object type could ever have. Found by a mutant: nothing had asked."""
    with pytest.raises(interfaces_service.InterfaceError, match="expected one of"):
        interfaces_service.parse_properties(
            [{"api_name": "checked", "data_type": "quaternion"}]
        )


def test_an_interface_cannot_declare_one_name_twice() -> None:
    """Two properties with one name is a shape with two answers to the same
    question, and the second would silently win at resolution time."""
    with pytest.raises(interfaces_service.InterfaceError, match="duplicate"):
        interfaces_service.parse_properties([
            {"api_name": "checked", "data_type": "date"},
            {"api_name": "checked", "data_type": "string"},
        ])


def test_an_interface_property_follows_the_property_naming_rule() -> None:
    """The same rule an object type's property has (0003), because an
    implementation maps one onto the other and a name shape only one of them
    could hold would be a difference with nothing behind it."""
    for bad in ("Checked", "1st_check", ""):
        with pytest.raises(interfaces_service.InterfaceError, match="invalid"):
            interfaces_service.parse_properties(
                [{"api_name": bad, "data_type": "date"}]
            )


# ---- through the API ----------------------------------------------------------
def test_an_interface_round_trips(client: TestClient, fx: Fixture) -> None:
    made = make_interface(client, fx)
    detail = client.get(
        f"{wbase(fx)}/interfaces/{made['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert [p["api_name"] for p in detail["properties"]] == [
        "last_inspection_date", "inspection_status"
    ]
    # Nothing extended, so the effective shape is its own.
    assert detail["effective_properties"] == detail["properties"]
    assert detail["status"] == "experimental"  # p.256's default


def test_an_interface_with_no_properties_is_allowed(
    client: TestClient, fx: Fixture
) -> None:
    """**A marker interface is a real thing**, and this is where it differs
    from the neighbouring type: p.149 requires a struct to have at least one
    field, and nothing says an interface must. A struct with no fields is a
    value with no content; an interface with none is a *taxonomy*, which p.62
    names explicitly - "taxonomic interfaces may include `MilitaryAsset` or
    `MedicalDevice`"."""
    made = make_interface(client, fx, properties=[])
    assert made["properties"] == []


def test_an_object_type_implements_an_interface(client: TestClient, fx: Fixture) -> None:
    """p.53's "implement an interface on multiple object types", and p.66's
    mapping — **the type's property is called something else**, which is the
    case that proves this is a mapping rather than a name match."""
    interface = make_interface(client, fx)
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    r = implement(client, fx, kind["id"], [{
        "interface_id": interface["id"],
        "property_mapping": {"last_inspection_date": "last_checked",
                             "inspection_status": "state"},
    }])
    assert r.status_code == 200, r.text
    assert [i["interface_id"] for i in r.json()] == [interface["id"]]

    listed = client.get(
        f"{wbase(fx)}/object-types/{kind['id']}/interfaces", headers=hdr(fx.viewer_sub)
    ).json()
    assert listed[0]["property_mapping"]["last_inspection_date"] == "last_checked"


def test_an_implementation_missing_a_property_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    interface = make_interface(client, fx)
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
    ])
    r = implement(client, fx, kind["id"], [{
        "interface_id": interface["id"],
        "property_mapping": {"last_inspection_date": "last_checked"},
    }])
    assert r.status_code == 422, r.text
    assert "inspection_status" in r.text


def test_a_bad_entry_leaves_the_whole_list_unchanged(
    client: TestClient, fx: Fixture
) -> None:
    """**Every entry checked before any is written.** A partial application
    would leave somebody working out which half went in — and it is the second
    entry that is wrong here, so a write-as-you-go implementation would have
    stored the first."""
    good = make_interface(client, fx)
    bad = make_interface(client, fx)
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    mapping = {"last_inspection_date": "last_checked", "inspection_status": "state"}
    assert implement(client, fx, kind["id"], [
        {"interface_id": good["id"], "property_mapping": mapping},
    ]).status_code == 200

    r = implement(client, fx, kind["id"], [
        {"interface_id": good["id"], "property_mapping": mapping},
        {"interface_id": bad["id"], "property_mapping": {}},
    ])
    assert r.status_code == 422, r.text
    still = client.get(
        f"{wbase(fx)}/object-types/{kind['id']}/interfaces", headers=hdr(fx.viewer_sub)
    ).json()
    assert [i["interface_id"] for i in still] == [good["id"]], (
        "the failed save changed the list it was refusing"
    )


def test_extending_an_interface_widens_what_an_implementation_must_supply(
    client: TestClient, fx: Fixture
) -> None:
    """The point of extension, seen from the implementing side: a type that
    satisfies the child must satisfy the parent too, and the refusal names the
    property it never heard of."""
    parent = make_interface(client, fx)
    child = make_interface(
        client, fx,
        properties=[{"api_name": "next_due", "display_name": "Next due",
                     "data_type": "date"}],
        extends=[parent["id"]],
    )
    detail = client.get(
        f"{wbase(fx)}/interfaces/{child['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert [p["api_name"] for p in detail["effective_properties"]] == [
        "next_due", "last_inspection_date", "inspection_status"
    ]

    kind = make_type(client, fx, [
        {"api_name": "next_due", "display_name": "Next due", "data_type": "date"},
    ])
    r = implement(client, fx, kind["id"], [{
        "interface_id": child["id"], "property_mapping": {"next_due": "next_due"},
    }])
    assert r.status_code == 422, r.text
    assert "last_inspection_date" in r.text


def test_a_circle_of_extensions_is_refused_by_the_api(
    client: TestClient, fx: Fixture
) -> None:
    """The pure check above, reached through the save that would create it -
    and the save is rolled back, so the circle is never visible."""
    a = make_interface(client, fx, properties=[])
    b = make_interface(client, fx, properties=[], extends=[a["id"]])
    r = client.put(
        f"{wbase(fx)}/interfaces/{a['id']}", headers=hdr(fx.editor_sub),
        json={"display_name": a["display_name"], "properties": [],
              "extends": [b["id"]]},
    )
    assert r.status_code == 422, r.text
    assert "circle" in r.text
    after = client.get(
        f"{wbase(fx)}/interfaces/{a['id']}", headers=hdr(fx.viewer_sub)
    ).json()
    assert after["extends"] == [], "the refused save left the extension behind"


def test_an_interface_in_use_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """**Deliberately unlike p.185's shared property**, which reverts its users
    to ordinary properties when it is deleted. A shared property gives a type
    metadata it can live without; an interface is a claim other resources are
    written against, so silently un-implementing three object types is a change
    to three object types and should be typed by whoever wants it."""
    interface = make_interface(client, fx)
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    assert implement(client, fx, kind["id"], [{
        "interface_id": interface["id"],
        "property_mapping": {"last_inspection_date": "last_checked",
                             "inspection_status": "state"},
    }]).status_code == 200

    r = client.delete(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert kind["display_name"] in r.text


def test_an_active_interface_cannot_be_deleted(client: TestClient, fx: Fixture) -> None:
    """p.256's status gate, which every other ontology resource here already
    has and this one did not until a panel tried to explain the rule to
    somebody.

    An interface carries a status for the reason all of them do (0055), and a
    status nothing consults is a label rather than a state - which is worse
    than no status, because it reads as a promise about deletion that nothing
    keeps.
    """
    interface = make_interface(client, fx)
    r = client.put(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub),
        json={"display_name": interface["display_name"],
              "properties": INSPECTABLE, "status": "active"},
    )
    assert r.status_code == 200, r.text

    r = client.delete(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert "deprecated or experimental" in r.text
    assert client.get(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 200, "the refused delete removed it anyway"


def test_deprecating_an_interface_makes_it_deletable_again(
    client: TestClient, fx: Fixture
) -> None:
    """The other half, and the half that makes the refusal a step rather than a
    dead end: the message says what to do, and doing it works."""
    interface = make_interface(client, fx)
    for status in ("active", "deprecated"):
        assert client.put(
            f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub),
            json={"display_name": interface["display_name"],
                  "properties": INSPECTABLE, "status": status,
                  "deprecation": {"reason": "folded into Trackable"}
                  if status == "deprecated" else None},
        ).status_code == 200

    r = client.delete(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 204, r.text


def test_an_experimental_interface_in_use_is_still_refused(
    client: TestClient, fx: Fixture
) -> None:
    """Two refusals rather than one, and passing the first does not clear the
    second - the ordering means an implemented interface at the default status
    still reports the thing that actually blocks it."""
    interface = make_interface(client, fx)
    assert interface["status"] == "experimental"
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    assert implement(client, fx, kind["id"], [{
        "interface_id": interface["id"],
        "property_mapping": {"last_inspection_date": "last_checked",
                             "inspection_status": "state"},
    }]).status_code == 200

    r = client.delete(
        f"{wbase(fx)}/interfaces/{interface['id']}", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 422, r.text
    assert kind["display_name"] in r.text


# ---- the panel's offer against the server's vocabulary (§190's pattern) ----
def _web(*parts: str) -> str:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return open(os.path.join(root, "web", "src", *parts), encoding="utf-8").read()


#: Base types the *object type editor* does not offer, each because the dialog
#: has no way to complete the declaration - the reasons are written out beside
#: `PROPERTY_TYPES` in `object-type-editor.tsx`. Named here so a new base type
#: with no editor is a failing test rather than a silent gap.
EDITOR_GAPS = {"attachment", "time_series"}


def test_every_base_type_is_offered_or_deliberately_held_back() -> None:
    """The interface property dropdown is `PROPERTY_TYPES` minus
    `NOT_INTERFACE_TYPES`, and both lists are in the browser while the
    vocabulary they narrow is here.

    Guarding against **the server's own list** rather than a second copy of it
    is the point (§191): a base type added to `ontology.PROPERTY_TYPES` is
    invisible to a test that only compares the two browser lists to each other.
    """
    import re

    offered = set(re.findall(
        r'"([a-z_]+)"',
        re.search(
            r"export const PROPERTY_TYPES: PropertyDataType\[\] = \[(.*?)\];",
            _web("components", "object-type-editor.tsx"), re.S,
        ).group(1),
    ))
    assert offered, "PROPERTY_TYPES not found - has object-type-editor.tsx moved?"

    excluded = set(re.findall(
        r'"([a-z_]+)"',
        re.search(
            r"export const NOT_INTERFACE_TYPES: string\[\] = \[(.*?)\];",
            _web("lib", "interfaces.ts"), re.S,
        ).group(1),
    ))
    assert excluded, (
        "NOT_INTERFACE_TYPES not found or empty - it is a subtraction with a "
        "written reason, and an empty one would make this test vacuous"
    )

    server = set(ontology_service.PROPERTY_TYPES)
    assert offered <= server, (
        "the editor offers base types the server does not accept: "
        f"{sorted(offered - server)}"
    )
    assert excluded <= server, (
        f"NOT_INTERFACE_TYPES names something that is not a base type: "
        f"{sorted(excluded - server)}"
    )
    assert server - offered == EDITOR_GAPS, (
        "a base type is neither offered by the object type editor nor listed "
        f"as a gap with a reason: {sorted((server - offered) ^ EDITOR_GAPS)}"
    )


def test_the_interface_dropdown_is_narrower_than_the_object_type_one() -> None:
    """The vacuity guard on the test above.

    If `NOT_INTERFACE_TYPES` ever became empty the subtraction would still
    pass every assertion there while offering `struct` again - an interface
    property whose promise `check_implementation` cannot check, because it
    compares base types and a struct's promise is its fields.
    """
    import re

    excluded = set(re.findall(
        r'"([a-z_]+)"',
        re.search(
            r"export const NOT_INTERFACE_TYPES: string\[\] = \[(.*?)\];",
            _web("lib", "interfaces.ts"), re.S,
        ).group(1),
    ))
    assert "struct" in excluded


def test_a_struct_interface_property_would_promise_nothing(
    client: TestClient, fx: Fixture
) -> None:
    """Why `struct` is off that list, stated as the failure it would cause.

    The server **accepts** the declaration - `interface_properties.data_type`
    is the full `property_data_type` enum - and then `check_implementation`
    compares base types, so any struct at all satisfies it. This test asserts
    that hole exists rather than pretending it does not, and the dropdown is
    where it is closed.
    """
    interfaces_service.check_implementation(
        interface_name="Addressable",
        required=[{"api_name": "address", "data_type": "struct", "required": True}],
        property_types={"postal": "struct"},
        mapping={"address": "postal"},
    )  # no refusal, whatever fields either side declares


def test_an_interface_that_is_not_here_is_404_rather_than_500(
    client: TestClient, fx: Fixture
) -> None:
    """§9's rule - an id not in this workspace is *not found*, so the answer
    does not say whether it exists somewhere else.

    §251 raised a bare `LookupError` and nothing caught it, so every read of a
    missing interface was a 500 - including the edit dialog reopening one
    somebody deleted in another tab. Nothing had ever asked for one until §254
    wrote a scope test.
    """
    for path in (
        f"{wbase(fx)}/interfaces/{uuid.uuid4()}",
        f"{wbase(fx)}/object-types/{uuid.uuid4()}/interfaces",
    ):
        r = client.get(path, headers=hdr(fx.viewer_sub))
        assert r.status_code == 404, f"{path} -> {r.status_code} {r.text}"


def test_a_viewer_cannot_declare_an_interface(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.viewer_sub),
        json={"api_name": "Readable", "display_name": "Readable"},
    )
    assert r.status_code == 403, r.text


def test_two_interfaces_cannot_share_a_name(client: TestClient, fx: Fixture) -> None:
    made = make_interface(client, fx)
    r = client.post(
        f"{wbase(fx)}/interfaces", headers=hdr(fx.editor_sub),
        json={"api_name": made["api_name"], "display_name": "Another"},
    )
    assert r.status_code == 422, r.text
    assert "already exists" in r.text


def test_an_interface_is_findable_by_name(client: TestClient, fx: Fixture) -> None:
    """p.28 lists interfaces among the seven kinds the header search covers, and
    §167 made the argument for closing this window fast: a shape somebody
    cannot find by name is a shape they declare a second time.

    The count that comes back is **implementations**, not properties, for the
    reason a group reports members: "3 object types" is what somebody is
    deciding on when the name comes back.
    """
    tag = uuid.uuid4().hex[:6]
    made = make_interface(
        client, fx, api_name=f"Schedulable{tag}", display_name=f"Schedulable {tag}"
    )
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    assert implement(client, fx, kind["id"], [{
        "interface_id": made["id"],
        "property_mapping": {"last_inspection_date": "last_checked",
                             "inspection_status": "state"},
    }]).status_code == 200

    r = client.get(
        f"{wbase(fx)}/ontology-search?q=Schedulable{tag}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    hits = [h for h in r.json() if h["kind"] == "interface"]
    assert [h["id"] for h in hits] == [made["id"]]
    assert hits[0]["usage_count"] == 1
    # It belongs to no object type, and a made-up owner would send whoever
    # clicked it somewhere unrelated to what they searched for.
    assert hits[0]["object_type_id"] is None


def test_the_object_type_listing_carries_what_each_type_implements(
    client: TestClient, fx: Fixture
) -> None:
    """A listing answers "what is this", and an implements list is part of the
    answer — the same slot p.262's groups occupy on the same row.

    **Names only, not the mapping.** How a type satisfies an interface is the
    answer to "how", which belongs on the type's own page; a list endpoint that
    carried every detail would be a detail endpoint that happens to return
    several rows, which is the argument `hidden_properties` already makes on
    this model.
    """
    interface = make_interface(client, fx)
    kind = make_type(client, fx, [
        {"api_name": "last_checked", "display_name": "Last checked",
         "data_type": "date"},
        {"api_name": "state", "display_name": "State", "data_type": "string"},
    ])
    other = make_type(client, fx, [])
    assert implement(client, fx, kind["id"], [{
        "interface_id": interface["id"],
        "property_mapping": {"last_inspection_date": "last_checked",
                             "inspection_status": "state"},
    }]).status_code == 200

    rows = client.get(
        f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub)
    ).json()
    by_id = {t["id"]: t for t in rows}
    assert [i["api_name"] for i in by_id[kind["id"]]["interfaces"]] == [
        interface["api_name"]
    ]
    # Two-sided: a listing that put every interface on every row would pass a
    # test that only looked at the implementing type.
    assert by_id[other["id"]]["interfaces"] == []
