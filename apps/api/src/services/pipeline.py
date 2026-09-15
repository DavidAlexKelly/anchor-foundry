"""Project pipeline graph (`ROADMAP.md` Models item 2).

Lineage (services/models.py's `lineage_for_dataset`) answers "what touches
*this* dataset" - a walk outward from one node, rendered as Mermaid. This
answers a different question: what does the whole project look like at
once, with every model's last-run state on it. Different question, so a
different endpoint rather than a flag on the old one; the walk is still the
right tool for a single node's provenance.

Three deliberate decisions:

  * **Layout is computed here, not in the browser.** The nodes come back
    with a `layer` (how far downstream they sit) and a `position` within
    it, so the frontend can lay a DAG out with arithmetic instead of a
    graph-layout library. That keeps a real dependency out of the web app
    for a view whose graphs are project-sized, and - the better reason -
    puts the graph logic somewhere it can be tested against real rows in
    pytest rather than only in a browser.

  * **Cycles are detected and reported rather than hidden.** Kahn's
    algorithm layers the graph; anything still unplaced when the queue
    drains is in (or downstream of) a cycle. Migration 0021 defers exactly
    this to this item: two models feeding each other oscillate under
    upstream triggers, one run each per poll pass, and nothing in the
    product could see it. Cyclic nodes get the layer they'd have from
    their placed inputs so they still render somewhere sensible, and are
    returned in `cycles` so the view can say what is wrong. Detecting is
    not the same as preventing - refusing to *save* a cycle is a separate
    decision about model edits, flagged in ROADMAP rather than smuggled in
    here.

  * **Ontology entities are on the graph, and link types are beside it**
    (§351; `data-lineage` p.30-32). Foundry's lineage is not dataset-only:
    "find object types defined by datasets in your lineage graph" (p.31), and
    the object types a dataset backs are what turn this from a pipeline view
    into the answer to "if I change this column, what breaks?". A sync is a
    flow, so a dataset→object type arrow is an ordinary edge; a **link type
    is not**, so it travels in `links` where it cannot be mistaken for a build
    dependency. p.30's *Related artifacts* panel is ○ rather than half-built:
    it lists Contour visualizations and Slate applications, and this platform
    has neither.

  * **Nothing is computed that isn't already stored.** Dataset health
    (§26) is read from the cached column only, never computed: this is one
    request for a whole project, and evaluating expectations for every
    dataset in it would turn a page load into a DuckDB pass per dataset.
    A dataset nobody has opened reports `null` health rather than a
    number bought at that price.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from ..lib.db import fetch_all
from ..lib.errors import NotFoundError


#: How bad each sync state is, worst first (§351; db 0003's
#: `object_sync_status`). An object type backed by several datasets reports the
#: **worst** of their syncs, because the question this graph answers is "what is
#: wrong downstream of here" and an `ok` beside an `error` would answer it with
#: the reassuring half.
#:
#: Module-level so the ordering is a named decision a test can read, rather than
#: a literal inside a loop that nothing can ask about.
_WORST = {"error": 0, "never_synced": 1, "syncing": 2, "ok": 3}


async def project_graph(
    conn: AsyncConnection, project_id: UUID, *, focus: str | None = None
) -> dict[str, Any]:
    """Every dataset and model in the project as one directed graph.

    With `focus` (a node id like "dataset:<uuid>"), the result is narrowed to
    the connected component containing that node - which is exactly what
    lineage means: everything that feeds it, everything it feeds, and nothing
    else. Roadmap Datasets item 5 asked for the lineage view to reuse "the
    same graph-rendering approach" as the project view; reusing the same
    *endpoint* is the stronger version of that, since the two really are one
    question asked from two entry points.
    """
    datasets = await fetch_all(
        conn,
        """
        SELECT d.id, d.name, d.slug, d.origin, d.row_count, d.current_version,
               d.updated_at,
               (SELECT v.expectation_results FROM dataset_versions v
                 WHERE v.dataset_id = d.id
                 ORDER BY v.version_number DESC LIMIT 1) AS expectation_results,
               -- When the dataset last *became* what it is (§352;
               -- `data-lineage` p.51). `datasets.updated_at` is not this: a
               -- rename touches it, and a rename is not a build.
               (SELECT v.created_at FROM dataset_versions v
                 WHERE v.dataset_id = d.id
                 ORDER BY v.version_number DESC LIMIT 1) AS built_at
          FROM datasets d
         WHERE d.project_id = :pid
         ORDER BY d.name
        """,
        {"pid": str(project_id)},
    )
    models = await fetch_all(
        conn,
        """
        SELECT m.id, m.name, m.language, m.trigger_mode, m.cron_schedule,
               m.output_dataset_id,
               (SELECT r.status FROM model_runs r WHERE r.model_id = m.id
                 ORDER BY r.queued_at DESC LIMIT 1) AS last_run_status,
               (SELECT r.queued_at FROM model_runs r WHERE r.model_id = m.id
                 ORDER BY r.queued_at DESC LIMIT 1) AS last_run_at
          FROM models m
         WHERE m.project_id = :pid
         ORDER BY m.name
        """,
        {"pid": str(project_id)},
    )
    inputs = await fetch_all(
        conn,
        """
        SELECT mi.model_id, mi.dataset_id, mi.input_alias
          FROM model_inputs mi
          JOIN models m ON m.id = mi.model_id
         WHERE m.project_id = :pid
        """,
        {"pid": str(project_id)},
    )
    # **The ontology entities** (§351; `data-lineage` p.30-32, TOC §7). One
    # row per *source*, not per object type: db 0003 allows an object type to
    # be backed by several datasets, and a type backed by two of this
    # project's datasets is downstream of both — which is the whole point of
    # drawing it here.
    #
    # `object_type_sources` has no project of its own; it is project-scoped by
    # the dataset it names, which is why this joins through `datasets` rather
    # than filtering the mapping directly.
    ontology = await fetch_all(
        conn,
        """
        SELECT ots.dataset_id, ot.id, ot.api_name, ot.display_name, ot.icon,
               ots.sync_status::text AS sync_status, ots.last_synced_at
          FROM object_type_sources ots
          JOIN datasets d ON d.id = ots.dataset_id
          JOIN object_types ot ON ot.id = ots.object_type_id
         WHERE d.project_id = :pid
         ORDER BY ot.display_name, ots.dataset_id
        """,
        {"pid": str(project_id)},
    )

    nodes: list[dict[str, Any]] = []
    for d in datasets:
        nodes.append({
            "id": f"dataset:{d['id']}",
            "kind": "dataset",
            "resource_id": str(d["id"]),
            "name": d["name"],
            "slug": d["slug"],
            "origin": d["origin"],
            "row_count": d["row_count"],
            "current_version": d["current_version"],
            "updated_at": d["updated_at"],
            "built_at": d["built_at"],
            # Read from the cache only - see this module's docstring.
            "health_status": _health_status(d["expectation_results"]),
            # Filled in below, once every node and edge is known.
            "out_of_date": False,
            "out_of_date_reason": None,
            "language": None,
            "trigger_mode": None,
            "last_run_status": None,
            "last_run_at": None,
        })
    for m in models:
        nodes.append({
            "id": f"model:{m['id']}",
            "kind": "model",
            "resource_id": str(m["id"]),
            "name": m["name"],
            "slug": None,
            "origin": None,
            "row_count": None,
            "current_version": None,
            "updated_at": m["last_run_at"],
            "built_at": None,
            "health_status": None,
            # A model is not a thing that goes out of date; its *output* is,
            # and that is the dataset node one edge along. Present so the node
            # shape stays one shape rather than two.
            "out_of_date": False,
            "out_of_date_reason": None,
            "language": m["language"],
            "trigger_mode": m["trigger_mode"],
            "last_run_status": m["last_run_status"],
            "last_run_at": m["last_run_at"],
        })

    # **One node per object type, whatever its sources number** (§351). The
    # query above is per source because the *edges* are, and folding here is
    # what keeps a type backed by three datasets one node with three arrows in
    # rather than three nodes with the same name.
    #
    # The fields are the node shape's own, used for what they say: an object
    # type's sync *is* its last run, so `last_run_status` carries db 0003's
    # `sync_status` and the view colours it the way it colours a model's. A
    # type with several sources reports the **worst** of them, because the
    # question this graph answers is "what is wrong downstream of here" and an
    # `ok` beside an `error` would answer it with the reassuring half.
    by_type: dict[str, dict[str, Any]] = {}
    for row in ontology:
        oid = str(row["id"])
        held = by_type.get(oid)
        status = str(row["sync_status"])
        if held is None:
            by_type[oid] = {
                "id": f"object_type:{oid}",
                "kind": "object_type",
                "resource_id": oid,
                "name": row["display_name"] or row["api_name"],
                "slug": row["api_name"],
                "origin": None,
                "row_count": None,
                "current_version": None,
                "updated_at": row["last_synced_at"],
                "built_at": None,
                "health_status": None,
                "out_of_date": False,
                "out_of_date_reason": None,
                "language": None,
                "trigger_mode": None,
                "last_run_status": status,
                "last_run_at": row["last_synced_at"],
            }
            continue
        if _WORST.get(status, 9) < _WORST.get(str(held["last_run_status"]), 9):
            held["last_run_status"] = status
        # The most recent sync of any source, so "when was this type last
        # written" reads as a fact about the type rather than about whichever
        # source the ordering happened to put last.
        if row["last_synced_at"] is not None and (
            held["last_run_at"] is None or row["last_synced_at"] > held["last_run_at"]
        ):
            held["last_run_at"] = row["last_synced_at"]
            held["updated_at"] = row["last_synced_at"]
    nodes.extend(by_type.values())

    known = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for row in ontology:
        # **A real flow, not a cross-reference**, which is why it belongs in
        # `edges` beside a model's: the sync reads the dataset and writes the
        # object type's instances, so the type is downstream of it exactly as
        # a model's output dataset is downstream of the model.
        src, dst = f"dataset:{row['dataset_id']}", f"object_type:{row['id']}"
        if src in known and dst in known:
            edges.append({"from": src, "to": dst, "label": None})
    for i in inputs:
        src, dst = f"dataset:{i['dataset_id']}", f"model:{i['model_id']}"
        # A model may read a dataset from another project only if something
        # went wrong - _validate_and_set_inputs refuses it - but the graph
        # must not invent a node for one if it ever happens.
        if src in known and dst in known:
            edges.append({"from": src, "to": dst, "label": i["input_alias"]})
    for m in models:
        if m["output_dataset_id"] is not None:
            src, dst = f"model:{m['id']}", f"dataset:{m['output_dataset_id']}"
            if src in known and dst in known:
                edges.append({"from": src, "to": dst, "label": None})

    if focus is not None:
        if focus not in known:
            raise NotFoundError("node")
        component = _connected_component(known, edges, focus)
        nodes = [n for n in nodes if n["id"] in component]
        edges = [e for e in edges if e["from"] in component and e["to"] in component]
        known = component

    # **p.32's link types, and they are deliberately *not* edges** (§351).
    #
    # > "You can then view link types related to the object type and use the
    # >  graph to visualize connections between your datasets and the newly
    # >  added object type." (p.32)
    #
    # `edges` means *data flows this way*: it is what `_layer` builds the
    # build order from and what `cycles` reports on. A link type is a
    # relationship between two object types, not a dependency between them —
    # so putting one in `edges` would make two types that reference each other
    # a reported "cycle" in a pipeline, which is an ordinary and correct
    # ontology and a false alarm about the data.
    #
    # It is also why they are resolved *after* the focus narrowing rather than
    # before: a link must not drag a dataset into a lineage view that has no
    # data path to the focus. Both ends have to be on the graph already, which
    # is the same `known` guard every other edge here passes through.
    on_graph = [n["resource_id"] for n in nodes if n["kind"] == "object_type"]
    links: list[dict[str, Any]] = []
    if on_graph:
        for row in await fetch_all(
            conn,
            """
            SELECT id, api_name, display_name, cardinality::text AS cardinality,
                   from_object_type_id, to_object_type_id
              FROM link_types
             WHERE from_object_type_id = ANY(CAST(:ids AS uuid[]))
               AND to_object_type_id = ANY(CAST(:ids AS uuid[]))
             ORDER BY display_name, api_name
            """,
            {"ids": on_graph},
        ):
            links.append({
                "id": str(row["id"]),
                "from": f"object_type:{row['from_object_type_id']}",
                "to": f"object_type:{row['to_object_type_id']}",
                "name": row["display_name"] or row["api_name"],
                "cardinality": row["cardinality"],
            })

    _mark_out_of_date(nodes, edges)

    layers, cycles = _layer(known, edges)
    for node in nodes:
        node["layer"] = layers[node["id"]]
        node["in_cycle"] = any(node["id"] in c for c in cycles)

    # Position within a layer: stable and name-ordered, so the same project
    # always draws the same way rather than shuffling between page loads.
    by_layer: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node in sorted(nodes, key=lambda n: (n["layer"], n["kind"], n["name"].lower())):
        node["position"] = len(by_layer[node["layer"]])
        by_layer[node["layer"]].append(node)

    for node in nodes:
        node["is_focus"] = node["id"] == focus

    return {
        "nodes": sorted(nodes, key=lambda n: (n["layer"], n["position"])),
        "edges": edges,
        # Beside the edges rather than among them — see where they are built.
        "links": links,
        "cycles": cycles,
        "layer_count": (max(layers.values()) + 1) if layers else 0,
    }


#: p.51's two answerable questions, as the two states a dataset can be in.
#: Ordered most specific first, which is also which one wins when both apply:
#: "its input is newer than it" names the dataset to rebuild, and "an upstream
#: is out of date" only says to look further up.
INPUT_IS_NEWER = "input_is_newer"
UPSTREAM_IS_OUT_OF_DATE = "upstream_is_out_of_date"


def _mark_out_of_date(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> None:
    """Which datasets are out of date, and which of p.51's reasons it is.

    > "Is my dataset build failing? Is there an **upstream dataset that hasn't
    >  built and isn't up to date**? Have we received up-to-date data from the
    >  source?" (`data-lineage` p.51)

    **Two of those three, and the third is named rather than guessed at.** The
    first is already on the graph — a model's `last_run_status` is red when its
    build failed. The second is this function. The third asks whether the
    *source* is current, which needs an expectation about how often data
    arrives that this platform has nowhere to record; inventing one would put a
    number on the screen that nothing stands behind.

    **Times are compared, not version numbers.** Two datasets' version numbers
    are independent counters, so "input is at v7 and output at v3" says nothing
    at all; when each last *became what it is* is the comparison that means
    something. `built_at` is the latest version's `created_at` rather than
    `datasets.updated_at`, because a rename touches the latter and a rename is
    not a build.

    **The two `None` guards are unfalsifiable, and they stay.** A sweep found
    that nothing can reach them: `models.output_dataset_id` is NULL until the
    first run, so a never-run model contributes no output *node* at all, and
    every dataset that exists has a version. §213 says delete a check nothing
    can make fail — with the stated exception of one whose absence would be a
    real fault, and this is that: `None > datetime` raises, and a `TypeError`
    here is a 500 on a read path rather than a wrong answer. Two lines against
    that trade is worth making, and saying so is better than a test that
    pretends to exercise them. The docstring is the guard's justification
    because no test can be.

    Mutates the nodes, because the caller is about to lay them out and a second
    pass to merge two lists of the same nodes is a second chance to mismatch
    them.
    """
    by_id = {n["id"]: n for n in nodes}
    # Dataset → the datasets feeding it, through whichever model sits between.
    # The graph's edges are dataset→model and model→dataset, so the producing
    # model is the hop this collapses.
    into: dict[str, list[str]] = defaultdict(list)
    downstream: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        downstream[edge["from"]].append(edge["to"])
    for model_id, outputs in list(downstream.items()):
        if not model_id.startswith("model:"):
            continue
        for output in outputs:
            for source, targets in downstream.items():
                if source.startswith("dataset:") and model_id in targets:
                    into[output].append(source)

    stale: set[str] = set()
    for output, sources in into.items():
        built = by_id.get(output, {}).get("built_at")
        if built is None:
            continue
        for source in sources:
            fed = by_id.get(source, {}).get("built_at")
            if fed is not None and fed > built:
                node = by_id[output]
                node["out_of_date"] = True
                node["out_of_date_reason"] = INPUT_IS_NEWER
                stale.add(output)
                break

    # Then downstream of those, which is p.51's second question asked one hop
    # further along. Breadth-first with a `seen` set, so a cycle terminates
    # rather than spinning — `_layer` reports cycles, it does not remove them.
    frontier = list(stale)
    seen = set(stale)
    while frontier:
        current = frontier.pop()
        for step in downstream.get(current, []):
            for onward in ([step] if step.startswith("dataset:")
                           else downstream.get(step, [])):
                if onward in seen or onward not in by_id:
                    continue
                seen.add(onward)
                frontier.append(onward)
                # **No "unless it already has a reason" here, because `seen`
                # already is that check.** It starts as the directly-stale set,
                # so every node this loop reaches is one nothing has marked —
                # a sweep proved the guard unfalsifiable, which is the tell for
                # a second answer to a question something else answers (§213).
                by_id[onward]["out_of_date"] = True
                by_id[onward]["out_of_date_reason"] = UPSTREAM_IS_OUT_OF_DATE


def _connected_component(node_ids: set[str], edges: list[dict[str, Any]], start: str) -> set[str]:
    """Every node reachable from `start` ignoring edge direction. Undirected
    on purpose: a dataset's lineage is both what produced it and what reads
    it, and a sibling model reading the same input is part of the same story
    - it is what someone tracing an outage needs to see."""
    adjacency: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        adjacency[e["from"]].add(e["to"])
        adjacency[e["to"]].add(e["from"])

    seen: set[str] = set()
    frontier = [start]
    while frontier:
        current = frontier.pop()
        if current in seen or current not in node_ids:
            continue
        seen.add(current)
        frontier.extend(adjacency[current] - seen)
    return seen


def _health_status(results: Any) -> str | None:
    """The overall status out of a cached expectation_results payload, or
    None when nothing has been evaluated for that dataset yet."""
    if not isinstance(results, dict):
        return None
    status = results.get("status")
    return status if isinstance(status, str) else None


def _layer(node_ids: set[str], edges: list[dict[str, Any]]) -> tuple[dict[str, int], list[list[str]]]:
    """Longest-path layering via Kahn's algorithm.

    A node sits one layer past its furthest-downstream input, so every edge
    points strictly rightwards and a source (an upload, a model with no
    inputs) starts at layer 0. Returns the layer of every node plus the
    cyclic groups, which is the same traversal: whatever still has
    unsatisfied inputs once the queue drains cannot be topologically
    ordered.
    """
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {n: 0 for n in node_ids}
    for e in edges:
        outgoing[e["from"]].append(e["to"])
        indegree[e["to"]] += 1

    layers = {n: 0 for n in node_ids}
    queue = sorted(n for n in node_ids if indegree[n] == 0)
    placed: set[str] = set()
    while queue:
        current = queue.pop(0)
        placed.add(current)
        for nxt in outgoing[current]:
            layers[nxt] = max(layers[nxt], layers[current] + 1)
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    unplaced = node_ids - placed
    if not unplaced:
        return layers, []

    # Everything left is in a cycle or downstream of one. Group it by
    # reachability so the view can name each cycle separately rather than
    # reporting one undifferentiated blob, and give each member a layer
    # past its placed inputs so it still draws left-to-right against the
    # acyclic part of the graph.
    for node in unplaced:
        upstream = [e["from"] for e in edges if e["to"] == node and e["from"] in placed]
        layers[node] = max((layers[u] + 1 for u in upstream), default=0)

    adjacency: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e["from"] in unplaced and e["to"] in unplaced:
            adjacency[e["from"]].add(e["to"])
            adjacency[e["to"]].add(e["from"])

    groups: list[list[str]] = []
    remaining = set(unplaced)
    while remaining:
        seed = min(remaining)
        group: set[str] = set()
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            if current in group:
                continue
            group.add(current)
            frontier.extend(adjacency[current] - group)
        remaining -= group
        groups.append(sorted(group))
    return layers, sorted(groups)
