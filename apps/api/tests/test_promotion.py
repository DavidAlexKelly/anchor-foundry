"""Who may promote, and what promoting does (parity `docs/parity/ontology.md`
§1.3; Foundry `object-link-types` p.255).

Two sentences of p.255 that §170 read past, and one deliberate divergence.

> "Only users with the `Ontology Owner` role on the ontology level can directly
> apply the `promoted` status." (p.255)

**The ontology level is a role this platform already had.** A workspace is this
platform's ontology (db 0003) and `workspace_role` has an `admin` tier above
editor, so p.255's requirement is a floor rather than a new permission system.
Foundry's own Ontology-roles chapter (`ontology-manager` p.43) is marked legacy
and superseded by "the Compass filesystem" - its project/folder permissions -
so a per-resource role registry here would have replicated the model Palantir
is migrating off. The divergence to hold in mind: our admin is workspace-wide
where Foundry's Ontology Owner is per resource, which is stricter rather than
looser.

> "Setting an object type's status to `promoted` will automatically set its
> visibility to `prominent`." (p.255)

**The trap this feature could have been.** The type editor sends the whole
definition on every save, so an editor pressing Save on an already-promoted
type sends `promoted` without asking for anything. Gating on the value rather
than on the *transition* would lock every editor out of every promoted type -
turning p.255's protection into a rule that makes the most important object
types uneditable by the people who build them. There is a test named after
that, and it is the one worth keeping.
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


def make_type(client: TestClient, fx: Fixture) -> dict:
    tag = uuid.uuid4().hex[:6]
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"thing_{tag}",
            "display_name": f"Thing {tag}",
            "properties": [{"api_name": "name", "data_type": "string"}],
            "title_property": "name",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def read_type(client: TestClient, fx: Fixture, type_id: str) -> dict:
    r = client.get(f"{wbase(fx)}/object-types/{type_id}", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def save(client: TestClient, fx: Fixture, detail: dict, *, sub: str, **over):
    body = {
        "display_name": detail["display_name"],
        "properties": [
            {k: v for k, v in p.items()
             if k in ("api_name", "data_type", "required", "description",
                      "visibility", "status", "deprecation")}
            for p in detail["properties"]
        ],
        "title_property": detail["properties"][0]["api_name"],
        **over,
    }
    return client.patch(
        f"{wbase(fx)}/object-types/{detail['id']}", headers=hdr(sub), json=body
    )


# ---- p.255's permission sentence -------------------------------------------
def test_an_editor_cannot_promote(client: TestClient, fx: Fixture) -> None:
    """p.255: "Only users with the `Ontology Owner` role on the ontology level
    can directly apply the `promoted` status." """
    created = make_type(client, fx)
    r = save(client, fx, read_type(client, fx, created["id"]),
             sub=fx.editor_sub, status="promoted")
    assert r.status_code == 422, r.text
    # The refusal names both the role and the way round it, because p.255's
    # own answer for everybody else is "ask an owner".
    assert "admin" in r.text and "active" in r.text
    assert read_type(client, fx, created["id"])["status"] == "experimental"


def test_an_admin_can_promote(client: TestClient, fx: Fixture) -> None:
    """The other half. A refusal nobody can get past is a feature that is
    simply off."""
    created = make_type(client, fx)
    r = save(client, fx, read_type(client, fx, created["id"]),
             sub=fx.admin_sub, status="promoted")
    assert r.status_code == 200, r.text
    assert read_type(client, fx, created["id"])["status"] == "promoted"


def test_an_editor_may_still_edit_a_promoted_type(
    client: TestClient, fx: Fixture
) -> None:
    """**The trap this could have been.**

    The editor sends the whole definition on every save, so an editor pressing
    Save on an already-promoted type sends `promoted` without asking for
    anything. Gating on the value rather than the transition would make the
    most important object types uneditable by the people who build them -
    p.255's protection turned into a lockout.
    """
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200

    detail = read_type(client, fx, created["id"])
    r = save(client, fx, detail, sub=fx.editor_sub,
             status="promoted", description="Edited by an editor")
    assert r.status_code == 200, r.text
    assert read_type(client, fx, created["id"])["description"] == "Edited by an editor"


def test_an_editor_may_demote_a_promoted_type(
    client: TestClient, fx: Fixture
) -> None:
    """p.255 restricts *applying* the status. Stepping down from it is the safe
    direction, and `check_deletable` still stops a promoted type being deleted
    on the way past."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200
    r = save(client, fx, read_type(client, fx, created["id"]),
             sub=fx.editor_sub, status="active")
    assert r.status_code == 200, r.text
    assert read_type(client, fx, created["id"])["status"] == "active"


def test_an_editor_saving_without_a_status_is_untouched(
    client: TestClient, fx: Fixture
) -> None:
    """§170's compatibility rule meeting §175's role floor. A client that says
    nothing about status must not be refused for a status it never mentioned."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200

    detail = read_type(client, fx, created["id"])
    body = {
        "display_name": detail["display_name"],
        "properties": [
            {k: v for k, v in p.items()
             if k in ("api_name", "data_type", "required")}
            for p in detail["properties"]
        ],
        "title_property": "name",
    }
    r = client.patch(
        f"{wbase(fx)}/object-types/{created['id']}",
        headers=hdr(fx.editor_sub), json=body,
    )
    assert r.status_code == 200, r.text
    assert read_type(client, fx, created["id"])["status"] == "promoted"


# ---- p.255's visibility sentence -------------------------------------------
def test_promoting_makes_the_type_prominent(client: TestClient, fx: Fixture) -> None:
    """p.255: "Setting an object type's status to `promoted` will
    automatically set its visibility to `prominent`, increasing its
    discoverability across the platform." """
    created = make_type(client, fx)
    assert read_type(client, fx, created["id"])["visibility"] == "normal"

    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200
    assert read_type(client, fx, created["id"])["visibility"] == "prominent"


def test_demoting_does_not_take_the_prominence_back(
    client: TestClient, fx: Fixture
) -> None:
    """**Raises and never lowers**, the same asymmetry propagation has.

    p.255 describes what promoting *does* and says nothing about demoting
    undoing it. A type somebody deliberately made prominent should not quietly
    stop being so because its status stepped down - that is a second decision,
    and it is theirs.
    """
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.editor_sub, status="active").status_code == 200

    detail = read_type(client, fx, created["id"])
    assert detail["status"] == "active"
    assert detail["visibility"] == "prominent"


def test_an_ordinary_status_change_leaves_visibility_alone(
    client: TestClient, fx: Fixture
) -> None:
    """The rule is about `promoted` and nothing else - a type going active
    stays as discoverable as it was."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.editor_sub, status="active").status_code == 200
    assert read_type(client, fx, created["id"])["visibility"] == "normal"


def test_the_listing_reports_visibility_too(client: TestClient, fx: Fixture) -> None:
    """p.255's stated purpose is discoverability *across the platform*, which
    is a claim about what other screens can see - so it has to be on the list
    endpoint, not only the detail one."""
    created = make_type(client, fx)
    assert save(client, fx, read_type(client, fx, created["id"]),
                sub=fx.admin_sub, status="promoted").status_code == 200

    r = client.get(f"{wbase(fx)}/object-types", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    row = next(t for t in r.json() if t["id"] == created["id"])
    assert row["visibility"] == "prominent"
