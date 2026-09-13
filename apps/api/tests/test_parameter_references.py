"""What a parameter points at, and what that stops you deleting (§339;
db 0083, 0085, 0086; `ontology-manager` p.68-74).

**Three references and one foreign key.** db 0083's `object_type_id` is a real
column with `ON DELETE RESTRICT`; db 0085's walk and db 0086's options document
are jsonb, and a jsonb column cannot carry one. All three migrations say so and
all three name the same ○: §325's cleanup queue is where a type is removed on
purpose, and it did not report an action parameter as a reason one will not go.

What that meant before this file existed, measured rather than assumed:

* deleting a link type a dropdown walks **succeeded** (204), leaving a dropdown
  that cannot be built for whoever next opens the form;
* deleting the object type a parameter's values come from **succeeded** (204),
  leaving a dropdown with nothing in it;
* deleting the object type a parameter *holds* returned **500** — `RESTRICT` is
  the right rule with a message nobody can act on.

So every test here asserts the sentence as well as the refusal. A 409 that does
not say which action, which parameter, and what to change is the same dead end
one status code further along.
"""
from __future__ import annotations

import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from test_action_options import a_type, wbase  # noqa: E402
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


@pytest.fixture(scope="module")
def world(client: TestClient, fx: Fixture):
    """A two-hop walk, so a type in the *middle* of one exists.

    Employees, the issues raised by them, and the repos those issues are in —
    so a parameter offering repo names walks employee → issue → repo. `issue` is
    then a type the walk passes through without being at either end of it, which
    is the reference a scan of the start and the landing type would miss.
    """
    tag = uuid.uuid4().hex[:8]
    employee = a_type(client, fx, f"remp{tag}", [("E1", "Ada")],
                      columns=("id", "name"))
    issue = a_type(client, fx, f"riss{tag}", [("I1", "E1", "R1")],
                   columns=("id", "employee_id", "repo_id"))
    repo = a_type(client, fx, f"rrepo{tag}", [("R1", "core")],
                  columns=("id", "name"))
    ticket = a_type(client, fx, f"rtkt{tag}", [("t1", "x")])

    def link(api_name: str, display: str, to_type: str, column: str) -> str:
        made = client.post(
            f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{api_name}_{tag}", "display_name": display,
                  "from_type_id": issue, "to_type_id": to_type,
                  "cardinality": "one_to_many",
                  "from_property": column, "to_property": "$primary_key"},
        )
        assert made.status_code == 201, made.text
        return made.json()["id"]

    raised_by = link("rraised", "Raised by", employee, "employee_id")
    in_repo = link("rinrepo", "In repo", repo, "repo_id")
    action = client.post(
        f"{wbase(fx)}/action-types", headers=hdr(fx.editor_sub),
        json={"object_type_id": ticket, "api_name": f"rassign_{tag}",
              "display_name": "Assign", "editable_properties": ["label"]},
    )
    assert action.status_code == 201, action.text
    return {"action": action.json()["id"], "employee": employee, "issue": issue,
            "repo": repo, "ticket": ticket,
            "raised_by": raised_by, "in_repo": in_repo}


def define(client, fx, world, parameters, rules=None):
    return client.put(
        f"{wbase(fx)}/action-types/{world['action']}/definition",
        headers=hdr(fx.editor_sub),
        json={"parameters": parameters,
              "rules": rules or [{"kind": "modify_object",
                                  "config": {"property": "label",
                                             "parameter": "name"}}],
              "criteria": []},
    )


def walked(world, **over) -> list[dict]:
    """`who` holds an Employee; `name` offers the repo names reached from them."""
    return [
        {"api_name": "who", "display_name": "Who", "data_type": "object",
         "object_type_id": world["employee"]},
        {"api_name": "name", "display_name": "Repo", "data_type": "string",
         "options_from": {"object_type_id": world["repo"], "property": "name"},
         "dropdown_search_around": {
             "start": {"kind": "parameter",
                       "object_type_id": world["employee"],
                       "parameter": "who"},
             "hops": [{"link_type_id": world["raised_by"]},
                      {"link_type_id": world["in_repo"]}]},
         **over},
    ]


def plain(world) -> list[dict]:
    """The same form with nothing pointing anywhere — the state every refusal
    below is measured against."""
    return [{"api_name": "name", "display_name": "Repo", "data_type": "string"}]


def delete_link(client, fx, link_id):
    return client.delete(f"{wbase(fx)}/link-types/{link_id}",
                         headers=hdr(fx.editor_sub))


def delete_type(client, fx, type_id):
    return client.delete(f"{wbase(fx)}/object-types/{type_id}",
                         headers=hdr(fx.editor_sub))


# ---- link types ----------------------------------------------------------------
def test_a_link_a_dropdown_walks_will_not_go(
    client: TestClient, fx: Fixture, world
) -> None:
    """db 0085's ○, closed. The delete used to return 204 and the walk found
    out about it at the moment somebody opened the form — which puts the
    sentence in front of the one person who cannot act on it."""
    define(client, fx, world, walked(world)).raise_for_status()
    refused = delete_link(client, fx, world["raised_by"])
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "'name'" in detail and "is a link its dropdown follows" in detail
    # The remedy, named: a refusal that does not say what to do is a dead end
    # one status code further along.
    assert "Change the walk first" in detail


def test_a_link_nothing_walks_still_goes(
    client: TestClient, fx: Fixture, world
) -> None:
    """**The negative control.** Without it every assertion above passes for a
    build where link types simply cannot be deleted — and the walk is left in
    place while an *unwalked* link goes, so this is the refusal being specific
    rather than the definition being empty."""
    spare = disposable(client, fx)
    define(client, fx, world, walked(world)).raise_for_status()
    assert delete_link(client, fx, spare["link"]).status_code == 204


def disposable(client, fx):
    """A near type, a far type and the link between them, for one test to
    delete.

    **Its own, rather than the shared world's.** The fixture is module-scoped
    and a walk names its links by id, so a test that deletes one leaves every
    later `define` refusing a link that is gone — which is a 422 about the
    definition, in a test about deletion, and it took three failures to read it
    as that rather than as the refusal misbehaving.
    """
    tag = uuid.uuid4().hex[:8]
    near = a_type(client, fx, f"dnear{tag}", [("n1", "f1")],
                  columns=("id", "far_id"))
    far = a_type(client, fx, f"dfar{tag}", [("f1", "west")],
                 columns=("id", "label"))
    link = client.post(
        f"{wbase(fx)}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"dlink_{tag}", "display_name": "Onto",
              "from_type_id": near, "to_type_id": far,
              "cardinality": "one_to_many",
              "from_property": "far_id", "to_property": "$primary_key"},
    )
    assert link.status_code == 201, link.text
    return {"near": near, "far": far, "link": link.json()["id"]}


def over(spare: dict) -> list[dict]:
    """One parameter offering the far type's labels, reached by one hop."""
    return [{
        "api_name": "name", "display_name": "Label", "data_type": "string",
        "options_from": {"object_type_id": spare["far"], "property": "label"},
        "dropdown_search_around": {
            "start": {"kind": "object_type", "object_type_id": spare["near"]},
            "hops": [{"link_type_id": spare["link"]}]},
    }]


def test_changing_the_walk_lets_the_link_go(
    client: TestClient, fx: Fixture, world
) -> None:
    """The remedy the message names, carried out. A refusal that cannot be
    satisfied is a refusal that is lying about what it wants."""
    spare = disposable(client, fx)
    define(client, fx, world, over(spare)).raise_for_status()
    assert delete_link(client, fx, spare["link"]).status_code == 409
    define(client, fx, world, plain(world)).raise_for_status()
    assert delete_link(client, fx, spare["link"]).status_code == 204


# ---- object types --------------------------------------------------------------
def test_the_type_a_parameter_holds_is_refused_with_a_sentence(
    client: TestClient, fx: Fixture, world
) -> None:
    """db 0083's `ON DELETE RESTRICT` is the right rule and was a **500**: it
    fires inside the DELETE as an integrity error with nothing in it about
    actions or parameters. Asked first, it is a sentence.

    The employee type is also where the walk starts, so both reasons are named
    — a refusal that named one would be answered by removing that one and
    refused again.
    """
    define(client, fx, world, walked(world)).raise_for_status()
    refused = delete_type(client, fx, world["employee"])
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert "'who'" in detail and "is the object type it holds" in detail
    assert "'name'" in detail and "walk starts" in detail


def test_the_type_the_values_come_from_will_not_go(
    client: TestClient, fx: Fixture, world
) -> None:
    """db 0086's ○. This one used to return 204, and the dropdown it describes
    is empty from then on — which the form says out loud, to somebody who
    cannot do anything about it."""
    define(client, fx, world, walked(world)).raise_for_status()
    refused = delete_type(client, fx, world["repo"])
    assert refused.status_code == 409, refused.text
    assert "is where its allowed values come from" in refused.json()["detail"]


def test_a_type_in_the_middle_of_a_walk_will_not_go(
    client: TestClient, fx: Fixture, world
) -> None:
    """**The reference a scan of both ends would miss.** The walk runs
    employee → issue → repo, so deleting `issue` breaks it without that type
    appearing at either end."""
    define(client, fx, world, walked(world)).raise_for_status()
    refused = delete_type(client, fx, world["issue"])
    assert refused.status_code == 409, refused.text
    assert "walk passes through" in refused.json()["detail"]


def test_a_type_no_parameter_points_at_still_goes(
    client: TestClient, fx: Fixture, world
) -> None:
    """The negative control for types, and it has to be a type this workspace
    has — this one is in the same ontology and simply unreferenced.

    Minted here rather than taken from the shared world, for `disposable`'s
    reason: a deleted type is one every later `define` refuses.
    """
    tag = uuid.uuid4().hex[:8]
    lonely = a_type(client, fx, f"rlone{tag}", [("l1", "z")])
    define(client, fx, world, plain(world)).raise_for_status()
    assert delete_type(client, fx, lonely).status_code == 204
