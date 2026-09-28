import { describe, expect, it } from "vitest";

import {
  MAX_EVENT_SETS, withEventStatistics, eventCount, eventSpan, eventsOf, liveEventSets, withEventSet, withLinkedEventSet,
  DEFAULT_DISPLAY, areaOf,
  DEFAULT_AXIS, MAX_AXES, axesOf, axisOf, axisProblem, axisSettingsOf, fractionOf, newAxisOf, valueAt,
  withAxisSetting, shownShape,
  canvasFor, initialEventSetsOf, objectEventsOf, placementOf,
  AXIS_ROOM, COLLAPSED_ROOM, DEFAULT_TOOLTIP, EDGE_ROOM, axisLayout, hoveredOf, readingAt, significant,
  tooltipOptionsOf,
  MIN_VIEW_MS, defaultRangeOf, inView, pannedRange, timeLabel, zoomedRange, displayOf, markerOf, markersOf, outlineOf, pointOptions, withDisplay,
  DEFAULT_BANDS, MAX_COMBINED, MAX_DEVIATIONS, bandsProblem, referenceTo, withBands, withCombined,
  MAX_PLOTS, MAX_ROOTS, PLOT_LABELS, PLOT_TYPES, canvasesOf, chainOf, pathOf, scaleOf, timesOf, readingsOf, rootOf, rootPlots,
  statsOf, withAddedRoot, openedView, savedViewOf, addDataSetsOf, objectLabelOf, MAX_ADD_DATA_SETS, withDerived, withPlotSetting, withRoots, withoutPlot, type Plot,
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

  it("keeps a root's display and axis as the set changes, and takes its new label (§661)", () => {
    const set = withPlotSetting(withDisplay(roots, "root:i1", "width", 3), "root:i1", "axis", 2);
    const next = withRoots(set, rootPlots([{ id: "i1", label: "Pump 1a" }], "t1", "pressure"));
    expect(next[0]).toMatchObject({ label: "Pump 1a", axis: 2, display: { width: 3 } });
  });

  it("adds a root of any object's series, which the set's changes leave be (§661)", () => {
    const pump9 = { objectId: "i9", typeId: "t2", property: "flow", objectLabel: "Pump 9" };
    const withNine = withDerived(withAddedRoot(roots, pump9, 2), "root:i2", [cumulative], 1);
    expect(withNine[2]).toEqual({ id: "added:i9:flow", label: "Pump 9 flow", canvas: 2, style: "solid",
      root: pump9, parent: null, transforms: [], added: true });
    const derivedNine = withDerived(withNine, "added:i9:flow", [cumulative], 2);
    const next = withRoots(derivedNine, rootPlots([pumps[1]!], "t1", "pressure"));
    expect(next.map((p) => p.id)).toEqual(["root:i2", "added:i9:flow", "plot-4", "plot-5"]);
    // The reader may remove what they added, with what was derived from it.
    expect(withoutPlot(derivedNine, "added:i9:flow").map((p) => p.id)).toEqual(["root:i1", "root:i2", "plot-4"]);
    // The same series twice is once, a set's root included, and the cap holds.
    expect(withAddedRoot(withNine, pump9, 1)).toEqual(withNine);
    expect(withAddedRoot(roots, { ...roots[0]!.root!, objectLabel: "x" }, 1)).toEqual(roots);
    expect(withAddedRoot(roots, { ...roots[0]!.root!, property: "flow" }, 1)).toHaveLength(3);
    let many = roots;
    while (many.length < MAX_PLOTS) many = withDerived(many, "root:i1", [cumulative], 1);
    expect(withAddedRoot(many, pump9, 1)).toHaveLength(MAX_PLOTS);
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
    const both = [readings, [{ t: readings[0]!.t, v: 13 }]];
    expect(timesOf(both)).toEqual({ t0: readings[0]!.t, t1: readings[2]!.t });
    const e = scaleOf(both)!;
    expect(e.v0).toBeCloseTo(1 - 0.6);
    expect(e.v1).toBeCloseTo(13 + 0.6);
    expect([e.log, e.invert]).toEqual([false, false]);
    expect(timesOf([[]])).toBeNull();
    expect(scaleOf([[]])).toBeNull();
    // One reading still has a width and a height to draw in.
    expect(timesOf([[{ t: 10, v: 5 }]])).toEqual({ t0: 9, t1: 11 });
    const one = scaleOf([[{ t: 10, v: 5 }]])!;
    expect([one.v0, one.v1]).toEqual([4, 6]);
    const zero = scaleOf([[{ t: 10, v: 0 }, { t: 20, v: 0 }]])!;
    expect([zero.v0, zero.v1]).toEqual([-1, 1]);
  });

  it("draws the line across the frame", () => {
    const frame = { width: 100, height: 50 };
    expect(pathOf([{ t: 0, v: 0 }, { t: 10, v: 10 }], { t0: 0, t1: 10, v0: 0, v1: 10, log: false, invert: false }, frame))
      .toBe("M0.0,50.0L100.0,0.0");
    expect(pathOf([], { t0: 0, t1: 1, v0: 0, v1: 1, log: false, invert: false }, frame)).toBe("");
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

describe("p.393's Linked event set (§654)", () => {
  const jobs = { link: "l1", direction: "inbound" as const, start: "started", end: "finished" };

  it("adds a set of the objects linked to a plot's root, named for the link's side", () => {
    const derived = withDerived(roots, "root:i1", [cumulative], 1);
    const sets = withLinkedEventSet([], derived, "plot-3", jobs, "Jobs");
    expect(sets).toEqual([{ id: "events-1", label: "Jobs of Pump 1", plot: "plot-3", linked: jobs,
      highlight: true }]);
    expect(withLinkedEventSet(sets, roots, "root:i2", { ...jobs, end: null }, "Jobs")[1])
      .toMatchObject({ id: "events-2", label: "Jobs of Pump 2", linked: { end: null } });
  });

  it("needs a plot with a root, a link and a start, under the cap", () => {
    expect(withLinkedEventSet([], roots, "gone", jobs, "Jobs")).toEqual([]);
    expect(withLinkedEventSet([], roots, "root:i1", { ...jobs, link: "" }, "Jobs")).toEqual([]);
    expect(withLinkedEventSet([], roots, "root:i1", { ...jobs, start: "" }, "Jobs")).toEqual([]);
    let sets = withEventSet([], roots, "root:i1", "gt", 0);
    const taken = [{ ...sets[0]!, id: "events-2" }];
    expect(withLinkedEventSet(taken, roots, "root:i1", jobs, "Jobs")[1]!.id).toBe("events-3");
    while (sets.length < MAX_EVENT_SETS) sets = withEventSet(sets, roots, "root:i1", "gt", sets.length);
    expect(withLinkedEventSet(sets, roots, "root:i1", jobs, "Jobs")).toHaveLength(MAX_EVENT_SETS);
  });

  it("is not what event statistics reads, whose events are found in the query", () => {
    const [set] = withLinkedEventSet([], roots, "root:i2", jobs, "Jobs");
    expect(withEventStatistics(roots, "root:i1", set, "avg", 1)).toEqual(roots);
  });
});

describe("p.394's Display (§655)", () => {
  const frame = { width: 100, height: 50 };
  const extent = { t0: 0, t1: 10, v0: 0, v1: 10, log: false, invert: false };
  const two = [{ t: 0, v: 0 }, { t: 10, v: 10 }];

  it("starts as the line always was, with no points and no gradient", () => {
    expect(displayOf(roots[0]!)).toEqual(DEFAULT_DISPLAY);
    expect(DEFAULT_DISPLAY).toEqual({ width: 1.6, gradient: false, shape: "none", size: 5, fill: "line",
      outline: 1, internal: "linear", external: "none" });
  });

  it("changes one plot's setting, holding a number to its bounds", () => {
    const wide = withDisplay(roots, "root:i1", "width", 3);
    expect(displayOf(wide[0]!).width).toBe(3);
    expect(wide[1]).toBe(roots[1]);
    expect(displayOf(withDisplay(wide, "root:i1", "gradient", true)[0]!)).toMatchObject({ width: 3, gradient: true });
    expect(displayOf(withDisplay(roots, "root:i1", "width", 99)[0]!).width).toBe(8);
    expect(displayOf(withDisplay(roots, "root:i1", "width", 0)[0]!).width).toBe(0.5);
    expect(displayOf(withDisplay(roots, "root:i1", "size", 1)[0]!).size).toBe(2);
    expect(displayOf(withDisplay(roots, "root:i1", "size", 40)[0]!).size).toBe(16);
    expect(displayOf(withDisplay(roots, "root:i1", "outline", 0)[0]!).outline).toBe(0.5);
    expect(displayOf(withDisplay(roots, "root:i1", "outline", 9)[0]!).outline).toBe(4);
    expect(withDisplay(roots, "root:i1", "width", Number.NaN)).toEqual(roots);
  });

  it("offers size and fill only with points, and the outline only round a white fill", () => {
    expect(pointOptions(DEFAULT_DISPLAY)).toEqual({ size: false, fill: false, outline: false });
    const circles = { ...DEFAULT_DISPLAY, shape: "circle" as const };
    expect(pointOptions(circles)).toEqual({ size: true, fill: true, outline: false });
    expect(pointOptions({ ...circles, fill: "white" })).toEqual({ size: true, fill: true, outline: true });
    expect(pointOptions({ ...circles, fill: "none" })).toEqual({ size: true, fill: true, outline: false });
    expect(outlineOf({ ...circles, fill: "white", outline: 2.5 })).toBe(2.5);
    expect(outlineOf({ ...circles, fill: "none", outline: 2.5 })).toBe(1);
    expect(outlineOf({ ...circles, outline: 2.5 })).toBe(0);
  });

  it("shades under the line to the frame's foot", () => {
    expect(areaOf(two, extent, frame)).toBe("M0.0,50.0L100.0,0.0L100.0,50.0L0.0,50.0Z");
    expect(areaOf([], extent, frame)).toBe("");
  });

  it("draws each shape centred on its point, size across", () => {
    expect(markerOf("square", 10, 20, 4)).toBe("M8.0,18.0h4.0v4.0h-4.0Z");
    expect(markerOf("diamond", 10, 20, 4)).toBe("M10.0,18.0L12.0,20.0L10.0,22.0L8.0,20.0Z");
    expect(markerOf("triangle", 10, 20, 4)).toBe("M10.0,18.0L12.0,22.0L8.0,22.0Z");
    expect(markerOf("circle", 10, 20, 4)).toBe("M8.0,20.0a2.0,2.0 0 1,0 4.0,0a2.0,2.0 0 1,0 -4.0,0Z");
    expect(markerOf("none", 10, 20, 4)).toBe("");
    expect(markersOf(two, extent, frame, "square", 2)).toBe("M-1.0,49.0h2.0v2.0h-2.0ZM99.0,-1.0h2.0v2.0h-2.0Z");
  });
});

describe("p.394-395's Axis options (§656)", () => {
  const frame = { width: 100, height: 50 };
  const line = [{ t: 0, v: 1 }, { t: 5, v: 10 }, { t: 10, v: 100 }];

  it("puts every plot on its canvas's first axis until it is moved", () => {
    expect(axisOf(roots[0]!)).toBe(1);
    expect(axesOf(roots, 1)).toEqual([1]);
    expect(axesOf(roots, 2)).toEqual([1]);
    const moved = withPlotSetting(roots, "root:i2", "axis", newAxisOf(roots, 1)!);
    expect(axesOf(moved, 1)).toEqual([1, 2]);
    // In order, whichever plot comes first.
    expect(axesOf(withPlotSetting(moved, "root:i1", "axis", 3), 1)).toEqual([2, 3]);
    expect(newAxisOf(moved, 1)).toBe(3);
    let many = moved;
    for (let n = 3; n <= MAX_AXES; n++) {
      many = withDerived(many, "root:i1", [cumulative], 1);
      many = withPlotSetting(many, many.at(-1)!.id, "axis", n);
    }
    expect(axesOf(many, 1)).toHaveLength(MAX_AXES);
    expect(newAxisOf(many, 1)).toBeNull();
  });

  it("keeps each canvas's axes' settings apart", () => {
    const axes = withAxisSetting(withAxisSetting({}, 1, 2, "log", true), 1, 2, "unit", "kPa".repeat(10));
    expect(axisSettingsOf(axes, 1, 2)).toEqual({ ...DEFAULT_AXIS, log: true, unit: "kPa".repeat(8) });
    expect(axisSettingsOf(axes, 1, 1)).toEqual(DEFAULT_AXIS);
    expect(axisSettingsOf(axes, 2, 2)).toEqual(DEFAULT_AXIS);
    expect(DEFAULT_AXIS).toEqual({ unit: "", auto: true, min: null, max: null, log: false, invert: false,
      align: "left" });
  });

  it("says what is wrong with a fixed range, and scales to the readings meanwhile", () => {
    const fixed = { ...DEFAULT_AXIS, auto: false };
    expect(axisProblem(DEFAULT_AXIS)).toBeNull();
    expect(axisProblem({ ...fixed, min: 0 })).toBe("An axis not scaled automatically needs a minimum and a maximum.");
    expect(axisProblem({ ...fixed, min: 0, max: Number.NaN })).toBe("An axis not scaled automatically needs a minimum and a maximum.");
    expect(axisProblem({ ...fixed, min: 5, max: 5 })).toBe("The axis minimum must be below its maximum.");
    expect(axisProblem({ ...fixed, min: 0, max: 5, log: true })).toBe("A log axis starts above zero.");
    expect(axisProblem({ ...fixed, min: 1, max: 5, log: true })).toBeNull();
    expect(scaleOf([line], { ...fixed, min: 0, max: 200 })).toEqual({ v0: 0, v1: 200, log: false, invert: false });
    expect(scaleOf([line], { ...fixed, min: 5, max: 5 })).toEqual(scaleOf([line]));
  });

  it("scales a log axis by ratio, over the readings above zero", () => {
    const log = { ...DEFAULT_AXIS, log: true };
    const s = scaleOf([[...line, { t: 11, v: 0 }, { t: 12, v: -3 }]], log)!;
    expect(s.v0).toBeCloseTo(1 / 100 ** 0.05);
    expect(s.v1).toBeCloseTo(100 * 100 ** 0.05);
    expect(scaleOf([[{ t: 0, v: 4 }]], log)).toEqual({ v0: 2, v1: 8, log: true, invert: false });
    expect(scaleOf([[{ t: 0, v: 0 }]], log)).toBeNull();
    const exact = { v0: 1, v1: 100, log: true, invert: false };
    expect(fractionOf(exact, 10)).toBeCloseTo(0.5);
    expect(valueAt(exact, 0.5)).toBeCloseTo(10);
    // A reading at or below zero has no place on it.
    const path = pathOf([{ t: 0, v: 0 }, ...line], { t0: 0, t1: 10, ...exact }, frame);
    expect(path).toBe("M0.0,50.0L50.0,25.0L100.0,0.0");
  });

  it("turns an inverted axis upside down", () => {
    const up = { v0: 0, v1: 10, log: false, invert: true };
    expect(fractionOf(up, 2)).toBeCloseTo(0.8);
    expect(valueAt(up, 1)).toBe(0);
    expect(valueAt(up, 0)).toBe(10);
    expect(pathOf([{ t: 0, v: 0 }, { t: 10, v: 10 }], { t0: 0, t1: 10, ...up }, frame)).toBe("M0.0,0.0L100.0,50.0");
  });
});

describe("p.395's Interpolation (§657)", () => {
  const frame = { width: 100, height: 50 };
  const extent = { t0: 0, t1: 10, v0: 0, v1: 10, log: false, invert: false };
  const three = [{ t: 2, v: 0 }, { t: 4, v: 10 }, { t: 8, v: 5 }];
  const how = (internal: "linear" | "previous" | "next" | "nearest" | "none", external: "none" | "nearest" = "none") =>
    ({ internal, external });

  it("joins readings straight, or in steps, or not at all", () => {
    expect(pathOf(three, extent, frame, how("linear"))).toBe("M20.0,50.0L40.0,0.0L80.0,25.0");
    expect(pathOf(three, extent, frame)).toBe(pathOf(three, extent, frame, how("linear")));
    expect(pathOf(three, extent, frame, how("previous"))).toBe("M20.0,50.0L40.0,50.0L40.0,0.0L80.0,0.0L80.0,25.0");
    expect(pathOf(three, extent, frame, how("next"))).toBe("M20.0,50.0L20.0,0.0L40.0,0.0L40.0,25.0L80.0,25.0");
    expect(pathOf(three, extent, frame, how("nearest")))
      .toBe("M20.0,50.0L30.0,50.0L30.0,0.0L40.0,0.0L60.0,0.0L60.0,25.0L80.0,25.0");
    expect(pathOf(three, extent, frame, how("none"))).toBe("");
  });

  it("holds the first and last readings to the edges when asked", () => {
    expect(pathOf(three, extent, frame, how("linear", "nearest")))
      .toBe("M0.0,50.0L20.0,50.0L40.0,0.0L80.0,25.0L100.0,25.0");
    expect(areaOf(three, extent, frame, how("linear", "nearest")))
      .toBe("M0.0,50.0L20.0,50.0L40.0,0.0L80.0,25.0L100.0,25.0L100.0,50.0L0.0,50.0Z");
    expect(pathOf([], extent, frame, how("linear", "nearest"))).toBe("");
    expect(areaOf(three, extent, frame, how("none"))).toBe("");
  });

  it("draws a plot with no line and no shape as circles", () => {
    expect(shownShape(DEFAULT_DISPLAY)).toBe("none");
    expect(shownShape({ ...DEFAULT_DISPLAY, internal: "none" })).toBe("circle");
    expect(shownShape({ ...DEFAULT_DISPLAY, internal: "none", shape: "square" })).toBe("square");
  });
});

describe("p.396's Plot options (§658)", () => {
  it("reads the builder's initial event sets that name a set and a start", () => {
    expect(initialEventSetsOf([
      { objectSetVariable: "v_jobs", start: "began", end: "ended", label: " Jobs " },
      { objectSetVariable: "v_jobs", start: "began", end: "", label: "" },
      { objectSetVariable: "", start: "began" },
      { objectSetVariable: "v_jobs", start: "" },
      { objectSetVariable: 5, start: "began" },
      null, "junk",
    ])).toEqual([
      { objectSetVariable: "v_jobs", start: "began", end: "ended", label: "Jobs" },
      { objectSetVariable: "v_jobs", start: "began", end: null, label: "v_jobs" },
    ]);
    expect(initialEventSetsOf({ objectSetVariable: "v_jobs", start: "began" })).toEqual([]);
    const many = Array.from({ length: MAX_EVENT_SETS + 2 }, () => ({ objectSetVariable: "v", start: "s" }));
    expect(initialEventSetsOf(many)).toHaveLength(MAX_EVENT_SETS);
  });

  it("makes each object an event, a moment where it has no end", () => {
    const objects = [
      { properties: { began: "2026-01-02T00:00:00Z", ended: "2026-01-03T00:00:00Z" } },
      { properties: { began: "2026-01-05T00:00:00Z", ended: null } },
      { properties: { began: "2026-01-08T00:00:00Z", ended: "2026-01-07T00:00:00Z" } },
      { properties: { began: "2026-01-09T00:00:00Z", ended: "" } },
      { properties: { ended: "2026-01-09T00:00:00Z" } },
    ];
    const day = (d: number) => Date.parse(`2026-01-0${d}T00:00:00Z`);
    expect(objectEventsOf(objects, "began", "ended")).toEqual([
      { start: day(2), end: day(3) }, { start: day(5), end: day(5) }, { start: day(7), end: day(8) },
      { start: day(9), end: day(9) },
    ]);
    expect(objectEventsOf(objects.slice(0, 1), "began", null)).toEqual([{ start: day(2), end: day(2) }]);
  });

  it("puts a new plot on its input's canvas, a new one, or the builder's", () => {
    expect(placementOf(undefined)).toBe("input");
    expect(placementOf("new")).toBe("new");
    expect(placementOf(3)).toBe(3);
    for (const junk of [0, 9, 1.5, "3", "elsewhere"]) expect(placementOf(junk)).toBe("input");
    expect(canvasFor("input", 2, [1, 2])).toBe(2);
    expect(canvasFor("new", 2, [1, 3])).toBe(4);
    expect(canvasFor("new", 1, [])).toBe(2);
    expect(canvasFor(5, 2, [1, 2])).toBe(5);
  });
});

describe("p.396's view range (§659)", () => {
  const HOUR = 3_600_000;
  const DAY = 24 * HOUR;
  const now = Date.parse("2026-01-15T00:00:00Z");
  const none = { start: null, end: null };

  it("opens on the full range, a fixed one, or one relative to the page's loading", () => {
    expect(defaultRangeOf("full", { start: 1, end: 2 }, 2, "week", now)).toBeNull();
    expect(defaultRangeOf(undefined, none, 2, "week", now)).toBeNull();
    expect(defaultRangeOf("fixed", { start: 10, end: 20 }, 2, "week", now)).toEqual({ from: 10, to: 20 });
    expect(defaultRangeOf("fixed", { start: 20, end: 20 }, 2, "week", now)).toBeNull();
    expect(defaultRangeOf("fixed", { start: 10, end: null }, 2, "week", now)).toBeNull();
    expect(defaultRangeOf("fixed", { start: null, end: 10 }, 2, "week", now)).toBeNull();
    expect(defaultRangeOf("relative", none, 2, "week", now)).toEqual({ from: now - 14 * DAY, to: now });
    expect(defaultRangeOf("relative", none, 3, "hour", now)).toEqual({ from: now - 3 * HOUR, to: now });
    for (const [amount, unit] of [[0, "day"], [-1, "day"], [Number.NaN, "day"], ["2", "day"], [2, "fortnight"],
      [2, null]] as const) {
      expect(defaultRangeOf("relative", none, amount, unit, now)).toBeNull();
    }
  });

  it("zooms about the middle, back to the full range", () => {
    const full = { t0: 0, t1: 4 * DAY };
    expect(zoomedRange(null, full, 0.5)).toEqual({ from: DAY, to: 3 * DAY });
    expect(zoomedRange({ from: DAY, to: 3 * DAY }, full, 0.5)).toEqual({ from: 1.5 * DAY, to: 2.5 * DAY });
    expect(zoomedRange({ from: DAY, to: 3 * DAY }, full, 2)).toBeNull();
    // Out from a view off to one side keeps its middle.
    expect(zoomedRange({ from: 3 * DAY, to: 4 * DAY }, full, 2)).toEqual({ from: 2.5 * DAY, to: 4.5 * DAY });
    // No narrower than a second.
    expect(zoomedRange({ from: 0, to: 1_000 }, full, 0.5)).toEqual({ from: 0, to: MIN_VIEW_MS });
  });

  it("pans by part of the view's own width", () => {
    const full = { t0: 0, t1: 4 * DAY };
    expect(pannedRange(null, full, -0.5)).toEqual({ from: -2 * DAY, to: 2 * DAY });
    expect(pannedRange({ from: DAY, to: 2 * DAY }, full, 0.5)).toEqual({ from: 1.5 * DAY, to: 2.5 * DAY });
  });

  it("keeps the readings in view, ends included", () => {
    const r = [{ t: 1, v: 1 }, { t: 2, v: 2 }, { t: 3, v: 3 }];
    expect(inView(r, { from: 2, to: 3 })).toEqual(r.slice(1));
    expect(inView(r, null)).toEqual(r);
    expect(inView(r, null)).not.toBe(r);
  });

  it("reads the server's zoneless readings and events as UTC", () => {
    const at = Date.parse("2026-01-01T06:00:00Z");
    expect(readingsOf([{ at: "2026-01-01T06:00:00", value: 1 }])).toEqual([{ t: at, v: 1 }]);
    expect(readingsOf([{ at: "2026-01-01T08:00:00+02:00", value: 1 }])).toEqual([{ t: at, v: 1 }]);
    expect(eventsOf([{ start: "2026-01-01T06:00:00", end: "2026-01-01T06:00:00Z" }]))
      .toEqual([{ start: at, end: at }]);
  });

  it("labels a time in UTC or the reader's own offset", () => {
    const t = Date.parse("2026-01-01T23:00:00Z");
    expect(timeLabel(t, DAY, 0)).toBe("01-01 23:00");
    expect(timeLabel(t, DAY, 120)).toBe("01-02 01:00");
    expect(timeLabel(t, 3 * DAY, 120)).toBe("2026-01-02");
    expect(timeLabel(t, 2 * DAY, 0)).toBe("01-01 23:00");
  });
});

describe("p.396's Chart options (§660)", () => {
  const plain = { overlay: false, collapsed: false, boundaries: false };

  it("gives each axis room beside the frame, or none over it, or a sliver collapsed", () => {
    expect(axisLayout(2, 1, plain)).toEqual({ per: AXIS_ROOM, left: 2 * AXIS_ROOM, right: AXIS_ROOM, ticks: [0, 0.5, 1] });
    expect(axisLayout(1, 0, plain)).toEqual({ per: AXIS_ROOM, left: AXIS_ROOM, right: EDGE_ROOM, ticks: [0, 0.5, 1] });
    expect(axisLayout(2, 1, { ...plain, overlay: true })).toMatchObject({ left: EDGE_ROOM, right: EDGE_ROOM });
    expect(axisLayout(2, 0, { ...plain, collapsed: true }))
      .toEqual({ per: COLLAPSED_ROOM, left: 2 * COLLAPSED_ROOM, right: EDGE_ROOM, ticks: [] });
    expect(axisLayout(1, 0, { ...plain, collapsed: true, boundaries: true }).ticks).toEqual([0, 1]);
    // Boundaries are for collapsed axes.
    expect(axisLayout(1, 0, { ...plain, boundaries: true }).ticks).toEqual([0, 0.5, 1]);
  });

  it("reads the builder's tooltip options, keeping the defaults for what is not one", () => {
    expect(tooltipOptionsOf(null)).toEqual(DEFAULT_TOOLTIP);
    expect(DEFAULT_TOOLTIP).toEqual({ show: true, values: "all", time: true, wrap: false, digits: 4 });
    expect(tooltipOptionsOf({ show: false, values: "hovered", time: false, wrap: true, digits: 10 }))
      .toEqual({ show: false, values: "hovered", time: false, wrap: true, digits: 10 });
    expect(tooltipOptionsOf({ show: "no", values: "some", time: 0, wrap: 1, digits: 0 })).toEqual(DEFAULT_TOOLTIP);
    for (const digits of [11, 2.5, "3"]) expect(tooltipOptionsOf({ digits }).digits).toBe(4);
    expect(tooltipOptionsOf({ digits: 1 }).digits).toBe(1);
  });

  it("finds the reading nearest a time, the earlier on a tie", () => {
    const r = [{ t: 0, v: 1 }, { t: 10, v: 2 }, { t: 20, v: 3 }];
    expect(readingAt(r, 4)).toEqual(r[0]);
    expect(readingAt(r, 6)).toEqual(r[1]);
    expect(readingAt(r, 15)).toEqual(r[1]);
    expect(readingAt(r, 99)).toEqual(r[2]);
    expect(readingAt([], 5)).toBeNull();
  });

  it("writes a value to its significant digits, and picks the plot drawn nearest", () => {
    expect(significant(123.456, 4)).toBe("123.5");
    expect(significant(123.456, 2)).toBe("120");
    expect(significant(0.000123456, 3)).toBe("0.000123");
    expect(significant(20, 4)).toBe("20");
    expect(hoveredOf([{ id: "a", y: 10 }, { id: "b", y: 50 }], 35)).toBe("b");
    expect(hoveredOf([{ id: "a", y: 10 }, { id: "b", y: 50 }], 30)).toBe("a");
    expect(hoveredOf([], 30)).toBeNull();
  });
});

describe("p.396's Add data options (§661)", () => {
  it("reads the builder's sets, once each", () => {
    expect(addDataSetsOf([{ objectSetVariable: "v_a" }, { objectSetVariable: "v_a" }, { objectSetVariable: "" },
      { objectSetVariable: 3 }, null, "v_b", { objectSetVariable: "v_c" }])).toEqual(["v_a", "v_c"]);
    expect(addDataSetsOf({ objectSetVariable: "v_a" })).toEqual([]);
    const many = Array.from({ length: MAX_ADD_DATA_SETS + 3 }, (_, n) => ({ objectSetVariable: `v_${n}` }));
    expect(addDataSetsOf(many)).toHaveLength(MAX_ADD_DATA_SETS);
  });

  it("names an object by its title, or its key", () => {
    const o = { primary_key: "S2", properties: { name: "South sensor", blank: "" } };
    expect(objectLabelOf(o, "name")).toBe("South sensor");
    expect(objectLabelOf(o, null)).toBe("S2");
    expect(objectLabelOf(o, "blank")).toBe("S2");
    expect(objectLabelOf(o, "gone")).toBe("S2");
    expect(objectLabelOf({ primary_key: 7, properties: { n: 0 } }, "n")).toBe("0");
  });
});

describe("p.397's saved analysis (§662)", () => {
  it("saves the plots, canvases, event sets and axes", () => {
    const plots = withDerived(roots, "root:i1", [cumulative], 2);
    const sets = withEventSet([], plots, "plot-3", "gt", 1);
    const axes = withAxisSetting({}, 1, 1, "log", true);
    expect(savedViewOf(plots, 3, sets, axes)).toEqual({ plots, canvases: 3, eventSets: sets, axes });
  });

  it("opens over the set's roots now, keeping a saved root the set has lost", () => {
    const plots = withDisplay(withDerived(roots, "root:i2", [cumulative], 2), "root:i1", "width", 4);
    const saved = JSON.parse(JSON.stringify(savedViewOf(plots, 2, withEventSet([], plots, "plot-3", "gt", 1), {})));
    // Pump 2 has left the set since; Pump 3 has joined it.
    const now = rootPlots([pumps[0]!, { id: "i3", label: "Pump 3" }], "t1", "pressure");
    const opened = openedView(saved, now);
    expect(opened.plots.map((p) => [p.id, !!p.added])).toEqual([
      ["root:i1", false], ["root:i3", false], ["root:i2", true], ["plot-3", false]]);
    expect(displayOf(opened.plots[0]!).width).toBe(4);
    expect(opened.canvases).toBe(2);
    expect(opened.eventSets.map((e) => e.plot)).toEqual(["plot-3"]);
    // Pump 2 back in the set is the set's again, once.
    const back = withRoots(opened.plots, roots);
    expect(back.map((p) => [p.id, !!p.added])).toEqual([["root:i1", false], ["root:i2", false], ["plot-3", false]]);
  });

  it("leaves out what is not a plot, an event set or a count", () => {
    const good = roots[0]!;
    const opened = openedView({
      plots: [good, { ...good, id: 5 }, { ...good, id: "p1", style: "dotted" },
        { ...good, id: "p4", root: { objectId: "x" } }, { ...good, id: "p2", parent: 3 },
        { ...good, id: "p3", transforms: "none" }, { ...good, id: "p5", canvas: "1" }, null],
      canvases: -1, eventSets: [{ id: "e", label: "E", plot: "root:i1" }, { id: "f" }], axes: [],
    }, roots);
    expect(opened.plots.map((p) => p.id)).toEqual(["root:i1", "root:i2"]);
    expect([opened.canvases, opened.eventSets.length, opened.axes]).toEqual([0, 1, {}]);
    expect(openedView(null, roots)).toEqual({ plots: roots, canvases: 0, eventSets: [], axes: {} });
    expect(openedView({ canvases: 2.5 }, roots).canvases).toBe(0);
  });
});
