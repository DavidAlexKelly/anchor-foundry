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

import type { PipelineColumn, PipelineEdge, PipelineNode } from "@/lib/types";
// Relative, and a value import rather than a type one: vitest resolves no
// `@/` alias, so an aliased value import is a module this file's own tests
// cannot load.
import { DEFAULT_COLOURING } from "./node-colouring";

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
 *
 * The order of the result is the graph's and **nothing promises it**, unlike
 * `toggleSelected`'s, because a rectangle has no order a reader chose. §356's
 * sweep confirmed it: sorting this output fails no test, and that is correct
 * rather than a gap (§213). A consumer that comes to need an order has to ask
 * for one here rather than assume this.
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

/* ------------------------------------------------------------------ *
 * Growing a selection along the lineage (§355; `data-lineage` p.7, p.52)
 * ------------------------------------------------------------------ */

/** Which way along the arrows an expansion walks. */
export type Direction = "upstream" | "downstream";

/**
 * A selection grown along the graph's edges (p.7's arrows, p.52's **Expand
 * node** and **Expand parents**).
 *
 * > "After adding nodes to the graph, you can add their related resources by
 * > clicking on the arrows on either side of the node or by using the
 * > **Expand** option in the graph tools." (p.7)
 *
 * > "Then, select **Expand node**. You can see all of the ancestor nodes for
 * > that dataset by clicking the double left arrow above **Expand parents**."
 * > (p.52)
 *
 * **Selection, not addition, and that is the whole translation.** Foundry's
 * graph is built up from nothing because its scope is an enterprise, so its
 * arrows *add* resources; this graph is a project drawn whole, so there is
 * nothing to add and the same gesture grows the **selection** instead. That
 * keeps what the control is for — "show me what this dataset feeds" — and
 * drops the mechanism it only needed because the graph started empty. It also
 * lands where §354 left the histogram: expand downstream from a source, and
 * p.55's Frequent Columns is answering about everything it touches.
 *
 * `hops` is p.52's two granularities in one argument: `1` is an arrow on one
 * side of the node, `Infinity` is the double arrow that takes the whole chain.
 *
 * **Edges, not links.** An ontology link type is a relationship, not a
 * direction data flows, so two object types referring to each other are not
 * one upstream of the other (§351's rule, read the other way round).
 *
 * Breadth-first with a `seen` set, so a cycle terminates rather than spinning
 * — this graph reports cycles rather than removing them (§352). The frontier
 * is the nodes *this* hop found, never everything found so far: `hops` is a
 * distance, and a frontier that only grows never empties.
 *
 * The seeds come back in the answer: growing a selection keeps what was
 * already in it, which is what makes clicking the same button twice reach
 * further rather than start over.
 */
export function relatives(
  edges: readonly Pick<PipelineEdge, "from" | "to">[],
  seeds: readonly string[],
  direction: Direction,
  hops: number,
): string[] {
  const next = new Map<string, string[]>();
  for (const edge of edges) {
    const [at, to] =
      direction === "downstream" ? [edge.from, edge.to] : [edge.to, edge.from];
    const already = next.get(at);
    if (already) already.push(to);
    else next.set(at, [to]);
  }
  const grown = [...seeds];
  const seen = new Set(seeds);
  let frontier = [...seeds];
  for (let hop = 0; hop < hops && frontier.length > 0; hop += 1) {
    const found: string[] = [];
    for (const id of frontier) {
      for (const neighbour of next.get(id) ?? []) {
        if (seen.has(neighbour)) continue;
        seen.add(neighbour);
        grown.push(neighbour);
        found.push(neighbour);
      }
    }
    frontier = found;
  }
  return grown;
}

/* ------------------------------------------------------------------ *
 * Finding nodes on the graph (§356; `data-lineage` p.8)
 * ------------------------------------------------------------------ */

/**
 * The nodes a search matches (p.8's search helper, minus the half that has
 * nowhere to go here).
 *
 * > "Use the search helper to find Foundry resources **and add them to the
 * > graph**. Use the free-text search or browse the tree to find resources.
 * > Add a resource by clicking on it or use the buttons at the bottom of the
 * > view to **add all search results**... Use the **Advanced** tab to add
 * > filters to your search and sort your results." (p.8)
 *
 * **Find carries over; add does not.** p.8's helper does two things, and the
 * adding is only there because Foundry's graph starts empty over an
 * enterprise. This graph is a project drawn whole (§355 settled that), so
 * every result is already on it — which leaves *finding* one by name, still
 * real on a graph with forty cards, and turns "add all search results" into
 * **select all of them**, where §354's histogram and §355's expansions can
 * take it further.
 *
 * `kinds` is p.8's Advanced tab: an empty set is no restriction, which is what
 * a reader who has not touched it means.
 *
 * **Nothing matches nothing.** An empty query with no kind chosen returns no
 * results rather than every node, because the page opens in that state and a
 * search that starts by highlighting the whole graph has said nothing. A kind
 * on its own *is* a question, though — "show me the models" — so it answers.
 *
 * Name **and** slug, because the slug is what somebody writing a transform or
 * an action against an object type actually types, and it is the line the card
 * already shows them (§351).
 *
 * Results come back in the nodes' own order, which is the graph's: the layer
 * order the server sorted them into, so "the first match" means the one
 * furthest upstream rather than whichever the search happened to reach first.
 *
 * **`columns` is p.11's other half** (§417): "you can either search for the
 * name of the node or column names in datasets". One box for both, because
 * p.11 gives one — and because the question a reader brings to it ("where does
 * `site_id` live") does not come with a decision about which kind of name they
 * are about to type.
 *
 * It costs nothing to supply: `columnsIn` already reads this index off the
 * same rows the graph draws (§353), so finding the datasets that have a column
 * is the histogram asked from the search box instead of from the list.
 *
 * Omitted means name and slug only, which is every caller written before §417
 * and is the honest default: a search that silently started matching columns
 * would change what an existing saved view (§360) resolves to.
 */
export function search(
  nodes: readonly Pick<PipelineNode, "id" | "kind" | "name" | "slug">[],
  query: string,
  kinds: readonly PipelineNode["kind"][] = [],
  columns: readonly PipelineColumn[] = [],
): string[] {
  const needle = query.trim().toLowerCase();
  if (needle === "" && kinds.length === 0) return [];
  const wanted = new Set(kinds);
  const byColumn = datasetsWithColumn(columns, needle);
  return nodes
    .filter((node) => {
      // The kind filter is p.8's Advanced tab and it applies to every match,
      // column ones included: "show me the models called site" and "show me
      // the models with a column called site" are both answered by nothing,
      // because only datasets have columns.
      if (wanted.size > 0 && !wanted.has(node.kind)) return false;
      if (needle === "") return true;
      const name = node.name.toLowerCase();
      const slug = (node.slug ?? "").toLowerCase();
      return name.includes(needle) || slug.includes(needle) || byColumn.has(node.id);
    })
    .map((node) => node.id);
}

/** The datasets holding a column whose name matches, as node ids.
 *
 * **Takes a needle that is already known to be non-empty.** An `if (needle ===
 * "") return out` guard stood here and the sweep found it equivalent: both
 * callers answer the empty query before they consult this, so nothing could
 * reach it — and a guard that cannot fire is a claim nobody can check (§223).
 * What it stated is pinned where it is observable instead, by the tests that
 * ask `search` and `foundByColumn` for an empty query.
 */
function datasetsWithColumn(
  columns: readonly PipelineColumn[],
  needle: string,
): Set<string> {
  const out = new Set<string>();
  for (const column of columns) {
    if (!column.name.toLowerCase().includes(needle)) continue;
    for (const id of column.datasets) out.add(id);
  }
  return out;
}

/**
 * Which results matched **only** because of a column (p.11; §417).
 *
 * **A card that lights up for a reason nobody can see is worse than one that
 * does not light up at all** (§214). Searching `site_id` highlights datasets
 * whose names contain no such text, and without this the reader is left to
 * guess whether the graph is answering their question or has misunderstood it.
 * The count beside the box says how many of the results are of this kind, so
 * the answer explains itself.
 *
 * **Only**, deliberately: a dataset called `sites` holding a column called
 * `site_id` is a name match and needs no explaining, and counting it here
 * would make the explanation bigger than the surprise it exists to cover.
 */
export function foundByColumn(
  nodes: readonly Pick<PipelineNode, "id" | "kind" | "name" | "slug">[],
  query: string,
  columns: readonly PipelineColumn[],
): string[] {
  const needle = query.trim().toLowerCase();
  // **An exit for cost, not a check for correctness**, and the sweep is how
  // that got stated: removing it changes no answer. An empty needle makes
  // `name.includes(needle)` true for every node, so the filter below excludes
  // all of them and the result is `[]` either way. What it saves is the walk —
  // the search box is empty on every render until somebody types, and without
  // this each of those renders would build a set of every dataset holding any
  // column in order to throw it away.
  //
  // Kept rather than removed under §223 because §223 is about a *check* that
  // cannot fail. This one does not claim a behaviour; the behaviour is pinned
  // by the empty-query tests, which pass with or without it.
  if (needle === "") return [];
  const byColumn = datasetsWithColumn(columns, needle);
  if (byColumn.size === 0) return [];
  return nodes
    .filter((node) => {
      if (!byColumn.has(node.id)) return false;
      const name = node.name.toLowerCase();
      const slug = (node.slug ?? "").toLowerCase();
      return !name.includes(needle) && !slug.includes(needle);
    })
    .map((node) => node.id);
}

/* ------------------------------------------------------------------ *
 * The view a graph can be saved or shared at (§360; `data-lineage` p.12)
 * ------------------------------------------------------------------ */

/**
 * What a person chose to look at, and nothing about where the window was.
 *
 * **The same shape the server stores** (migration 0089), so a saved graph
 * round-trips without a translation layer in between — which is where the two
 * would drift.
 *
 * No zoom or pan, and that is db 0089's decision: where a viewport happened to
 * be is not what somebody means by "look at this", and a recipient whose
 * window is a different size lands somewhere else anyway (§214).
 */
export interface GraphView {
  focus?: string;
  column?: string;
  selected?: string[];
  query?: string;
  /** Wire-typed as strings because that is what comes back from the server;
   *  `kindsIn` narrows it at the boundary. */
  kinds?: string[];
  /** p.38's node colouring (§419). **A reading, not a decoration**, which is
   *  why it belongs in a saved view at all: a graph shared to say "these three
   *  are out of date with an ancestor" and reopened coloured by build status
   *  is a different sentence. Narrowed by `colouringIn` at the boundary, for
   *  the reason `kinds` is narrowed by `kindsIn`. */
  colouring?: string;
}

/** The kinds this graph draws, which is what a stored filter may name. */
export const GRAPH_KINDS: PipelineNode["kind"][] = ["dataset", "model", "object_type"];

/**
 * The kinds a stored view names, minus any this build does not draw.
 *
 * **Dropped rather than trusted.** A view saved by a later build, or by a
 * build that drew a kind this one has since removed, would otherwise put a
 * filter on the graph that matches nothing and offer no way to see that it
 * had. The server validates against its own list when a view is saved; this is
 * the same question asked at the other end, where the answer can have changed
 * in between.
 */
export function kindsIn(view: GraphView | undefined): PipelineNode["kind"][] {
  const known = new Set<string>(GRAPH_KINDS);
  return (view?.kinds ?? []).filter(
    (kind): kind is PipelineNode["kind"] => known.has(kind),
  );
}

/**
 * The view as the graph currently stands, with the empty parts left out.
 *
 * **Omitted rather than sent as empty**, matching what the server stores: a
 * view carrying `query: ""` and `selected: []` would save as a filter nobody
 * set, and reopen looking like somebody had chosen nothing on purpose.
 */
export function viewOf(state: {
  selected: readonly string[];
  column: string | null;
  query: string;
  kinds: readonly string[];
  colouring: string;
}): GraphView {
  const view: GraphView = {};
  if (state.selected.length > 0) view.selected = [...state.selected];
  if (state.column !== null) view.column = state.column;
  if (state.query.trim() !== "") view.query = state.query;
  if (state.kinds.length > 0) view.kinds = [...state.kinds];
  // The default is left out for the same reason an empty query is: it is the
  // state somebody who chose nothing is already in, and storing it would make
  // a graph saved before §419 existed and one saved with the picker untouched
  // into two different records of the same view.
  if (state.colouring !== DEFAULT_COLOURING) view.colouring = state.colouring;
  return view;
}
