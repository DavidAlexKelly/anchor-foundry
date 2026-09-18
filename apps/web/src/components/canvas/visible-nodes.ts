/** Which layout nodes are on screen right now (§392; `workshop` p.75).
 *
 * > "In both view and edit mode, Workshop variables will compute and recompute
 * > lazily only when displayed by a visible widget or layout. This means that
 * > variables used in non-visible pages, tabs, overlays, or non-visible pages
 * > of a looped layout will not be computed until they are shown. This
 * > behavior is the same for non-visible variables used in embedded modules."
 * > (p.75)
 *
 * **The server owns which variables that implies, and this owns which nodes
 * they are.** Only the browser knows what is on screen; only the graph knows
 * that a chart needs its set and the set needs its filter. So this answers the
 * first question and `workshop_variables.displayed` answers the second, and
 * neither is tempted to guess at the other's.
 *
 * **What counts as on screen is the tree, walked.** A page that is not the
 * current page is not on screen, nor is a tab panel that is not showing, nor
 * an overlay that is not open. Everything else under the current page is, and
 * that includes things the reader cannot see for other reasons: a collapsed
 * section keeps its children mounted (`hidden`, not unmounted — a table inside
 * one must not refetch every time somebody opens it), and p.75 does not list
 * collapse. Inventing a rule the source does not state would be a divergence
 * dressed as an optimisation.
 *
 * **The header is always on screen**, because it is the toolbar above every
 * page rather than something on one, which is what makes a module have at most
 * one of them — so it is reached by the walk from ROOT rather than named
 * specially. The Unused holding node is under ROOT too and is skipped, for the
 * reason written at the line that skips it.
 *
 * **A tab backed by a variable settles in one round trip, not never.** Which
 * tab shows can depend on a variable (p.84), and which variables are computed
 * depends on which tab shows — which reads like a circle and is not one. The
 * *section* is on the current page, so its `tabVariable` is referenced by a
 * visible node and is therefore computed; the first resolve returns it, and
 * the second knows the right tab. That is the same one-frame settle the
 * backing variable for page selection already has, and for the same reason.
 */
import type { LayoutNodes } from "../../lib/workshop-module";
import { activeTab, tabLabels, type TabOverride } from "./tab-selection";
import { UNUSED_NAME } from "./unused";

/** The node kinds that are only on screen when they are the chosen one. */
const PAGE = "CanvasPage";
const OVERLAY = "CanvasOverlay";

function nameOf(node: unknown): string | null {
  const resolved = (node as { type?: { resolvedName?: unknown } } | undefined)?.type
    ?.resolvedName;
  return typeof resolved === "string" ? resolved : null;
}

function childrenOf(node: unknown): string[] {
  const n = node as { nodes?: unknown; linkedNodes?: Record<string, unknown> } | undefined;
  const direct = Array.isArray(n?.nodes) ? n!.nodes : [];
  const linked = Object.values(n?.linkedNodes ?? {});
  return [...direct, ...linked].filter((c): c is string => typeof c === "string");
}

export interface VisibleInput {
  /** The node id of the page being shown, or null when there is none. */
  page: string | null;
  /** The open overlay's node id, when one is open (p.75's "overlays"). */
  overlay?: string | null;
  /** p.54's tab overrides, by section node id — what the last click said. */
  tabs?: Record<string, TabOverride>;
  /**
   * Resolved variable values, for p.84's Variable-Based Tab Selection.
   *
   * **Which tab shows can depend on a variable, and which variables are
   * computed depends on which tab shows.** That reads like a circle and is
   * not one: the *section* is on the current page, so its `tabVariable` is
   * referenced by a visible node and is computed on the first resolve; the
   * second knows the right tab. Until then `activeTab` falls back to the
   * first tab, which is what the renderer does too.
   */
  values?: Record<string, unknown>;
}

/**
 * Every node id currently on screen.
 *
 * The root is included when it exists, because a module's own props are as
 * much on screen as a widget's, and walking from the page alone would miss a
 * variable bound at the top of the document.
 *
 * A cycle cannot occur in a well-formed Craft.js tree, and this walks a
 * document that arrived from anywhere — so `seen` is a guard against hanging
 * the viewer, which is a worse answer than a partial one. `routing.ts` makes
 * the same note about the same hazard.
 */
export function visibleNodes(layout: unknown, input: VisibleInput): Set<string> {
  const found = new Set<string>();
  if (!layout || typeof layout !== "object") return found;
  const nodes = layout as LayoutNodes;

  const walk = (nodeId: string) => {
    if (found.has(nodeId)) return;
    const node = nodes[nodeId];
    if (!node) return;
    found.add(nodeId);

    const children = childrenOf(node);

    // A tabbed section shows one part. The labels are positional — part `i` is
    // `labels[i]` — and `tabLabels` plus `activeTab` are the *same* two
    // functions the renderer calls, rather than a second rule that agrees
    // until somebody renames a tab (§292).
    const props = (node as { props?: Record<string, unknown> }).props ?? {};
    const labels = props.direction === "tabs"
      ? tabLabels(props.tabs as string | null | undefined, children.length)
      : [];
    const backing = typeof props.tabVariable === "string" && props.tabVariable
      ? input.values?.[props.tabVariable]
      : undefined;
    const showing = labels.length > 0
      ? activeTab(input.tabs?.[nodeId], backing, labels)
      : null;
    if (showing !== null) {
      const at = labels.indexOf(showing);
      const only = at >= 0 ? children[at] : undefined;
      if (only !== undefined) walk(only);
      return;
    }

    for (const child of children) {
      const childKind = nameOf(nodes[child]);
      // A page or an overlay is reached because it was *chosen*, never by
      // falling into it from its parent. Walking into every page from ROOT is
      // exactly the bug this module exists to remove.
      if (childKind === PAGE || childKind === OVERLAY) continue;
      // **The Unused area is under ROOT and renders nothing** (decision 0010).
      // Falling into it would put every parked widget on screen for this
      // purpose, which is the mirror of the mistake `workshop_variables.
      // displayed` refuses on the server: a parked widget counts as a *usage*
      // so its variable cannot be deleted, and counts as visible never.
      if (childKind === UNUSED_NAME) continue;
      walk(child);
    }
  };

  // ROOT's own props, and the header under it — the toolbar above every page,
  // which is why it is not on one.
  if (nodes.ROOT) walk("ROOT");
  if (input.page) walk(input.page);
  if (input.overlay) walk(input.overlay);
  return found;
}
