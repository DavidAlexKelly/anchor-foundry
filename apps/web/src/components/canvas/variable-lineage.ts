/** p.77's variable lineage graph: how variables and widgets depend on one
 * another.
 *
 * > "Use the Variable lineage graph option found in the header of the Variables
 * > panel, to visualize how variables and widgets in your module depend on one
 * > another. Use it to debug recompute behavior, **trace which widgets read or
 * > write a variable**, and better understand complex relationships between
 * > application elements." (p.77)
 *
 * > "Each node on the graph represents a variable or widget. Nodes with
 * > dependencies have chevron arrows on their top and bottom edges. Select an
 * > arrow to expand a node's **parents** (upstream dependencies) or **children**
 * > (downstream consumers)… Use the **Show all** action in the graph header to
 * > expand to the full application graph or **Clear** to remove all nodes."
 * > (p.78)
 *
 * ---
 *
 * **"Read or write" is the whole design.** A widget that reads a variable is
 * downstream of it; a widget that writes one is upstream. Get that backwards
 * for a single prop and the graph points an arrow the wrong way — which is
 * worse than not drawing it, because the feature exists to be trusted while
 * debugging.
 *
 * So every entry in `REFERENCE_PROPS` is classified here. A prop missing from
 * this catalogue is an edge the graph silently omits: the widget and the
 * variable both appear, unconnected, and nothing says why. That is the fourth
 * instance of the shape §190, §191 and §193 were each caught by, so it gets its
 * guard on the way in rather than after somebody notices a missing arrow — and
 * here the guard is the **type**: `PROP_DIRECTION` is keyed by `REFERENCE_PROPS`
 * itself, so an unclassified prop does not compile. The test beside this module
 * pins each direction by hand, which the type cannot do.
 *
 * **This module is the graph and the expansion state, not the drawing.** p.78's
 * chevrons, Show all, Clear and undo/redo are all operations on a set of
 * visible node ids, and a set of ids is testable without a browser.
 */
import { REFERENCE_PROPS, referencesOf } from "../../lib/workshop-module";
import type { WorkshopVariable } from "../../lib/types";

/** Which direction a widget prop points.
 *
 * `read` — the widget consumes the variable, so the widget is **downstream**.
 * `write` — the widget produces it, so the widget is **upstream**.
 *
 * The judgement per prop, stated once:
 *
 * - a **Parameter control**'s `name` is the variable it sets, so a write;
 * - a **Filter List**'s `filterParameter` and a **Search**'s `searchParameter`
 *   are p.67's "output variable… created when adding the widget", so writes;
 * - a chart's `drilldownVariable` is p.69's "'Selected Objects' object set
 *   output produced by the Object Table widget" by another name — a write;
 * - everything else names something the widget *displays or obeys*: the set it
 *   draws, the boolean that hides it, the tab it follows. Reads.
 */
export const PROP_DIRECTION: Record<(typeof REFERENCE_PROPS)[number], "read" | "write"> = {
  // Writes — p.69's "output variables… data passed out of a given widget".
  name: "write",
  filterParameter: "write",
  searchParameter: "write",
  drilldownVariable: "write",
  // p.224's Object Table outputs - "data passed out of a given widget".
  activeVariable: "write",
  selectedVariable: "write",
  filterVariable: "write",
  // Reads — p.69's "input variables… data passed into a given widget".
  variable: "read",
  // The User Select *reads* its group filter and writes its selection
  // elsewhere, so this one prop is upstream while `variable` is downstream.
  groupsVariable: "read",
  objectSetVariable: "read",
  enabledVariable: "read",
  visibleWhen: "read",
  subjectVariable: "read",
  seriesVariable: "read",
  collapsedWhen: "read",
  tabVariable: "read",
  arrayVariable: "read",
  // p.461: the selector *reads* its options from this variable.
  optionsVariable: "read",
  // p.464: the picker *reads* its timezone from this variable.
  timezoneVariable: "read",
  // p.316's Markdown text read from a string variable.
  textVariable: "read",
};

/** The same judgement for `NESTED_REFERENCE_PROPS`, keyed by `prop.inner`.
 *
 * A second map rather than entries in the one above, because the keys are a
 * different shape: a nested reference arrives from `referencesOf` as
 * `steps[1].completedVariable`, so the index has to come off before a
 * direction can be looked up. Keyed by the outer prop *and* the inner one,
 * since two nested props on the same widget need not point the same way — a
 * step could gain a variable it writes without that making its completion
 * variable a write too.
 */
export const NESTED_PROP_DIRECTION: Record<string, "read" | "write"> = {
  // p.313: the Stepper *displays* progress the module records, so a step's
  // completion variable is upstream of the widget. §219's whole design is that
  // completion is read and never stored, and an arrow pointing the other way
  // would say the opposite in the one view built to be trusted while debugging.
  "steps.completedVariable": "read",
  // p.348: a layer *displays* the set it names, so the set is upstream of the
  // widget - the same direction as every other `objectSetVariable`, which is
  // why the flat catalogue calls that one a read too.
  "layers.objectSetVariable": "read",
};

/** The direction of a reference `referencesOf` reported, nested or not. */
export function directionOf(prop: string): "read" | "write" | undefined {
  if (prop in PROP_DIRECTION) return PROP_DIRECTION[prop as keyof typeof PROP_DIRECTION];
  const nested = prop.match(/^([A-Za-z_]+)\[\d+\]\.([A-Za-z_]+)$/);
  return nested ? NESTED_PROP_DIRECTION[`${nested[1]}.${nested[2]}`] : undefined;
}

export interface LineageNode {
  id: string;
  kind: "variable" | "widget";
  label: string;
}

export interface LineageEdge {
  /** Upstream: the thing depended on. */
  from: string;
  /** Downstream: the thing that depends on it. */
  to: string;
  /** Why the edge exists, for a tooltip and for reading a test failure. */
  via: string;
}

export interface Lineage {
  nodes: Map<string, LineageNode>;
  edges: LineageEdge[];
}

interface LayoutNode {
  type?: { resolvedName?: string } | string;
  props?: Record<string, unknown>;
  custom?: Record<string, unknown>;
}

function resolvedName(node: LayoutNode | undefined): string {
  const t = node?.type;
  return typeof t === "string" ? t : (t?.resolvedName ?? "");
}

/** A widget's name in the graph: what the Layout panel calls it, so a node and
 * a tree row are recognisably the same thing. */
function widgetLabel(id: string, node: LayoutNode): string {
  const renamed = (node.custom as { displayName?: string } | undefined)?.displayName;
  if (renamed) return renamed;
  const props = node.props ?? {};
  for (const key of ["title", "label", "text", "name"]) {
    const value = props[key];
    if (typeof value === "string" && value.trim()) return value.trim().slice(0, 28);
  }
  return resolvedName(node) || id;
}

/** The whole dependency graph of a module.
 *
 * Nodes are every declared variable and every layout node that references one.
 * A widget referencing nothing is left out: p.77 describes a graph of things
 * that "depend on one another", and a module's fortieth Text widget is noise in
 * a view whose whole purpose is finding a relationship.
 */
export function buildGraph(
  variables: Record<string, WorkshopVariable>,
  layout: Record<string, unknown>,
): Lineage {
  const nodes = new Map<string, LineageNode>();
  const edges: LineageEdge[] = [];

  for (const variable of Object.values(variables)) {
    nodes.set(variable.id, { id: variable.id, kind: "variable", label: variable.label });
  }

  // variable → variable, from derivation inputs. The input is upstream.
  for (const variable of Object.values(variables)) {
    for (const input of variable.derivation?.inputs ?? []) {
      if (nodes.has(input)) {
        edges.push({ from: input, to: variable.id, via: "derivation" });
      }
    }
  }

  for (const [nodeId, raw] of Object.entries(layout)) {
    if (nodeId === "ROOT" || !raw || typeof raw !== "object") continue;
    const node = raw as LayoutNode;
    let referenced = false;
    for (const { prop, ref } of referencesOf(node.props)) {
      if (!variables[ref]) continue;
      // **A reference with no direction draws no edge**, rather than an edge
      // this code guessed the direction of. `PROP_DIRECTION` is keyed by
      // `REFERENCE_PROPS` itself, so a flat prop cannot get here unclassified —
      // the compiler refuses it. A *nested* one can, since its map is keyed by
      // strings, and the tests beside this module are what hold that: a `??
      // "read"` here would point an arrow backwards, which p.77 says is worse
      // than not drawing it.
      const direction = directionOf(prop);
      if (!direction) continue;
      referenced = true;
      edges.push(
        direction === "write"
          ? { from: nodeId, to: ref, via: prop }
          : { from: ref, to: nodeId, via: prop },
      );
    }
    if (referenced) {
      nodes.set(nodeId, { id: nodeId, kind: "widget", label: widgetLabel(nodeId, node) });
    }
  }

  return { nodes, edges };
}

/** p.78's "parents (upstream dependencies)". */
export function parentsOf(graph: Lineage, id: string): string[] {
  return unique(graph.edges.filter((e) => e.to === id).map((e) => e.from));
}

/** p.78's "children (downstream consumers)". */
export function childrenOf(graph: Lineage, id: string): string[] {
  return unique(graph.edges.filter((e) => e.from === id).map((e) => e.to));
}

function unique(ids: string[]): string[] {
  return [...new Set(ids)];
}

/** Whether a node has anything to expand in a direction — p.78's "Nodes with
 * dependencies have chevron arrows on their top and bottom edges", which means
 * a node with none must draw no chevron rather than one that does nothing. */
export function hasMore(graph: Lineage, shown: ReadonlySet<string>, id: string,
                        direction: "parents" | "children"): boolean {
  const neighbours = direction === "parents" ? parentsOf(graph, id) : childrenOf(graph, id);
  return neighbours.some((n) => !shown.has(n));
}

/** p.78's chevron: add one node's parents or children to what is shown.
 *
 * Returns the same set when nothing is added, so a click on a chevron that has
 * nothing left to reveal costs no history entry — undo would otherwise step
 * through actions that changed nothing.
 */
export function expand(
  graph: Lineage,
  shown: ReadonlySet<string>,
  id: string,
  direction: "parents" | "children",
): ReadonlySet<string> {
  const neighbours = direction === "parents" ? parentsOf(graph, id) : childrenOf(graph, id);
  const missing = neighbours.filter((n) => !shown.has(n));
  if (missing.length === 0) return shown;
  return new Set([...shown, ...missing]);
}

/** p.78's collapse: drop a node's neighbours in one direction, but **only the
 * ones nothing else is holding on screen**.
 *
 * Without that rule, collapsing one node's parents would take away a node that
 * a *different* visible node also depends on — and the graph would lose an edge
 * the author is looking at, in a view whose purpose is tracing edges.
 */
export function collapse(
  graph: Lineage,
  shown: ReadonlySet<string>,
  id: string,
  direction: "parents" | "children",
): ReadonlySet<string> {
  const neighbours = direction === "parents" ? parentsOf(graph, id) : childrenOf(graph, id);
  const others = [...shown].filter((s) => s !== id);
  const drop = neighbours.filter((n) => {
    if (!shown.has(n) || n === id) return false;
    // Held by another visible node in either direction.
    return !others.some((other) =>
      other !== n
      && (parentsOf(graph, other).includes(n) || childrenOf(graph, other).includes(n)));
  });
  if (drop.length === 0) return shown;
  const next = new Set(shown);
  for (const n of drop) next.delete(n);
  return next;
}

/** p.78's "Show all action… to expand to the full application graph". */
export function showAll(graph: Lineage): ReadonlySet<string> {
  return new Set(graph.nodes.keys());
}

/** p.78's "Clear to remove all nodes". */
export function clear(): ReadonlySet<string> {
  return new Set();
}

/** p.78's undo/redo, "step backward and forward through expand, collapse, and
 * selection actions".
 *
 * A history of whole states rather than of operations: the states are sets of a
 * few dozen ids, and inverting `collapse` would need to know which nodes it
 * dropped *and why* — which is the sort of bookkeeping that goes wrong quietly.
 */
export interface History {
  past: { shown: ReadonlySet<string>; selected: string | null }[];
  present: { shown: ReadonlySet<string>; selected: string | null };
  future: { shown: ReadonlySet<string>; selected: string | null }[];
}

export function initial(shown: ReadonlySet<string> = new Set()): History {
  return { past: [], present: { shown, selected: null }, future: [] };
}

/** Record a new state. A step that changes nothing is dropped rather than
 * pushed, so undo never appears to do nothing — p.78 ties undo to *actions*,
 * and an action that changed no state is not one. */
export function step(
  history: History,
  next: { shown?: ReadonlySet<string>; selected?: string | null },
): History {
  const shown = next.shown ?? history.present.shown;
  const selected = next.selected === undefined ? history.present.selected : next.selected;
  if (shown === history.present.shown && selected === history.present.selected) {
    return history;
  }
  return {
    past: [...history.past, history.present],
    present: { shown, selected },
    future: [],
  };
}

export function undo(history: History): History {
  const previous = history.past[history.past.length - 1];
  if (!previous) return history;
  return {
    past: history.past.slice(0, -1),
    present: previous,
    future: [history.present, ...history.future],
  };
}

export function redo(history: History): History {
  const next = history.future[0];
  if (!next) return history;
  return {
    past: [...history.past, history.present],
    present: next,
    future: history.future.slice(1),
  };
}

/** How far downstream each shown node sits, for laying the graph out left to
 * right. Upstream nodes get lower numbers.
 *
 * Computed over the **shown** subgraph rather than the whole one, because the
 * graph is expanded a node at a time and a layer that jumped when an unrelated
 * branch opened would move everything the author was reading.
 *
 * Cycle-safe: the server refuses a cyclic *derivation*, but a widget can read
 * one variable and write another that feeds back, and a view for debugging is
 * the worst place to hang.
 */
export function layers(graph: Lineage, shown: ReadonlySet<string>): Map<string, number> {
  const out = new Map<string, number>();
  const ids = [...shown].filter((id) => graph.nodes.has(id));
  const inside = new Set(ids);
  const depth = (id: string, seen: Set<string>): number => {
    if (out.has(id)) return out.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const ups = parentsOf(graph, id).filter((p) => inside.has(p));
    const value = ups.length === 0 ? 0 : Math.max(...ups.map((p) => depth(p, seen))) + 1;
    seen.delete(id);
    out.set(id, value);
    return value;
  };
  for (const id of ids) depth(id, new Set());
  return out;
}
