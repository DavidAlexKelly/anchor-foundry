/** An object set filter's default whose values are variables, and p.148's
 * *Update used variables on filter value changes* (§592; `workshop`
 * p.146-148).
 *
 *     "A default state for the filter can also be specified by selecting
 *      object types, property types, and values for those property types.
 *      The values can be specified inline, or as variables." (p.146)
 *
 *     "When the filter value is updated to a filter that matches the shape of
 *      the default filter, the value for each variable in the configured
 *      default will be updated to the extracted value from the filter."
 *      (p.148)
 *
 * A value read from a variable is `{"variable": "<id>"}` in the default's
 * clauses. The server fills those in when the filter has no value of its own
 * (`workshop_variables.filled_default`); this writes them back when a widget
 * sets one, since it is the viewer's filter that changed.
 *
 * **The shape is each clause's property and the kind of bound it is**, not
 * its exact operator. p.148's own example is a histogram range feeding two
 * numeric inputs, and a Filter List's histogram writes `gte` and then `lt`
 * or `lte` depending on whether the bar is the last (`filter-list.ts`
 * `withBucket`), so matching `lte` alone would miss every bar but one. The
 * same goes for a single choice, which a Filter List writes as `eq`, and
 * several, as `in`: one choice read into a variable that expects several is
 * a list of one, and one out of a list of one is its only entry.
 */

import type { Clause } from "./filter-clause";

/** Mirrors `FILTER_REF_KINDS` in `services/workshop_variables.py`: what a
 * default value may read, a plain value somebody sets. */
export const FILTER_REF_KINDS: readonly string[] = [
  "string", "number", "boolean", "date", "timestamp", "array",
];

/** The operators that say the same thing about a clause's shape. */
const FAMILIES: Record<string, string> = {
  gt: "lower", gte: "lower", lt: "upper", lte: "upper", eq: "choice", in: "choice",
};

function familyOf(op: string): string {
  return FAMILIES[op] ?? op;
}

/** The variable a default clause's value reads, or null for a value given
 * inline. */
export function refOf(value: unknown): string | null {
  // A list has no `variable`, so it falls through to null without a case.
  if (!value || typeof value !== "object") return null;
  const variable = (value as Record<string, unknown>).variable;
  return typeof variable === "string" && Object.keys(value).length === 1 ? variable : null;
}

/** A filter default, or a filter's value, as clauses. The panel keeps a
 * typed default as its JSON text (§590), and a value can arrive either way. */
export function clausesOf(raw: unknown): Clause[] | null {
  let value = raw;
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return null;
    }
  }
  if (!Array.isArray(value)) return null;
  const out: Clause[] = [];
  for (const c of value) {
    if (!c || typeof c !== "object" || typeof (c as Clause).property !== "string") return null;
    out.push(c as Clause);
  }
  return out;
}

/** The variables a default's values read, each once, in clause order. */
export function usedVariables(rawDefault: unknown): string[] {
  const out: string[] = [];
  for (const clause of clausesOf(rawDefault) ?? []) {
    const ref = refOf(clause.value);
    if (ref && !out.includes(ref)) out.push(ref);
  }
  return out;
}

/** One chosen value, as the default's operator would hold it. */
function asHeld(wantedOp: string, clause: Clause): { value: unknown } | null {
  if (wantedOp === "eq" && clause.op === "in") {
    return Array.isArray(clause.value) && clause.value.length === 1
      ? { value: clause.value[0] } : null;
  }
  if (wantedOp === "in" && clause.op === "eq") return { value: [clause.value] };
  return { value: clause.value };
}

/** Each used variable's value out of `filter`, or null when the filter does
 * not have the default's shape: as many clauses, each on the same property
 * with the same kind of bound as one of the default's. */
export function extractUsed(rawDefault: unknown, filter: unknown): Record<string, unknown> | null {
  const wanted = clausesOf(rawDefault);
  const given = clausesOf(filter);
  if (!wanted || !given || wanted.length !== given.length) return null;
  const left = [...given];
  const out: Record<string, unknown> = {};
  for (const clause of wanted) {
    const at = left.findIndex(
      (c) => c.property === clause.property && familyOf(c.op) === familyOf(clause.op),
    );
    if (at < 0) return null;
    const match = left.splice(at, 1)[0] as Clause;
    const ref = refOf(clause.value);
    if (!ref) continue;
    const held = asHeld(clause.op, match);
    if (!held) return null;
    out[ref] = held.value;
  }
  return out;
}

type Declared = Record<string, {
  kind: string; default?: unknown; update_used_variables?: boolean; derivation?: unknown;
}>;

/** What p.148 writes now: for each filter that updates its used variables and
 * whose value changed since `seen`, the extracted values that differ from
 * what those variables hold. `seen` is each such filter's value as last
 * looked at, as JSON, and is updated in place, so a filter is read once per
 * change rather than on every render. A filter with no value (never set, or
 * reset) is remembered and writes nothing: it is back on its default, which
 * reads the variables rather than writing them. */
export function usedUpdates(
  declared: Declared, values: Record<string, unknown>, seen: Record<string, string>,
): Record<string, unknown> {
  const updates: Record<string, unknown> = {};
  for (const [id, variable] of Object.entries(declared)) {
    if (variable.kind !== "object_set_filter" || !variable.update_used_variables) continue;
    const key = JSON.stringify(values[id] ?? null);
    if (seen[id] === key) continue;
    seen[id] = key;
    // An unset filter extracts nothing (`clausesOf` reads no clauses), so it
    // needs no case of its own.
    const extracted = extractUsed(variable.default, values[id]);
    for (const [ref, value] of Object.entries(extracted ?? {})) {
      if (!declared[ref] || declared[ref].derivation) continue;
      if (JSON.stringify(values[ref] ?? null) !== JSON.stringify(value ?? null)) {
        updates[ref] = value;
      }
    }
  }
  return updates;
}
