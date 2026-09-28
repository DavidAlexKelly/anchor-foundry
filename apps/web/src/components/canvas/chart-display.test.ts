import { describe, expect, it } from "vitest";

import {
  axisProblem, axisTitlesOf, chartSortOf, defaultValueTitle, orientationOf, sortPoints,
  valueAxisOf, valueScale, type ValueAxis,
} from "./chart-display";

const points = [
  { label: "Site 10", value: 3 },
  { label: "site 2", value: 7 },
  { label: "Site 1", value: 3 },
];

describe("sortPoints (p.283's Sort by)", () => {
  it("keeps the data's order unless told otherwise", () => {
    expect(sortPoints(points, "source")).toEqual(points);
    expect(chartSortOf(undefined)).toBe("source");
    expect(chartSortOf("sideways")).toBe("source");
    expect(chartSortOf("keyDesc")).toBe("keyDesc");
  });

  it("orders keys as a person reads them, whatever their case", () => {
    expect(sortPoints(points, "keyAsc").map((p) => p.label)).toEqual(["Site 1", "site 2", "Site 10"]);
    expect(sortPoints(points, "keyDesc").map((p) => p.label)).toEqual(["Site 10", "site 2", "Site 1"]);
  });

  it("orders by value, with a tie falling back to the key", () => {
    expect(sortPoints(points, "valueDesc").map((p) => p.label)).toEqual(["site 2", "Site 1", "Site 10"]);
    expect(sortPoints(points, "valueAsc").map((p) => p.label)).toEqual(["Site 1", "Site 10", "site 2"]);
  });

  it("does not reorder what it was given", () => {
    const copy = [...points];
    sortPoints(points, "keyAsc");
    expect(points).toEqual(copy);
  });
});

describe("orientationOf (p.284)", () => {
  it("is horizontal only for a bar chart that asks", () => {
    expect(orientationOf("horizontal", "bar")).toBe("horizontal");
    expect(orientationOf("horizontal", "line")).toBe("vertical");
    expect(orientationOf("horizontal", "scatter")).toBe("vertical");
    expect(orientationOf(undefined, "bar")).toBe("vertical");
  });
});

const linear: ValueAxis = { scale: "linear", min: null, max: null };
const log: ValueAxis = { scale: "log", min: null, max: null };

describe("valueAxisOf (p.283's Scale type and bounds)", () => {
  it("is linear and calculated unless set", () => {
    expect(valueAxisOf({})).toEqual(linear);
    expect(valueAxisOf({ scaleType: "sideways", minBound: "3", maxBound: Infinity })).toEqual(linear);
    expect(valueAxisOf({ scaleType: "log", minBound: 0.5, maxBound: 900 }))
      .toEqual({ scale: "log", min: 0.5, max: 900 });
  });
});

describe("axisProblem", () => {
  it("refuses a backwards axis and a logarithm of zero", () => {
    expect(axisProblem({ ...linear, min: 5, max: 5 })).toMatch(/below the maximum/);
    expect(axisProblem({ ...linear, min: -5, max: 5 })).toBeNull();
    expect(axisProblem({ ...linear, min: -5 })).toBeNull();
    expect(axisProblem({ ...log, min: 0 })).toMatch(/above 0/);
    expect(axisProblem({ ...log, max: -1 })).toMatch(/above 0/);
    expect(axisProblem({ ...log, min: 0.1, max: 10 })).toBeNull();
    expect(axisProblem(log)).toBeNull();
  });
});

describe("valueScale", () => {
  it("draws a calculated linear axis as before: from zero, five ticks", () => {
    const s = valueScale([10, 30, 40], linear);
    expect([s.lo, s.hi]).toEqual([0, 40]);
    expect(s.ticks).toEqual([0, 10, 20, 30, 40]);
    expect(s.at(30)).toBe(0.75);
    expect(s.base).toBe(0);
    expect(s.undrawn).toBe(0);
    const negative = valueScale([-10, 30], linear);
    expect([negative.lo, negative.hi]).toEqual([-10, 30]);
    expect(negative.base).toBe(0.25);
    expect(valueScale([], linear).hi).toBe(1);
  });

  it("holds a fixed bound, and starts a bar at the nearer end when zero is off the axis", () => {
    const s = valueScale([10, 30, 40], { ...linear, min: 20 });
    expect([s.lo, s.hi]).toEqual([20, 40]);
    expect(s.base).toBe(0);
    expect(s.at(10)).toBe(-0.5);
    const capped = valueScale([10, 30, 40], { ...linear, max: 20 });
    expect([capped.lo, capped.hi]).toEqual([0, 20]);
    expect(capped.at(40)).toBe(2);
    const below = valueScale([-40, -10], { ...linear, max: -20 });
    expect([below.lo, below.hi]).toEqual([-40, -20]);
    expect(below.base).toBe(1);
  });

  it("widens an axis a single bound would leave empty", () => {
    expect(valueScale([1, 2], { ...linear, min: 5 })).toMatchObject({ lo: 5, hi: 10 });
    expect(valueScale([1, 2], { ...linear, min: 0 })).toMatchObject({ lo: 0, hi: 2 });
    expect(valueScale([0], { ...linear, min: 0 })).toMatchObject({ lo: 0, hi: 1 });
    expect(valueScale([5, 6], { ...linear, max: -4 })).toMatchObject({ lo: -8, hi: -4 });
    expect(valueScale([5, 6], { ...linear, max: 0 })).toMatchObject({ lo: -1, hi: 0 });
  });

  it("ignores bounds that have a problem", () => {
    expect(valueScale([10, 40], { ...linear, min: 50, max: 20 })).toMatchObject({ lo: 0, hi: 40 });
    expect(valueScale([10, 40], { ...log, min: 0, max: 20 })).toMatchObject({ lo: 10, hi: 100 });
  });

  it("runs a logarithmic axis between powers of ten, a tick at each", () => {
    const s = valueScale([3, 40, 700], log);
    expect([s.lo, s.hi]).toEqual([1, 1000]);
    expect(s.ticks).toEqual([1, 10, 100, 1000]);
    expect(s.at(10)).toBeCloseTo(1 / 3);
    expect(s.at(100)).toBeCloseTo(2 / 3);
    expect(s.base).toBe(0);
    const small = valueScale([0.002, 0.5], log);
    expect(small.ticks).toEqual([0.001, 0.01, 0.1, 1]);
    // Exactly a power of ten: the decade below it, so its bar has a height.
    expect(valueScale([100, 100], log)).toMatchObject({ lo: 10, hi: 100 });
    expect(valueScale([], log)).toMatchObject({ lo: 1, hi: 10 });
  });

  it("cannot draw zero or less on a logarithmic axis, and counts what it left out", () => {
    const s = valueScale([0, -3, 50], log);
    expect(s.at(0)).toBeNull();
    expect(s.at(-3)).toBeNull();
    expect(s.undrawn).toBe(2);
    expect([s.lo, s.hi]).toEqual([10, 100]);
  });

  it("keeps a logarithmic axis's fixed bounds as its ends, and thins a long run of ticks", () => {
    const s = valueScale([30], { ...log, min: 5, max: 5000 });
    expect(s.ticks).toEqual([5, 10, 100, 1000, 5000]);
    expect(s.at(5)).toBe(0);
    expect(s.at(5000)).toBe(1);
    expect(valueScale([2], { ...log, min: 50 })).toMatchObject({ lo: 50, hi: 500 });
    expect(valueScale([2000], { ...log, max: 50 })).toMatchObject({ lo: 5, hi: 50 });
    const wide = valueScale([1e-6, 1e9], log);
    expect(wide.ticks.length).toBeLessThanOrEqual(8);
    expect(wide.ticks).toEqual([1e-6, 1e-3, 1, 1e3, 1e6, 1e9]);
  });
});

describe("axis titles (p.283's Show title)", () => {
  it("defaults the value title to the aggregation and what it is of", () => {
    expect(defaultValueTitle("bar", "count", "capacity")).toBe("Count");
    expect(defaultValueTitle("bar", undefined, null)).toBe("Count");
    expect(defaultValueTitle("bar", "sum", "capacity")).toBe("Sum of capacity");
    expect(defaultValueTitle("line", "avg", "temp")).toBe("Average of temp");
    expect(defaultValueTitle("bar", "min", null)).toBe("Minimum of …");
    expect(defaultValueTitle("bar", "max", "x")).toBe("Maximum of x");
    expect(defaultValueTitle("scatter", "sum", "height")).toBe("height");
    expect(defaultValueTitle("line", "last", "temp")).toBe("temp");
  });

  it("shows a title only when asked, its override over its default", () => {
    const defaults = { category: "region", value: "Count" };
    expect(axisTitlesOf({}, defaults)).toEqual({ category: null, value: null });
    expect(axisTitlesOf({ showCategoryTitle: true, showValueTitle: true }, defaults))
      .toEqual(defaults);
    expect(axisTitlesOf({
      showCategoryTitle: true, categoryTitle: " Where ", showValueTitle: "yes", valueTitle: "Sites",
    }, defaults)).toEqual({ category: "Where", value: null });
    expect(axisTitlesOf({ showValueTitle: true, valueTitle: "   " }, defaults).value).toBe("Count");
    expect(axisTitlesOf({ showCategoryTitle: true }, { category: null, value: null }).category)
      .toBeNull();
  });
});
