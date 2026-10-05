/**
 * Sorting an Object Table by a derived column (Workshop p.173; §781).
 *
 * > "When sorting object sets that use derived properties, the object set size
 * > is limited to 200 rows. For larger object sets that require sorting,
 * > consider expressing the derived property logic as a function-backed column
 * > instead, which supports sorting up to 1,000 rows." (p.173)
 *
 * A derived column has no value in the store, so the store cannot order by it.
 * The table reads the whole set instead - up to p.173's limit - computes the
 * column for every row as the export does (`derived-export.ts`), and orders the
 * rows here. The server still orders by the table's other sorts first, so they
 * break ties as a second sort would.
 */

import type { DerivedColumn } from "./derived-columns";
import type { Entry } from "./property-sort";

/** p.173's two limits. */
export const DERIVED_SORT_LIMIT = 200;
export const FUNCTION_SORT_LIMIT = 1000;

export function derivedSortLimit(column: DerivedColumn): number {
  return column.kind === "function" ? FUNCTION_SORT_LIMIT : DERIVED_SORT_LIMIT;
}

/** The first sort naming a derived column, and the sorts the server takes.
 * A later sort naming a derived column is dropped: the rows are ordered here
 * by one, and a second would need every row's value for it too. */
export function splitSorts(
  entries: readonly Entry[],
  derived: readonly string[],
): { derived: Entry | null; server: Entry[] } {
  const names = new Set(derived);
  // A fixed sort's property is "", which no column is named.
  const named = entries.filter((e) => names.has(e.property));
  return {
    derived: named[0] ?? null,
    server: entries.filter((e) => !names.has(e.property)),
  };
}

/** Two values as a sort compares them: numbers as numbers, text as a person
 * reads it ("Site 2" before "Site 10"), and nothing after everything, either
 * way round - an empty value says nothing about where it belongs. */
function compare(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true });
}

/** The rows in the column's order. Stable, so the server's order of what ties
 * is kept. */
export function sortRowsBy<T extends { primary_key: string }>(
  rows: readonly T[],
  values: Map<string, Record<string, unknown>>,
  name: string,
  descending: boolean,
): T[] {
  const value = (row: T) => values.get(row.primary_key)?.[name];
  const empty = (v: unknown) => v === null || v === undefined || v === "";
  return rows
    .map((row) => ({ row, v: value(row) }))
    .sort((x, y) => {
      if (empty(x.v) || empty(y.v)) return empty(x.v) && empty(y.v) ? 0 : empty(x.v) ? 1 : -1;
      const order = compare(x.v, y.v);
      return descending ? -order : order;
    })
    .map((x) => x.row);
}

/** Every row of a set up to `limit`, a page at a time, or how many it holds
 * when that is more. A short page ends the read: the set shrank. */
export async function readUpTo<T>(
  fetchPage: (offset: number, limit: number) => Promise<{ rows: readonly T[]; total: number }>,
  limit: number,
  pageSize = 200,
): Promise<{ rows: T[] } | { tooMany: number }> {
  const first = await fetchPage(0, pageSize);
  if (first.total > limit) return { tooMany: first.total };
  const rows = [...first.rows];
  while (rows.length < first.total) {
    const next = await fetchPage(rows.length, pageSize);
    if (next.rows.length === 0) break;
    rows.push(...next.rows);
  }
  return { rows };
}
