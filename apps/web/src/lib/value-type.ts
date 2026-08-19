/**
 * Building and offering a value type (Foundry `object-link-types` p.222–234).
 *
 * **Pure, and for the same reason `lib/shared-property.ts` is.** The server
 * decides what is *legal* — `services/value_constraints.py` is authoritative
 * and enforces the rule on every synced row — while this decides what a form
 * may *offer* and what it produces. Nothing here can widen what a save
 * accepts; it can only stop the form from proposing one that fails.
 *
 * The one part worth having a second copy of is `constraintProblem`. A
 * constraint dialog that let somebody press Save on `minimum: 10, maximum: 1`
 * and then showed them a 422 is a worse form than one that says so while the
 * numbers are still on screen — and the server refuses it either way, so the
 * two cannot drift into disagreement about whether it is allowed, only about
 * *when* it is reported.
 */

import type { PropertyDataType, ValueConstraint, ValueType } from "@/lib/types";

/** p.233's base type lists, narrowed to the types this platform has. Kept in
 * step with `value_constraints.py`'s constants by the browser test that pins
 * each list — a divergence here shows up as a form offering a kind the save
 * refuses. */
export const ENUM_TYPES: PropertyDataType[] = ["string", "integer", "float", "boolean"];
export const RANGE_TYPES: PropertyDataType[] = [
  "integer", "float", "date", "timestamp", "string",
];
export const STRING_ONLY: PropertyDataType[] = ["string"];

export type ConstraintKind = ValueConstraint["kind"];

/** Which constraint kinds may be attached to `baseType` (p.233).
 *
 * Offering a regex on an integer would be offering a save that fails, and —
 * worse — a check that could never pass if it somehow got through. */
export function kindsFor(baseType: PropertyDataType): ConstraintKind[] {
  const out: ConstraintKind[] = [];
  if (ENUM_TYPES.includes(baseType)) out.push("enum");
  if (RANGE_TYPES.includes(baseType)) out.push("range");
  if (STRING_ONLY.includes(baseType)) out.push("regex", "uuid");
  return out;
}

/** What a range's bounds mean for this base type.
 *
 * p.233: "For String properties, the length of the string is constrained." A
 * form that said "Minimum" for both would be describing two different things
 * with one word, and the string case is the surprising one. */
export function rangeLabel(baseType: PropertyDataType): string {
  return baseType === "string" ? "Length" : "Value";
}

/** The first reason `constraint` could not be saved, as a sentence, or null.
 *
 * Mirrors `value_constraints.parse`'s refusals — deliberately, and only the
 * ones a form can put in front of somebody before they press Save. */
export function constraintProblem(
  constraint: ValueConstraint | null,
  baseType: PropertyDataType,
): string | null {
  if (constraint === null) return null;
  if (!kindsFor(baseType).includes(constraint.kind)) {
    return `A ${constraint.kind} constraint does not apply to a ${baseType} value type.`;
  }
  if (constraint.kind === "enum") {
    if (!constraint.values.length) return "List at least one allowed value.";
    const seen = new Set(constraint.values.map((v) => String(v)));
    if (seen.size !== constraint.values.length) return "That lists the same value twice.";
    return null;
  }
  if (constraint.kind === "range") {
    const { minimum, maximum } = constraint;
    if (minimum === undefined && maximum === undefined) {
      return "A range needs a minimum, a maximum, or both.";
    }
    if (baseType === "string" && typeof minimum === "number" && minimum < 0) {
      return "A length cannot be negative.";
    }
    if (minimum !== undefined && maximum !== undefined && !above(maximum, minimum)) {
      return "The minimum is above the maximum, so nothing could satisfy it.";
    }
    return null;
  }
  if (constraint.kind === "regex") {
    if (!constraint.pattern.trim()) return "A regex constraint needs a pattern.";
    try {
      new RegExp(constraint.pattern);
    } catch {
      // The browser's own engine, which is not the one that will run it — so
      // this catches a typo early and the server still has the final word.
      return "That pattern is not a valid regular expression.";
    }
    return null;
  }
  return null;
}

/** Whether `high` is at or above `low`, comparing as numbers when both are,
 * and as instants when both are temporal strings.
 *
 * Text comparison is wrong for timestamps carrying an offset — the bug §168's
 * mutation testing found on the server — so this does the same conversion the
 * server does rather than a second, looser one. */
function above(high: number | string, low: number | string): boolean {
  if (typeof high === "number" && typeof low === "number") return high >= low;
  const a = Date.parse(String(high));
  const b = Date.parse(String(low));
  if (Number.isNaN(a) || Number.isNaN(b)) return true; // not ours to judge
  return a >= b;
}

/** The value types that may be offered for a property of `dataType` (p.222).
 *
 * A value type *is* the type, so only a matching base type can be attached —
 * the same rule `offerableTo` applies to shared properties, and the same
 * reason: the alternative is a dropdown full of saves that fail. */
export function offerableTo(
  types: ValueType[],
  dataType: PropertyDataType,
): ValueType[] {
  return types.filter((t) => t.base_type === dataType);
}

/** How a value type reads on one line, for a picker: the name, and what it
 * actually enforces. `constraint_summary` comes from the server so the two
 * cannot disagree about what a rule says. */
export function optionLabel(type: ValueType): string {
  return `${type.display_name} — ${type.constraint_summary}`;
}
