"use client";

import { useMemo, useRef, useState } from "react";
import type { PipelineGraph, PipelineNode } from "@/lib/types";

// One renderer, two entry points: the project-wide Pipeline page and a
// single dataset's lineage, which is the same endpoint with a `focus`
// (apps/api/src/services/pipeline.py). Roadmap Datasets item 5 asked for
// lineage to reuse "whatever graph-rendering approach Models item 2 settles
// on" - this file is that approach, so there is only ever one of it.
//
// The API returns each node's layer and its position within that layer
// (apps/api/src/services/pipeline.py), so laying the graph out is arithmetic
// rather than a graph-layout library — see that module's docstring for why
// the layering lives on the server.
const NODE_W = 190;
const NODE_H = 74;
const GAP_X = 88;
const GAP_Y = 26;
const PAD = 28;

function x(layer: number) {
  return PAD + layer * (NODE_W + GAP_X);
}
function y(position: number) {
  return PAD + position * (NODE_H + GAP_Y);
}

/** A cubic bezier from one node's right edge to the next node's left edge.
 *  Horizontal control points keep every edge reading left-to-right even when
 *  it spans several layers. */
function edgePath(from: PipelineNode, to: PipelineNode): string {
  const x1 = x(from.layer) + NODE_W;
  const y1 = y(from.position) + NODE_H / 2;
  const x2 = x(to.layer);
  const y2 = y(to.position) + NODE_H / 2;
  const bend = Math.max(30, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

function statusColour(node: PipelineNode): string {
  if (node.kind === "model") {
    if (node.last_run_status === "succeeded") return "var(--accent)";
    if (node.last_run_status === "failed") return "var(--danger)";
    return "var(--line-strong)";
  }
  if (node.health_status === "fail") return "var(--danger)";
  if (node.health_status === "warn") return "var(--brass)";
  if (node.health_status === "pass") return "var(--accent)";
  return "var(--line-strong)";
}

function subtitle(node: PipelineNode): string {
  if (node.kind === "model") {
    const trigger =
      node.trigger_mode === "cron" ? "scheduled"
      : node.trigger_mode === "upstream" ? "on new input data"
      : "manual";
    return `${node.language === "python" ? "Python" : "SQL"} · ${trigger}`;
  }
  const rows = node.row_count === null ? "" : `${node.row_count.toLocaleString()} rows`;
  return [rows, node.origin === "model_output" ? "model output" : node.origin]
    .filter(Boolean)
    .join(" · ");
}

function NodeCard({
  node,
  selected,
  onSelect,
}: {
  node: PipelineNode;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      title={node.name}
      style={{
        position: "absolute",
        left: x(node.layer),
        top: y(node.position),
        width: NODE_W,
        height: NODE_H,
        textAlign: "left",
        padding: "9px 11px",
        background: "var(--panel)",
        border: `${node.is_focus ? 2 : 1}px solid ${
          selected || node.is_focus
            ? "var(--accent)"
            : node.in_cycle
              ? "var(--danger)"
              : "var(--line-strong)"
        }`,
        borderLeft: `4px solid ${statusColour(node)}`,
        borderRadius: "var(--radius)",
        boxShadow: selected ? "var(--shadow-card-hover)" : "var(--shadow-card)",
        cursor: "pointer",
        display: "block",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--ink-soft)",
        }}
      >
        {node.kind}
        {node.in_cycle && <span style={{ color: "var(--danger)" }}> · in a cycle</span>}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display)",
          fontSize: 13.5,
          color: "var(--ink)",
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {node.name}
      </div>
      <div style={{ fontSize: 11.5, color: "var(--ink-soft)" }}>{subtitle(node)}</div>
    </button>
  );
}

function Details({
  node,
  onOpen,
}: {
  node: PipelineNode;
  onOpen: () => void;
}) {
  const when = node.last_run_at ?? node.updated_at;
  return (
    <div
      style={{
        borderTop: "1px solid var(--line)",
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        gap: 16,
        flexWrap: "wrap",
      }}
    >
      <div>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 14 }}>{node.name}</div>
        <div className="slug">{node.slug ?? node.kind}</div>
      </div>
      {node.kind === "model" ? (
        <>
          <span className="chip">{node.language === "python" ? "Python" : "SQL"}</span>
          <span className="chip">{node.trigger_mode}</span>
          <span
            className={
              node.last_run_status === "succeeded" ? "status-ok"
              : node.last_run_status === "failed" ? "status-error"
              : "status-unconfigured"
            }
          >
            <span className="status-dot" />
            <span className="status-label">{node.last_run_status ?? "never run"}</span>
          </span>
        </>
      ) : (
        <>
          <span className="chip">v{node.current_version}</span>
          <span className="chip">{node.row_count?.toLocaleString()} rows</span>
          {node.health_status && <span className="chip">health: {node.health_status}</span>}
        </>
      )}
      {when && <span className="slug">{new Date(when).toLocaleString()}</span>}
      <button className="btn quiet" style={{ marginLeft: "auto" }} onClick={onOpen}>
        Open {node.kind}
      </button>
    </div>
  );
}



export function PipelineGraphView({
  graph,
  onOpen,
  maxHeight = 560,
}: {
  graph: PipelineGraph;
  onOpen: (node: PipelineNode) => void;
  maxHeight?: number;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);

  const byId = useMemo(() => new Map(graph.nodes.map((n) => [n.id, n])), [graph.nodes]);
  const canvas = useMemo(() => {
    const width = PAD + graph.layer_count * (NODE_W + GAP_X);
    const rows = Math.max(1, ...graph.nodes.map((n) => n.position + 1));
    return { width: Math.max(width, 400), height: PAD * 2 + rows * (NODE_H + GAP_Y) };
  }, [graph]);

  const selectedNode = selected ? byId.get(selected) ?? null : null;

  if (graph.nodes.length === 0) {
    return (
      <div className="state">
        Nothing to draw yet — upload a dataset or create a model and it appears here.
      </div>
    );
  }

  return (
    <>
      {graph.cycles.length > 0 && (
        <div className="form-error" style={{ marginBottom: 12 }}>
          {graph.cycles.length === 1 ? "A cycle" : `${graph.cycles.length} cycles`} here:{" "}
          {graph.cycles.flat().length} resources feed each other in a loop. A model in a
          cycle set to run on new input data will re-trigger itself indefinitely.
        </div>
      )}
      <div className="form-actions" style={{ marginBottom: 8, justifyContent: "flex-end" }}>
        <button className="btn quiet" onClick={() => setZoom((z) => Math.max(0.4, z - 0.15))}>
          −
        </button>
        <button
          className="btn quiet"
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button className="btn quiet" onClick={() => setZoom((z) => Math.min(2, z + 0.15))}>
          +
        </button>
      </div>
      <div
        style={{
          border: "1px solid var(--line)",
          borderRadius: "var(--radius)",
          background: "var(--paper)",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            // Tall enough for the graph, capped so a wide pipeline doesn't
            // push the detail bar off the screen.
            height: Math.min(maxHeight, Math.max(240, canvas.height)),
            overflow: "hidden",
            position: "relative",
            cursor: drag.current ? "grabbing" : "grab",
          }}
          onMouseDown={(e) => {
            drag.current = { x: e.clientX, y: e.clientY, panX: pan.x, panY: pan.y };
          }}
          onMouseMove={(e) => {
            if (!drag.current) return;
            setPan({
              x: drag.current.panX + (e.clientX - drag.current.x),
              y: drag.current.panY + (e.clientY - drag.current.y),
            });
          }}
          onMouseUp={() => {
            drag.current = null;
          }}
          onMouseLeave={() => {
            drag.current = null;
          }}
        >
          <div
            style={{
              position: "absolute",
              transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
              transformOrigin: "0 0",
              width: canvas.width,
              height: canvas.height,
            }}
          >
            <svg
              width={canvas.width}
              height={canvas.height}
              style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
            >
              <defs>
                <marker
                  id="pipeline-arrow"
                  viewBox="0 0 8 8"
                  refX="7"
                  refY="4"
                  markerWidth="7"
                  markerHeight="7"
                  orient="auto"
                >
                  <path d="M 0 0 L 8 4 L 0 8 z" fill="var(--line-strong)" />
                </marker>
              </defs>
              {graph.edges.map((e, i) => {
                const from = byId.get(e.from);
                const to = byId.get(e.to);
                if (!from || !to) return null;
                const touched = selected === e.from || selected === e.to;
                return (
                  <path
                    key={i}
                    d={edgePath(from, to)}
                    fill="none"
                    stroke={touched ? "var(--accent)" : "var(--line-strong)"}
                    strokeWidth={touched ? 2 : 1.25}
                    markerEnd="url(#pipeline-arrow)"
                  />
                );
              })}
            </svg>
            {graph.nodes.map((n) => (
              <NodeCard
                key={n.id}
                node={n}
                selected={selected === n.id}
                onSelect={() => setSelected(n.id === selected ? null : n.id)}
              />
            ))}
          </div>
        </div>
        {selectedNode && <Details node={selectedNode} onOpen={() => onOpen(selectedNode)} />}
      </div>
    </>
  );
}
