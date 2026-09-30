/**
 * Editing an object from the Explorer's results (§324; `action-types` p.135-137).
 *
 *     "Inline edits are available in both Workshop and Object Explorer…
 *      Inline edits allow users to quickly edit values of an object in the
 *      **Object Explorer results view** or native Object View widgets." (p.135)
 *
 *     "For action-backed inline edits, every parameter is optional and defaults
 *      to the existing value of the object, so a user can make individual
 *      changes to properties one at a time." (p.135)
 *
 * **The second surface for one mechanism, not a second write path.** §238
 * decides on the server which action types may back a cell edit, §239 built the
 * staged-edit machinery for the Object Table, and the batch route enforces
 * p.138's all-or-nothing. Everything here is about what the Explorer may
 * *offer*, which is a different question from the Object Table's because the
 * Explorer searches across types.
 *
 * The staging itself is `components/canvas/inline-edit.ts` and is shared —
 * two copies of "what is staged and may it be submitted" is the thing this
 * repo has spent several units collapsing.
 */
import {
  UNKNOWN_ROW_LIMIT, rowLimitOf, type EditAction, type Staged,
} from "../components/canvas/inline-edit";
import { liveInlineParameter, type InlineAction } from "./property-inline-action";

/**
 * Why the Explorer is not offering to edit these results, if it is not.
 *
 * `null` means it is. Phrased as one sentence a reader can act on rather than a
 * boolean, because every one of these states looks identical on screen — a
 * table with no editors — and §214's rule is that a control which is absent
 * should say why rather than leave somebody hunting for it.
 *
 * **The cross-type case is the one p.135 does not have to mention.** Foundry's
 * Object Explorer opens one object type; this one searches the whole workspace
 * and a result set can hold three types at once. An inline edit needs *an*
 * action type, and an action type belongs to one object type — so a mixed
 * result set has no single action to offer, and offering a different picker per
 * row would be a table where each row means something different.
 */
export function editingUnavailable(
  onlyType: { display_name: string } | null | undefined,
  eligible: readonly EditAction[],
  canWrite: boolean,
  /** Where a write to this type would land. Several is an ambiguity the
   * Explorer refuses rather than resolves; none means nothing maps the type,
   * so there is nowhere for a write to go at all. */
  projects: readonly { name: string }[] = [],
): string | null {
  if (!onlyType) {
    return "Narrow the search to one object type to edit results here.";
  }
  if (!canWrite) {
    return "You can read these objects but not change them.";
  }
  if (eligible.length === 0) {
    // p.136: "Select a property and navigate to Inline edit in the sidebar"
    // (§600) - the configuration is per property, so that is where to send
    // somebody.
    return `No property of ${onlyType.display_name} has an inline action. ` +
      "Choose one for a property in the Ontology Manager.";
  }
  if (projects.length === 0) {
    return `${onlyType.display_name} has no dataset behind it, so there is nowhere to write.`;
  }
  if (projects.length > 1) {
    // **Named rather than counted.** "Editing is unavailable" sends somebody
    // looking for a permission problem; naming the two projects tells them the
    // type is mapped twice, which is a thing they can go and change (§214).
    //
    // **Sorted here rather than trusted from the server**, and the mutation
    // sweep is the reason. `editing_projects` has an `ORDER BY p.name`, and no
    // test could be made to fail without it: two rows come back in whatever
    // order the plan produces, which coincides with alphabetical about half
    // the time, so the check passed or failed by luck rather than by rule.
    // A probabilistically-flaky test is worse than none. The order somebody
    // *reads* is wording, wording belongs here, and here it can be pinned
    // exactly — which leaves the server's clause as the belt to this braces
    // rather than the only copy.
    const named = [...projects].map((p) => p.name).sort();
    return (
      `${onlyType.display_name} is mapped in ${projects.length} projects ` +
      `(${named.join(", ")}), so an edit here has no ` +
      "single place to go. Open the object to edit it."
    );
  }
  return null;
}

/**
 * Which of the table's columns take an editor, and through which action and
 * parameter (§600; `action-types` p.136).
 *
 *     "To set up an inline edit action, navigate to the Properties tab of
 *      your object type … Select a property and navigate to Inline edit …
 *      Each property can have only one inline edit action type. You can use
 *      the same action type as an inline edit for multiple properties, or you
 *      can have separate action types for different properties."
 *
 * **The property's own inline action** (§594), not the first eligible action
 * on the type with its parameters matched to columns by name, which is what
 * this was before p.136's binding existed. Re-read against the action as it
 * is now (`liveInlineParameter`), so an action that has stopped writing the
 * property, or stopped being eligible, draws no editor.
 */
export function inlineColumns(
  properties: readonly { api_name: string; inline_action_type_id?: string | null }[],
  actions: readonly InlineAction[] | undefined,
  columns: readonly string[],
): Record<string, InlineColumn> {
  const out: Record<string, InlineColumn> = {};
  for (const column of columns) {
    const chosen = properties.find((p) => p.api_name === column)?.inline_action_type_id;
    const action = chosen ? (actions ?? []).find((a) => a.id === chosen) : undefined;
    const parameter = liveInlineParameter(action, column);
    if (action && parameter) out[column] = { actionId: action.id, parameter };
  }
  return out;
}

export interface InlineColumn {
  actionId: string;
  parameter: string;
}

/** The actions the columns edit through, each once. */
export function backingActions<T extends { id: string }>(
  columns: Record<string, InlineColumn>, actions: readonly T[] | undefined,
): T[] {
  const ids = new Set(Object.values(columns).map((c) => c.actionId));
  return (actions ?? []).filter((a) => ids.has(a.id));
}

/** p.242's row cap for a submission several actions may share: the smallest
 * of theirs, since every row goes into each batch it touches. */
export function editLimitFor(actions: readonly EditAction[]): number {
  return actions.length === 0 ? UNKNOWN_ROW_LIMIT : Math.min(...actions.map(rowLimitOf));
}

/** What Save submits: one batch per action, each row's typed columns as that
 * action's parameters. Several properties on one action go in one batch, as
 * p.136's "use the same action type as an inline edit for multiple
 * properties" means them to. In a stated order, so the same edits are always
 * submitted the same way. */
export function batchesOf(
  staged: Staged, columns: Record<string, InlineColumn>,
): { actionId: string; edits: { instance_id: string; values: Record<string, unknown> }[] }[] {
  const byAction = new Map<string, Map<string, Record<string, unknown>>>();
  for (const instanceId of Object.keys(staged).sort()) {
    for (const [column, value] of Object.entries(staged[instanceId] ?? {})) {
      const target = columns[column];
      if (!target) continue;
      const rows = byAction.get(target.actionId) ?? new Map();
      byAction.set(target.actionId, rows);
      rows.set(instanceId, { ...(rows.get(instanceId) ?? {}), [target.parameter]: value });
    }
  }
  return [...byAction.keys()].sort().map((actionId) => ({
    actionId,
    edits: [...byAction.get(actionId)!.entries()].map(([instance_id, values]) => ({
      instance_id, values,
    })),
  }));
}

/**
 * What Submit says, and whether it may be pressed.
 *
 * **The count is in the label.** p.138 makes a submission whole or nothing, so
 * the number of rows about to change is the one fact somebody needs before
 * pressing it — "Save" over a table where three cells were typed into an hour
 * ago is a button whose blast radius is invisible.
 */
export function submitLabel(rows: number): string {
  if (rows === 0) return "Nothing to save";
  return rows === 1 ? "Save 1 object" : `Save ${rows} objects`;
}

/**
 * What the reader is told after a submission that did not happen.
 *
 * The server's own sentence when there is one: p.138's refusals name the row or
 * the rule that stopped it, and replacing that with "couldn't save" would throw
 * away the only part somebody can act on. §322's `comments-error` rule.
 */
export function failureMessage(error: string | null | undefined): string {
  return error?.trim() || "Couldn't save these edits.";
}

/**
 * How a saved submission reads.
 *
 * p.138's all-or-nothing is why this is one sentence rather than a per-row
 * list: every row in the submission has the same outcome, so a list would be
 * the same word repeated (`BatchResult` says so on the wire, which is where
 * this reading comes from rather than being decided again here).
 */
export function savedMessage(rows: number): string {
  return rows === 1 ? "Saved 1 object." : `Saved ${rows} objects.`;
}
