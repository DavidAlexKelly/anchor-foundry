/**
 * What values an action parameter accepts, the parts a form decides (§584;
 * `action-types` p.8, p.45, p.71).
 *
 * > "Select the Priority parameter to limit the values it can take on. Change
 * > the constraints from User input to Multiple choice… Add P0, P1 and P2 as
 * > options." (p.8)
 *
 * **The rule is the server's** (`services/action_constraints.py`), applied
 * where a submission is bound, after p.45's overrides. This decides what the
 * editor may offer and what the form draws: p.8's multiple choice as a
 * dropdown of its options, and anything else as a line saying what is allowed
 * beside the box, in the server's own words (`constraint_summary`).
 */

import type { PropertyDataType, ValueConstraint } from "@/lib/types";

/** The parameter types a constraint can be put on: p.233's. Kept in step with
 * `action_constraints.CONSTRAINABLE` by the API test that saves each. */
export const CONSTRAINABLE: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp",
];

interface Constrainable {
  data_type?: string;
  array_of?: string | null;
  value_constraint?: ValueConstraint | null;
}

/** The type a parameter's constraint is read against, or null when it cannot
 * carry one: its own type, or an array's element type (each item is checked). */
export function constraintBaseType(parameter: Constrainable): PropertyDataType | null {
  const type = parameter.data_type === "array" ? parameter.array_of ?? "" : parameter.data_type ?? "";
  return (CONSTRAINABLE as string[]).includes(type) ? (type as PropertyDataType) : null;
}

/** p.8's multiple choice: the options a value is picked from, or null when
 * the parameter takes typed input. On an array parameter they are each
 * item's, and every row is a dropdown of them. */
export function multipleChoice(parameter: Constrainable): unknown[] | null {
  const constraint = parameter.value_constraint;
  if (!constraint || constraint.kind !== "enum") return null;
  return constraint.values;
}

/** What the form says under a constrained box, or "" for p.8's User input.
 * Not said for a dropdown, whose options already say it. */
export function constraintNote(
  parameter: Constrainable & { constraint_summary?: string | null },
): string {
  if (!parameter.value_constraint || multipleChoice(parameter)) return "";
  const summary = parameter.constraint_summary ?? "";
  if (!summary) return "";
  return parameter.data_type === "array" ? `Each item: ${summary}.` : `Allowed: ${summary}.`;
}

/** p.71-72's struct fields (§585): each field's options, for the fields whose
 * constraint is p.8's multiple choice, or null when none is. */
export function fieldChoices(parameter: {
  field_constraints?: Record<string, ValueConstraint> | null;
}): Record<string, unknown[]> | null {
  const out: Record<string, unknown[]> = {};
  for (const [field, constraint] of Object.entries(parameter.field_constraints ?? {})) {
    if (constraint?.kind === "enum") out[field] = constraint.values;
  }
  return Object.keys(out).length ? out : null;
}

/** What the form says under a struct for its other constrained fields, one
 * line each, named by the field's label. A dropdown field says it already. */
export function fieldNotes(parameter: {
  field_constraints?: Record<string, ValueConstraint> | null;
  field_constraint_summaries?: Record<string, string> | null;
  struct_fields?: { api_name: string; display_name?: string }[] | null;
}): string[] {
  const labels = new Map(
    (parameter.struct_fields ?? []).map((f) => [f.api_name, f.display_name?.trim() || f.api_name]),
  );
  return Object.entries(parameter.field_constraints ?? {})
    .filter(([field, constraint]) =>
      constraint?.kind !== "enum" && parameter.field_constraint_summaries?.[field])
    .map(([field]) =>
      `${labels.get(field) ?? field}: ${parameter.field_constraint_summaries?.[field]}.`);
}

/** Whether a parameter is p.66's struct, or a list of them, whose fields take
 * constraints of their own (p.71, §585). */
export function isStructParameter(parameter: Constrainable): boolean {
  return parameter.data_type === "struct"
    || (parameter.data_type === "array" && parameter.array_of === "struct");
}
