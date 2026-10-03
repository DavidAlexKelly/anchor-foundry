/**
 * An Object Table's derived columns in its CSV export (Workshop p.223; §778).
 *
 * > "Enable export to CSV: … This feature supports exporting function-backed
 * > columns and linked object properties and is capable of exporting up to
 * > 10,000 rows at a time." (p.223)
 *
 * The export reads every row of the set, not the page the table shows, so each
 * derived column is computed again for all of them: ontology derived
 * properties and the module's linked columns from the derived-values read, a
 * page of keys at a time as the table reads them; column math from those and
 * the row's own values; and a function column with every key as its runtime
 * input, one call per function, version and inputs, as the table shares one.
 */

import type { DerivedValuesPage, FunctionResult } from "@/lib/types";
import {
  valueFor, type ColumnMathColumn, type DerivedColumn, type FunctionColumn,
} from "./derived-columns";
import { callKey, cellOf } from "./function-columns";
import type { ExportRow } from "./object-export";

/** The derived-values read's own limit (`MAX_DERIVED_KEYS`). */
export const DERIVED_KEYS_PER_READ = 200;

export interface DeriveForExport {
  /** The derived-values read for these keys: the type's derived properties
   * and the module's linked columns the shown columns need. Absent when no
   * shown column needs one. */
  readDerived?: (keys: string[]) => Promise<DerivedValuesPage>;
  /** A function column's call with these keys as its runtime input. */
  callFunction: (column: FunctionColumn, keys: string[]) => Promise<FunctionResult>;
}

/** Each row's derived values, by primary key and column name. A value that
 * could not be read is null, as the table's cell is blank. */
export async function derivedForExport(
  rows: readonly ExportRow[],
  columns: readonly DerivedColumn[],
  deps: DeriveForExport,
  /** The type's own derived properties among the columns (§604), which a set
   * read leaves out as it leaves out a linked column. */
  derivedProperties: readonly string[] = [],
): Promise<Map<string, Record<string, unknown>>> {
  const keys = rows.map((r) => r.primary_key);
  const out = new Map<string, Record<string, unknown>>(keys.map((k) => [k, {}]));
  const read: Record<string, Record<string, unknown>> = {};
  const unreadable = new Set<string>();
  if (deps.readDerived) {
    for (let at = 0; at < keys.length; at += DERIVED_KEYS_PER_READ) {
      const page = await deps.readDerived(keys.slice(at, at + DERIVED_KEYS_PER_READ));
      for (const name of Object.keys(page.errors)) unreadable.add(name);
      for (const row of page.rows) read[row.primary_key] = row.values;
    }
  }
  for (const name of derivedProperties) {
    for (const k of keys) {
      out.get(k)![name] = unreadable.has(name) ? null : read[k]?.[name] ?? null;
    }
  }
  const calls = new Map<string, Promise<FunctionResult | null>>();
  for (const column of columns) {
    if (column.kind === "function") {
      const key = callKey(column);
      if (!calls.has(key)) {
        calls.set(key, deps.callFunction(column, keys).catch(() => null));
      }
      const result = await calls.get(key)!;
      for (const k of keys) out.get(k)![column.api_name] = result ? cellOf(result, k, column.field) ?? null : null;
    } else if (column.kind === "linked") {
      for (const k of keys) {
        out.get(k)![column.api_name] = unreadable.has(column.api_name)
          ? null : read[k]?.[column.api_name] ?? null;
      }
    } else {
      for (const row of rows) {
        out.get(row.primary_key)![column.api_name] = valueFor(column as ColumnMathColumn, {
          ...row.properties, ...(read[row.primary_key] ?? {}),
        });
      }
    }
  }
  return out;
}
