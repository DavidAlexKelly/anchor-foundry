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
                 ORDER BY v.version_number DESC LIMIT 1) AS expectation_results
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
            # Read from the cache only - see this module's docstring.
            "health_status": _health_status(d["expectation_results"]),
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
            "health_status": None,
            "language": m["language"],
            "trigger_mode": m["trigger_mode"],
            "last_run_status": m["last_run_status"],
            "last_run_at": m["last_run_at"],
        })

    known = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
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
        "cycles": cycles,
        "layer_count": (max(layers.values()) + 1) if layers else 0,
    }


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
