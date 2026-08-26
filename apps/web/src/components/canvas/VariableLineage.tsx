"use client";

/** p.77's variable lineage graph, drawn.
 *
 * > "Each node on the graph represents a variable or widget. Nodes with
 * > dependencies have chevron arrows on their top and bottom edges. Select an
 * > arrow to expand a node's parents (upstream dependencies) or children
 * > (downstream consumers)… Use the Show all action in the graph header to
 * > expand to the full application graph or Clear to remove all nodes.
 * >
 * > Undo and redo options in the graph header step backward and forward through
 * > expand, collapse, and selection actions." (p.78)
 *
 * The graph, the expansion rules and the history are in `variable-lineage.ts`
 * and tested without a browser. What is here is the drawing and the wiring.
 *
 * **Laid out by arithmetic, not by a graph library.** `pipeline-graph.tsx` made
 * this choice first and the reasoning carries: a layer index and a position
 * within it are enough for a left-to-right dependency graph, and a library
 * would be a dependency, a bundle and a second set of behaviours to learn for a
 * panel this size. Layers come from the model; position is the order within a
 * layer.
 *
 * **Divergence, stated:** p.78's chevrons sit "on the top and bottom edges" of
 * a node, which is a vertical graph. This draws left-to-right, because that is
 * what `pipeline-graph.tsx` already does for the same kind of picture and two
 * directions for two dependency graphs in one product is a worse divergence
 * than one direction that differs from Foundry's. The chevrons are on the left
 * and right edges accordingly, and mean exactly what p.78 says: upstream and
 * downstream.
 */
import { useMemo, useState } from "react";

import type { WorkshopVariable } from "@/lib/types";
import {
  buildGraph, clear, collapse, expand, hasMore, initial, layers, redo, showAll,
  step, undo, type History, type Lineage,
} from "./variable-lineage";

const NODE_W = 150;
const NODE_H = 44;
const GAP_X = 70;
const GAP_Y = 16;
const PAD = 24;
/** A chevron's clickable square. The glyph is a few pixels wide; a pointer
 * target has to be bigger than its ink or the arrow is decoration. */
const HIT = 18;

function x(layer: number) {
  return PAD + layer * (NODE_W + GAP_X);
}
function y(position: number) {
  return PAD + position * (NODE_H + GAP_Y);
}

interface Placed {
  id: string;
  layer: number;
  position: number;
}

/** Where each shown node sits. Layer from the model; position is its order
 * within the layer, taken from the id so the picture does not reshuffle when
 * something elsewhere expands. */
function place(graph: Lineage, shown: ReadonlySet<string>): Placed[] {
  const byLayer = layers(graph, shown);
  const counts = new Map<number, number>();
  return [...shown]
    .filter((id) => graph.nodes.has(id))
    .sort()
    .map((id) => {
      const layer = byLayer.get(id) ?? 0;
      const position = counts.get(layer) ?? 0;
      counts.set(layer, position + 1);
      return { id, layer, position };
    });
}

function edgePath(from: Placed, to: Placed): string {
  const x1 = x(from.layer) + NODE_W;
  const y1 = y(from.position) + NODE_H / 2;
  const x2 = x(to.layer);
  const y2 = y(to.position) + NODE_H / 2;
  const bend = Math.max(24, (x2 - x1) / 2);
  return `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`;
}

/** One chevron: a glyph over a square hit area, as one clickable group. */
function Chevron({
  at, glyph, title, testid, onSelect,
}: {
  at: number;
  glyph: string;
  title: string;
  testid: string;
  onSelect: () => void;
}) {
  return (
    <g
      className="lineage-chevron"
      data-testid={testid}
      role="button"
      onClick={onSelect}
      transform={`translate(${at}, ${(NODE_H - HIT) / 2})`}
    >
      <title>{title}</title>
      <rect width={HIT} height={HIT} rx={4} />
      <text x={HIT / 2} y={HIT / 2 + 1}>{glyph}</text>
    </g>
  );
}

export function VariableLineage({
  variables,
  layout,
  /** The variable the panel has open, if any: p.77 puts this behind a button in
   * the Variables panel header, so opening it while looking at a variable
   * should start from that variable rather than from nothing. */
  focus,
  onClose,
}: {
  variables: Record<string, WorkshopVariable>;
  layout: unknown;
  focus?: string | null;
  onClose: () => void;
}) {
  const graph = useMemo(
    () => buildGraph(variables, (layout ?? {}) as Record<string, unknown>),
    [variables, layout],
  );
  const [history, setHistory] = useState<History>(() =>
    initial(new Set(focus && variables[focus] ? [focus] : [])));
  const { shown, selected } = history.present;
  const placed = useMemo(() => place(graph, shown), [graph, shown]);
  const at = new Map(placed.map((p) => [p.id, p]));

  const width = Math.max(...placed.map((p) => x(p.layer) + NODE_W + PAD), 360);
  const height = Math.max(...placed.map((p) => y(p.position) + NODE_H + PAD), 180);

  const act = (next: Parameters<typeof step>[1]) => setHistory((h) => step(h, next));

  return (
    <div className="canvas-scrim" data-testid="lineage">
      <div className="lineage">
        <div className="lineage-head">
          <h3>Variable lineage</h3>
          <div className="lineage-actions">
            <button
              type="button" className="btn quiet" data-testid="lineage-undo"
              disabled={history.past.length === 0}
              onClick={() => setHistory(undo)}
            >
              Undo
            </button>
            <button
              type="button" className="btn quiet" data-testid="lineage-redo"
              disabled={history.future.length === 0}
              onClick={() => setHistory(redo)}
            >
              Redo
            </button>
            <button
              type="button" className="btn quiet" data-testid="lineage-show-all"
              onClick={() => act({ shown: showAll(graph) })}
            >
              Show all
            </button>
            <button
              type="button" className="btn quiet" data-testid="lineage-clear"
              onClick={() => act({ shown: clear(), selected: null })}
            >
              Clear
            </button>
            <button
              type="button" className="btn quiet" data-testid="lineage-close"
              onClick={onClose}
            >
              Close
            </button>
          </div>
        </div>

        {placed.length === 0 ? (
          <p className="state" data-testid="lineage-empty">
            Nothing on the graph. Open a variable and reopen this, or use Show all.
          </p>
        ) : (
          <div className="lineage-canvas">
            <svg
              width={width} height={height}
              role="img" aria-label="Variable lineage graph"
            >
              {graph.edges.map((edge) => {
                const from = at.get(edge.from);
                const to = at.get(edge.to);
                if (!from || !to) return null;
                return (
                  <path
                    key={`${edge.from}->${edge.to}:${edge.via}`}
                    className="lineage-edge"
                    d={edgePath(from, to)}
                    fill="none"
                  >
                    <title>{edge.via}</title>
                  </path>
                );
              })}
              {placed.map((p) => {
                const node = graph.nodes.get(p.id)!;
                // p.78's chevrons, and their inverses. Each is drawn only when
                // it would do something: an arrow that changes nothing is worse
                // than no arrow, because it claims a dependency is there.
                const moreUp = hasMore(graph, shown, p.id, "parents");
                const moreDown = hasMore(graph, shown, p.id, "children");
                const foldUp = collapse(graph, shown, p.id, "parents") !== shown;
                const foldDown = collapse(graph, shown, p.id, "children") !== shown;
                return (
                  <g
                    key={p.id}
                    className="lineage-group"
                    transform={`translate(${x(p.layer)}, ${y(p.position)})`}
                  >
                    <rect
                      className={`lineage-node is-${node.kind}${
                        selected === p.id ? " on" : ""}`}
                      data-testid={`lineage-node-${node.kind}`}
                      data-id={p.id}
                      width={NODE_W} height={NODE_H} rx={6}
                      onClick={() => act({ selected: selected === p.id ? null : p.id })}
                    >
                      <title>{node.label}</title>
                    </rect>
                    <text className="lineage-label" x={10} y={19}>
                      {node.label.slice(0, 18)}
                    </text>
                    <text className="lineage-kind" x={10} y={34}>{node.kind}</text>
                    {moreUp && (
                      <Chevron
                        at={-HIT - 4} glyph="‹" title="Show upstream"
                        testid={`lineage-parents-${p.id}`}
                        onSelect={() => act({ shown: expand(graph, shown, p.id, "parents") })}
                      />
                    )}
                    {foldUp && (
                      <Chevron
                        at={moreUp ? -HIT * 2 - 8 : -HIT - 4} glyph="›" title="Hide upstream"
                        testid={`lineage-collapse-parents-${p.id}`}
                        onSelect={() => act({ shown: collapse(graph, shown, p.id, "parents") })}
                      />
                    )}
                    {moreDown && (
                      <Chevron
                        at={NODE_W + 4} glyph="›" title="Show downstream"
                        testid={`lineage-children-${p.id}`}
                        onSelect={() => act({ shown: expand(graph, shown, p.id, "children") })}
                      />
                    )}
                    {foldDown && (
                      <Chevron
                        at={moreDown ? NODE_W + HIT + 8 : NODE_W + 4}
                        glyph="‹" title="Hide downstream"
                        testid={`lineage-collapse-children-${p.id}`}
                        onSelect={() => act({ shown: collapse(graph, shown, p.id, "children") })}
                      />
                    )}
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}
