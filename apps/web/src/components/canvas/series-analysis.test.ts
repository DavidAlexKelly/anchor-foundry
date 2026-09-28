import { describe, expect, it } from "vitest";

import {
  MAX_EVENT_SETS, withEventStatistics, eventCount, eventSpan, eventsOf, liveEventSets, withEventSet,
  DEFAULT_BANDS, MAX_COMBINED, MAX_DEVIATIONS, bandsProblem, referenceTo, withBands, withCombined,
  MAX_PLOTS, MAX_ROOTS, PLOT_LABELS, PLOT_TYPES, canvasesOf, chainOf, extentOf, pathOf, readingsOf, rootOf, rootPlots,
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

describe("p.393's Combine time series (§650)", () => {
  it("reads a plot as its root's raw series through its whole chain", () => {
    const once = withDerived(roots, "root:i2", [cumulative], 1);
    expect(referenceTo(once, "plot-3", [derivative])).toEqual({
      object_type_id: "t1", instance_id: "i2", property: "pressure", interval: "none",
      aggregate: "avg", transforms: [cumulative, derivative] });
    expect(referenceTo(once, "gone")).toBeNull();
  });

  it("combines a plot with others as inputs, named for them", () => {
    const next = withCombined(roots, "root:i1", ["root:i2"], "max", 2);
    const made = next[2]!;
    expect(made).toMatchObject({ id: "plot-3", label: "Pump 1 combined with Pump 2", canvas: 2,
      parent: "root:i1" });
    expect(made.transforms).toEqual([{ kind: "combine", aggregate: "max", inputs: {
      y: referenceTo(roots, "root:i2") } }]);
  });

  it("leaves the plot itself out, takes at most four, and needs one", () => {
    let many = roots;
    for (let n = 0; n < 5; n++) many = withDerived(many, "root:i2", [cumulative], 1);
    const others = many.slice(1).map((p) => p.id);
    const made = withCombined(many, "root:i1", ["root:i1", ...others], "sum", 1).at(-1)!;
    expect(Object.keys((made.transforms[0] as { inputs: object }).inputs)).toEqual(["y", "z", "a", "b"]);
    expect(MAX_COMBINED).toBe(4);
    expect(withCombined(roots, "root:i1", [], "sum", 1)).toEqual(roots);
    expect(withCombined(roots, "root:i1", ["root:i1"], "sum", 1)).toEqual(roots);
    expect(withCombined(roots, "root:i1", ["gone"], "sum", 1)).toEqual(roots);
    expect(withCombined(roots, "gone", ["root:i2"], "sum", 1)).toEqual(roots);
  });

  it("makes p.393's Linear aggregation the same way (§653)", () => {
    const made = withCombined(roots, "root:i1", ["root:i2"], "sum", 1, "linear_aggregate")[2]!;
    expect(made.label).toBe("Linear aggregation of Pump 1 with Pump 2");
    expect(made.transforms).toEqual([{ kind: "linear_aggregate", aggregate: "sum", inputs: {
      y: referenceTo(roots, "root:i2") } }]);
    expect(PLOT_LABELS.linear_aggregate).toBe("Linear aggregation");
    expect(PLOT_TYPES).toContain("linear_aggregate");
  });
});

describe("p.392's Time series search (§651)", () => {
  it("adds an event set searching a plot, named for what it asks", () => {
    const sets = withEventSet([], roots, "root:i1", "gte", 20);
    expect(sets).toEqual([{ id: "events-1", label: "Pump 1 at least 20", plot: "root:i1", op: "gte",
      value: 20, highlight: true }]);
    expect(withEventSet(sets, roots, "root:i2", "lt", -1.5)[1]!.label).toBe("Pump 2 below -1.5");
    expect(withEventSet([], roots, "gone", "gt", 1)).toEqual([]);
    expect(withEventSet([], roots, "root:i1", "gt", Number.NaN)).toEqual([]);
  });

  it("names a new set so no two share an id, and stops at the cap", () => {
    const taken = [{ ...withEventSet([], roots, "root:i1", "gt", 1)[0]!, id: "events-2" }];
    expect(withEventSet(taken, roots, "root:i1", "gt", 2)[1]!.id).toBe("events-3");
    let sets = withEventSet([], roots, "root:i1", "gt", 0);
    while (sets.length < MAX_EVENT_SETS) sets = withEventSet(sets, roots, "root:i1", "gt", sets.length);
    expect(withEventSet(sets, roots, "root:i1", "gt", 99)).toHaveLength(MAX_EVENT_SETS);
  });

  it("drops a search whose plot is gone", () => {
    const derived = withDerived(roots, "root:i1", [cumulative], 1);
    const sets = withEventSet(withEventSet([], derived, "plot-3", "gt", 1), derived, "root:i2", "gt", 1);
    expect(liveEventSets(sets, withoutPlot(derived, "plot-3")).map((e) => e.plot)).toEqual(["root:i2"]);
  });

  it("reads events as times and counts those in the view", () => {
    const events = eventsOf([
      { start: "2026-01-02T00:00:00Z", end: "2026-01-03T00:00:00Z" },
      { start: "2026-01-05T00:00:00Z", end: "2026-01-05T00:00:00Z" },
      { start: "no", end: "2026-01-06T00:00:00Z" },
      { start: 7, end: "2026-01-06T00:00:00Z" },
    ]);
    expect(events).toHaveLength(2);
    expect(eventCount(events)).toBe(2);
    const view = { from: Date.parse("2026-01-03T00:00:00Z"), to: Date.parse("2026-01-04T00:00:00Z") };
    expect(eventCount(events, view)).toBe(1);
    expect(eventCount(events, { from: 0, to: 1 })).toBe(0);
  });

  it("shades an event across the frame, a one-reading event visibly", () => {
    const extent = { t0: 0, t1: 100 };
    expect(eventSpan({ start: 10, end: 30 }, extent, 200)).toEqual({ x: 20, width: 40 });
    expect(eventSpan({ start: 50, end: 50 }, extent, 200)).toEqual({ x: 100, width: 2 });
    expect(eventSpan({ start: 100, end: 100 }, extent, 200)).toEqual({ x: 198, width: 2 });
    expect(eventSpan({ start: -50, end: 10 }, extent, 200)).toEqual({ x: 0, width: 20 });
    expect(eventSpan({ start: 150, end: 160 }, extent, 200)).toBeNull();
    expect(eventSpan({ start: -20, end: -10 }, extent, 200)).toBeNull();
  });
});

describe("p.393's Event statistics (§652)", () => {
  it("aggregates a plot over the events of an event set, searched through its plot's chain", () => {
    const derived = withDerived(roots, "root:i2", [cumulative], 1);
    const [set] = withEventSet([], derived, "plot-3", "gte", 20);
    const next = withEventStatistics(derived, "root:i1", set, "max", 2);
    const made = next.at(-1)!;
    expect(made).toMatchObject({ id: "plot-4", parent: "root:i1", canvas: 2,
      label: "max of Pump 1 per event of Cumulative aggregate of Pump 2 at least 20" });
    expect(made.transforms).toEqual([{ kind: "event_statistics", aggregate: "max", op: "gte", value: 20,
      inputs: { e: referenceTo(derived, "plot-3") } }]);
  });

  it("needs the set, its plot and the parent", () => {
    const [set] = withEventSet([], roots, "root:i2", "gt", 1);
    expect(withEventStatistics(roots, "root:i1", undefined, "avg", 1)).toEqual(roots);
    expect(withEventStatistics(roots, "gone", set, "avg", 1)).toEqual(roots);
    expect(withEventStatistics(roots, "root:i1", { ...set!, plot: "gone" }, "avg", 1)).toEqual(roots);
  });
});
