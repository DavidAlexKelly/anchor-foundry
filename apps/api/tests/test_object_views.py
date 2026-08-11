"""Configured Object Views (parity `docs/parity/ontology.md` §4.2; Foundry
`object-views` p.2-4).

> "Configured Object Views are fully customizable representations of an object
> built using Workshop." (p.2)

What is worth testing here is not that a row can be written - it is the four
refusals that stop somebody configuring a view nobody could open, and the one
rule p.2 states outright: the standard view stays reachable, always.
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


def pbase(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


@pytest.fixture(scope="module")
def type_id(client: TestClient, fx: Fixture) -> str:
    r = client.post(
        f"{wbase(fx)}/object-types",
        headers=hdr(fx.editor_sub),
        json={
            "api_name": f"viewed_{uuid.uuid4().hex[:8]}",
            "display_name": f"Viewed {fx.tag}",
            "properties": [{"api_name": "status", "data_type": "string"}],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def make_module(client: TestClient, fx: Fixture, *, variables: dict) -> str:
    """A Workshop module with the given variables, saved and published.

    Published because that is what an object view has to be: it is read by
    whoever can read the object, and an unpublished module is readable only
    inside its own project.
    """
    r = client.post(
        f"{pbase(fx)}/canvas-apps",
        headers=hdr(fx.editor_sub),
        json={"name": f"View {uuid.uuid4().hex[:8]}"},
    )
    assert r.status_code == 201, r.text
    app_id = r.json()["id"]
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{app_id}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "definition": {
                "format": 2,
                "layout": {"ROOT": {"type": "Container", "nodes": []}},
                "variables": variables,
                "events": {},
            }
        },
    )
    assert r.status_code == 200, r.text
    r = client.put(
        f"{pbase(fx)}/canvas-apps/{app_id}/publish",
        headers=hdr(fx.admin_sub),
        json={"scope": "workspace"},
    )
    assert r.status_code == 200, r.text
    return app_id


@pytest.fixture(scope="module")
def module_id(client: TestClient, fx: Fixture) -> str:
    return make_module(
        client, fx,
        variables={"v_obj": {"id": "v_obj", "kind": "single_object", "label": "The object"}},
    )


def test_a_type_with_no_configured_view_answers_null(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    """**Null, not 404.** Every object screen asks this on the way to rendering
    something, and "no configured view" is the ordinary answer - p.10's
    standard view is what happens next, not an error page."""
    r = client.get(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200
    assert r.json() is None


def test_a_module_becomes_the_view_and_can_be_taken_back_off(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    """The round trip, and p.2's rule that clearing it is not a deletion: the
    module is still there afterwards, and the standard view - which was never
    stored - is what the reader gets again."""
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": module_id, "subject_variable": "v_obj"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["canvas_app_id"] == module_id
    assert r.json()["subject_variable"] == "v_obj"
    assert r.json()["form_factor"] == "full"

    r = client.get(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub))
    assert r.json()["canvas_app_id"] == module_id

    assert client.delete(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.get(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub)
    ).json() is None
    # The module survives being un-nominated - it was never this table's to
    # delete.
    assert client.get(
        f"{pbase(fx)}/canvas-apps/{module_id}", headers=hdr(fx.editor_sub)
    ).status_code == 200


def test_setting_a_view_twice_replaces_rather_than_conflicts(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    """One view per type and form factor. A second PUT is somebody changing
    their mind, not a collision - refusing it would mean clearing the old one
    first, which leaves the type on its standard view in between."""
    other = make_module(
        client, fx,
        variables={"v_thing": {"id": "v_thing", "kind": "single_object", "label": "Thing"}},
    )
    for app_id, variable in ((module_id, "v_obj"), (other, "v_thing")):
        r = client.put(
            f"{wbase(fx)}/object-types/{type_id}/view",
            headers=hdr(fx.editor_sub),
            json={"canvas_app_id": app_id, "subject_variable": variable},
        )
        assert r.status_code == 200, r.text
    view = client.get(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub)
    ).json()
    assert view["canvas_app_id"] == other
    assert view["subject_variable"] == "v_thing"
    client.delete(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub))


def test_a_variable_that_does_not_hold_an_object_is_refused(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    """The binding *is* the variable. A string variable would receive the
    object and have nowhere to put it, and every widget reading the object
    would render nothing - which reads as no data rather than as a
    misconfigured view."""
    module = make_module(
        client, fx,
        variables={"v_txt": {"id": "v_txt", "kind": "string", "label": "Text"}},
    )
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": module, "subject_variable": "v_txt"},
    )
    assert r.status_code == 422
    assert "single-object variable" in r.text


def test_a_variable_the_module_does_not_declare_is_refused(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": module_id, "subject_variable": "v_missing"},
    )
    assert r.status_code == 422
    assert "single-object variable" in r.text


def test_an_unpublished_module_is_refused(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    """An object view is read by whoever can read the object; an unpublished
    module is readable only inside its own project. Allowing it would configure
    a view that renders for its author and 404s for everybody else - which is
    the shape of failure nobody reports as a permission problem."""
    r = client.post(
        f"{pbase(fx)}/canvas-apps",
        headers=hdr(fx.editor_sub),
        json={"name": f"Private {uuid.uuid4().hex[:8]}"},
    )
    app_id = r.json()["id"]
    client.put(
        f"{pbase(fx)}/canvas-apps/{app_id}/definition",
        headers=hdr(fx.editor_sub),
        json={
            "definition": {
                "format": 2,
                "layout": {"ROOT": {"type": "Container", "nodes": []}},
                "variables": {"v_obj": {"id": "v_obj", "kind": "single_object", "label": "O"}},
                "events": {},
            }
        },
    )
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": app_id, "subject_variable": "v_obj"},
    )
    assert r.status_code == 422
    assert "publish this module" in r.text


def test_a_module_this_workspace_does_not_have_is_refused(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": str(uuid.uuid4()), "subject_variable": "v_obj"},
    )
    assert r.status_code == 404


def test_an_unknown_form_factor_is_refused(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    """`full` and `panel` are p.3-4's two. A third would be stored by the enum
    only as an error, and this says so where somebody can read it."""
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": module_id, "subject_variable": "v_obj",
              "form_factor": "sidebar"},
    )
    assert r.status_code == 422
    assert "form factor" in r.text


def test_the_two_form_factors_are_separate_views(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    """p.3-4: Full is "comprehensive", Panel is "for embedding in other
    applications, focused on critical data". Two different screens of the same
    object, so setting one must not disturb the other."""
    panel = make_module(
        client, fx,
        variables={"v_p": {"id": "v_p", "kind": "single_object", "label": "Panel object"}},
    )
    for app_id, variable, factor in (
        (module_id, "v_obj", "full"), (panel, "v_p", "panel")
    ):
        r = client.put(
            f"{wbase(fx)}/object-types/{type_id}/view",
            headers=hdr(fx.editor_sub),
            json={"canvas_app_id": app_id, "subject_variable": variable,
                  "form_factor": factor},
        )
        assert r.status_code == 200, r.text

    full = client.get(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub)
    ).json()
    assert full["canvas_app_id"] == module_id
    other = client.get(
        f"{wbase(fx)}/object-types/{type_id}/view?form_factor=panel",
        headers=hdr(fx.viewer_sub),
    ).json()
    assert other["canvas_app_id"] == panel

    # And clearing one leaves the other, for the same reason.
    assert client.delete(
        f"{wbase(fx)}/object-types/{type_id}/view?form_factor=panel",
        headers=hdr(fx.editor_sub),
    ).status_code == 204
    assert client.get(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub)
    ).json()["canvas_app_id"] == module_id
    client.delete(f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub))


def test_a_viewer_cannot_configure_a_view(
    client: TestClient, fx: Fixture, type_id: str, module_id: str
) -> None:
    """Same floor as editing the object type itself: configuring a view changes
    what every reader of that type sees."""
    r = client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.viewer_sub),
        json={"canvas_app_id": module_id, "subject_variable": "v_obj"},
    )
    assert r.status_code == 403


def test_clearing_a_view_that_is_not_there_is_a_404(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    assert client.delete(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.editor_sub)
    ).status_code == 404


def test_an_unknown_object_type_is_a_404(client: TestClient, fx: Fixture) -> None:
    assert client.get(
        f"{wbase(fx)}/object-types/{uuid.uuid4()}/view", headers=hdr(fx.viewer_sub)
    ).status_code == 404


def test_deleting_the_module_takes_the_view_with_it(
    client: TestClient, fx: Fixture, type_id: str
) -> None:
    """ON DELETE CASCADE, not SET NULL. A view pointing at a module that no
    longer exists is a configured view that renders nothing, and the standard
    view it was standing in front of is the better answer."""
    module = make_module(
        client, fx,
        variables={"v_o": {"id": "v_o", "kind": "single_object", "label": "O"}},
    )
    assert client.put(
        f"{wbase(fx)}/object-types/{type_id}/view",
        headers=hdr(fx.editor_sub),
        json={"canvas_app_id": module, "subject_variable": "v_o"},
    ).status_code == 200
    assert client.delete(
        f"{pbase(fx)}/canvas-apps/{module}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert client.get(
        f"{wbase(fx)}/object-types/{type_id}/view", headers=hdr(fx.viewer_sub)
    ).json() is None
