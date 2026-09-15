/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * > "Click the Settings icon next to the object type to view its
 * > configuration in a new Ontology manager tab." (p.32)
 *
 * **One rule in one place, because there are three graphs.** The project
 * pipeline page, the dataset app's Lineage tab and the datasets page's lineage
 * dialog all draw `PipelineGraphView`, and each had its own `onOpen` written
 * out by hand — which is how `object_type` would have become a node three
 * places draw and two of them cannot open.
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type { PipelineColumn, PipelineNode } from "@/lib/types";

/** The project-relative section each kind of node belongs to. */
export function nodeSection(node: Pick<PipelineNode, "kind">): string {
  if (node.kind === "model") return "models";
  if (node.kind === "object_type") return "objects";
  return "datasets";
}

/**
 * The path to open this node at, under a workspace and project.
 *
 * Whether a caller *should* open a given kind is the caller's own decision —
 * the lineage dialog opened from the datasets list deliberately does nothing
 * for a dataset node, because the list it was opened over is right behind it.
 * This answers "where would it go", which is the half that must not differ
 * between the three graphs.
 */
export function nodePath(
  node: Pick<PipelineNode, "kind">, workspace: string, project: string,
): string {
  return `/${workspace}/${project}/${nodeSection(node)}`;
}

/**
 * What a node's out-of-date state reads as (§352; `data-lineage` p.51).
 *
 * > "Is there an upstream dataset that hasn't built and isn't up to date?"
 * > (p.51)
 *
 * **Two sentences rather than one badge**, because the two states send a
 * reader to different places: one names *this* dataset as the thing to
 * rebuild, and the other says the thing to rebuild is further up. A single
 * "out of date" would have somebody rebuilding the wrong one and watching it
 * come back stale.
 *
 * Returns `""` for a node that is current, which is most of them.
 */
export function outOfDateNote(
  node: Pick<PipelineNode, "out_of_date" | "out_of_date_reason">,
): string {
  if (!node.out_of_date) return "";
  if (node.out_of_date_reason === "upstream_is_out_of_date") {
    return "an upstream is out of date";
  }
  // Anything else out of date is the direct case. Not keyed on the exact
  // string: a reason this build has not heard of still means *something* is
  // stale, and saying so beats drawing nothing at all.
  return "its input is newer";
}

/* ------------------------------------------------------------------ *
 * Selecting several nodes (§354; `data-lineage` p.7, p.54, p.55)
 * ------------------------------------------------------------------ */

/**
 * Node card geometry, and where a node sits on the canvas.
 *
 * **Here rather than in the component** because §354 gave the numbers a second
 * reader: the drag rectangle has to know where the cards are, and the cards
 * have to be drawn there. Two copies of this arithmetic is a marquee that
 * selects the node above the one it is drawn over, and nothing on the screen
 * says which copy is wrong (§191).
 *
 * The API returns each node's layer and its position within it
 * (apps/api/src/services/pipeline.py), so this is arithmetic rather than a
 * layout library.
 */
export const NODE_W = 190;
export const NODE_H = 74;
export const GAP_X = 88;
export const GAP_Y = 26;
export const PAD = 28;

export function nodeX(layer: number): number {
  return PAD + layer * (NODE_W + GAP_X);
}
export function nodeY(position: number): number {
  return PAD + position * (NODE_H + GAP_Y);
}

/** Two corners of a drag, in canvas coordinates. Either corner may be first. */
export interface Rect {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

/**
 * How far the pointer must travel before a press counts as a drag rather than
 * a click.
 *
 * A press on a node card in Drag select mode is both — the card's own click
 * handler fires *and* a zero-sized rectangle closes over it, and the two
 * cancel each other out, so the node a person clicked ends up unselected. The
 * floor is what lets the click handler have it.
 */
export const DRAG_FLOOR = 4;

export function isDrag(rect: Rect): boolean {
  return (
    Math.abs(rect.x2 - rect.x1) >= DRAG_FLOOR ||
    Math.abs(rect.y2 - rect.y1) >= DRAG_FLOOR
  );
}

/**
 * The nodes a drag rectangle covers (p.7's Drag select mode).
 *
 * > "To use the cursor to select multiple nodes, switch to **Drag select**
 * > mode in the graph tools or hold `Shift` while clicking and dragging."
 * > (p.7)
 *
 * **Overlap, not containment.** A rectangle that visibly covers most of a card
 * has selected it as far as the person drawing it is concerned; requiring the
 * whole card means dragging past the edge of a graph you cannot see the end of
 * to pick up the node you are looking at.
 */
export function nodesInRect(
  nodes: readonly Pick<PipelineNode, "id" | "layer" | "position">[],
  rect: Rect,
): string[] {
  const left = Math.min(rect.x1, rect.x2);
  const right = Math.max(rect.x1, rect.x2);
  const top = Math.min(rect.y1, rect.y2);
  const bottom = Math.max(rect.y1, rect.y2);
  return nodes
    .filter((node) => {
      const nx = nodeX(node.layer);
      const ny = nodeY(node.position);
      return nx <= right && nx + NODE_W >= left && ny <= bottom && ny + NODE_H >= top;
    })
    .map((node) => node.id);
}

/**
 * What clicking a node does to the selection (p.54).
 *
 * > "You can also hold down `Ctrl` / `Command` to select multiple nodes at
 * > once, or use `Ctrl` / `Command` + A to select all nodes." (p.54)
 *
 * A plain click replaces the selection, and clicking the one selected node
 * clears it — the behaviour the single-selection graph already had, because a
 * click that could only ever add would leave a reader with no way back to one
 * node. `additive` (Ctrl/Cmd) toggles just this node and leaves the rest.
 *
 * Order is preserved rather than sorted: this is what the reader clicked, in
 * the order they clicked it, and nothing downstream reads it as a set.
 */
export function toggleSelected(
  selected: readonly string[],
  id: string,
  additive: boolean,
): string[] {
  if (additive) {
    return selected.includes(id)
      ? selected.filter((each) => each !== id)
      : [...selected, id];
  }
  if (selected.length === 1 && selected[0] === id) return [];
  return [id];
}

/**
 * The frequent-columns histogram, narrowed to a selection (p.54, p.55).
 *
 * > "Under the Frequent Columns section, you can see the most frequent columns
 * > by name **in your selection**." (p.55)
 *
 * §353 built this over the graph as drawn, which is p.54's first step — "ensure
 * you added all datasets of interest in your pipeline to your lineage graph" —
 * with the second step missing. This is the second step, and it is done here
 * rather than on the server because the server already sends which datasets
 * hold each column: narrowing is an intersection over data the page has, and a
 * round trip per rectangle would lag behind the drag that caused it.
 *
 * **An empty selection is the whole graph**, not an empty histogram. Nothing
 * selected is the state the page opens in, and a panel that stays blank until
 * you have drawn a rectangle is a panel most readers never see working.
 *
 * A selection of nodes that are not datasets *does* come back empty, and that
 * is the honest answer: two models have no columns between them.
 *
 * Re-sorted rather than filtered in place, because narrowing changes the
 * counts and so changes the order — the whole point of the list is that the
 * first name is the most frequent one.
 */
export function columnsIn(
  columns: readonly PipelineColumn[],
  selected: readonly string[],
): PipelineColumn[] {
  if (selected.length === 0) return [...columns];
  const within = new Set(selected);
  return columns
    .map((column) => ({
      name: column.name,
      datasets: column.datasets.filter((id) => within.has(id)),
    }))
    .filter((column) => column.datasets.length > 0)
    .sort(
      (a, b) =>
        b.datasets.length - a.datasets.length ||
        // Codepoint order, not `localeCompare`: this re-sorts a list the
        // server already sorted with Python's `sorted(...)` on the name, and a
        // tie broken one way here and the other way there would have the list
        // reorder itself the moment a reader selects every node on the graph.
        (a.name < b.name ? -1 : a.name > b.name ? 1 : 0),
    );
}
