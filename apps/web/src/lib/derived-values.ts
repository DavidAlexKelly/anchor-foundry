/**
 * A table's derived columns (§604; `object-link-types` p.143, `workshop`
 * p.169).
 *
 * A derived property is not on a list read's rows - it is calculated from the
 * object's links - so a table showing one asks for the page's values in a
 * second read and draws each cell from that. What a cell says has three
 * states, and the one that matters is the difference between them:
 *
 * - **pending**, while the page is being answered, which is not "empty" - an
 *   average that has not arrived yet is not an average of nothing;
 * - **error**, when the page reached too far for that column, with the
 *   server's sentence, once for the column rather than once per cell;
 * - **value**, which may itself be null (a sum over no orders) - the
 *   property's own empty, drawn the way the table draws any empty.
 */
import type { DerivedValuesPage } from "./types";

export type DerivedCell =
  | { state: "pending" }
  | { state: "error"; reason: string }
  | { state: "value"; value: unknown };

/** The derived properties among the columns a table is showing, in column
 * order: the names the page's read asks for. */
export function derivedNames(
  properties: readonly { api_name: string; derivation?: unknown }[],
): string[] {
  return properties.filter((p) => !!p.derivation).map((p) => p.api_name);
}

/** One cell. A row the answer does not mention is one the server could not
 * see any more (deleted since the table drew it), which has no value. */
export function derivedCell(
  page: DerivedValuesPage | undefined,
  key: string,
  name: string,
): DerivedCell {
  if (!page) return { state: "pending" };
  const reason = page.errors[name];
  if (reason) return { state: "error", reason };
  const row = page.rows.find((r) => r.primary_key === key);
  return { state: "value", value: row?.values[name] ?? null };
}

/** A value with no property row to format it by - a module's linked column
 * (§605) - as the cell shows it: a collection as a list, a number in the
 * reader's locale, and nothing as nothing (`null`, for the table's own empty
 * text). */
export function plainValue(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (Array.isArray(value)) {
    return value.length ? value.map((v) => plainValue(v) ?? "").join(", ") : null;
  }
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}
