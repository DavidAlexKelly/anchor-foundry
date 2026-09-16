"""Save and share a lineage graph (§360; `data-lineage` p.12, migration 0089).

> "**Save / Open**: Save your Data Lineage graph and re-open it by clicking on
>  Open graph. **Get quick share link**: Generates a shareable link that
>  provides read-only access to your graph." (p.12)

This follows db 0040's saved searches, so most of what it asserts is the same
shape: a stored *definition* rather than results, shared within its scope, one
name per scope, validated when it is saved rather than when it is opened.
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
from src.services import saved_graphs  # noqa: E402


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


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}/saved-graphs"


def node(kind: str = "dataset") -> str:
    return f"{kind}:{uuid.uuid4()}"


def listed(client: TestClient, fx: Fixture, sub: str):
    """Every saved graph this person can see.

    **There is no route for one graph by id, and that is deliberate.** The Open
    dialog reads the list — a saved view is small and comes back whole — so a
    single-graph route would be surface with no caller, which is the shape
    §358 found shipping a `modelApi.runs` nobody called. The tests read the
    same way the screen does."""
    r = client.get(base(fx), headers=hdr(sub))
    return r.status_code, {g["id"]: g for g in (r.json() if r.status_code == 200 else [])}


def save(client: TestClient, fx: Fixture, **body) -> dict:
    body.setdefault("name", f"View {uuid.uuid4().hex[:6]}")
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json=body)
    assert r.status_code == 201, r.text
    return r.json()


# ---- what a view may hold ----------------------------------------------------

def test_a_saved_graph_holds_the_view_and_gives_it_back(client: TestClient, fx: Fixture) -> None:
    """p.12's Save / Open, end to end."""
    focus, picked = node(), node("model")
    saved = save(client, fx, view={
        "focus": focus, "column": "id", "selected": [picked],
        "query": "orders", "kinds": ["dataset"],
    })
    status, graphs = listed(client, fx, fx.viewer_sub)
    assert status == 200 and saved["id"] in graphs, (status, sorted(graphs))
    assert graphs[saved["id"]]["view"] == {
        "focus": focus, "column": "id", "selected": [picked],
        "query": "orders", "kinds": ["dataset"],
    }


def test_a_view_that_cannot_open_is_refused_when_it_is_saved(
    client: TestClient, fx: Fixture
) -> None:
    """**db 0040's rule, and its reason**: a definition validated at open time
    means the person who finds out is not the person who made the mistake."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Bad {uuid.uuid4().hex[:6]}",
                          "view": {"focus": "not-a-node"}})
    assert r.status_code == 422, r.text
    assert "focus must be" in r.text


def test_the_graph_route_and_a_saved_graph_agree_on_what_a_focus_is(
    client: TestClient, fx: Fixture
) -> None:
    """**The reason `NODE_ID` has one home.** The pipeline route refuses a
    malformed focus and so does saving one; two copies would let a view be
    saved that the graph then declines to draw."""
    bad = "dataset:nope"
    graph = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}/pipeline?focus={bad}",
        headers=hdr(fx.viewer_sub),
    )
    saved = client.post(base(fx), headers=hdr(fx.editor_sub),
                        json={"name": f"Bad {uuid.uuid4().hex[:6]}", "view": {"focus": bad}})
    assert graph.status_code == 422 and saved.status_code == 422, (graph.text, saved.text)


def test_a_focus_with_something_after_it_is_still_refused(
    client: TestClient, fx: Fixture
) -> None:
    """`fullmatch`, not `match`. A node id that *starts* right and carries a
    path after it is the shape that walks through a prefix check, and it is the
    shape somebody would try: the focus is read straight back out of a URL."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Tail {uuid.uuid4().hex[:6]}",
                          "view": {"focus": f"{node()}/../secrets"}})
    assert r.status_code == 422, r.text
    assert "focus must be" in r.text


def test_a_selected_node_is_held_to_the_same_grammar_as_the_focus(
    client: TestClient, fx: Fixture
) -> None:
    """A selection is node ids, and a view whose selection cannot be matched to
    anything on the graph opens with nothing highlighted — the silent kind of
    wrong this module exists to refuse at save time."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Odd {uuid.uuid4().hex[:6]}",
                          "view": {"selected": [node(), "dataset:nope"]}})
    assert r.status_code == 422, r.text
    assert "dataset:nope" in r.text


def test_a_search_longer_than_a_search_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """`MAX_QUERY` is a stored column's ceiling, so it needs a check that can
    fail: without one the limit is a comment."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Long {uuid.uuid4().hex[:6]}",
        "view": {"query": "x" * (saved_graphs.MAX_QUERY + 1)},
    })
    assert r.status_code == 422, r.status_code
    assert str(saved_graphs.MAX_QUERY) in r.text


def test_a_kind_this_graph_does_not_draw_is_refused(
    client: TestClient, fx: Fixture
) -> None:
    """A filter naming a kind that does not exist hides everything, and reads
    as a graph with nothing in it rather than as a mistake."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Kind {uuid.uuid4().hex[:6]}",
                          "view": {"kinds": ["dataset", "pipeline"]}})
    assert r.status_code == 422, r.text
    assert "pipeline" in r.text


def test_a_column_that_is_only_spaces_is_not_a_column(
    client: TestClient, fx: Fixture
) -> None:
    """p.55's highlight is "the datasets that contain this column"; a blank one
    names no column and would highlight by matching nothing."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Blank {uuid.uuid4().hex[:6]}",
                          "view": {"column": "   "}})
    assert r.status_code == 422, r.text
    assert "column must be" in r.text


def test_a_view_that_is_not_an_object_is_refused(fx: Fixture) -> None:
    """**Called directly, and that is the point.** The route's body model
    already declares `view: dict`, so nothing sent over HTTP can reach this
    branch — pydantic refuses it first. `parse` is the module's contract rather
    than the route's private helper (the pipeline route reads `NODE_ID` from
    here too), so the check is worth keeping and is worth a test that can
    actually reach it. Asserting it through the route would be a test that
    passes whatever this code does."""
    with pytest.raises(saved_graphs.GraphViewError) as refused:
        saved_graphs.parse(["focus"])
    assert "must be an object" in str(refused.value)


def test_a_key_the_view_does_not_have_is_refused_rather_than_dropped(
    client: TestClient, fx: Fixture
) -> None:
    """A misspelled key silently dropped reopens a graph missing whatever it
    was for, and the reader sees something that looks deliberate."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub),
                    json={"name": f"Odd {uuid.uuid4().hex[:6]}",
                          "view": {"focuss": node()}})
    assert r.status_code == 422, r.text
    assert "focuss" in r.text


def test_an_empty_view_is_a_graph_as_it_opens(client: TestClient, fx: Fixture) -> None:
    """Saving the graph as drawn is a legitimate thing to save — it is the
    project's pipeline, named."""
    assert save(client, fx, view={})["view"] == {}


# ---- the tidying `parse` does ------------------------------------------------

def test_a_node_selected_twice_is_selected_once(client: TestClient, fx: Fixture) -> None:
    """The same node twice is not a different view, and a count drawn from it
    would be wrong."""
    picked = node()
    assert save(client, fx, view={"selected": [picked, picked]})["view"]["selected"] == [picked]


def test_every_kind_chosen_is_no_filter_at_all(client: TestClient, fx: Fixture) -> None:
    """Saving it as a filter would have a reader believe one is applied."""
    assert "kinds" not in save(
        client, fx, view={"kinds": ["dataset", "model", "object_type"]}
    )["view"]


def test_the_same_kind_twice_is_one_kind(client: TestClient, fx: Fixture) -> None:
    """Two of a kind is the same filter as one, and a "2 kinds" drawn from this
    would be wrong in the same way a double-counted selection is."""
    assert save(client, fx, view={"kinds": ["dataset", "dataset"]})["view"]["kinds"] == [
        "dataset"
    ]


def test_a_blank_search_is_not_stored(client: TestClient, fx: Fixture) -> None:
    """A saved graph carrying `query: ""` reopens with the box focused on
    nothing."""
    assert "query" not in save(client, fx, view={"query": "   "})["view"]


def test_a_selection_has_a_ceiling(client: TestClient, fx: Fixture) -> None:
    """Forty nodes is a large graph; four hundred is somebody's script, and
    opening it would be slower than drawing the graph."""
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={
        "name": f"Huge {uuid.uuid4().hex[:6]}",
        "view": {"selected": [node() for _ in range(saved_graphs.MAX_SELECTED + 1)]},
    })
    assert r.status_code == 422, r.status_code
    assert str(saved_graphs.MAX_SELECTED) in r.text


# ---- sharing -----------------------------------------------------------------

def test_a_saved_graph_is_shared_within_its_project(client: TestClient, fx: Fixture) -> None:
    """db 0040's decision: one only its author can see gets reinvented slightly
    differently by everybody else. A viewer reads it without having saved it."""
    saved = save(client, fx)
    listed = client.get(base(fx), headers=hdr(fx.viewer_sub))
    assert listed.status_code == 200, listed.text
    assert saved["id"] in [g["id"] for g in listed.json()]


def test_a_saved_graph_belongs_to_its_project_and_not_the_workspace(
    client: TestClient, fx: Fixture
) -> None:
    """**db 0089's scope, checked rather than only argued for in its header.**
    Saved searches are workspace-wide because object types are (db 0040); a
    lineage graph is over datasets and models, which belong to a project — so
    one saved next door must not turn up here, including for somebody who can
    read both projects, which is the case RLS alone would let through."""
    tag = uuid.uuid4().hex[:6]
    other = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.editor_sub),
        json={"name": f"Next door {tag}"},
    )
    assert other.status_code == 201, other.text
    elsewhere = client.post(
        f"/api/workspaces/{fx.workspace}/projects/{other.json()['id']}/saved-graphs",
        headers=hdr(fx.editor_sub), json={"name": f"Next door {tag}", "view": {}},
    )
    assert elsewhere.status_code == 201, elsewhere.text
    assert elsewhere.json()["id"] not in listed(client, fx, fx.editor_sub)[1]


def test_the_link_carries_no_access_of_its_own(client: TestClient, fx: Fixture) -> None:
    """**p.12's "read-only access", read rather than copied.** The link
    reproduces a view; it does not admit somebody to the project. A stranger
    holding the id gets what they would get for any resource here."""
    save(client, fx)
    status, _ = listed(client, fx, fx.outsider_sub)
    assert status == 404, status


def test_saving_needs_more_than_reading(client: TestClient, fx: Fixture) -> None:
    r = client.post(base(fx), headers=hdr(fx.viewer_sub),
                    json={"name": f"Nope {uuid.uuid4().hex[:6]}", "view": {}})
    assert r.status_code == 403, r.text


def test_two_saved_graphs_cannot_share_a_name(client: TestClient, fx: Fixture) -> None:
    """db 0040: two called the same thing that differ is what sharing exists to
    prevent."""
    name = f"Taken {uuid.uuid4().hex[:6]}"
    save(client, fx, name=name)
    r = client.post(base(fx), headers=hdr(fx.editor_sub), json={"name": name, "view": {}})
    assert r.status_code == 409, r.text


def test_a_saved_graph_can_be_put_down(client: TestClient, fx: Fixture) -> None:
    saved = save(client, fx)
    assert client.delete(
        f"{base(fx)}/{saved['id']}", headers=hdr(fx.editor_sub)
    ).status_code == 204
    assert saved["id"] not in listed(client, fx, fx.viewer_sub)[1]


def test_saved_graphs_are_listed_by_name(client: TestClient, fx: Fixture) -> None:
    """Ordered rather than in save order: **Open graph** is a list somebody
    scans for a name they remember, and the newest-first arrangement that suits
    a feed makes a remembered name move every time anybody saves anything."""
    tag = uuid.uuid4().hex[:6]
    for name in (f"Zephyr {tag}", f"Alpha {tag}"):
        save(client, fx, name=name)
    listed = [g["name"] for g in client.get(base(fx), headers=hdr(fx.viewer_sub)).json()]
    assert listed.index(f"Alpha {tag}") < listed.index(f"Zephyr {tag}"), listed


def test_a_name_is_stored_without_the_space_around_it(
    client: TestClient, fx: Fixture
) -> None:
    """Untrimmed, `"Fleet "` and `"Fleet"` are two different names, which is
    exactly the pair the one-name-per-project rule exists to prevent — and the
    difference is invisible in the list that shows them."""
    tag = uuid.uuid4().hex[:6]
    assert save(client, fx, name=f"  Fleet {tag}  ")["name"] == f"Fleet {tag}"
    clash = client.post(base(fx), headers=hdr(fx.editor_sub),
                        json={"name": f"Fleet {tag}", "view": {}})
    assert clash.status_code == 409, clash.text


def test_putting_a_saved_graph_down_needs_more_than_reading(
    client: TestClient, fx: Fixture
) -> None:
    """It is shared with the project, so deleting one takes it from everybody —
    a viewer's read-only access does not reach that far."""
    saved = save(client, fx)
    assert client.delete(
        f"{base(fx)}/{saved['id']}", headers=hdr(fx.viewer_sub)
    ).status_code == 403
    assert saved["id"] in listed(client, fx, fx.viewer_sub)[1]


def test_saving_a_graph_is_audited(client: TestClient, fx: Fixture) -> None:
    """Every other resource here records who made it; a saved graph is shared
    with the project, so "who put this in front of everybody" has an answer."""
    save(client, fx)
    entries = client.get("/api/org/audit?limit=200", headers=hdr(fx.admin_sub))
    assert entries.status_code == 200, entries.text
    assert "graph.save" in {e["action"] for e in entries.json()}
