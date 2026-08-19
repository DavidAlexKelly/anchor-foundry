"""Value types end to end (parity `docs/parity/ontology.md` §1.2; Foundry
`object-link-types` p.222-234).

`test_value_constraints.py` covers what a constraint *means*, purely. This
covers the parts that need a database: the versioning rule p.229 sets out, the
attachment p.227 allows in two places, and the two moments a constraint is
actually enforced.

**The enforcement split is this platform's, and it is a deliberate divergence.**
p.227 says an object type with failing values "will fail to index" - which would
take the whole type off every screen because one row is wrong. §154 already
chose the other way for required properties, following p.116's own split, and
this follows it: **the sync reports, the action refuses.**
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


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("value-types")))
    )
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


def make_value_type(client: TestClient, fx: Fixture, **over) -> dict:
    body = {
        "api_name": f"email_{uuid.uuid4().hex[:6]}",
        "display_name": "Email address",
        "description": "A working email address",
        "example_value": "ada@example.com",
        "base_type": "string",
        "constraint": {"kind": "regex", "pattern": r"[a-z]+@example\.com"},
        **over,
    }
    r = client.post(f"{wbase(fx)}/value-types", headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()


def make_type(client: TestClient, fx: Fixture, properties: list[dict]) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"contact_{tag}",
            "display_name": f"Contact {tag}",
            "properties": properties,
            "title_property": properties[0]["api_name"],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def prop_of(detail: dict, api_name: str) -> dict:
    return next(p for p in detail["properties"] if p["api_name"] == api_name)


# ---- the definition and its versions (p.224, p.229) -------------------------
def test_a_value_type_is_created_with_version_one(client: TestClient, fx: Fixture) -> None:
    vt = make_value_type(client, fx)
    assert vt["version_number"] == 1
    assert vt["base_type"] == "string"
    assert vt["constraint"]["kind"] == "regex"
    # p.225 step 7's preview value, and the sentence a listing can show.
    assert vt["example_value"] == "ada@example.com"
    assert "matches" in vt["constraint_summary"]


def test_a_value_type_may_carry_meaning_without_a_constraint(
    client: TestClient, fx: Fixture
) -> None:
    """p.224 step 6 marks the constraint "(Optional)". p.222's first argument
    for value types is the *meaning* they carry - "each property that uses this
    value type is explicitly understood to contain an email address" - and that
    survives having no rule to check."""
    vt = make_value_type(client, fx, constraint=None)
    assert vt["constraint"] is None
    assert vt["constraint_summary"] == "no constraint"


def test_editing_the_metadata_does_not_make_a_version(
    client: TestClient, fx: Fixture
) -> None:
    """p.229: "The metadata values for name, description, and apiName can be
    changed whenever necessary." Only the constraint is versioned, so a typo
    fixed in a description should not leave a version somebody has to read."""
    vt = make_value_type(client, fx)
    r = client.patch(
        f"{wbase(fx)}/value-types/{vt['id']}",
        headers=hdr(fx.editor_sub),
        json={"display_name": "Email", "description": "Renamed",
              "example_value": "grace@example.com"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "Email"
    assert r.json()["version_number"] == 1, "metadata is not versioned"


def test_changing_the_constraint_appends_a_version(
    client: TestClient, fx: Fixture
) -> None:
    """p.229: "If you choose to update the constraints of a value type, a new
    version of the value type is created." The old rule stays readable, which
    is the whole reason for making constraints immutable."""
    vt = make_value_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/value-types/{vt['id']}/versions",
        headers=hdr(fx.editor_sub),
        json={"constraint": {"kind": "regex", "pattern": r"[a-z.]+@example\.(com|org)"}},
    )
    assert r.status_code == 201, r.text
    assert r.json()["version_number"] == 2

    versions = client.get(
        f"{wbase(fx)}/value-types/{vt['id']}/versions", headers=hdr(fx.viewer_sub)
    ).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    # The first version still says what it said.
    assert versions[1]["constraint"]["pattern"] == r"[a-z]+@example\.com"


def test_a_version_that_changes_nothing_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """A version recording no change is a version somebody has to read to
    discover it says the same thing."""
    vt = make_value_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/value-types/{vt['id']}/versions",
        headers=hdr(fx.editor_sub),
        json={"constraint": vt["constraint"]},
    )
    assert r.status_code == 422, r.text
    assert "already has" in r.text


def test_the_base_type_cannot_be_changed_by_any_route(
    client: TestClient, fx: Fixture
) -> None:
    """p.229 calls the base type immutable alongside the constraints, and it is
    the stronger claim: a value type whose base type changed would be attached
    to properties it can no longer describe, and all of them would start
    failing at once. Neither endpoint takes the field, and a new version
    inherits it."""
    vt = make_value_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/value-types/{vt['id']}/versions",
        headers=hdr(fx.editor_sub),
        json={"constraint": {"kind": "range", "minimum": 1}},
    )
    # A range on a string is a *length* range and is legal; the point is that
    # it was parsed against `string`, the base type it already had.
    assert r.status_code == 201, r.text
    assert r.json()["base_type"] == "string"


def test_a_constraint_that_does_not_fit_the_base_type_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    r = client.post(
        f"{wbase(fx)}/value-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"score_{uuid.uuid4().hex[:6]}", "display_name": "Score",
              "base_type": "integer",
              "constraint": {"kind": "regex", "pattern": "^x$"}},
    )
    assert r.status_code == 422, r.text
    assert "does not apply" in r.text


def test_two_value_types_cannot_share_a_name(client: TestClient, fx: Fixture) -> None:
    vt = make_value_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/value-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": vt["api_name"], "display_name": "Other",
              "base_type": "string"},
    )
    assert r.status_code == 409, r.text


def test_a_viewer_cannot_create_or_delete_one(client: TestClient, fx: Fixture) -> None:
    vt = make_value_type(client, fx)
    assert client.post(
        f"{wbase(fx)}/value-types", headers=hdr(fx.viewer_sub),
        json={"api_name": "nope", "display_name": "Nope", "base_type": "string"},
    ).status_code == 403
    assert client.delete(
        f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 403


# ---- attaching one (p.227) ---------------------------------------------------
def test_a_property_carries_its_value_types_current_constraint(
    client: TestClient, fx: Fixture
) -> None:
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    prop = prop_of(read_type(client, fx, created["id"]), "email")
    assert prop["value_type_id"] == vt["id"]
    assert prop["value_type_api_name"] == vt["api_name"]
    assert prop["value_constraint"]["pattern"] == r"[a-z]+@example\.com"


def test_a_new_version_reaches_the_properties_already_using_it(
    client: TestClient, fx: Fixture
) -> None:
    """p.230: a new version "will automatically propagate to the Ontology,
    ensuring that all uses of the value type across the Ontology are updated to
    the latest version".

    A property references the value type, never a version, so this is the test
    that a resolved-at-read implementation actually resolves - a stored copy
    would pass every test that only reads back what it wrote.
    """
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    assert client.post(
        f"{wbase(fx)}/value-types/{vt['id']}/versions",
        headers=hdr(fx.editor_sub),
        json={"constraint": {"kind": "regex", "pattern": "^changed$"}},
    ).status_code == 201
    prop = prop_of(read_type(client, fx, created["id"]), "email")
    assert prop["value_constraint"]["pattern"] == "^changed$"


def test_a_value_type_of_the_wrong_base_type_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """p.222's proposition is that the value type *is* the type. An email
    (string) value type on an integer property would reject every row - p.227's
    "will fail to index", arriving on a screen rather than on the save."""
    vt = make_value_type(client, fx)
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"contact_{tag}", "display_name": "Contact",
              "properties": [
                  {"api_name": "name", "data_type": "string"},
                  {"api_name": "score", "data_type": "integer",
                   "value_type_id": vt["id"]},
              ]},
    )
    assert r.status_code == 422, r.text
    assert "is a string" in r.text


def test_a_value_type_from_nowhere_is_refused(client: TestClient, fx: Fixture) -> None:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"contact_{tag}", "display_name": "Contact",
              "properties": [{"api_name": "name", "data_type": "string",
                              "value_type_id": str(uuid.uuid4())}]},
    )
    assert r.status_code == 422, r.text
    assert "no value type" in r.text


def test_a_property_inherits_its_shared_propertys_value_type(
    client: TestClient, fx: Fixture
) -> None:
    """p.227 allows a value type on a shared property too. A property attached
    to that shared property is then constrained without having chosen a value
    type itself - and the two ids are reported apart, because echoing the
    inherited one back on a save would quietly make it a local choice."""
    vt = make_value_type(client, fx)
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"contact_email_{uuid.uuid4().hex[:6]}",
              "display_name": "Contact email", "data_type": "string",
              "value_type_id": vt["id"]},
    )
    assert r.status_code == 201, r.text
    shared = r.json()
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string",
          "shared_property_id": shared["id"]}],
    )
    prop = prop_of(read_type(client, fx, created["id"]), "email")
    assert prop["value_type_id"] is None, "it did not choose one itself"
    assert prop["effective_value_type_id"] == vt["id"]
    assert prop["value_constraint"] is not None


def test_the_editor_can_save_back_what_it_read(client: TestClient, fx: Fixture) -> None:
    """The read-modify-write round trip. §163 shipped an API that could not
    accept its own output, and this is the check that stops a repeat."""
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    detail = read_type(client, fx, created["id"])
    r = client.patch(
        f"{wbase(fx)}/object-types/{created['id']}",
        headers=hdr(fx.editor_sub),
        json={
            "display_name": "Edited",
            "properties": [
                {k: v for k, v in p.items()
                 if k not in ("id", "sort_order", "shared_property_api_name",
                              "value_type_api_name", "value_constraint",
                              "effective_value_type_id")}
                for p in detail["properties"]
            ],
            "title_property": "name",
        },
    )
    assert r.status_code == 200, r.text
    assert prop_of(read_type(client, fx, created["id"]), "email")["value_type_id"] == vt["id"]


def test_deleting_a_value_type_unconstrains_rather_than_deletes(
    client: TestClient, fx: Fixture
) -> None:
    """The same shape as p.185's shared property delete: the properties survive
    with everything except the reference. Deleting a reusable definition must
    not take the properties that used it - and their instances' values - out of
    every application that reads them."""
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    assert client.delete(
        f"{wbase(fx)}/value-types/{vt['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    detail = read_type(client, fx, created["id"])
    assert {p["api_name"] for p in detail["properties"]} == {"name", "email"}
    prop = prop_of(detail, "email")
    assert prop["value_type_id"] is None
    assert prop["value_constraint"] is None


def test_usage_names_both_of_the_places_a_value_type_can_be_used(
    client: TestClient, fx: Fixture
) -> None:
    """p.227 names two, and they are different enough that a row has to say
    which it is - "email on Contact" and "the contact_email shared property"
    are different things to go and look at."""
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "name", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    r = client.post(
        f"{wbase(fx)}/shared-properties",
        headers=hdr(fx.editor_sub),
        json={"api_name": f"shared_email_{uuid.uuid4().hex[:6]}",
              "display_name": "Shared email", "data_type": "string",
              "value_type_id": vt["id"]},
    )
    assert r.status_code == 201, r.text

    rows = client.get(
        f"{wbase(fx)}/value-types/{vt['id']}/usage", headers=hdr(fx.viewer_sub)
    ).json()
    kinds = {row["kind"] for row in rows}
    assert kinds == {"object_type_property", "shared_property"}
    on_type = next(r for r in rows if r["kind"] == "object_type_property")
    assert on_type["object_type_id"] == created["id"]
    assert on_type["property_api_name"] == "email"
    # And the count on the value type agrees with the list.
    listed = client.get(
        f"{wbase(fx)}/value-types", headers=hdr(fx.viewer_sub)
    ).json()
    assert next(v for v in listed if v["id"] == vt["id"])["usage_count"] == len(rows)


# ---- enforcement: the sync reports (p.227, and §154's split) ----------------
CONTACTS = b"id,email\n1,ada@example.com\n2,not-an-email\n3,grace@example.com\n"


def test_a_sync_reports_the_rows_that_break_the_constraint(
    client: TestClient, fx: Fixture
) -> None:
    """**The divergence, tested.** p.227 says the object type "will fail to
    index"; this reports instead, so two good rows are still browsable and the
    bad one is named. The example is what makes the report actionable - "412
    rows failed" sends somebody to read 412 rows."""
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "id", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Contacts {uuid.uuid4().hex[:6]}"},
        files={"file": ("contacts.csv", io.BytesIO(CONTACTS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset_id = r.json()["id"]
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": created["id"], "dataset_id": dataset_id,
              "primary_key_column": "id",
              "column_mappings": {"id": "id", "email": "email"}},
    )
    assert r.status_code == 201, r.text
    source_id = r.json()["id"]

    r = client.post(
        f"{pbase(fx)}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["ok"] is True, "one bad row does not fail the sync"
    assert result["upserted"] == 3, "and the good rows still index"
    assert result["constraint_violations"]["email"]["count"] == 1
    assert "not-an-email" in result["constraint_violations"]["email"]["example"]


def test_a_sync_of_compliant_data_reports_nothing(
    client: TestClient, fx: Fixture
) -> None:
    """A report that is never empty is a report nobody reads."""
    vt = make_value_type(client, fx)
    created = make_type(
        client, fx,
        [{"api_name": "id", "data_type": "string"},
         {"api_name": "email", "data_type": "string", "value_type_id": vt["id"]}],
    )
    good = b"id,email\n1,ada@example.com\n"
    r = client.post(
        f"{pbase(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Good {uuid.uuid4().hex[:6]}"},
        files={"file": ("good.csv", io.BytesIO(good), "text/csv")},
    )
    dataset_id = r.json()["id"]
    r = client.post(
        f"{pbase(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": created["id"], "dataset_id": dataset_id,
              "primary_key_column": "id",
              "column_mappings": {"id": "id", "email": "email"}},
    )
    source_id = r.json()["id"]
    r = client.post(
        f"{pbase(fx)}/object-type-sources/{source_id}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text
    assert r.json()["constraint_violations"] == {}


# ---- enforcement: an action refuses (p.222, and §154's split) ---------------
def test_an_action_that_writes_a_bad_value_is_refused() -> None:
    """The other half of the split. §154 tests `check_required` at this level
    for the same reason: the rule is a pure function of what the action writes
    and what the type declares, and driving a whole apply to reach it would
    test the plumbing rather than the rule."""
    from src.services import actions as actions_service

    constrained = {
        "email": ("string", {"kind": "regex", "pattern": r"[a-z]+@example\.com",
                             "substring": False})
    }
    with pytest.raises(ValueError, match="fails its value type"):
        actions_service.check_constraints({"email": "nope"}, constrained)
    # And the message says why, not just that.
    try:
        actions_service.check_constraints({"email": "nope"}, constrained)
    except ValueError as exc:
        assert "does not match" in str(exc)


def test_an_action_that_writes_a_good_value_is_allowed() -> None:
    from src.services import actions as actions_service

    constrained = {
        "email": ("string", {"kind": "regex", "pattern": r"[a-z]+@example\.com",
                             "substring": False})
    }
    actions_service.check_constraints({"email": "ada@example.com"}, constrained)


def test_an_action_is_not_judged_on_what_it_does_not_write() -> None:
    """**The line §154 already drew**, and the reason it matters here too: a
    row that was already non-compliant is the sync's business to report.
    Refusing on the strength of a value the action is not touching would make
    the one action that could fix an object the one action that cannot run."""
    from src.services import actions as actions_service

    constrained = {"email": ("string", {"kind": "uuid"})}
    actions_service.check_constraints({"note": "unrelated"}, constrained)


def test_a_property_with_no_constraint_is_not_checked() -> None:
    from src.services import actions as actions_service

    actions_service.check_constraints({"email": "anything"}, {})


def test_constrained_properties_reads_the_resolved_constraint() -> None:
    """`constrained_properties` is what both enforcement points are built on,
    and it reads `value_constraint` - the field `list_properties` resolves from
    the value type's *current* version (p.230). A property whose value type has
    no constraint is absent rather than present with None: it carries meaning
    without a rule, and there is nothing to check."""
    from src.services import ontology as ontology_service

    rule = {"kind": "uuid"}
    properties = [
        {"api_name": "email", "data_type": "string", "value_constraint": rule},
        {"api_name": "note", "data_type": "string", "value_constraint": None},
        {"api_name": "other", "data_type": "string"},
    ]
    assert ontology_service.constrained_properties(properties) == {
        "email": ("string", rule)
    }
