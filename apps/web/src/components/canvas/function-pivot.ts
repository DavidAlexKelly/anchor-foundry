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
 *
 * **Expandable rows are the same rows, one field deeper** (p.340-341): "Add
 * row fields to the Expandable rows section … Structure your data to support
 * different levels of expansion." A point that names its row fields and the
 * first k expandable fields is a line k levels down, under the line naming
 * one fewer; a line's own values are its subtotal. `GROUP BY ROLLUP(region,
 * product_type, product_name)` gives every level at once.
 */

import type { FunctionResult } from "@/lib/types";

export interface PivotFields {
  /** Grouping fields down the side, outermost first. */
  rows: string[];
  /** The grouping field across the top, or none for a one-way pivot. */
  column: string | null;
  /** The value fields each cell shows. */
  values: string[];
  /** p.340's expandable rows: fields a line opens into, outermost first. */
  expandable?: string[];
}

export type PivotValues = Record<string, unknown>;

export interface FunctionPivot {
  /** Each line's grouping values, in the order they first came, with each
   * expanded line under the line it opens from. A line `d` levels down has
   * its row fields and the first `d` expandable fields. */
  rowKeys: string[][];
  /** The lines that open into others, by `rowKey`. */
  parents: Set<string>;
  /** The column field's values, in the order they first came. */
  columnKeys: string[];
  cells: Map<string, PivotValues>;
  rowTotals: Map<string, PivotValues>;
  columnTotals: Map<string, PivotValues>;
  grand: PivotValues | null;
  /** Points the grid has no line for: some of the row fields but not all, or
   * an expandable field without the one it opens from. */
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
  const expandable = fields.expandable ?? [];
  if (expandable.length > 0 && fields.rows.length === 0) {
    return "Expandable rows open from a row field; choose one (Workshop p.340).";
  }
  const names = new Set((result.columns ?? []).map((c) => c.name));
  const missing = [...fields.rows, ...expandable, ...(fields.column ? [fields.column] : []),
                   ...fields.values].find((f) => !names.has(f));
  return missing ? `The function gives no field ${missing}.` : null;
}

/** The grid: each data point placed by its grouping fields (module note). */
export function pivotFrom(result: FunctionResult, fields: PivotFields): FunctionPivot {
  const index = new Map((result.columns ?? []).map((c, i) => [c.name, i]));
  const at = (row: unknown[], name: string) => row[index.get(name)!];
  const label = (v: unknown) => (v == null ? null : String(v));
  const out: FunctionPivot = {
    rowKeys: [], parents: new Set(), columnKeys: [], cells: new Map(), rowTotals: new Map(),
    columnTotals: new Map(), grand: null, unplaced: 0,
  };
  const expandable = fields.expandable ?? [];
  const seenRows = new Set<string>();
  const seenColumns = new Set<string>();
  for (const row of result.rows ?? []) {
    const groups = fields.rows.map((f) => label(at(row, f)));
    const column = fields.column ? label(at(row, fields.column)) : "";
    const values: PivotValues = {};
    for (const v of fields.values) values[v] = at(row, v);
    const given = groups.filter((g) => g !== null).length;
    const deeper = expandable.map((f) => label(at(row, f)));
    const depth = deeper.indexOf(null) === -1 ? deeper.length : deeper.indexOf(null);
    if ((given !== 0 && given !== groups.length)
        || deeper.slice(depth).some((d) => d !== null) || (given === 0 && depth > 0)) {
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
      const key = [...groups, ...deeper.slice(0, depth)] as string[];
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
  else if (expandable.length > 0) treeOrder(out, fields.rows.length);
  return out;
}

/** Each line under the line it opens from, in the order the lines came. A
 * line whose parent the function did not return still opens from one: the
 * parent is drawn, with no values of its own. */
function treeOrder(out: FunctionPivot, top: number): void {
  const roots: string[][] = [];
  const children = new Map<string, string[][]>();
  const seen = new Set<string>();
  for (const key of out.rowKeys) {
    for (let n = top; n <= key.length; n++) {
      const line = key.slice(0, n);
      if (seen.has(rowKey(line))) continue;
      seen.add(rowKey(line));
      if (n === top) {
        roots.push(line);
      } else {
        const parent = rowKey(key.slice(0, n - 1));
        out.parents.add(parent);
        children.set(parent, [...(children.get(parent) ?? []), line]);
      }
    }
  }
  const ordered: string[][] = [];
  const walk = (line: string[]) => {
    ordered.push(line);
    for (const child of children.get(rowKey(line)) ?? []) walk(child);
  };
  roots.forEach(walk);
  out.rowKeys = ordered;
}

/** The lines shown: every top line, and a deeper one only when each line it
 * opens from is open. */
export function visibleRows(
  grid: FunctionPivot,
  top: number,
  open: ReadonlySet<string>,
): string[][] {
  return grid.rowKeys.filter((key) => {
    for (let n = top; n < key.length; n++) {
      if (!open.has(rowKey(key.slice(0, n)))) return false;
    }
    return true;
  });
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
