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
