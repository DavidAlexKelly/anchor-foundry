/**
 * A Pivot Table drawn from a function (Workshop p.335-340; §774; decision 0018
 * option B).
 *
 * > "A function-backed pivot table derives its data from the output of a
 * > function." (p.335) "After selecting a function in the dropdown, builders
 * > can choose: Group-by fields … Value fields" (p.336)
 *
 * The function's output is a table: one row per data point, its grouping
 * fields and its values. p.335's "array of structs" with a `values` struct is
 * that table with the value columns named by the builder rather than nested.
 *
 * **Totals are rows with grouping fields left out** (p.338): with every
 * column field NULL a row total, with every row field NULL a column total,
 * and with all of them NULL the grand total. SQL's `GROUP BY ROLLUP` and
 * `GROUPING SETS` give exactly these rows. p.339's null bucket, "undefined"
 * as against omitted, has no SQL spelling: SQL has one NULL where TypeScript
 * has two, and it is the total's here. A null bucket is a value the query
 * names, such as `coalesce(part, 'Unknown')`.
 */

import type { FunctionResult } from "@/lib/types";

export interface PivotFields {
  /** Grouping fields down the side, outermost first. */
  rows: string[];
  /** The grouping field across the top, or none for a one-way pivot. */
  column: string | null;
  /** The value fields each cell shows. */
  values: string[];
}

export type PivotValues = Record<string, unknown>;

export interface FunctionPivot {
  /** Each row's grouping values, in the order they first came. */
  rowKeys: string[][];
  /** The column field's values, in the order they first came. */
  columnKeys: string[];
  cells: Map<string, PivotValues>;
  rowTotals: Map<string, PivotValues>;
  columnTotals: Map<string, PivotValues>;
  grand: PivotValues | null;
  /** Rows with only some of their row fields: a subtotal the grid has no
   * line for (p.340's expandable rows are not built). */
  unplaced: number;
}

/** Fields from a comma-separated setting, as the other pivot settings are kept. */
export function fieldsOf(raw: string | null | undefined): string[] {
  return (raw ?? "").split(",").map((f) => f.trim()).filter(Boolean);
}

export function cellKey(row: readonly string[], column: string): string {
  return JSON.stringify([row, column]);
}

export function rowKey(row: readonly string[]): string {
  return JSON.stringify(row);
}

/** Why the pivot cannot be drawn from this result, or null. */
export function pivotProblem(
  result: FunctionResult | undefined,
  fields: PivotFields,
): string | null {
  if (!result) return null;
  if (result.kind !== "table") {
    return `The function returns ${result.kind}; a pivot table reads a table (Workshop p.335).`;
  }
  if (fields.rows.length === 0 && !fields.column) return "Choose a field to group by.";
  if (fields.values.length === 0) return "Choose a value field.";
  const names = new Set((result.columns ?? []).map((c) => c.name));
  const missing = [...fields.rows, ...(fields.column ? [fields.column] : []), ...fields.values]
    .find((f) => !names.has(f));
  return missing ? `The function gives no field ${missing}.` : null;
}

/** The grid: each data point placed by its grouping fields (module note). */
export function pivotFrom(result: FunctionResult, fields: PivotFields): FunctionPivot {
  const index = new Map((result.columns ?? []).map((c, i) => [c.name, i]));
  const at = (row: unknown[], name: string) => row[index.get(name)!];
  const label = (v: unknown) => (v == null ? null : String(v));
  const out: FunctionPivot = {
    rowKeys: [], columnKeys: [], cells: new Map(), rowTotals: new Map(),
    columnTotals: new Map(), grand: null, unplaced: 0,
  };
  const seenRows = new Set<string>();
  const seenColumns = new Set<string>();
  for (const row of result.rows ?? []) {
    const groups = fields.rows.map((f) => label(at(row, f)));
    const column = fields.column ? label(at(row, fields.column)) : "";
    const values: PivotValues = {};
    for (const v of fields.values) values[v] = at(row, v);
    const given = groups.filter((g) => g !== null).length;
    if (given !== 0 && given !== groups.length) {
      out.unplaced += 1;
      continue;
    }
    const placed = given === groups.length && groups.length > 0;
    if (!placed && column === null) {
      out.grand = values;
    } else if (!placed) {
      if (fields.rows.length === 0) {
        // A one-way pivot across the top: its single line is its cells.
        remember(out.columnKeys, seenColumns, column!);
        out.cells.set(cellKey([], column!), values);
      } else {
        remember(out.columnKeys, seenColumns, column!);
        out.columnTotals.set(column!, values);
      }
    } else {
      const key = groups as string[];
      if (!seenRows.has(rowKey(key))) {
        seenRows.add(rowKey(key));
        out.rowKeys.push(key);
      }
      if (column === null) {
        out.rowTotals.set(rowKey(key), values);
      } else {
        remember(out.columnKeys, seenColumns, column);
        out.cells.set(cellKey(key, column), values);
      }
    }
  }
  if (fields.rows.length === 0 && out.columnKeys.length > 0) out.rowKeys = [[]];
  return out;
}

function remember(list: string[], seen: Set<string>, value: string): void {
  if (seen.has(value)) return;
  seen.add(value);
  list.push(value);
}

/** One value as a cell shows it: a number as the locale writes it. */
export function shown(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}
