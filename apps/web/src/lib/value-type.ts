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
  "integer", "float", "date", "timestamp", "string", "array",
];
export const STRING_ONLY: PropertyDataType[] = ["string"];
/** What a nested or elements constraint may name (§681): a scalar value type,
 * as `value_constraints.REFERENCE_TYPES` has it. */
export const REFERENCE_TYPES: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp",
];
const FIELD_RE = /^[a-z][a-z0-9_]{0,99}$/;

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
  // p.234's array and struct constraints (§681).
  if (baseType === "array") out.push("unique", "nested");
  if (baseType === "struct") out.push("elements");
  return out;
}

/** The value types an array's items or a struct's fields may be held to
 * (§681): the scalar ones, less the deprecated ones the stored rule does not
 * already name (§764) — the server refuses a new reference to one. */
export function referable(types: ValueType[], keep: string[] = []): ValueType[] {
  return types.filter(
    (t) => REFERENCE_TYPES.includes(t.base_type) && takesNewUses(t, keep),
  );
}

/** p.229's deprecation, as an offer (§764): a deprecated value type keeps what
 * already uses it and takes nothing new, so it is offered only where it is
 * already the choice — leaving it off there would show a select with no entry
 * matching its own value. */
export function takesNewUses(type: ValueType, keep: (string | null | undefined)[]): boolean {
  return type.status !== "deprecated" || keep.includes(type.id);
}

/** What a deprecated value type may name as its replacement (p.254, p.229's
 * "creating a new one"): any other value type, less the deprecated ones —
 * pointing somebody at another value type on its way out is no help. */
export function replacements(types: ValueType[], self: string): ValueType[] {
  return types.filter((t) => t.id !== self && t.status !== "deprecated");
}

/** What a range's bounds mean for this base type.
 *
 * p.233: "For String properties, the length of the string is constrained." A
 * form that said "Minimum" for both would be describing two different things
 * with one word, and the string case is the surprising one. */
export function rangeLabel(baseType: PropertyDataType): string {
  if (baseType === "array") return "Size";
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
    if (baseType === "array" && typeof minimum === "number" && minimum < 0) {
      return "A size cannot be negative.";
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
  if (constraint.kind === "nested") {
    return constraint.value_type ? null : "Choose the value type every item must be.";
  }
  if (constraint.kind === "elements") {
    const entries = Object.entries(constraint.fields);
    if (!entries.length) return "Name at least one field and its value type.";
    for (const [field, ref] of entries) {
      if (!FIELD_RE.test(field)) return `"${field}" is not a struct field identifier.`;
      if (!ref) return `Choose the value type for ${field}.`;
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
  /** The property's current choice, kept on offer if deprecated (§764). */
  current: string | null = null,
): ValueType[] {
  return types.filter((t) => t.base_type === dataType && takesNewUses(t, [current]));
}

/** How a value type reads on one line, for a picker: the name, and what it
 * actually enforces. `constraint_summary` comes from the server so the two
 * cannot disagree about what a rule says. */
export function optionLabel(type: ValueType): string {
  const label = `${type.display_name} — ${type.constraint_summary}`;
  return type.status === "deprecated" ? `${label} (deprecated)` : label;
}
