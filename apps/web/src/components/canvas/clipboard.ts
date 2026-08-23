/** Cut, copy and paste for sections and widgets (Foundry `workshop` p.55,
 * p.68-69).
 *
 * > "Cut, copy, and paste options are available for whole sections and
 * > individual widgets within a module, providing tools for a faster module
 * > building experience.
 * >
 * > When pasting sections or widgets, builders have two options for managing
 * > the new section's or widget's input variables:
 * >
 * > **Paste with same input variable**: Paste a new section or widget that
 * > reuses the copied section's or widget's input variables.
 * >
 * > **Paste with duplicate input variables**: Pastes a new section or widget
 * > that uses newly created input variables that match the copied section's or
 * > widget's input variables." (p.55)
 *
 * The two modes are the whole design question. Everything else here is
 * bookkeeping: a subtree walk, fresh ids, and rewriting the references that
 * point inside what moved.
 *
 * **Why a pure module over the serialised layout.** Craft.js has a node-tree
 * API, but the layout *is* the serialised map (decision 0002) and the builder
 * already deserialises one on load. Transforming the map and handing it back
 * to `actions.deserialize` is one code path instead of two, and the whole of
 * it is testable without a browser - which matters more here than usual,
 * because "paste rewrote the wrong reference" is invisible until somebody
 * edits the copy and watches the original change.
 *
 * ---
 *
 * **What travels, and what does not.**
 *
 * *Nodes*: the selected node and every descendant, through both `nodes` and
 * `linkedNodes` - a Page's children hang off the latter, so a walk that missed
 * them would paste an empty page and lose the contents silently.
 *
 * *Variables*: the definitions of every variable the subtree references
 * through `REFERENCE_PROPS`. In `same` mode they are carried only so a paste
 * into a module that has since lost one can still be refused sensibly; in
 * `duplicate` mode they are the source for the new ones.
 *
 * *Events*: every event **triggered from a node inside the subtree**. p.55
 * does not mention events, and it would have been defensible to leave them
 * behind - but a copied Button that has lost its on-click is a copy that
 * silently does less than the thing it copied, which is the failure mode this
 * repo spends most of its time removing. Effects that name a node *inside* the
 * subtree are remapped; effects naming a node outside it are left pointing
 * where they pointed, because that node is still there.
 *
 * *Not carried*: a variable's **derivation inputs**. If a duplicated variable
 * is derived from two others, the duplicate keeps the same derivation and so
 * reads the same upstream values. p.55 says "input variables", which are the
 * widget's own inputs, not the whole graph behind them - and duplicating the
 * graph would clone the object set a filter narrows, which is precisely the
 * thing an author duplicating a filter wants to keep shared. Stated because it
 * is a judgement call: the other reading is defensible and produces a very
 * different feature.
 */
import { REFERENCE_PROPS } from "../../lib/workshop-module";
import type { LayoutNodes } from "../../lib/workshop-module";
import type { WorkshopEvent, WorkshopVariable } from "../../lib/types";

/** One serialised Craft node, in the shape the layout stores. */
interface LayoutNode {
  type?: { resolvedName?: string } | string;
  isCanvas?: boolean;
  props?: Record<string, unknown>;
  parent?: string | null;
  nodes?: string[];
  linkedNodes?: Record<string, string>;
  custom?: Record<string, unknown>;
}

export type PasteMode = "same" | "duplicate";

/** What a copy or a cut put on the clipboard. */
export interface Clipping {
  /** The node that was selected. Its `parent` is deliberately *not* recorded:
   * a clipping is pasted wherever the author is now, not back where it came
   * from. */
  root: string;
  /** The subtree, keyed by the ids it had in the document it came from. Those
   * ids never reach a document again - `paste` mints fresh ones - but keeping
   * them makes a clipping readable in a debugger and makes the remap testable
   * against known names. */
  nodes: LayoutNodes;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  /** What the author is holding, for a panel to say so. A clipboard with no
   * label is a Paste button that gives no clue what it will paste. */
  label: string;
}

function nodeAt(layout: LayoutNodes, id: string): LayoutNode | null {
  const node = layout[id];
  return node && typeof node === "object" ? (node as LayoutNode) : null;
}

function childrenOf(node: LayoutNode): string[] {
  const direct = Array.isArray(node.nodes) ? node.nodes : [];
  const linked = node.linkedNodes ? Object.values(node.linkedNodes) : [];
  return [...direct, ...linked].filter((id): id is string => typeof id === "string");
}

/** Every node id in the subtree rooted at `nodeId`, in **document order**:
 * the root, then each child depth-first in the order the parent lists them.
 *
 * The order is part of the contract rather than an accident of the walk,
 * because `paste` mints one id per entry in this sequence. Document order
 * makes the result predictable - the first child of the copy gets the first
 * new id - which is what makes a pasted subtree legible in a diff and a
 * remap testable against named ids rather than against a regex.
 *
 * **Cycle-safe.** A layout is a tree and should not contain a cycle, but this
 * walks a document that can arrive from anywhere - a raw-JSON edit, an older
 * writer - and a `visited` set is cheaper than the hang it prevents.
 */
export function subtreeIds(layout: LayoutNodes, nodeId: string): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const walk = (id: string) => {
    if (seen.has(id)) return;
    const node = nodeAt(layout, id);
    if (!node) return;
    seen.add(id);
    out.push(id);
    for (const child of childrenOf(node)) walk(child);
  };
  walk(nodeId);
  return out;
}

/** The variable ids a set of nodes references. */
export function referencedVariables(nodes: LayoutNodes): string[] {
  const found = new Set<string>();
  for (const node of Object.values(nodes)) {
    const props = (node as LayoutNode)?.props;
    if (!props) continue;
    for (const prop of REFERENCE_PROPS) {
      const value = props[prop];
      if (typeof value === "string" && value) found.add(value);
    }
  }
  return [...found].sort();
}

/** The events a set of nodes is the trigger for. */
function eventsTriggeredBy(
  events: Record<string, WorkshopEvent>,
  ids: ReadonlySet<string>,
): Record<string, WorkshopEvent> {
  const out: Record<string, WorkshopEvent> = {};
  for (const [eid, event] of Object.entries(events)) {
    if (event?.trigger?.node && ids.has(event.trigger.node)) out[eid] = event;
  }
  return out;
}

/** Copy `nodeId` and everything under it.
 *
 * Returns null for a node that is not there, and for ROOT: copying the whole
 * document is not a paste anybody can complete, since the only place it could
 * go is inside itself.
 */
export function clip(
  layout: LayoutNodes,
  variables: Record<string, WorkshopVariable>,
  events: Record<string, WorkshopEvent>,
  nodeId: string,
  label: string,
): Clipping | null {
  if (!nodeId || nodeId === "ROOT" || !nodeAt(layout, nodeId)) return null;
  const ids = subtreeIds(layout, nodeId);
  const nodes: LayoutNodes = {};
  for (const id of ids) nodes[id] = layout[id];
  const referenced = referencedVariables(nodes);
  const carried: Record<string, WorkshopVariable> = {};
  for (const vid of referenced) if (variables[vid]) carried[vid] = variables[vid];
  return {
    root: nodeId,
    nodes,
    variables: carried,
    events: eventsTriggeredBy(events, new Set(ids)),
    label,
  };
}

/** The layout with `nodeId` and its descendants removed, and the parent's
 * child list closed up behind it. The delete half of a cut. */
export function withoutSubtree(layout: LayoutNodes, nodeId: string): LayoutNodes {
  if (!nodeAt(layout, nodeId) || nodeId === "ROOT") return layout;
  const gone = new Set(subtreeIds(layout, nodeId));
  const out: LayoutNodes = {};
  for (const [id, raw] of Object.entries(layout)) {
    if (gone.has(id)) continue;
    const node = raw as LayoutNode;
    const nodes = Array.isArray(node.nodes)
      ? node.nodes.filter((child) => !gone.has(child))
      : node.nodes;
    const linkedNodes = node.linkedNodes
      ? Object.fromEntries(
        Object.entries(node.linkedNodes).filter(([, child]) => !gone.has(child)),
      )
      : node.linkedNodes;
    out[id] = { ...node, ...(nodes ? { nodes } : {}), ...(linkedNodes ? { linkedNodes } : {}) };
  }
  return out;
}

/** Where a clipping can actually land.
 *
 * A widget cannot hold children, so pasting "into" one means pasting beside
 * it. Walking up to the nearest canvas is what makes the Paste button work
 * wherever the author happens to be selected, instead of being disabled most
 * of the time with no explanation.
 */
export function pasteTarget(layout: LayoutNodes, selected: string | null): string | null {
  let id = selected;
  const seen = new Set<string>();
  while (id && !seen.has(id)) {
    seen.add(id);
    const node = nodeAt(layout, id);
    if (!node) break;
    if (node.isCanvas) return id;
    id = node.parent ?? null;
  }
  // Nothing selected, or nothing on the way up can hold a child: the document
  // itself can, and always could.
  return layout.ROOT ? "ROOT" : null;
}

export interface PasteResult {
  layout: LayoutNodes;
  variables: Record<string, WorkshopVariable>;
  events: Record<string, WorkshopEvent>;
  /** The new id of the pasted root, so the caller can select it - a paste you
   * cannot see the result of is a paste that looks like it failed. */
  root: string;
}

/** Paste a clipping into `into`, in one of p.55's two modes. */
export function paste(
  layout: LayoutNodes,
  variables: Record<string, WorkshopVariable>,
  events: Record<string, WorkshopEvent>,
  clipping: Clipping,
  options: {
    into: string;
    mode: PasteMode;
    /** Injected so a test can assert on the result rather than on a regex over
     * random ids. The builder passes the same generators it uses everywhere
     * else. */
    mintNode: () => string;
    mintVariable: () => string;
    mintEvent: () => string;
  },
): PasteResult {
  const { into, mode, mintNode, mintVariable, mintEvent } = options;
  const parent = nodeAt(layout, into);
  if (!parent) return { layout, variables, events, root: clipping.root };

  const nodeIdFor = new Map<string, string>();
  for (const id of Object.keys(clipping.nodes)) nodeIdFor.set(id, mintNode());

  // p.55's second mode, and the only part of this that is a decision rather
  // than bookkeeping. In `same` mode nothing is minted and the pasted props
  // keep pointing at the variables the original used.
  const variableIdFor = new Map<string, string>();
  const newVariables: Record<string, WorkshopVariable> = {};
  if (mode === "duplicate") {
    for (const [vid, definition] of Object.entries(clipping.variables)) {
      const fresh = mintVariable();
      variableIdFor.set(vid, fresh);
      newVariables[fresh] = {
        ...definition,
        id: fresh,
        // A copy of a variable called "Region" is "Region copy", not a second
        // "Region": two identical names in the Variables panel is a list
        // nobody can use, and the panel is where an author goes next to point
        // the duplicate somewhere new.
        label: `${definition.label} copy`,
        // **The external ID is dropped, not copied.** It is what a URL and an
        // embedding module address, and the server refuses two variables that
        // share one - so carrying it across would make the paste unsaveable.
        ...(definition.external_id ? { external_id: undefined } : {}),
      };
    }
  }

  const remapProps = (props: Record<string, unknown> | undefined) => {
    if (!props) return props;
    const next = { ...props };
    for (const prop of REFERENCE_PROPS) {
      const value = next[prop];
      if (typeof value === "string" && variableIdFor.has(value)) {
        next[prop] = variableIdFor.get(value);
      }
    }
    return next;
  };

  const pasted: LayoutNodes = {};
  for (const [oldId, raw] of Object.entries(clipping.nodes)) {
    const node = raw as LayoutNode;
    const fresh = nodeIdFor.get(oldId) as string;
    pasted[fresh] = {
      ...node,
      props: remapProps(node.props),
      // The root's parent is where it was dropped; everything else keeps its
      // place within the subtree, under its own new id.
      parent: oldId === clipping.root ? into : nodeIdFor.get(node.parent ?? "") ?? into,
      ...(Array.isArray(node.nodes)
        ? { nodes: node.nodes.map((child) => nodeIdFor.get(child) ?? child) }
        : {}),
      ...(node.linkedNodes
        ? {
          linkedNodes: Object.fromEntries(
            Object.entries(node.linkedNodes).map(
              ([slot, child]) => [slot, nodeIdFor.get(child) ?? child],
            ),
          ),
        }
        : {}),
    };
  }

  const newRoot = nodeIdFor.get(clipping.root) as string;
  const nextLayout: LayoutNodes = {
    ...layout,
    ...pasted,
    [into]: {
      ...parent,
      nodes: [...(Array.isArray(parent.nodes) ? parent.nodes : []), newRoot],
    },
  };

  // Events last, because they name nodes and the map is only complete now.
  const nextEvents = { ...events };
  for (const event of Object.values(clipping.events)) {
    const eid = mintEvent();
    nextEvents[eid] = {
      ...event,
      id: eid,
      trigger: {
        ...event.trigger,
        node: nodeIdFor.get(event.trigger.node) ?? event.trigger.node,
      },
      effects: (event.effects ?? []).map((effect) => ({
        ...effect,
        config: remapEffectConfig(effect.config, nodeIdFor, variableIdFor),
      })),
    };
  }

  return {
    layout: nextLayout,
    variables: { ...variables, ...newVariables },
    events: nextEvents,
    root: newRoot,
  };
}

/** Config keys that name a layout node, and the one that names a variable.
 *
 * Listed rather than remapped by guessing at string shapes: a `value` of
 * `"sec"` is a string somebody typed, and rewriting it because a node happens
 * to share the name would corrupt the copy in a way nothing would report.
 */
const NODE_KEYS = ["page", "section", "overlay"] as const;
const VARIABLE_KEYS = ["variable"] as const;

function remapEffectConfig(
  config: Record<string, unknown> | undefined,
  nodeIdFor: Map<string, string>,
  variableIdFor: Map<string, string>,
): Record<string, unknown> {
  const next = { ...(config ?? {}) };
  for (const key of NODE_KEYS) {
    const value = next[key];
    // Only remapped when the target came *with* the clipping. An effect
    // pointing at a page outside the copied subtree still points at a page
    // that is there, and rewriting it would break a working link.
    if (typeof value === "string" && nodeIdFor.has(value)) next[key] = nodeIdFor.get(value);
  }
  for (const key of VARIABLE_KEYS) {
    const value = next[key];
    if (typeof value === "string" && variableIdFor.has(value)) {
      next[key] = variableIdFor.get(value);
    }
  }
  return next;
}
