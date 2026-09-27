/** p.142-143's array operations and checks, as the Variables panel offers
 * them (§567). The server evaluates them (`services/variable_arrays.py`).
 * Pure. */

const ARITY: Record<string, number | "many"> = {
  array_compose: "many", array_intersection: "many", array_update_element: 2,
  array_get_element: 1, array_length: 1, array_contains: "many", array_does_not_contain: "many",
  array_is_subset_of: 2,
};
/** The two that take p.142-143's "specified index". */
export const INDEXED = new Set(["array_update_element", "array_get_element"]);
export const MAX_INDEX = 10_000;

export function isArrayOp(transform: string): boolean {
  return transform in ARITY;
}

export function arrayArity(transform: string): number | "many" {
  return ARITY[transform] ?? 1;
}

/** What each input is called. */
export function arraySlotLabel(transform: string, index: number): string {
  if (transform === "array_compose" || transform === "array_intersection") return `Array ${index + 1}`;
  if (transform === "array_update_element") return index === 0 ? "Array" : "New value";
  if (transform === "array_is_subset_of") return index === 0 ? "Array" : "Of";
  if (transform === "array_contains" || transform === "array_does_not_contain") {
    return index === 0 ? "Array" : "Value";
  }
  return "Array";
}

/** An index as the server takes it: a whole position from 0, or null. */
export function indexOf(text: string): number | null {
  if (text.trim() === "") return null;
  const n = Number(text);
  return Number.isInteger(n) && n >= 0 && n <= MAX_INDEX ? n : null;
}
