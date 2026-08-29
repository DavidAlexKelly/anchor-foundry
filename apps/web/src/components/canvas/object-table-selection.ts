/** p.224's Selection block: the Object Table's two output variables.
 *
 * > "**Active object**: This is the first of two output variables in the Object
 * > Table and outputs an object set of the currently active / highlighted
 * > object… **Disable active object auto-selection**: By default, the first row
 * > in the table is automatically set as the active object at load time.
 * > Disabling this setting prevents this and results in an empty active object
 * > at load time. Note that auto-selection only triggers when the widget is
 * > visible; if the Object Table is within a collapsed section, auto-selection
 * > will not occur until the section is expanded and the widget becomes
 * > visible." (p.224)
 *
 * > "**Enable multi-select**… **Selected objects**: This is the second of two
 * > output variables… Note: this output variable will only be in use and
 * > populated if the Enable multi-select toggle is set to true." (p.224)
 *
 * ---
 *
 * **Both outputs are a list of keys, and the active one is a list of at most
 * one.** p.224 describes the active object as "an object set of the currently
 * active / highlighted object" — a set, not an object — so one shape covers
 * both, and "nothing is active" and "nothing is selected" are the same empty
 * list rather than two different absences.
 *
 * **The widget writes clauses, not a set definition, and that is deliberate.**
 * A clause list is what `narrow_set` consumes (the Pivot Table's drill-down
 * already works this way), so the meaning of a selection is recomputed against
 * whatever the table's set currently is. Writing a whole definition would be
 * closer to p.224's wording and would freeze the base set at the moment of the
 * click: filter the table afterwards and the selection variable would still
 * carry the old filters, describing objects that are no longer on screen.
 *
 * **`in []` is the empty set, and the server had to be taught that** — see the
 * argument in `services/object_sets.py`'s `parse`. Without it a selection has
 * no value for "nothing is selected", and the alternatives all hand downstream
 * widgets the *whole* set, which is the failure decision 0002 exists to
 * prevent.
 */

/** The property name that addresses an instance's primary key.
 *
 * **The same string as `PRIMARY_KEY_FILTER` in `services/object_sets.py`**, and
 * a test pins them together: a clause naming anything else would be a filter on
 * a property that happens to be missing, which narrows to nothing and looks
 * exactly like an empty selection.
 */
export const PRIMARY_KEY = "$primary_key";

export interface Clause {
  property: string;
  op: string;
  value: unknown;
}

export interface Row {
  primary_key: string;
}

/** The clauses that describe a selection of these keys.
 *
 * Always one clause, always `in`, empty list included — so the shape a
 * downstream `narrow_set` sees never changes with the size of the selection.
 */
export function selectionClauses(keys: readonly string[]): Clause[] {
  return [{ property: PRIMARY_KEY, op: "in", value: [...keys] }];
}

/** Which keys a clause list names, for reading the selection back out.
 *
 * **The variable is the source of truth, not a second copy in component
 * state.** A table that kept its own set would disagree with the variable the
 * moment anything else wrote to it — an event that clears the selection, a
 * saved state restored on load — and the checkboxes would show one answer while
 * every downstream widget acted on another.
 */
export function keysOf(clauses: unknown): string[] {
  if (!Array.isArray(clauses)) return [];
  for (const clause of clauses) {
    if (!clause || typeof clause !== "object") continue;
    const c = clause as Partial<Clause>;
    if (c.property !== PRIMARY_KEY || c.op !== "in") continue;
    if (!Array.isArray(c.value)) continue;
    return c.value.map((v) => String(v));
  }
  return [];
}

/** Whether a selection has been *stated* at all.
 *
 * **"Nothing is selected" and "nobody has said" are different values, and only
 * one of them is safe to hand downstream.** An empty clause list means *no
 * narrowing* — `narrow_set` returns the base set unchanged, which is right for
 * a Filter List nobody has touched. A clause list holding `in []` means the
 * empty set. A variable the widget has never written is the first, so a table
 * whose active object is empty would give every downstream widget the whole
 * table until somebody clicked a row.
 *
 * So the widget writes `in []` on load rather than leaving the variable alone,
 * and this is how it knows whether it already has: `keysOf` cannot tell the two
 * apart, because both come back as no keys.
 */
export function hasSelection(clauses: unknown): boolean {
  if (!Array.isArray(clauses)) return false;
  return clauses.some((clause) => {
    if (!clause || typeof clause !== "object") return false;
    const c = clause as Partial<Clause>;
    return c.property === PRIMARY_KEY && c.op === "in" && Array.isArray(c.value);
  });
}

/** Add or remove one key, keeping the order stable.
 *
 * Stable because the clause list is written into a variable and compared as a
 * value: reordering on every click would make the set look changed when it is
 * not, and re-resolve everything downstream.
 */
export function toggle(keys: readonly string[], key: string): string[] {
  return keys.includes(key) ? keys.filter((k) => k !== key) : [...keys, key];
}

export interface AutoSelect {
  rows: readonly Row[] | undefined;
  /** What the variable currently holds. */
  current: readonly string[];
  /** p.224's setting, stated as the positive: false is "Disable". */
  enabled: boolean;
  /** Whether the widget is actually on screen (p.224's collapsed section). */
  visible: boolean;
}

/** The key to auto-select, or `null` for "leave it alone".
 *
 * p.224's rule has four ways to say no and one to say yes, and the ones worth
 * naming are the last two:
 *
 * * **A viewer's choice is never overwritten.** Rows arriving again — a refetch,
 *   a page turn, a filter narrowing — must not move the active object back to
 *   the first row under somebody who picked the fourth.
 * * **Visibility is checked here rather than assumed**, because a collapsed
 *   section keeps its children *mounted* (they should not refetch every time
 *   somebody folds a section away), so a table inside one is running and would
 *   otherwise auto-select against a viewer who cannot see it — and then the
 *   drawer p.224 describes opens for a row nobody chose.
 */
export function autoSelectKey({ rows, current, enabled, visible }: AutoSelect): string | null {
  if (!enabled || !visible) return null;
  if (current.length > 0) return null;
  const first = rows?.[0];
  return first ? first.primary_key : null;
}
