/** p.140-141's math operations and numeric comparisons, as the Variables
 * panel offers them (§564). The server evaluates them
 * (`services/variable_math.py`); this is what each one's inputs are called
 * and how many it takes, for the panel. Pure. */

import type { WorkshopTransform } from "@platform/types";

/** How many inputs each takes: a fixed number, or "many" with a least. */
export const MATH_ARITY: Record<string, { least: number; most: number | null }> = {
  add: { least: 1, most: null },
  subtract: { least: 2, most: null },
  multiply: { least: 1, most: null },
  divide: { least: 2, most: 2 },
  absolute: { least: 1, most: 1 },
  negate: { least: 1, most: 1 },
  round_up: { least: 1, most: 1 },
  round_down: { least: 1, most: 1 },
  round_nearest: { least: 1, most: 1 },
  max: { least: 1, most: null },
  min: { least: 1, most: null },
  equal_to: { least: 2, most: null },
  not_equal_to: { least: 2, most: null },
  less_than: { least: 2, most: null },
  less_or_equal: { least: 2, most: null },
  greater_than: { least: 2, most: null },
  greater_or_equal: { least: 2, most: null },
};

const COMPARISONS = new Set([
  "equal_to", "not_equal_to", "less_than", "less_or_equal", "greater_than", "greater_or_equal",
]);
/** p.140's "rounded … to a specified precision". */
export const ROUNDINGS = new Set(["round_up", "round_down", "round_nearest"]);
export const MAX_PRECISION = 10;

export function isMath(transform: WorkshopTransform | string): boolean {
  return transform in MATH_ARITY;
}

/** The panel's slots: exactly the fixed number, or every input so far and one
 * empty one to add another - never fewer than the least. */
export function mathArity(transform: string): number | "many" {
  const arity = MATH_ARITY[transform];
  if (!arity) return 1;
  return arity.most === arity.least ? arity.least : "many";
}

/** What one input is called. p.141 compares "the first given numeric value"
 * with "the second given numeric value(s)", and p.140 subtracts the rest
 * from the first. */
export function mathSlotLabel(transform: string, index: number): string {
  if (COMPARISONS.has(transform)) return index === 0 ? "Value" : "Compared with";
  if (transform === "subtract") return index === 0 ? "From" : "Take away";
  if (transform === "divide") return index === 0 ? "Divide" : "By";
  if (MATH_ARITY[transform]?.most === 1) return "Value";
  return `Value ${index + 1}`;
}

/** A precision as the server takes it: whole places from -10 to 10, or null
 * for anything else, which the field leaves unsaved. */
export function precisionOf(text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  return Number.isInteger(n) && Math.abs(n) <= MAX_PRECISION ? n : null;
}
