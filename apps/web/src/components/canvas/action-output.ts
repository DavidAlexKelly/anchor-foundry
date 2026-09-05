/** p.513's **Output object set**, as the browser's half.
 *
 * > "Output object set: Specify the object set that will be created or
 * > modified when the Action is submitted." (Workshop p.513)
 *
 * The server answers *which* objects an action wrote — only it can, because a
 * rule may create an object whose primary key comes from a parameter and modify
 * one a different parameter names (§240). What is here is the rest: which of
 * those belong in this variable, and what a widget writes so that a
 * `narrow_set` derivation can turn them into a set.
 */

import { selectionClauses } from "./object-table-selection";

/** One object the executor reported writing. */
export type Touched = {
  object_type_id?: string | null;
  primary_key?: string | null;
  change?: string | null;
};

/** The keys to name in the output, out of everything the action touched.
 *
 * **One object type, and that is a stated divergence.** p.513 says "the object
 * set", singular, and an object set here is a set *of a type*: `narrow_set`
 * narrows one base set by a clause list, so a mixed list would describe rows
 * the base set does not contain. An action that also writes another type's
 * objects therefore reports them and this leaves them out, rather than
 * producing a set that silently resolves to fewer rows than it names.
 *
 * Deduplicated, because a clause list is a set and `$primary_key in ["a","a"]`
 * is the same set written twice — and because the count is what a module shows
 * next to it.
 */
export function outputKeys(
  touched: readonly Touched[] | undefined,
  objectTypeId: string | null | undefined,
): string[] {
  if (!objectTypeId) return [];
  const out: string[] = [];
  for (const entry of touched ?? []) {
    if (entry?.object_type_id !== objectTypeId) continue;
    const key = entry?.primary_key;
    if (typeof key !== "string" || key === "") continue;
    if (out.includes(key)) continue;
    out.push(key);
  }
  return out;
}

/** What the widget writes to the bound variable.
 *
 * **Clauses, not a finished set definition** — §207's rule, arrived at from the
 * other side. A stored definition would freeze the base set at the moment of
 * the submit; clauses mean "these keys, against whatever set this is narrowed
 * from", which is what lets the output stay a view of live data rather than a
 * snapshot.
 *
 * An action that wrote nothing of this type still writes — an **empty** clause
 * list, which `object_sets.parse` reads as the empty set (§207). Leaving the
 * variable alone would leave the previous submission's objects on screen, and
 * a reader would act on rows the last press of Submit did not touch.
 */
export function outputClauses(
  touched: readonly Touched[] | undefined,
  objectTypeId: string | null | undefined,
): ReturnType<typeof selectionClauses> {
  return selectionClauses(outputKeys(touched, objectTypeId));
}
