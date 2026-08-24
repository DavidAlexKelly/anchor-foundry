/** p.68's *Unused widgets* area: a widget that is in the module but on no page.
 *
 * > "After configuring a widget, you can copy it to reuse anywhere in the
 * > module… Use `Cmd+V` (macOS) or `Ctrl+V` (Windows) to paste the widget into
 * > the Unused widgets area located at the bottom of the Layouts section in the
 * > left side panel. Add the widget to your module by choosing + Add widget,
 * > then find it in the Unused widgets tab of the widget selector modal."
 * > (p.68)
 *
 * Every other node in this document is reachable from `ROOT` by walking
 * children, and the viewer renders exactly that walk — so "in the module but
 * not in the tree" is a state the format has never had to express.
 *
 * **Parked widgets live in the node map, under a holding node.** The full
 * argument is `docs/decisions/0010-unused-widgets.md`; the short version is one
 * function. `workshop_variables.usages()` decides whether a variable may be
 * deleted, and it iterates the node map rather than walking the tree — so a
 * parked widget kept in the map counts as a usage for free, and one kept in a
 * sibling key does not. Under the sibling-key design, parking a Filter List
 * makes its variable report as unused, an author deletes it, and the widget
 * comes back bound to nothing. No error at any step.
 *
 * The holding node renders **nothing**, in both modes. That is the property
 * this design is most likely to lose later — a `CanvasUnused` that started
 * drawing its children would put parked widgets on the page for every reader —
 * so there is a browser test that opens a module with one parked as a reader
 * and asserts it is not there.
 *
 * This module is the bookkeeping: finding the holding node, listing what is in
 * it, and moving a subtree between it and the tree. It mints no ids and makes
 * no copies — placing a parked widget **moves** it, so its variable bindings
 * and the events triggered from it come along untouched, which is the whole
 * point of having parked it rather than copied it.
 */
import type { LayoutNodes } from "../../lib/workshop-module";

/** The resolved name of the holding node. One constant, because the panel, the
 * transform and the widget registry must agree and a second spelling would be
 * a parked widget nobody can find. */
export const UNUSED_NAME = "CanvasUnused";

interface LayoutNode {
  type?: { resolvedName?: string } | string;
  isCanvas?: boolean;
  props?: Record<string, unknown>;
  parent?: string | null;
  nodes?: string[];
  linkedNodes?: Record<string, string>;
  custom?: Record<string, unknown>;
}

function nodeAt(layout: LayoutNodes, id: string): LayoutNode | null {
  const node = layout[id];
  return node && typeof node === "object" ? (node as LayoutNode) : null;
}

function resolvedName(node: LayoutNode | null): string {
  if (!node) return "";
  const t = node.type;
  return typeof t === "string" ? t : (t?.resolvedName ?? "");
}

function childIds(node: LayoutNode | null): string[] {
  if (!node) return [];
  const direct = Array.isArray(node.nodes) ? node.nodes : [];
  const linked = node.linkedNodes ? Object.values(node.linkedNodes) : [];
  return [...direct, ...linked].filter((id): id is string => typeof id === "string");
}

/** The holding node's id, or null when the document has never parked anything.
 *
 * Null rather than a created-on-demand node: a document that has never used
 * this feature should not grow a node because something asked a question about
 * it, and every caller here has a sensible answer for "there isn't one".
 */
export function unusedNode(layout: LayoutNodes): string | null {
  const root = nodeAt(layout, "ROOT");
  for (const id of childIds(root)) {
    if (resolvedName(nodeAt(layout, id)) === UNUSED_NAME) return id;
  }
  return null;
}

/** The parked widgets, in the order they were parked. */
export function unusedIds(layout: LayoutNodes): string[] {
  const holder = unusedNode(layout);
  return holder ? childIds(nodeAt(layout, holder)) : [];
}

/** Whether this node is the holding node or sits inside it.
 *
 * Used by the Layout panel to keep parked widgets out of the main tree — they
 * are listed separately, and a widget appearing in both places would read as
 * two widgets.
 *
 * Walks up rather than checking the immediate parent: a parked *section* has
 * children of its own, and every one of them is equally not-on-a-page.
 */
export function isParked(layout: LayoutNodes, id: string): boolean {
  const seen = new Set<string>();
  let cursor: string | null = id;
  while (cursor && !seen.has(cursor)) {
    seen.add(cursor);
    if (resolvedName(nodeAt(layout, cursor)) === UNUSED_NAME) return true;
    cursor = nodeAt(layout, cursor)?.parent ?? null;
  }
  return false;
}

/** Move a subtree to a new parent, appending it to that parent's children.
 *
 * The one primitive both directions need: parking is a move into the holding
 * node, placing is a move out of it. **A move, never a copy** — ids are
 * preserved, so the variables the widget reads and the events triggered from it
 * keep pointing at it, which is what separates this from a paste.
 *
 * Returns the layout unchanged when the move cannot be made, rather than
 * throwing or half-applying: an author who selected something odd and pressed a
 * button gets nothing, which is recoverable, instead of a document with a node
 * listed under two parents.
 */
export function move(layout: LayoutNodes, id: string, into: string): LayoutNodes {
  const node = nodeAt(layout, id);
  const parent = nodeAt(layout, into);
  if (!node || !parent || id === into || id === "ROOT") return layout;
  // Moving a node into its own subtree would detach both from the document.
  if (isDescendant(layout, into, id)) return layout;
  if (childIds(parent).includes(id)) return layout;

  const out: LayoutNodes = {};
  for (const [nodeId, current] of Object.entries(layout)) {
    const asNode = current as LayoutNode;
    if (nodeId === id) {
      out[nodeId] = { ...asNode, parent: into } as LayoutNodes[string];
      continue;
    }
    if (nodeId === into) continue; // written below, after the old parent is trimmed
    const kids = Array.isArray(asNode.nodes) ? asNode.nodes : null;
    out[nodeId] = (kids && kids.includes(id)
      ? { ...asNode, nodes: kids.filter((child) => child !== id) }
      : asNode) as LayoutNodes[string];
  }
  const trimmed = (Array.isArray(parent.nodes) ? parent.nodes : []).filter((c) => c !== id);
  out[into] = { ...parent, nodes: [...trimmed, id] } as LayoutNodes[string];
  return out;
}

function isDescendant(layout: LayoutNodes, id: string, of: string): boolean {
  const seen = new Set<string>();
  let cursor: string | null = id;
  while (cursor && !seen.has(cursor)) {
    if (cursor === of) return true;
    seen.add(cursor);
    cursor = nodeAt(layout, cursor)?.parent ?? null;
  }
  return false;
}

/** Add a holding node to a document that has none, so something can be parked.
 *
 * Separate from `move` because it is the only part of this that *adds* to the
 * document, and a caller that has one already must not get a second — two
 * holding nodes would split the list in half and hide whichever the panel did
 * not read.
 */
export function ensureUnusedNode(
  layout: LayoutNodes,
  mintId: () => string,
): { layout: LayoutNodes; id: string } | null {
  const existing = unusedNode(layout);
  if (existing) return { layout, id: existing };
  const root = nodeAt(layout, "ROOT");
  if (!root) return null;
  const id = mintId();
  return {
    id,
    layout: {
      ...layout,
      [id]: {
        type: { resolvedName: UNUSED_NAME },
        isCanvas: true,
        props: {},
        parent: "ROOT",
        nodes: [],
        linkedNodes: {},
      } as LayoutNodes[string],
      ROOT: {
        ...root,
        nodes: [...(Array.isArray(root.nodes) ? root.nodes : []), id],
      } as LayoutNodes[string],
    },
  };
}

/** p.68's paste target: park the selected subtree.
 *
 * Creates the holding node on the way if the document has none, which is what
 * makes this one action from the author's side rather than two.
 */
export function park(
  layout: LayoutNodes,
  id: string,
  mintId: () => string,
): LayoutNodes {
  if (!nodeAt(layout, id) || id === "ROOT" || !canPark(layout, id)) return layout;
  const ensured = ensureUnusedNode(layout, mintId);
  if (!ensured) return layout;
  return move(ensured.layout, id, ensured.id);
}

/** What may be parked. p.68 is about *widgets*, and the two exclusions are the
 * nodes for which parking would mean something other than what it looks like.
 *
 * A **page** is not a widget: parking one takes its entire contents off the
 * module in a click, and a page in the holding area has nowhere to be placed
 * back to except `ROOT`, which is a different operation wearing the same
 * button. An **overlay** is a page by another name and goes with it.
 *
 * The **holding node itself** cannot be parked inside itself; that is a
 * degenerate case rather than a policy, but it reaches the same guard.
 *
 * Exported so the panel can disable the control rather than offering one that
 * silently does nothing — §193's rule: a choice that fails is worse than a
 * choice that is not offered.
 */
export function canPark(layout: LayoutNodes, id: string): boolean {
  const name = resolvedName(nodeAt(layout, id));
  return name !== "" && name !== UNUSED_NAME
    && name !== "CanvasPage" && name !== "CanvasOverlay";
}
