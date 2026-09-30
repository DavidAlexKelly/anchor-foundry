/** p.142's string and boolean comparisons, as the Variables panel offers
 * them (§566). The server evaluates them (`services/variable_checks.py`).
 * Pure. */

const STRING_CHECKS = new Set([
  "string_is", "string_is_not", "string_contains", "string_does_not_contain",
  "string_starts_with", "string_ends_with",
]);
const BOOLEAN_CHECKS = new Set(["is_true", "is_false", "is_null", "is_not_null"]);

export function isCheck(transform: string): boolean {
  return STRING_CHECKS.has(transform) || BOOLEAN_CHECKS.has(transform);
}

/** A string comparison takes the text and as many to compare with as are
 * wanted; a boolean check takes one value. */
export function checkArity(transform: string): number | "many" {
  return STRING_CHECKS.has(transform) ? "many" : 1;
}

/** What each input is called: the text, then what it is compared with. */
export function checkSlotLabel(transform: string, index: number): string {
  if (!STRING_CHECKS.has(transform)) return "Value";
  return index === 0 ? "Text" : "Compared with";
}
