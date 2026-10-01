import { describe, expect, it } from "vitest";

import {
  DEFAULT_BANDS, MAX_DEVIATIONS, bandsProblem, withBands,
  MAX_PLOTS, MAX_ROOTS, canvasesOf, chainOf, extentOf, pathOf, readingsOf, rootOf, rootPlots,
  statsOf, withDerived, withPlotSetting, withRoots, withoutPlot, type Plot,
} from "./series-analysis";
import type { SeriesTransform } from "./series-transforms";

const pumps = [{ id: "i1", label: "Pump 1" }, { id: "i2", label: "Pump 2" }];
const roots = rootPlots(pumps, "t1", "pressure");
const cumulative: SeriesTransform = { kind: "cumulative", aggregate: "sum" };
const derivative: SeriesTransform = { kind: "derivative", unit: "hour" };

describe("the analysis's plots (§647)", () => {
  it("starts with one root plot per object, on the first canvas", () => {
    expect(roots).toEqual([
      { id: "root:i1", label: "Pump 1", canvas: 1, style: "solid", parent: null, transforms: [],
        root: { objectId: "i1", typeId: "t1", property: "pressure", objectLabel: "Pump 1" } },
      { id: "root:i2", label: "Pump 2", canvas: 1, style: "solid", parent: null, transforms: [],
        root: { objectId: "i2", typeId: "t1", property: "pressure", objectLabel: "Pump 2" } },
    ]);
    const many = Array.from({ length: MAX_ROOTS + 3 }, (_, n) => ({ id: `i${n}`, label: `P${n}` }));
    expect(rootPlots(many, "t1", "p")).toHaveLength(MAX_ROOTS);
  });

  it("derives a plot as its input's chain with one more transform", () => {
    const once = withDerived(roots, "root:i1", [cumulative], 2);
    const derived = once[2]!;
    expect(derived).toMatchObject({ id: "plot-3", label: "Cumulative aggregate of Pump 1",
      canvas: 2, parent: "root:i1", root: null });
    expect(chainOf(once, derived.id)).toEqual([cumulative]);
    const twice = withDerived(once, derived.id, [derivative], 1);
    expect(twice[3]!.label).toBe("Derivative of Cumulative aggregate of Pump 1");
    expect(chainOf(twice, twice[3]!.id)).toEqual([cumulative, derivative]);
    expect(rootOf(twice, twice[3]!.id)?.id).toBe("root:i1");
    expect(chainOf(twice, "root:i2")).toEqual([]);
  });

  it("names a new plot so no two share an id, after a removal too", () => {
    // plot-3 was removed, so three plots are left and the next count is 4.
    const taken: Plot[] = [...roots, { ...roots[0]!, id: "plot-4", root: null, parent: "root:i1",
      transforms: [cumulative] }];
    expect(withDerived(taken, "root:i1", [derivative], 1).at(-1)!.id).toBe("plot-5");
  });

  it("stops at the cap, and ignores a parent that is not there", () => {
    let plots = roots;
    while (plots.length < MAX_PLOTS) plots = withDerived(plots, "root:i1", [cumulative], 1);
    expect(withDerived(plots, "root:i1", [cumulative], 1)).toHaveLength(MAX_PLOTS);
    expect(withDerived(roots, "gone", [cumulative], 1)).toEqual(roots);
    expect(withDerived(roots, "root:i1", [], 1)).toEqual(roots);
    // A chain of several is kept in order, and named for its first.
    const two = withDerived(roots, "root:i1", [derivative, cumulative], 1);
    expect(chainOf(two, "plot-3")).toEqual([derivative, cumulative]);
    expect(two[2]!.label).toBe("Derivative of Pump 1");
  });

  it("removes a plot with everything derived from it, and never a root", () => {
    const once = withDerived(roots, "root:i1", [cumulative], 1);
    const twice = withDerived(once, "plot-3", [derivative], 1);
    const other = withDerived(twice, "root:i2", [derivative], 1);
    expect(withoutPlot(other, "plot-3").map((p) => p.id)).toEqual(["root:i1", "root:i2", "plot-5"]);
    expect(withoutPlot(other, "root:i1")).toEqual(other);
    expect(withoutPlot(other, "nope")).toEqual(other);
  });

  it("follows the object set, keeping what the reader set", () => {
    const styled = withPlotSetting(withDerived(roots, "root:i1", [cumulative], 2), "root:i1", "style", "dashed");
    const moved = withPlotSetting(styled, "root:i1", "canvas", 3);
    // Pump 2 leaves the set and Pump 3 joins it.
    const next = withRoots(moved, rootPlots([pumps[0]!, { id: "i3", label: "Pump 3" }], "t1", "pressure"));
    expect(next.map((p) => p.id)).toEqual(["root:i1", "root:i3", "plot-3"]);
    expect(next[0]).toMatchObject({ style: "dashed", canvas: 3 });
    // A plot derived from a root that left goes with it.
    const fromTwo = withDerived(roots, "root:i2", [cumulative], 1);
    expect(withRoots(fromTwo, rootPlots([pumps[0]!], "t1", "pressure")).map((p) => p.id))
      .toEqual(["root:i1"]);
  });

  it("finds no root for a broken or circular chain", () => {
    const loop: Plot[] = [
      { id: "a", label: "a", canvas: 1, style: "solid", root: null, parent: "b", transforms: [cumulative] },
      { id: "b", label: "b", canvas: 1, style: "solid", root: null, parent: "a", transforms: [derivative] },
    ];
    expect(rootOf(loop, "a")).toBeNull();
    expect(chainOf(loop, "a")).toEqual([derivative, cumulative]);
    expect(rootOf([{ ...loop[0]!, parent: null }], "a")).toBeNull();
  });

  it("draws every canvas in use and any added, in order", () => {
    const on3 = withPlotSetting(roots, "root:i2", "canvas", 3);
    expect(canvasesOf(on3, 0)).toEqual([1, 3]);
    expect(canvasesOf(on3, 2)).toEqual([1, 2, 3]);
    expect(canvasesOf(roots, 4)).toEqual([1, 2, 3, 4]);
    expect(canvasesOf([], 0)).toEqual([1]);
  });
});

describe("readings, statistics and the line (§647)", () => {
  const points = [
    { at: "2026-01-01T02:00:00Z", value: 4 },
    { at: "2026-01-01T00:00:00Z", value: "1" },
    { at: "2026-01-01T01:00:00Z", value: null },
    { at: "not a time", value: 9 },
    { at: "2026-01-01T03:00:00Z", value: "" },
    { at: "2026-01-01T04:00:00Z", value: 7 },
  ];
  const readings = readingsOf(points);

  it("keeps readings with a time and a value, in time order", () => {
    expect(readings.map((r) => r.v)).toEqual([1, 4, 7]);
    expect(readings[0]!.t).toBe(Date.parse("2026-01-01T00:00:00Z"));
  });

  it("gives the statistics within the view range", () => {
    expect(statsOf(readings)).toEqual({ min: 1, max: 7, mean: 4, count: 3 });
    const early = { from: Date.parse("2026-01-01T00:00:00Z"), to: Date.parse("2026-01-01T02:00:00Z") };
    expect(statsOf(readings, early)).toEqual({ min: 1, max: 4, mean: 2.5, count: 2 });
    expect(statsOf([])).toBeNull();
    expect(statsOf(readings, { from: 0, to: 1 })).toBeNull();
  });

  it("frames several plots together, padded", () => {
    const e = extentOf([readings, [{ t: readings[0]!.t, v: 13 }]])!;
    expect(e.t0).toBe(readings[0]!.t);
    expect(e.t1).toBe(readings[2]!.t);
    expect(e.v0).toBeCloseTo(1 - 0.6);
    expect(e.v1).toBeCloseTo(13 + 0.6);
    expect(extentOf([[]])).toBeNull();
    // One reading still has a width and a height to draw in.
    const one = extentOf([[{ t: 10, v: 5 }]])!;
    expect([one.t0, one.t1, one.v0, one.v1]).toEqual([9, 11, 4, 6]);
    const zero = extentOf([[{ t: 10, v: 0 }, { t: 20, v: 0 }]])!;
    expect([zero.v0, zero.v1]).toEqual([-1, 1]);
  });

  it("draws the line across the frame", () => {
    const frame = { width: 100, height: 50 };
    expect(pathOf([{ t: 0, v: 0 }, { t: 10, v: 10 }], { t0: 0, t1: 10, v0: 0, v1: 10 }, frame))
      .toBe("M0.0,50.0L100.0,0.0");
    expect(pathOf([], { t0: 0, t1: 1, v0: 0, v1: 1 }, frame)).toBe("");
  });
});

describe("p.393's Bollinger bands (§649)", () => {
  const bands = { window: 2, unit: "day" as const, deviations: 2 };

  it("adds a moving average and a band either side, from the parent's own chain", () => {
    const derived = withDerived(roots, "root:i1", [cumulative], 2);
    const next = withBands(derived, "plot-3", bands, 2);
    const [average, upper, lower] = next.slice(3);
    expect(next).toHaveLength(6);
    expect(average).toMatchObject({ id: "plot-4", label: "Moving average of Cumulative aggregate of Pump 1",
      parent: "plot-3", canvas: 2, style: "solid",
      transforms: [{ kind: "rolling", aggregate: "avg", window: 2, unit: "day" }] });
    expect(upper!.label).toBe("Upper Bollinger band of Cumulative aggregate of Pump 1");
    expect(upper!.style).toBe("dashed");
    expect(lower!.id).toBe("plot-6");
    const formula = upper!.transforms[0] as Extract<SeriesTransform, { kind: "formula" }>;
    expect(formula.expression).toBe("y + 2 * z");
    expect((lower!.transforms[0] as { expression: string }).expression).toBe("y - 2 * z");
    // Each input is the same object's series, through the parent's chain and
    // then the rolling window.
    expect(formula.inputs).toEqual({
      y: { object_type_id: "t1", instance_id: "i1", property: "pressure", interval: "none",
        aggregate: "avg", transforms: [cumulative,
          { kind: "rolling", aggregate: "avg", window: 2, unit: "day" }] },
      z: { object_type_id: "t1", instance_id: "i1", property: "pressure", interval: "none",
        aggregate: "avg", transforms: [cumulative,
          { kind: "rolling", aggregate: "stddev", window: 2, unit: "day" }] },
    });
    expect(chainOf(next, upper!.id)).toEqual([cumulative, formula]);
  });

  it("needs room for all three, a root to read, and numbers that make bands", () => {
    let full = roots;
    while (full.length < MAX_PLOTS - 2) full = withDerived(full, "root:i1", [cumulative], 1);
    expect(withBands(full, "root:i1", bands, 1)).toEqual(full);
    // One fewer, and the three fit exactly.
    expect(withBands(full.slice(0, -1), "root:i1", bands, 1)).toHaveLength(MAX_PLOTS);
    expect(withBands(roots, "gone", bands, 1)).toEqual(roots);
    expect(withBands(roots, "root:i1", { ...bands, deviations: 0 }, 1)).toEqual(roots);
  });

  it("says what is wrong with the numbers", () => {
    expect(bandsProblem(DEFAULT_BANDS)).toBeNull();
    expect(bandsProblem({ ...bands, window: 1.5 })).toMatch(/^The window/);
    expect(bandsProblem({ ...bands, window: 0 })).toMatch(/^The window/);
    expect(bandsProblem({ ...bands, deviations: Number.NaN })).toMatch(/standard deviations/);
    expect(bandsProblem({ ...bands, deviations: MAX_DEVIATIONS + 0.5 })).toMatch(/standard deviations/);
    expect(bandsProblem({ ...bands, deviations: MAX_DEVIATIONS })).toBeNull();
  });
});
