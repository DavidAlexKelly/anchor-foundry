/** p.55's conditional-visibility indicators for the Layout panel.
 *
 * > "Sections can be configured with conditional visibility to show or hide
 * > based on variable values. The layout panel displays icons and tooltips to
 * > indicate which sections have conditional visibility enabled, making it
 * > easier to identify and manage conditionally visible sections even when they
 * > are currently hidden in the module view." (p.55)
 *
 * **The second half of that sentence is the requirement, not the decoration.**
 * The point is not that a marked row looks informative; it is that a section
 * whose condition is false right now can still be *found and edited*. So the
 * indicator has to be driven by the document — does this node carry a
 * condition — and never by the condition's current value, or it would go out
 * exactly when it is needed.
 *
 * That is also why this reads props rather than resolved values, and why there
 * is no "currently hidden" state here at all. The canvas already marks a
 * node whose condition is false with "hidden unless <label>" (`useVisibility`
 * in `widgets.tsx`), and that marker *is* value-driven because it is answering
 * a different question: what is happening now, rather than what is configured.
 *
 * ---
 *
 * **Two conditions, not one.** p.55 names visibility, but a section can also
 * carry p.82's collapse backing, and an author looking at a tree row wants the
 * same answer about both: is this row's state coming from a variable, and
 * which one. Reporting only `visibleWhen` would leave the other invisible for
 * no reason a reader of p.55 would expect.
 *
 * **The tooltip names the variable.** "Conditionally visible" alone would
 * satisfy the letter of p.55 and none of its purpose — "easier to identify and
 * manage" means knowing *which* variable to go and look at, and the label is
 * the only part of that an author can act on.
 */
import type { WorkshopVariable } from "../../lib/types";

/** A prop that makes a node's state a function of a variable, and the words
 * for what it does. Keyed by prop so the catalogue is checkable against
 * `REFERENCE_PROPS` rather than against a second copy of itself. */
export const CONDITION_PROPS = {
  visibleWhen: { icon: "◐", verb: "Visible when" },
  collapsedWhen: { icon: "▣", verb: "Collapsed when" },
} as const;

export type ConditionProp = keyof typeof CONDITION_PROPS;

export interface Condition {
  prop: ConditionProp;
  /** The variable id the prop names. */
  variable: string;
}

/** The conditions a node carries, in a fixed order.
 *
 * Fixed rather than however the props happen to be spelled out in the node,
 * because the marker is read left to right and a row whose icons reorder
 * between renders is a row nobody can scan.
 */
export function conditionsOf(props: Record<string, unknown> | undefined): Condition[] {
  if (!props) return [];
  const out: Condition[] = [];
  for (const prop of Object.keys(CONDITION_PROPS) as ConditionProp[]) {
    const value = props[prop];
    if (typeof value === "string" && value.trim()) {
      out.push({ prop, variable: value.trim() });
    }
  }
  return out;
}

export interface Marker {
  /** What the row shows. Empty when there is nothing to mark. */
  icon: string;
  /** The `title` attribute, and the accessible name of the indicator. */
  tooltip: string;
}

/** The icon and tooltip for a set of conditions, or `null` for none.
 *
 * Split from `conditionsOf` because the two halves are read at different
 * moments and from different sources. Which conditions a node carries is a
 * fact about the **document**, and the Layout panel reads it inside Craft's
 * node-map selector; what each condition's variable is *called* is a fact
 * about the **variable list**, which that selector does not re-run for. Doing
 * both in one pass left a tooltip that kept saying a variable's old name after
 * a rename, until something unrelated changed the tree.
 */
export function markerOf(
  conditions: readonly Condition[],
  declared: Record<string, WorkshopVariable>,
): Marker | null {
  if (conditions.length === 0) return null;
  return {
    icon: conditions.map(({ prop }) => CONDITION_PROPS[prop].icon).join(""),
    tooltip: conditions
      .map(({ prop, variable }) =>
        `${CONDITION_PROPS[prop].verb} ${declared[variable]?.label || variable}`)
      .join(" · "),
  };
}

/** The icon and tooltip for a node, or `null` when it carries no condition.
 *
 * `null` rather than an empty marker so a caller cannot accidentally render an
 * indicator with no text on every row in the tree — an icon that means nothing
 * on most rows is worse than no icon, because it stops meaning anything on the
 * rows it is for.
 *
 * A variable with no definition falls back to its **id**. That state is
 * reachable: the server refuses to delete a variable something references, but
 * a document can arrive from a raw-JSON edit or an older writer, and a marker
 * that said "Visible when undefined" would describe the tooling rather than
 * the problem.
 */
export function markerFor(
  props: Record<string, unknown> | undefined,
  declared: Record<string, WorkshopVariable>,
): Marker | null {
  return markerOf(conditionsOf(props), declared);
}
