/** The Object Table's inline edits, as rules a test can reach
 * (Foundry `workshop` p.240–243).
 *
 * > "Enabling inline editing allows module users to modify cell-level data
 * > displayed within the Object Table and then save these edits to objects
 * > data." (p.240)
 *
 * **The split is the repo's usual one, and this feature makes the reason for it
 * unusually plain.** The server owns what is *legal* — §238's
 * `inline_edit_refusals` decides which actions may back a cell edit at all, and
 * the batch endpoint refuses a submission that breaks p.138. This file owns
 * what the browser *offers*: which actions reach the picker, which columns take
 * an editor, what a staged edit is, and when Submit may be pressed. Nothing
 * here re-derives a rule the server states — `eligibleActions` reads a verdict
 * it did not compute, and the row cap arrives on the wire rather than being
 * typed in twice.
 */

/** Just enough of an action type for these rules. The panel and the widget both
 * hold the full `ActionType`; naming only what is read keeps the unit tests from
 * having to build one. */
export type EditAction = {
  id: string;
  display_name?: string | null;
  api_name?: string | null;
  parameters?: readonly { api_name: string; display_name?: string | null }[];
  inline_edit_refusals?: readonly string[];
  inline_edit_row_limit?: number;
};

/** p.242's cap when the server has not said. **Not a second copy of the rule**
 * — the server sends `inline_edit_row_limit` on every action type, and this is
 * what a widget uses in the instant before the action has loaded, where the
 * honest answer is "no rows may be staged yet". Zero rather than 200, because
 * an unknown cap that permits everything is the direction that writes data. */
export const UNKNOWN_ROW_LIMIT = 0;

/** The actions a builder may pick, out of everything on the object type.
 *
 * **Absent refusals are a refusal.** An action type whose payload predates
 * §238 — or which came from somewhere that does not compute the field — has an
 * unknown verdict, and offering an unknown one is offering a save that fails,
 * which is §214's rule. So eligibility is "the list is present and empty",
 * never "the list is not non-empty".
 */
export function eligibleActions<T extends EditAction>(actions: readonly T[] | undefined): T[] {
  return (actions ?? []).filter(
    (a) => Array.isArray(a.inline_edit_refusals) && a.inline_edit_refusals.length === 0,
  );
}

/** How many rows may be staged at once, as the chosen action reports it. */
export function rowLimitOf(action: EditAction | null | undefined): number {
  const raw = action?.inline_edit_row_limit;
  return typeof raw === "number" && Number.isFinite(raw) && raw > 0
    ? Math.floor(raw)
    : UNKNOWN_ROW_LIMIT;
}

/** p.241's automatic mapping.
 *
 * > "For an easier configuration experience, action parameter IDs should match
 * > the property IDs displayed within the table. This will allow an automatic
 * > mapping of action parameters to table columns."
 *
 * **A recommendation, which means the non-matching case is legal** and has to
 * stay configurable by hand — so this seeds a mapping rather than replacing
 * one. Only columns the table actually displays are matched: p.241's sentence
 * is about the properties "displayed within the table", and mapping a parameter
 * onto a hidden column would put an editor on a cell nobody can see.
 */
export function automaticMapping(
  action: EditAction | null | undefined,
  columns: readonly string[],
): Record<string, string> {
  const shown = new Set(columns);
  const out: Record<string, string> = {};
  for (const parameter of action?.parameters ?? []) {
    if (shown.has(parameter.api_name)) out[parameter.api_name] = parameter.api_name;
  }
  return out;
}

/** The stored mapping, read as the document may actually hold it.
 *
 * Anything naming a parameter the action no longer declares, or a column the
 * table no longer shows, is **dropped rather than kept**: both sides of a
 * mapping can be edited long after it was made, and a mapping onto a column
 * that is not there is an editor that cannot be rendered. Same rule the table's
 * own `columns` prop has followed since §207.
 */
export function mappingOf(
  raw: unknown,
  action: EditAction | null | undefined,
  columns: readonly string[],
): Record<string, string> {
  const declared = new Set((action?.parameters ?? []).map((p) => p.api_name));
  const shown = new Set(columns);
  const out: Record<string, string> = {};
  if (typeof raw !== "object" || raw === null) return out;
  // **No `Array.isArray` guard here, and `stagedOf` below has one.** A mutant
  // removing it survived: `Object.entries` on an array yields the keys "0",
  // "1", …, and a parameter api_name is `^[a-z][a-z0-9_]{0,99}$` on the server,
  // so `declared.has` rejects every one of them already. `stagedOf` has nothing
  // to filter against and needs its guard, which is why the two look the same
  // and only one is a check.
  for (const [parameter, column] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof column !== "string" || !column) continue;
    if (!declared.has(parameter) || !shown.has(column)) continue;
    out[parameter] = column;
  }
  return out;
}

/** Which parameter, if any, edits this column.
 *
 * **Keyed the other way round from the stored mapping**, because the table asks
 * per column and the panel configures per parameter. Two parameters pointed at
 * one column is a configuration nothing prevents, and the first one wins in
 * key order rather than an arbitrary one, so the same document always draws the
 * same editor.
 */
export function parameterForColumn(
  mapping: Record<string, string>,
  column: string,
): string | undefined {
  for (const parameter of Object.keys(mapping).sort()) {
    if (mapping[parameter] === column) return parameter;
  }
  return undefined;
}

/** Staged edits: one entry per row, holding the parameter values typed into it.
 *
 * p.242 counts *rows*, not edits — "up to 200 rows at a time" — which is why
 * this is keyed by instance and not by cell.
 */
export type Staged = Record<string, Record<string, unknown>>;

export function stagedOf(raw: unknown): Staged {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return {};
  const out: Staged = {};
  for (const [instance, values] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof values === "object" && values !== null && !Array.isArray(values)) {
      out[instance] = { ...(values as Record<string, unknown>) };
    }
  }
  return out;
}

/** Whether a cell may be typed into at all.
 *
 * p.242's cap is about **rows**, so a row that is already staged stays editable
 * however full the batch is — the alternative freezes a reader halfway through
 * correcting the row they are looking at. A row that is not yet staged is
 * refused once the limit is reached.
 */
export function canStage(staged: Staged, instanceId: string, limit: number): boolean {
  if (Object.prototype.hasOwnProperty.call(staged, instanceId)) return true;
  return Object.keys(staged).length < limit;
}

/** Record one cell's value. Returns a new map; refuses over the cap. */
export function stage(
  staged: Staged,
  instanceId: string,
  parameter: string,
  value: unknown,
  limit: number,
): Staged {
  if (!canStage(staged, instanceId, limit)) return staged;
  return { ...staged, [instanceId]: { ...(staged[instanceId] ?? {}), [parameter]: value } };
}

/** p.242's Undo, "as seen in the left-most column of the table".
 *
 * **The whole row**, which is what the screenshot's single button per row can
 * mean. Undoing one cell would need a control per cell, and p.242 draws one per
 * row.
 */
export function undoRow(staged: Staged, instanceId: string): Staged {
  if (!Object.prototype.hasOwnProperty.call(staged, instanceId)) return staged;
  const out = { ...staged };
  delete out[instanceId];
  return out;
}

export function isStaged(staged: Staged, instanceId: string): boolean {
  return Object.prototype.hasOwnProperty.call(staged, instanceId);
}

/** What this cell should show: the staged value if the reader typed one, and
 * the stored value otherwise.
 *
 * **`hasOwnProperty`, not a truthiness test**, because clearing a cell stages
 * an empty string and that is an edit — a falsy check would show the old value
 * back to somebody who had just deleted it.
 */
export function cellValue(
  staged: Staged,
  instanceId: string,
  parameter: string,
  stored: unknown,
): unknown {
  const row = staged[instanceId];
  if (row && Object.prototype.hasOwnProperty.call(row, parameter)) return row[parameter];
  return stored;
}

export function stagedCount(staged: Staged): number {
  return Object.keys(staged).length;
}

/** The request body §238's `execute-batch` takes.
 *
 * Sorted by instance id so a submission is deterministic: the server refuses a
 * batch naming one object twice and reports the first row that fails a
 * criterion, and a map's insertion order would make which row that is depend on
 * the order the reader happened to type in.
 */
export function toEdits(staged: Staged): { instance_id: string; values: Record<string, unknown> }[] {
  return Object.keys(staged)
    .sort()
    .map((instance_id) => ({ instance_id, values: { ...staged[instance_id] } }));
}

/** p.242's Custom button text, with the label p.242 itself uses. */
export const DEFAULT_BUTTON_TEXT = "Edit table";

export function buttonTextOf(raw: unknown): string {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text || DEFAULT_BUTTON_TEXT;
}

/** p.242's "Enable edit mode by default" and p.243's "One-click submit".
 *
 * `=== true` rather than a truthiness test: both are stored booleans, and a
 * document holding the string `"false"` — which the raw JSON editor (§117) can
 * put there — would otherwise turn a safeguard off.
 */
export function editByDefaultOf(raw: unknown): boolean {
  return raw === true;
}

export function oneClickOf(raw: unknown): boolean {
  return raw === true;
}

/** Whether the table is showing editors right now.
 *
 * Two inputs and one rule: p.242's toggle decides the *starting* state, and the
 * button toggles from there. Expressed as a function rather than an initialiser
 * because a table whose configuration changes under a live viewer — the builder
 * flipping the toggle while the preview is open — must follow it.
 */
export function editing(open: boolean | null, byDefault: unknown): boolean {
  return open === null ? editByDefaultOf(byDefault) : open;
}

/** Whether Submit may be pressed: something staged, and an action to submit it
 * to. **Not "is the batch valid"** — that is p.138's question and the server's
 * to answer, and asking it here would be a second criteria evaluator. */
export function canSubmit(staged: Staged, action: EditAction | null | undefined): boolean {
  return stagedCount(staged) > 0 && !!action?.id;
}

/** What the footer says about how full the batch is (p.242's cap).
 *
 * Only once the cap is reached, because a count on screen from the first edit
 * is a number nobody needs and a warning that is always there is not a warning.
 */
export function limitNotice(staged: Staged, limit: number): string | null {
  if (limit <= 0 || stagedCount(staged) < limit) return null;
  return `${limit} rows staged, which is the most one submission can carry. `
    + "Submit these before editing another row.";
}
