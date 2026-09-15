"""Pipeline graph tests (ROADMAP Models item 2).

Its own project rather than a case in test_models.py: this endpoint returns
*everything* in a project, so sharing a project with tests that create models
would make the assertions depend on test order.
"""
from __future__ import annotations

import io
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_api import Fixture, LocalVerifier, hdr  # noqa: E402
from src.main import create_app  # noqa: E402
from src.middleware import auth as auth_mw  # noqa: E402
from src.routes import datasets as ds_routes  # noqa: E402
from src.services.storage import LocalStorageGateway  # noqa: E402

ROWS = b"id,val\n1,10\n2,20\n3,30\n"


@pytest.fixture(scope="module")
def fx() -> Fixture:
    return Fixture()


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    auth_mw.configure_verifier(LocalVerifier())
    ds_routes.configure_storage_gateway(
        LocalStorageGateway(str(tmp_path_factory.mktemp("pipeline-storage")))
    )
    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


@pytest.fixture(autouse=True)
def _fresh_identity_cache() -> None:
    auth_mw.clear_identity_cache()


def base(fx: Fixture) -> str:
    return f"/api/workspaces/{fx.workspace}/projects/{fx.project}"


def graph(client: TestClient, fx: Fixture, sub: str | None = None) -> dict:
    r = client.get(f"{base(fx)}/pipeline", headers=hdr(sub or fx.viewer_sub))
    assert r.status_code == 200, r.text
    return r.json()


def node(g: dict, name: str, kind: str) -> dict:
    # Kind is required, not a convenience: a model's output dataset is named
    # after the model, so every chain here has two nodes per name.
    matches = [n for n in g["nodes"] if n["name"] == name and n["kind"] == kind]
    assert len(matches) == 1, f"{kind} {name!r} not in {[(n['kind'], n['name']) for n in g['nodes']]}"
    return matches[0]


@pytest.fixture(scope="module")
def chain(client: TestClient, fx: Fixture) -> dict[str, str]:
    """source -> A -> A out -> B -> B out. Built through the real API, so
    the output datasets exist because the models actually ran."""
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Source {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    source = r.json()["id"]

    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"A {fx.tag}", "code": "SELECT id, val * 2 AS doubled FROM raw",
              "inputs": [{"dataset_id": source, "input_alias": "raw"}]},
    )
    assert r.status_code == 201, r.text
    a = r.json()["id"]
    r = client.post(f"{base(fx)}/models/{a}/run", headers=hdr(fx.editor_sub))
    assert r.json()["ok"], r.text
    a_out = r.json()["output_dataset"]["id"]

    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"B {fx.tag}", "code": "SELECT sum(doubled) AS total FROM a",
              "inputs": [{"dataset_id": a_out, "input_alias": "a"}]},
    )
    assert r.status_code == 201, r.text
    b = r.json()["id"]
    r = client.post(f"{base(fx)}/models/{b}/run", headers=hdr(fx.editor_sub))
    assert r.json()["ok"], r.text
    b_out = r.json()["output_dataset"]["id"]

    return {"source": source, "a": a, "a_out": a_out, "b": b, "b_out": b_out,
            "a_name": f"A {fx.tag}", "b_name": f"B {fx.tag}",
            "source_name": f"Source {fx.tag}"}


def test_chain_layers_strictly_left_to_right(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    g = graph(client, fx)
    assert g["cycles"] == []
    assert g["layer_count"] == 5

    layers = {n["id"]: n["layer"] for n in g["nodes"]}
    # Every edge must point strictly rightwards - that is the whole promise
    # the frontend lays out against.
    for e in g["edges"]:
        assert layers[e["to"]] > layers[e["from"]], e

    assert node(g, chain["source_name"], "dataset")["layer"] == 0
    assert node(g, chain["a_name"], "model")["layer"] == 1
    assert node(g, chain["b_name"], "model")["layer"] == 3


def test_nodes_carry_the_state_the_view_renders(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    g = graph(client, fx)

    source = node(g, chain["source_name"], "dataset")
    assert source["kind"] == "dataset" and source["origin"] == "upload"
    assert source["row_count"] == 3 and source["current_version"] == 1
    # Nothing has asked for this dataset's health, so it is not computed
    # here - one project-wide request must not trigger a DuckDB pass per
    # dataset (services/pipeline.py's docstring).
    assert source["health_status"] is None

    a = node(g, chain["a_name"], "model")
    assert a["kind"] == "model" and a["language"] == "sql"
    assert a["trigger_mode"] == "manual"
    assert a["last_run_status"] == "succeeded" and a["last_run_at"] is not None
    assert a["row_count"] is None, "model nodes carry no dataset fields"

    aliased = [e for e in g["edges"] if e["to"] == a["id"]]
    assert [e["label"] for e in aliased] == ["raw"]


def test_health_appears_once_something_has_evaluated_it(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    r = client.post(
        f"{base(fx)}/datasets/{chain['source']}/expectations", headers=hdr(fx.editor_sub),
        json={"column_name": "id", "rule_type": "not_null"},
    )
    assert r.status_code == 201, r.text
    assert client.get(
        f"{base(fx)}/datasets/{chain['source']}/health", headers=hdr(fx.viewer_sub)
    ).json()["status"] == "pass"

    assert node(graph(client, fx), chain["source_name"], "dataset")["health_status"] == "pass"


def test_closing_a_loop_is_refused_at_save_time(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    """Roadmap Models item 7. B reads A's output, so feeding B's output back
    into A would make A depend on itself two hops away - which migration
    0021's self-loop guard cannot see, and which re-fires forever under
    upstream triggers."""
    r = client.patch(
        f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.editor_sub),
        json={"inputs": [{"dataset_id": chain["source"], "input_alias": "raw"},
                         {"dataset_id": chain["b_out"], "input_alias": "loop"}]},
    )
    assert r.status_code == 422, r.text
    assert "dependency loop" in r.json()["detail"]

    # Refused, not half-applied.
    r = client.get(f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.viewer_sub))
    assert [i["input_alias"] for i in r.json()["inputs"]] == ["raw"]
    assert graph(client, fx)["cycles"] == []

    # A model reading its own output directly is the same refusal.
    r = client.patch(
        f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.editor_sub),
        json={"inputs": [{"dataset_id": chain["a_out"], "input_alias": "self_ref"}]},
    )
    assert r.status_code == 422 and "dependency loop" in r.json()["detail"]

    # A sibling reading the same output is not a loop and must still be
    # allowed - the walk is directional, not "anything already in the graph".
    r = client.post(
        f"{base(fx)}/models", headers=hdr(fx.editor_sub),
        json={"name": f"Sibling {fx.tag}", "code": "SELECT count(*) AS n FROM d",
              "inputs": [{"dataset_id": chain["a_out"], "input_alias": "d"}]},
    )
    assert r.status_code == 201, r.text
    client.delete(f"{base(fx)}/models/{r.json()['id']}", headers=hdr(fx.editor_sub))


def test_a_pre_existing_cycle_is_reported_rather_than_hidden(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    """Cycles created before the save-time check existed are grandfathered
    (services/models.py `_refuse_cycles`), so the graph still has to report
    one. Written straight to the database, which is the only way to get one
    now - and exactly the state an older deployment can be in."""
    import psycopg
    from test_api import ADMIN_DSN

    with psycopg.connect(ADMIN_DSN, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO model_inputs (model_id, dataset_id, input_alias) VALUES (%s,%s,'loop')",
            (chain["a"], chain["b_out"]),
        )
    try:
        g = graph(client, fx)
        assert len(g["cycles"]) == 1, g["cycles"]
        members = set(g["cycles"][0])
        assert members == {
            f"model:{chain['a']}", f"dataset:{chain['a_out']}",
            f"model:{chain['b']}", f"dataset:{chain['b_out']}",
        }, members
        # A cyclic node still lands somewhere sensible rather than vanishing.
        assert node(g, chain["a_name"], "model")["in_cycle"] is True
        assert node(g, chain["source_name"], "dataset")["in_cycle"] is False
        assert all(n["layer"] >= 0 for n in g["nodes"])
    finally:
        # Editing your way *out* of a grandfathered cycle must be allowed -
        # the check validates the proposed set, not the current one.
        r = client.patch(
            f"{base(fx)}/models/{chain['a']}", headers=hdr(fx.editor_sub),
            json={"inputs": [{"dataset_id": chain["source"], "input_alias": "raw"}]},
        )
        assert r.status_code == 200, r.text
    assert graph(client, fx)["cycles"] == []


def test_focus_narrows_the_graph_to_one_node_s_lineage(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    """Roadmap Datasets item 5. Lineage is the connected component around a
    node, computed by the same endpoint the whole-project view uses."""
    # An unrelated dataset in the same project must not appear.
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Unrelated {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text

    whole = graph(client, fx)
    r = client.get(
        f"{base(fx)}/pipeline?focus=dataset:{chain['a_out']}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 200, r.text
    focused = r.json()

    assert len(focused["nodes"]) < len(whole["nodes"])
    assert {n["name"] for n in focused["nodes"]} == {
        chain["source_name"], chain["a_name"], chain["b_name"],
    }, [n["name"] for n in focused["nodes"]]

    # Both directions: what produced it and what reads it.
    ids = {n["id"] for n in focused["nodes"]}
    assert f"model:{chain['a']}" in ids and f"model:{chain['b']}" in ids
    assert f"dataset:{chain['source']}" in ids

    marked = [n for n in focused["nodes"] if n["is_focus"]]
    assert [n["id"] for n in marked] == [f"dataset:{chain['a_out']}"]
    assert all(not n["is_focus"] for n in whole["nodes"])

    # It is still a laid-out graph, not just a filtered list.
    layers = {n["id"]: n["layer"] for n in focused["nodes"]}
    for e in focused["edges"]:
        assert layers[e["to"]] > layers[e["from"]], e


def test_a_bad_or_unknown_focus_is_refused(
    client: TestClient, fx: Fixture, chain: dict[str, str]
) -> None:
    import uuid as _uuid

    r = client.get(f"{base(fx)}/pipeline?focus=nonsense", headers=hdr(fx.viewer_sub))
    assert r.status_code == 422

    r = client.get(
        f"{base(fx)}/pipeline?focus=dataset:{_uuid.uuid4()}", headers=hdr(fx.viewer_sub)
    )
    assert r.status_code == 404, "a node outside this project is not lineage to show"


def test_an_empty_project_is_an_empty_graph(client: TestClient, fx: Fixture) -> None:
    r = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
        json={"name": f"Empty {fx.tag}", "slug": f"empty-{fx.tag}"},
    )
    assert r.status_code == 201, r.text
    empty = r.json()["id"]
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{empty}/pipeline", headers=hdr(fx.owner_sub)
    )
    assert r.status_code == 200, r.text
    # `links` joined this shape in §351. Asserted as the **whole** dict on
    # purpose: an empty graph is the one case where every key can be named,
    # so a key added without a thought about what "empty" means for it fails
    # here rather than reaching a client that did not expect it.
    assert r.json() == {"nodes": [], "edges": [], "links": [], "cycles": [],
                        "layer_count": 0}


def test_an_outsider_cannot_read_the_graph(client: TestClient, fx: Fixture) -> None:
    assert client.get(f"{base(fx)}/pipeline", headers=hdr(fx.outsider_sub)).status_code == 404


# ---- ontology entities (§351; `data-lineage` p.30-32) ------------------------
@pytest.fixture(scope="module")
def ontology(client: TestClient, fx: Fixture, chain: dict[str, str]) -> dict[str, str]:
    """Two object types on this project's data, joined by a link type.

    `sites` is backed by **both** the source and A's output, which is the case
    db 0003's `UNIQUE (object_type_id, dataset_id)` allows and the one that
    decides whether a type is one node or several. `visits` is backed by the
    source alone, so there is a link with both ends on the graph.
    """
    wbase = f"/api/workspaces/{fx.workspace}"
    made: dict[str, str] = {}
    for name, columns in (("sites", ["id"]), ("visits", ["id"])):
        r = client.post(
            f"{wbase}/object-types", headers=hdr(fx.editor_sub),
            json={"api_name": f"{name}_{fx.tag}",
                  "display_name": f"{name.title()} {fx.tag}",
                  "properties": [{"api_name": c, "data_type": "string"} for c in columns],
                  "title_property": "id"},
        )
        assert r.status_code == 201, r.text
        made[name] = r.json()["id"]

    sources: dict[tuple[str, str], str] = {}
    for object_type, dataset in (
        (made["sites"], chain["source"]),
        (made["sites"], chain["a_out"]),
        (made["visits"], chain["source"]),
    ):
        r = client.post(
            f"{base(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
            json={"object_type_id": object_type, "dataset_id": dataset,
                  "primary_key_column": "id", "column_mappings": {"id": "id"}},
        )
        assert r.status_code == 201, r.text
        sources[(object_type, dataset)] = r.json()["id"]

    # **One of `sites`' two sources is synced and the other is not**, which is
    # what gives the fold something to fold. A sweep found the version of this
    # fixture where both were `never_synced`: the mutant that stopped folding
    # survived, because with two identical states there is nothing a fold can
    # do that not folding does differently (§213).
    synced = sources[(made["sites"], chain["source"])]
    r = client.post(
        f"{base(fx)}/object-type-sources/{synced}/sync", headers=hdr(fx.editor_sub)
    )
    assert r.status_code == 200, r.text

    r = client.post(
        f"{wbase}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"visited_{fx.tag}", "display_name": f"Visited {fx.tag}",
              "from_type_id": made["sites"], "to_type_id": made["visits"],
              "cardinality": "one_to_many"},
    )
    assert r.status_code == 201, r.text
    made["link"] = r.json()["id"]
    return made


def test_an_object_type_is_downstream_of_every_dataset_backing_it(
    client: TestClient, fx: Fixture, chain: dict[str, str], ontology: dict[str, str]
) -> None:
    """p.31's "find object types defined by datasets in your lineage graph",
    which is what turns this view into the answer to "if I change this column,
    what breaks?".

    **One node with two arrows in, not two nodes.** A type backed by two of
    this project's datasets is one thing downstream of both, and the query
    behind this is per *source* — so folding is a real step and getting it
    wrong would draw the same object type twice under the same name.
    """
    g = graph(client, fx)
    sites = node(g, f"Sites {fx.tag}", "object_type")
    assert sites["resource_id"] == ontology["sites"]
    assert sites["slug"] == f"sites_{fx.tag}"

    into = {e["from"] for e in g["edges"] if e["to"] == sites["id"]}
    assert into == {f"dataset:{chain['source']}", f"dataset:{chain['a_out']}"}, into
    # And it is an ordinary edge, so the layering promise still holds over it:
    # a sync reads the dataset and writes the type, which is a flow.
    layers = {n["id"]: n["layer"] for n in g["nodes"]}
    for e in g["edges"]:
        assert layers[e["to"]] > layers[e["from"]], e


def test_an_object_type_reports_the_worst_of_its_syncs(
    client: TestClient, fx: Fixture, ontology: dict[str, str]
) -> None:
    """Never synced beside never synced is never synced — the interesting half
    is that a type with several sources answers with **one** state, and which
    one is a decision rather than whichever row sorted last.

    The question this graph answers is "what is wrong downstream of here", so
    an `ok` beside an `error` has to read as the error.
    """
    from src.services import pipeline as pipeline_service

    g = graph(client, fx)
    sites = node(g, f"Sites {fx.tag}", "object_type")
    visits = node(g, f"Visits {fx.tag}", "object_type")

    # `sites` has one source synced and one never synced, so the two halves of
    # the fold answer from **different rows** — and that pairing is what makes
    # this test able to fail. Without folding the node takes whichever row the
    # query returned last, which gives either ("ok", a timestamp) or
    # ("never_synced", None); neither is this.
    assert sites["last_run_status"] == "never_synced", sites
    assert sites["last_run_at"] is not None, sites

    # The control: a type whose one source is untouched says so plainly, which
    # is what stops the assertion above from passing on a build that reports
    # "never_synced" for everything.
    assert visits["last_run_status"] == "never_synced"
    assert visits["last_run_at"] is None, visits

    # And the ordering itself, named so the decision is readable rather than a
    # literal inside a loop.
    ranked = ["error", "never_synced", "syncing", "ok"]
    assert ranked == sorted(ranked, key=lambda s: pipeline_service._WORST[s]), (
        "the order that decides which of a type's syncs it reports"
    )


def test_a_link_type_is_drawn_beside_the_edges_and_not_among_them(
    client: TestClient, fx: Fixture, ontology: dict[str, str]
) -> None:
    """> "You can then view link types related to the object type and use the
    > graph to visualize connections between your datasets and the newly added
    > object type." (p.32)

    **The separation is the assertion.** `edges` is what the layering and the
    cycle report are built from, and a link type is a relationship rather than
    a dependency — so two object types that reference each other are an
    ordinary ontology, and putting the link in `edges` would report them as a
    cycle in the *pipeline*.
    """
    g = graph(client, fx)
    sites = node(g, f"Sites {fx.tag}", "object_type")
    visits = node(g, f"Visits {fx.tag}", "object_type")

    assert g["links"] == [{
        "id": ontology["link"],
        "from": sites["id"], "to": visits["id"],
        "name": f"Visited {fx.tag}", "cardinality": "one_to_many",
    }], g["links"]
    # Nowhere in `edges`, which is the half that keeps `cycles` meaning what it
    # says.
    assert not [e for e in g["edges"]
                if {e["from"], e["to"]} == {sites["id"], visits["id"]}]
    assert g["cycles"] == []


def test_a_lineage_view_carries_the_object_types_its_data_backs(
    client: TestClient, fx: Fixture, chain: dict[str, str], ontology: dict[str, str]
) -> None:
    """Focused on one dataset, which is how the dataset app asks. The object
    types the focus feeds are part of its component, because the edge into them
    is a real one."""
    r = client.get(
        f"{base(fx)}/pipeline?focus=dataset:{chain['source']}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    g = r.json()
    kinds = {(n["kind"], n["name"]) for n in g["nodes"]}
    assert ("object_type", f"Sites {fx.tag}") in kinds
    assert ("object_type", f"Visits {fx.tag}") in kinds
    assert g["links"], "both ends are on this component, so the link is drawn"


@pytest.fixture(scope="module")
def apart(client: TestClient, fx: Fixture, ontology: dict[str, str]) -> dict[str, str]:
    """An object type on a dataset **no model touches**, linked to `sites`.

    The chain is one connected component from end to end — `_connected_
    component` is undirected on purpose, so focusing its last dataset still
    reaches its first. Testing that a link does not widen a component therefore
    needs a second component, which is what this is.
    """
    r = client.post(
        f"{base(fx)}/datasets/upload", headers=hdr(fx.editor_sub),
        data={"name": f"Aside {fx.tag}"},
        files={"file": ("rows.csv", io.BytesIO(ROWS), "text/csv")},
    )
    assert r.status_code == 201, r.text
    dataset = r.json()["id"]

    wbase = f"/api/workspaces/{fx.workspace}"
    r = client.post(
        f"{wbase}/object-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"aside_{fx.tag}", "display_name": f"Aside {fx.tag}",
              "properties": [{"api_name": "id", "data_type": "string"}],
              "title_property": "id"},
    )
    assert r.status_code == 201, r.text
    object_type = r.json()["id"]
    r = client.post(
        f"{base(fx)}/object-type-sources", headers=hdr(fx.editor_sub),
        json={"object_type_id": object_type, "dataset_id": dataset,
              "primary_key_column": "id", "column_mappings": {"id": "id"}},
    )
    assert r.status_code == 201, r.text
    r = client.post(
        f"{wbase}/link-types", headers=hdr(fx.editor_sub),
        json={"api_name": f"aside_of_{fx.tag}", "display_name": f"Aside of {fx.tag}",
              "from_type_id": ontology["sites"], "to_type_id": object_type,
              "cardinality": "one_to_many"},
    )
    assert r.status_code == 201, r.text
    return {"dataset": dataset, "object_type": object_type}


def test_a_link_never_widens_the_component_it_is_drawn_on(
    client: TestClient, fx: Fixture, chain: dict[str, str],
    ontology: dict[str, str], apart: dict[str, str],
) -> None:
    """**The reason links are resolved after the narrowing, not before.**

    A link is not a data path, so it must not pull a dataset into a lineage
    view that has no flow to the focus. `Aside` is linked to `Sites` and sits
    on a dataset nothing in the chain touches — so focusing the chain must
    leave it out, link and all.

    The whole-project graph is the control: the link *is* real, and a test that
    only looked for its absence would pass against a build that never drew one.
    """
    whole = graph(client, fx)
    assert any(l["to"] == f"object_type:{apart['object_type']}"
               for l in whole["links"]), whole["links"]

    r = client.get(
        f"{base(fx)}/pipeline?focus=dataset:{chain['b_out']}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    g = r.json()
    # The positive wait first: the component is real and contains the focus.
    assert any(n["id"] == f"dataset:{chain['b_out']}" for n in g["nodes"])
    # `Sites` is here — it is downstream of the chain's source — and `Aside` is
    # not, because the only thing joining them is a link.
    drawn = {n["name"] for n in g["nodes"] if n["kind"] == "object_type"}
    assert f"Sites {fx.tag}" in drawn, drawn
    assert f"Aside {fx.tag}" not in drawn, drawn
    assert not [l for l in g["links"]
                if l["to"] == f"object_type:{apart['object_type']}"]


def test_an_object_type_is_a_node_a_lineage_view_can_centre_on(
    client: TestClient, fx: Fixture, ontology: dict[str, str]
) -> None:
    """A node the graph draws and cannot be centred on is a node whose
    neighbours are unreachable from it — so `focus` takes an object type too
    (§351), and the datasets backing it are what comes back."""
    r = client.get(
        f"{base(fx)}/pipeline?focus=object_type:{ontology['sites']}",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    g = r.json()
    sites = node(g, f"Sites {fx.tag}", "object_type")
    assert sites["is_focus"] is True
    assert {n["kind"] for n in g["nodes"]} >= {"dataset", "object_type"}

    # And a shape the regex used to refuse outright is now a 404 about *this*
    # workspace rather than a 422 about the spelling — the distinction §9 draws.
    import uuid as _uuid
    missing = client.get(
        f"{base(fx)}/pipeline?focus=object_type:{_uuid.uuid4()}",
        headers=hdr(fx.viewer_sub),
    )
    assert missing.status_code == 404, missing.text


def test_an_object_type_backed_by_another_projects_data_is_not_here(
    client: TestClient, fx: Fixture, ontology: dict[str, str]
) -> None:
    """The boundary this graph has always had, stated for the ontology (§351).

    `object_types` are **workspace**-scoped and this graph is a *project's*, so
    a type reached through another project's dataset is not this project's
    lineage — the same line `_validate_and_set_inputs` draws for a model's
    inputs. A link to it is not drawn either, because both ends must be on the
    graph.
    """
    other = client.post(
        f"/api/workspaces/{fx.workspace}/projects", headers=hdr(fx.owner_sub),
        json={"name": f"Elsewhere {fx.tag}", "slug": f"elsewhere-{fx.tag}"},
    )
    assert other.status_code == 201, other.text
    g = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{other.json()['id']}/pipeline",
        headers=hdr(fx.owner_sub),
    ).json()
    # `sites` is a workspace resource and is perfectly visible from here — it
    # is simply not on *this* project's graph, because no dataset here backs it.
    assert [n for n in g["nodes"] if n["kind"] == "object_type"] == []
    assert g["links"] == []


def test_the_mermaid_walk_carries_object_types_too(
    client: TestClient, fx: Fixture, chain: dict[str, str], ontology: dict[str, str]
) -> None:
    """The *other* lineage builder (§351). `models.lineage_for_dataset` answers
    "what touches this dataset" as a walk plus a Mermaid rendering, and the
    graph the browser draws comes from `project_graph` — two builders, one
    question, and a feature added to one of them is a feature half the product
    does not have.

    **Link types are deliberately absent here** and that is asserted: the walk
    follows data, an object type is where the data stops being a dataset, and a
    link type joins two object types rather than touching any dataset.
    """
    r = client.get(
        f"/api/workspaces/{fx.workspace}/projects/{fx.project}"
        f"/datasets/{chain['source']}/lineage",
        headers=hdr(fx.viewer_sub),
    )
    assert r.status_code == 200, r.text
    g = r.json()
    names = {o["name"] for o in g["object_types"]}
    assert f"Sites {fx.tag}" in names and f"Visits {fx.tag}" in names, names
    assert {"from": f"dataset:{chain['source']}",
            "to": f"object_type:{ontology['sites']}"} in g["edges"]
    # A third Mermaid shape, so the diagram can be read: `([...])` is neither
    # the dataset's box nor the model's hexagon.
    assert "([" in g["mermaid"], g["mermaid"]
    # And no link type anywhere in it.
    assert f"Visited {fx.tag}" not in g["mermaid"]
