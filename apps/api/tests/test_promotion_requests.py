"""Proposals to promote an object type (§767; db 0152; Foundry
`object-link-types` p.255).

> "Only users with the `Ontology Owner` role on the ontology level can
> directly apply the `promoted` status. Other users must submit a proposal for
> review and approval by an `Ontology Owner`." (p.255)
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import hdr  # noqa: E402
from test_value_types import (  # noqa: E402,F401
    _fresh_identity_cache, client, fx, make_type, read_type, wbase,
)


def a_type(client, fx) -> dict:
    return make_type(client, fx, [{"api_name": "name", "data_type": "string"},
                                  {"api_name": "code", "data_type": "string"}])


def ask(client, fx, type_id: str, who: str | None = None, reason: str = "Used everywhere"):
    return client.post(f"{wbase(fx)}/object-types/{type_id}/promotion-requests",
                       headers=hdr(who or fx.editor_sub), json={"reason": reason})


def decide(client, fx, request_id: str, verdict: str, who: str | None = None, note: str = ""):
    return client.post(f"{wbase(fx)}/promotion-requests/{request_id}/{verdict}",
                       headers=hdr(who or fx.admin_sub), json={"note": note})


def pending(client, fx) -> list[dict]:
    r = client.get(f"{wbase(fx)}/promotion-requests", headers=hdr(fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def test_an_editor_asks_and_an_admin_approves(client, fx) -> None:
    kind = a_type(client, fx)
    r = ask(client, fx, kind["id"])
    assert r.status_code == 201, r.text
    req = r.json()
    assert (req["state"], req["reason"], req["object_type_status"]) == (
        "pending", "Used everywhere", "experimental")
    assert req["mine"] is True and req["requested_by_name"]
    assert req["id"] in {p["id"] for p in pending(client, fx)}
    # Somebody else reading the list did not ask.
    assert next(p for p in pending(client, fx) if p["id"] == req["id"])["mine"] is False

    r = decide(client, fx, req["id"], "approve", note="Agreed")
    assert r.status_code == 200, r.text
    assert (r.json()["state"], r.json()["decision_note"]) == ("approved", "Agreed")
    assert r.json()["decided_by_name"] and r.json()["decided_at"]
    # Applied as an admin's own promotion: p.255's visibility comes with it,
    # and p.256's propagation runs (both properties stay experimental, below
    # the type, since promotion never raises them).
    detail = read_type(client, fx, kind["id"])
    assert (detail["status"], detail["visibility"]) == ("promoted", "prominent")
    assert {p["status"] for p in detail["properties"]} == {"experimental"}
    assert req["id"] not in {p["id"] for p in pending(client, fx)}
    # And the type's history says so.
    r = client.get(f"{wbase(fx)}/ontology-history", headers=hdr(fx.viewer_sub),
                   params={"resource_id": kind["id"]})
    actions = {e["action"] for e in r.json()}
    assert {"object_type.promotion_requested", "object_type.promotion_approved"} <= actions


def test_a_rejection_changes_nothing_and_lets_them_ask_again(client, fx) -> None:
    kind = a_type(client, fx)
    req = ask(client, fx, kind["id"]).json()
    r = decide(client, fx, req["id"], "reject", note="Not yet stable")
    assert r.status_code == 200, r.text
    assert (r.json()["state"], r.json()["decision_note"]) == ("rejected", "Not yet stable")
    assert read_type(client, fx, kind["id"])["status"] == "experimental"
    # Answered, so it cannot be answered again.
    r = decide(client, fx, req["id"], "approve")
    assert r.status_code == 409, r.text
    assert "already rejected" in r.text
    assert ask(client, fx, kind["id"]).status_code == 201


def test_one_question_at_a_time(client, fx) -> None:
    kind = a_type(client, fx)
    assert ask(client, fx, kind["id"]).status_code == 201
    r = ask(client, fx, kind["id"])
    assert r.status_code == 409, r.text
    assert "already has a promotion request waiting" in r.text


def test_what_would_ask_nothing_is_refused(client, fx) -> None:
    kind = a_type(client, fx)
    r = ask(client, fx, kind["id"], who=fx.admin_sub)
    assert r.status_code == 422, r.text
    assert "promotes an object type directly" in r.text
    req = ask(client, fx, kind["id"]).json()
    decide(client, fx, req["id"], "approve")
    r = ask(client, fx, kind["id"])
    assert r.status_code == 422, r.text
    assert "already promoted" in r.text


def test_only_an_admin_answers_and_a_viewer_cannot_ask(client, fx) -> None:
    kind = a_type(client, fx)
    assert ask(client, fx, kind["id"], who=fx.viewer_sub).status_code == 403
    req = ask(client, fx, kind["id"]).json()
    for verdict in ("approve", "reject"):
        assert decide(client, fx, req["id"], verdict, who=fx.editor_sub).status_code == 403
    assert read_type(client, fx, kind["id"])["status"] == "experimental"


def test_only_whoever_asked_withdraws(client, fx) -> None:
    kind = a_type(client, fx)
    req = ask(client, fx, kind["id"]).json()
    # An admin is not the asker.
    r = client.post(f"{wbase(fx)}/promotion-requests/{req['id']}/withdraw",
                    headers=hdr(fx.admin_sub))
    assert r.status_code == 403, r.text
    assert "only the person who asked" in r.text
    r = client.post(f"{wbase(fx)}/promotion-requests/{req['id']}/withdraw",
                    headers=hdr(fx.editor_sub))
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "withdrawn"
    assert decide(client, fx, req["id"], "approve").status_code == 409
    # Every request is kept, answered or not, for the record.
    r = client.get(f"{wbase(fx)}/promotion-requests", headers=hdr(fx.viewer_sub),
                   params={"pending": "false"})
    assert next(p for p in r.json() if p["id"] == req["id"])["state"] == "withdrawn"


def test_a_request_from_nowhere_is_not_found(client, fx) -> None:
    import uuid
    assert decide(client, fx, str(uuid.uuid4()), "approve").status_code == 404
    assert ask(client, fx, str(uuid.uuid4())).status_code == 404
