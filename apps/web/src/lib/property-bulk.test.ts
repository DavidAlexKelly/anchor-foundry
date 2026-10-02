import { describe, expect, it } from "vitest";

import { bulkApply, classesIn, sharedDataType, toggled } from "./property-bulk";

/** p.91's bulk edit (§672). */

const ROWS = [
  { api_name: "a", data_type: "string" as const, visibility: "normal" as const, type_classes: ["x:1"],
    value_format: null },
  { api_name: "b", data_type: "array" as const, array_of: "string" as const, type_classes: ["x:1", "y:2"] },
  { api_name: "c", data_type: "integer" as const, shared_property_id: "sp", visibility: "normal" as const },
  { api_name: "d", data_type: "string" as const },
];
const ALL = new Set([0, 1, 2]);

describe("bulkApply", () => {
  it("changes the base type of each selected row, its element type with it", () => {
    const { rows, skipped } = bulkApply(ROWS, new Set([0, 1]), { kind: "data_type", value: "array" });
    expect(rows.map((r) => [r.data_type, r.array_of ?? null])).toEqual([
      ["array", "string"], ["array", "string"], ["integer", null], ["string", null]]);
    expect(skipped).toBe(0);
    const back = bulkApply(ROWS, new Set([1]), { kind: "data_type", value: "integer" }).rows[1]!;
    expect([back.data_type, back.array_of]).toEqual(["integer", null]);
  });

  it("leaves a shared property's inherited settings, and counts it", () => {
    for (const change of [
      { kind: "data_type", value: "float" }, { kind: "visibility", value: "hidden" },
      { kind: "value_format", value: null },
    ] as const) {
      const { rows, skipped } = bulkApply(ROWS, ALL, change);
      expect(rows[2]).toBe(ROWS[2]);
      expect(skipped).toBe(1);
    }
    expect(bulkApply(ROWS, ALL, { kind: "visibility", value: "hidden" }).rows.map((r) => r.visibility))
      .toEqual(["hidden", "hidden", "normal", undefined]);
  });

  it("adds a type class once and removes it, a shared property's too", () => {
    const added = bulkApply(ROWS, ALL, { kind: "add_class", value: "y:2" });
    expect(added.rows.map((r) => r.type_classes)).toEqual([["x:1", "y:2"], ["x:1", "y:2"], ["y:2"], undefined]);
    expect(added.rows[1]).toBe(ROWS[1]);
    expect(added.skipped).toBe(0);
    const removed = bulkApply(ROWS, ALL, { kind: "remove_class", value: "x:1" });
    expect(removed.rows.map((r) => r.type_classes)).toEqual([[], ["y:2"], [], undefined]);
  });

  it("sets or clears the formatting of each selected row", () => {
    const format = { kind: "number", style: "plain" } as never;
    const { rows } = bulkApply(ROWS, new Set([0, 3]), { kind: "value_format", value: format });
    expect(rows.map((r) => (r as { value_format?: unknown }).value_format ?? null))
      .toEqual([format, null, null, format]);
    // Rows not selected are the same objects.
    expect(rows[1]).toBe(ROWS[1]);
  });
});

describe("the selection", () => {
  it("offers the classes the selected rows have, and the base type they share", () => {
    expect(classesIn(ROWS, new Set([1, 0]))).toEqual(["x:1", "y:2"]);
    expect(classesIn(ROWS, new Set([3]))).toEqual([]);
    expect(sharedDataType(ROWS, new Set([0, 3]))).toBe("string");
    expect(sharedDataType(ROWS, new Set([0, 2]))).toBeNull();
    expect(toggled(new Set([1]), 2)).toEqual(new Set([1, 2]));
    expect(toggled(new Set([1, 2]), 2)).toEqual(new Set([1]));
  });
});
