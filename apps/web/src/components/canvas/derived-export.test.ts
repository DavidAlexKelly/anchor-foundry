/** An Object Table's derived columns in its CSV export (Workshop p.223; §778). */
import { describe, expect, it, vi } from "vitest";

import { DERIVED_KEYS_PER_READ, derivedForExport } from "./derived-export";
import type { DerivedColumn, FunctionColumn } from "./derived-columns";
import type { ExportRow } from "./object-export";
import type { DerivedValuesPage, FunctionResult } from "@/lib/types";

const rows: ExportRow[] = [
  { primary_key: "S1", properties: { capacity: 10 } },
  { primary_key: "S2", properties: { capacity: 30 } },
];

function fnColumn(over: Partial<FunctionColumn> = {}): FunctionColumn {
  return { api_name: "level", kind: "function", function_id: "f", version: null,
    objects_parameter: "shown", field: "level", inputs: { cutoff: { value: 20 } }, ...over };
}

function mapResult(entries: Record<string, Record<string, unknown>>): FunctionResult {
  return { kind: "map", version: "1.0.0", columns: [{ name: "level", data_type: "VARCHAR" }],
    entries };
}

describe("a function-backed column (p.223)", () => {
  it("is one call with every key, shared by the columns of one call", async () => {
    const callFunction = vi.fn(async (_c: FunctionColumn, keys: string[]) => mapResult(
      Object.fromEntries(keys.map((k) => [k, { level: `L-${k}`, doubled: k.length }]))));
    const got = await derivedForExport(rows, [
      fnColumn(), fnColumn({ api_name: "twice", field: "doubled" })], { callFunction });
    expect(callFunction).toHaveBeenCalledTimes(1);
    expect(callFunction.mock.calls[0]?.[1]).toEqual(["S1", "S2"]);
    expect(got.get("S1")).toEqual({ level: "L-S1", twice: 2 });
    expect(got.get("S2")).toEqual({ level: "L-S2", twice: 2 });
  });

  it("is blank, not an error, when the call fails or has nothing for a row", async () => {
    const failing = await derivedForExport(rows, [fnColumn()], {
      callFunction: async () => { throw new Error("no"); } });
    expect(failing.get("S1")).toEqual({ level: null });
    const partial = await derivedForExport(rows, [fnColumn()], {
      callFunction: async () => mapResult({ S1: { level: "x" } }) });
    expect(partial.get("S2")).toEqual({ level: null });
  });
});

describe("linked columns, derived properties and column math", () => {
  const linked: DerivedColumn = { api_name: "parts", kind: "linked", derivation: null };
  const math: DerivedColumn = { api_name: "spare", kind: "column_math",
    expression: "capacity - parts" };

  it("reads a page of keys at a time and computes math over them", async () => {
    // The server's `MAX_DERIVED_KEYS`: a page over it is refused.
    expect(DERIVED_KEYS_PER_READ).toBe(200);
    const many: ExportRow[] = Array.from({ length: DERIVED_KEYS_PER_READ + 1 }, (_, i) => ({
      primary_key: `K${i}`, properties: { capacity: i } }));
    const readDerived = vi.fn(async (keys: string[]): Promise<DerivedValuesPage> => ({
      rows: keys.map((k) => ({ primary_key: k, values: { parts: 1, rating: 5 } })), errors: {} }));
    const got = await derivedForExport(many, [linked, math],
      { readDerived, callFunction: vi.fn() }, ["rating"]);
    expect(readDerived.mock.calls.map((c) => c[0].length)).toEqual([DERIVED_KEYS_PER_READ, 1]);
    expect(got.get("K3")).toEqual({ rating: 5, parts: 1, spare: 2 });
    expect(got.get(`K${DERIVED_KEYS_PER_READ}`)?.spare).toBe(DERIVED_KEYS_PER_READ - 1);
  });

  it("leaves blank what the read could not answer", async () => {
    const got = await derivedForExport(rows, [linked], {
      readDerived: async (keys) => ({
        rows: keys.map((k) => ({ primary_key: k, values: { parts: 9, rating: 1 } })),
        errors: { parts: "too far", rating: "no" } }),
      callFunction: vi.fn() }, ["rating"]);
    expect(got.get("S1")).toEqual({ rating: null, parts: null });
  });

  it("reads nothing without a reader, and math uses the row alone", async () => {
    const got = await derivedForExport(rows, [{ api_name: "half", kind: "column_math",
      expression: "capacity / 2" }], { callFunction: vi.fn() });
    expect(got.get("S2")).toEqual({ half: 15 });
    expect((await derivedForExport([], [linked], {
      readDerived: async () => { throw new Error("read"); }, callFunction: vi.fn() })).size)
      .toBe(0);
  });
});
