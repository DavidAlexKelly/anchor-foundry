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
import { editableParameters, type EditAction } from "../components/canvas/inline-edit";

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
): string | null {
  if (!onlyType) {
    return "Narrow the search to one object type to edit results here.";
  }
  if (!canWrite) {
    return "You can read these objects but not change them.";
  }
  if (eligible.length === 0) {
    return `No action on ${onlyType.display_name} can back an inline edit.`;
  }
  return null;
}

/**
 * Which of the table's columns take an editor, and through which parameter.
 *
 * p.241's automatic mapping — a parameter edits the column of the same name —
 * is the whole rule here. The Object Table lets a builder correct a mapping by
 * hand because a Workshop module is configured; the Explorer is not configured
 * by anybody, so a name match is all there is, and a parameter matching nothing
 * simply offers no editor.
 *
 * Hidden parameters are already out: `editableParameters` drops them (§324),
 * which is a column not offered rather than an action refused.
 */
export function editableColumns(
  action: EditAction | null | undefined,
  columns: readonly string[],
): Record<string, string> {
  const shown = new Set(columns);
  const out: Record<string, string> = {};
  for (const parameter of editableParameters(action)) {
    if (shown.has(parameter.api_name)) out[parameter.api_name] = parameter.api_name;
  }
  return out;
}

/** Whether this column has an editor, asked the way a table row asks it. */
export function editsColumn(
  mapping: Record<string, string>,
  column: string,
): string | null {
  for (const parameter of Object.keys(mapping).sort()) {
    if (mapping[parameter] === column) return parameter;
  }
  return null;
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
