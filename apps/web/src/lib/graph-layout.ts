/**
 * p.11's Layout menu: where the cards go (§424).
 *
 * > "The layout button provide various arrangement option for the nodes on the
 * > graph. Layout all nodes applies automatic layout for all the nodes on the
 * > graphs. When you select multiple nodes on the graph, you can apply other
 * > layouts (vertical, hierarchical, by level, etc.)." (p.11)
 *
 * > "You can arrange your nodes on the graph by color group under Layouts."
 * > (p.11)
 *
 * **This is the one place the cards' positions are decided, and that is the
 * whole point of the module.** Before §424 the arithmetic was two exported
 * functions (`nodeX`, `nodeY`) that four things read — the cards, the edge
 * curves, §354's drag rectangle and §423's SVG export — and adding a second
 * arrangement without gathering them first would have produced a graph whose
 * marquee selected the node that *would* have been under the pointer in the
 * old layout. That is §191's hazard with a new face, and §354's own note
 * already says it: two copies of the layer arithmetic is a marquee that
 * selects the node above the one it is drawn over.
 *
 * ---
 *
 * **Not gated on a selection, though p.11 gates its other layouts that way.**
 * Foundry's graph is built up node by node, so "lay out these" is a sensible
 * scope; this graph is a project drawn whole (§355), and an arrangement that
 * applied to part of it would leave the rest where the other arrangement put
 * them — two layouts on one canvas, overlapping. The layouts here apply to
 * the graph, which is the only scope that means anything when there is only
 * one graph.
 *
 * **Every layout keeps the server's layering.** `services/pipeline.py` runs
 * Kahn's and guarantees that every edge points from a lower layer to a higher
 * one; an arrangement that reordered by anything else would draw edges that
 * point backwards and stop being a picture of a pipeline. So a layout chooses
 * *which axis the layers run along* and *how nodes are grouped within one* —
 * never whether an ancestor is drawn before its descendant.
 */

import type { PipelineNode } from "./types";

export const NODE_W = 190;
export const NODE_H = 74;
export const GAP_X = 88;
export const GAP_Y = 26;
export const PAD = 28;

export interface LayoutOption {
  id: string;
  label: string;
  hint: string;
}

/** p.11's menu, narrowed to arrangements that mean something on this graph.
 *
 * `level` first and default, because it is what the graph drew before there
 * was a choice — p.11's own "Layout all nodes", which is the automatic one.
 */
export const LAYOUTS: LayoutOption[] = [
  { id: "level", label: "By level",
    hint: "p.11: left to right, a column per step of the pipeline" },
  { id: "vertical", label: "Vertical",
    hint: "p.11: the same order running down the page" },
  { id: "colour", label: "By colour group",
    hint: "p.11: rows grouped by what the colouring says" },
];

export const DEFAULT_LAYOUT = "level";

/** Where one card sits on the canvas. */
export interface Place {
  x: number;
  y: number;
}

/** What a layout needs of a node. `group` is §419's swatch key for it, which
 *  only the colour layout reads — passed in rather than computed here, so
 *  there is one rule about what a colour means and this module is not a
 *  second one (§292). */
export interface PlacedNode {
  id: string;
  layer: number;
  position: number;
  group?: string | null;
}

export interface Layout {
  /** Where each node goes, by node id. */
  at: Map<string, Place>;
  width: number;
  height: number;
}

/**
 * The canvas a set of places needs.
 *
 * **A gap's worth of room past the last card, not a padding's.** That is what
 * the canvas was before §424 gathered the arithmetic here, and keeping it
 * exactly is deliberate: this unit changes which arrangement is drawn and
 * nothing else, and a canvas that quietly shrank would move the viewport's
 * height, the scroll extent and where a drag past the last card lands. A
 * browser test caught precisely that — the first version computed a tight box
 * plus `PAD`, which is tidier and is a different feature.
 *
 * **A minimum rather than a hug**: a viewport sized to nothing is a panel a
 * reader would call broken, and an empty project is an ordinary thing to open
 * (§214).
 */
export function canvasOf(places: Map<string, Place>): { width: number; height: number } {
  let width = 400;
  let height = PAD * 2 + NODE_H;
  for (const place of places.values()) {
    width = Math.max(width, place.x + NODE_W + GAP_X);
    height = Math.max(height, place.y + NODE_H + GAP_Y + PAD);
  }
  return { width, height };
}

function sized(places: Map<string, Place>): Layout {
  return { at: places, ...canvasOf(places) };
}

/** p.11's automatic layout: a column per layer, left to right. */
function byLevel(nodes: readonly PlacedNode[]): Map<string, Place> {
  return new Map(nodes.map((node) => [node.id, {
    x: PAD + node.layer * (NODE_W + GAP_X),
    y: PAD + node.position * (NODE_H + GAP_Y),
  }]));
}

/** p.11's *vertical*: the same order running down the page.
 *
 * **The axes swap, and the gaps swap with them.** `GAP_X` is the horizontal
 * gap because a card is 190 wide and needs room for an edge curve between
 * columns; turned on its side, the *rows* are what the curve crosses. Reusing
 * each gap on its own axis would put 26px between stacked cards that are 74
 * tall and 88px between neighbours that are 190 wide — a drawing nobody could
 * read either way round. */
function vertical(nodes: readonly PlacedNode[]): Map<string, Place> {
  return new Map(nodes.map((node) => [node.id, {
    x: PAD + node.position * (NODE_W + GAP_Y),
    y: PAD + node.layer * (NODE_H + GAP_X),
  }]));
}

/** p.11's "arrange your nodes on the graph by color group".
 *
 * A row per group, the layers still running left to right within it — so a
 * reader can see every failing dataset together *and* still read which feeds
 * which, which neither a plain grid nor the level layout gives them.
 *
 * **Groups are ordered by first appearance in the node list**, which is the
 * server's ordering, so the rows do not reshuffle between renders. An
 * ungrouped node (the colouring is off, or it has no verdict) goes in a row of
 * its own at the end rather than being folded into the first group — §210,
 * one more time: no answer is not the same answer as everybody else's. */
function byColour(nodes: readonly PlacedNode[]): Map<string, Place> {
  const rows: string[] = [];
  const of = (node: PlacedNode) => node.group ?? "";
  for (const node of nodes) {
    const key = of(node);
    if (!rows.includes(key)) rows.push(key);
  }
  // Ungrouped last, whatever order it first appeared in.
  const order = [...rows.filter((r) => r !== ""), ...rows.filter((r) => r === "")];

  const places = new Map<string, Place>();
  let top = PAD;
  for (const row of order) {
    const inRow = nodes.filter((node) => of(node) === row);
    // The layers still run left to right inside the row, and a row is as tall
    // as its deepest stack of same-layer nodes.
    const byLayer = new Map<number, PlacedNode[]>();
    for (const node of inRow) {
      const held = byLayer.get(node.layer);
      if (held) held.push(node);
      else byLayer.set(node.layer, [node]);
    }
    let tallest = 1;
    for (const [layer, stack] of byLayer) {
      tallest = Math.max(tallest, stack.length);
      stack.forEach((node, index) => {
        places.set(node.id, {
          x: PAD + layer * (NODE_W + GAP_X),
          y: top + index * (NODE_H + GAP_Y),
        });
      });
    }
    // A clear gap between groups, so the rows read as groups rather than as
    // one grid with uneven spacing.
    top += tallest * (NODE_H + GAP_Y) + GAP_Y;
  }
  return places;
}

/**
 * Every card's place under one layout, with the canvas it needs.
 *
 * An unknown layout id falls back to the default rather than to nothing, for
 * the reason `swatchFor` does: a saved view (§360) naming a layout a later
 * build dropped should open looking like the graph.
 */
export function layoutOf(
  nodes: readonly PlacedNode[],
  layout: string,
): Layout {
  switch (layout) {
    case "vertical":
      return sized(vertical(nodes));
    case "colour":
      return sized(byColour(nodes));
    default:
      return sized(byLevel(nodes));
  }
}

/** The layout a stored view names, or the default if it names nothing this
 *  build offers — `colouringIn`'s rule, for `colouringIn`'s reason: the
 *  picker is a `<select>`, and a value no `<option>` carries shows the first
 *  one while the graph draws something else (§214). */
export function layoutIn(view: { layout?: string } | undefined): string {
  const named = view?.layout;
  if (named === undefined) return DEFAULT_LAYOUT;
  return LAYOUTS.some((option) => option.id === named) ? named : DEFAULT_LAYOUT;
}

/** Two corners of a drag, in canvas coordinates. Either corner may be first. */
export interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/**
 * The nodes a drag rectangle covers, **under the layout actually drawn**
 * (§354, §424).
 *
 * This moved here from `lib/pipeline-graph` when there was more than one
 * arrangement, and the move is the point: left where it was, it would have
 * gone on asking where a card *would* be under the level layout, and a
 * marquee drawn over a vertical graph would have selected a different set of
 * cards than the one it was drawn around. Nothing on the screen says which
 * copy of the arithmetic is wrong, which is exactly §191.
 *
 * **Overlap, not containment**: a rectangle that visibly covers most of a card
 * has selected it as far as the person drawing it is concerned, and requiring
 * the whole card means dragging past the edge of a graph you cannot see the
 * end of to pick up the node you are looking at.
 *
 * The order of the result is the node list's and **nothing promises it**,
 * unlike `toggleSelected`'s, because a rectangle has no order a reader chose.
 * §356's sweep confirmed it: sorting this output fails no test, and that is
 * correct rather than a gap (§213). A consumer that comes to need an order has
 * to ask for one here rather than assume this.
 */
export function nodesInRect(
  nodes: readonly Pick<PipelineNode, "id">[],
  rect: Rect,
  at: Map<string, Place>,
): string[] {
  const left = Math.min(rect.x1, rect.x2);
  const right = Math.max(rect.x1, rect.x2);
  const top = Math.min(rect.y1, rect.y2);
  const bottom = Math.max(rect.y1, rect.y2);
  return nodes
    .filter((node) => {
      const place = at.get(node.id);
      if (place === undefined) return false;
      return (
        place.x <= right && place.x + NODE_W >= left
        && place.y <= bottom && place.y + NODE_H >= top
      );
    })
    .map((node) => node.id);
}
