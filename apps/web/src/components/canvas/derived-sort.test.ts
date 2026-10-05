/** Sorting an Object Table by a derived column (Workshop p.173; §781). */
import { describe, expect, it, vi } from "vitest";

import {
  DERIVED_SORT_LIMIT, FUNCTION_SORT_LIMIT, derivedSortLimit, readUpTo, sortRowsBy, splitSorts,
} from "./derived-sort";
import { entryOf } from "./property-sort";
import type { Entry } from "./property-sort";

const e = (raw: string) => entryOf(raw) as Entry;

describe("p.173's limits", () => {
  it("are 200 for a derived column and 1,000 for a function-backed one", () => {
    expect([DERIVED_SORT_LIMIT, FUNCTION_SORT_LIMIT]).toEqual([200, 1000]);
    expect(derivedSortLimit({ api_name: "x", kind: "column_math", expression: "a" })).toBe(200);
    expect(derivedSortLimit({ api_name: "x", kind: "linked", derivation: null })).toBe(200);
    expect(derivedSortLimit({ api_name: "x", kind: "function", function_id: "f", version: null,
      objects_parameter: "s", field: "", inputs: {} })).toBe(1000);
  });
});

describe("which sorts the store takes", () => {
  it("is every sort but the first naming a derived column, and any later one", () => {
    const split = splitSorts([e("region"), e("-level"), e("recent"), e("spare")], ["level", "spare"]);
    expect(split.derived?.key).toBe("-level");
    expect(split.server.map((x) => x.key)).toEqual(["region", "recent"]);
    expect(splitSorts([e("region")], ["level"])).toEqual({ derived: null, server: [e("region")] });
    expect(splitSorts([e("recent")], ["level"]).server.map((x) => x.key)).toEqual(["recent"]);
  });
});

describe("the order", () => {
  const rows = ["A", "B", "C", "D", "E"].map((k) => ({ primary_key: k }));
  const values = new Map<string, Record<string, unknown>>([
    ["A", { v: 10 }], ["B", { v: null }], ["C", { v: 2 }], ["D", { v: 10 }], ["E", {}],
  ]);

  it("is numbers as numbers, ties in the store's order, nothing last either way", () => {
    expect(sortRowsBy(rows, values, "v", false).map((r) => r.primary_key))
      .toEqual(["C", "A", "D", "B", "E"]);
    expect(sortRowsBy(rows, values, "v", true).map((r) => r.primary_key))
      .toEqual(["A", "D", "C", "B", "E"]);
  });

  it("is a number's value, not its digits", () => {
    const signed = new Map<string, Record<string, unknown>>([
      ["A", { v: 1.5 }], ["B", { v: -2 }], ["C", { v: 1.25 }], ["D", { v: -10 }]]);
    expect(sortRowsBy(rows.slice(0, 4), signed, "v", false).map((r) => r.primary_key))
      .toEqual(["D", "B", "C", "A"]);
  });

  it("is text as a person reads it", () => {
    const text = new Map<string, Record<string, unknown>>([
      ["A", { v: "Site 10" }], ["B", { v: "Site 2" }], ["C", { v: "" }]]);
    expect(sortRowsBy(rows.slice(0, 3), text, "v", false).map((r) => r.primary_key))
      .toEqual(["B", "A", "C"]);
  });
});

describe("reading the whole set", () => {
  it("reads page after page up to the limit", async () => {
    const all = Array.from({ length: 5 }, (_, i) => i);
    const fetch = vi.fn(async (at: number, n: number) => ({ rows: all.slice(at, at + n), total: 5 }));
    expect(await readUpTo(fetch, 5, 2)).toEqual({ rows: all });
    expect(fetch.mock.calls.map((c) => c[0])).toEqual([0, 2, 4]);
  });

  it("says how many when there are more than the limit, reading no more", async () => {
    const fetch = vi.fn(async () => ({ rows: [1, 2], total: 6 }));
    expect(await readUpTo(fetch, 5, 2)).toEqual({ tooMany: 6 });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("stops at a short page", async () => {
    const fetch = vi.fn(async (at: number) => ({ rows: at === 0 ? [1, 2] : [], total: 4 }));
    expect(await readUpTo(fetch, 5, 2)).toEqual({ rows: [1, 2] });
  });
});
