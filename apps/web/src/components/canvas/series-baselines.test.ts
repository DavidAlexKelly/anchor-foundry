/** §563: p.592-593's baselines on the Object Table's series columns. */
import { describe, expect, it } from "vitest";

import {
  COLUMN_BASELINE_KINDS, baselineFor, baselinesByColumn, columnBaselineOf, withColumnBaseline,
} from "./series-baselines";

describe("a column's baseline", () => {
  it("offers p.592's three kinds and none", () => {
    expect(Object.keys(COLUMN_BASELINE_KINDS)).toEqual(["none", "static", "property", "series"]);
  });

  it("reads what a document holds, and nothing half-configured", () => {
    expect(columnBaselineOf({ kind: "static", value: 1000 })).toEqual({ kind: "static", value: 1000 });
    expect(columnBaselineOf({ kind: "static", value: "1000" })).toBeNull();
    expect(columnBaselineOf({ kind: "static", value: NaN })).toBeNull();
    expect(columnBaselineOf({ kind: "property", property: "capacity" }))
      .toEqual({ kind: "property", property: "capacity" });
    expect(columnBaselineOf({ kind: "property", property: "" })).toBeNull();
    expect(columnBaselineOf({ kind: "series", summary: "max" })).toEqual({ kind: "series", summary: "max" });
    expect(columnBaselineOf({ kind: "series" })).toEqual({ kind: "series", summary: "last" });
    expect(columnBaselineOf({ kind: "none" })).toBeNull();
    expect(columnBaselineOf(null)).toBeNull();
    expect(columnBaselineOf("static")).toBeNull();
  });

  it("keeps one per column, and none left is null", () => {
    const stat = { kind: "static" as const, value: 5 };
    expect(baselinesByColumn({ a: stat, b: { kind: "static" }, c: 3 })).toEqual({ a: stat });
    expect(baselinesByColumn([stat])).toEqual({ 0: stat });
    expect(baselinesByColumn(null)).toEqual({});
    expect(withColumnBaseline(null, "a", stat)).toEqual({ a: stat });
    expect(withColumnBaseline({ a: stat }, "b", stat)).toEqual({ a: stat, b: stat });
    expect(withColumnBaseline({ a: stat, b: stat }, "a", null)).toEqual({ b: stat });
    expect(withColumnBaseline({ a: stat }, "a", null)).toBeNull();
  });
});

describe("a row's baseline", () => {
  const values = [3, 9, 6];

  it("is the static value for every row", () => {
    expect(baselineFor({ kind: "static", value: 1000 }, {}, values)).toBe(1000);
  });

  it("is the row's own numeric property, and none where it has none", () => {
    const b = { kind: "property" as const, property: "capacity" };
    expect(baselineFor(b, { capacity: 40 }, values)).toBe(40);
    expect(baselineFor(b, { capacity: "12.5" }, values)).toBe(12.5);
    expect(baselineFor(b, { capacity: null }, values)).toBeNull();
    expect(baselineFor(b, { capacity: "" }, values)).toBeNull();
    expect(baselineFor(b, {}, values)).toBeNull();
    expect(baselineFor(b, { capacity: "lots" }, values)).toBeNull();
  });

  it("is the row's series summarised", () => {
    expect(baselineFor({ kind: "series", summary: "last" }, {}, values)).toBe(6);
    expect(baselineFor({ kind: "series", summary: "max" }, {}, values)).toBe(9);
    expect(baselineFor({ kind: "series", summary: "last" }, {}, [])).toBeNull();
  });

  it("is nothing without a baseline", () => {
    expect(baselineFor(null, { capacity: 1 }, values)).toBeNull();
  });
});
