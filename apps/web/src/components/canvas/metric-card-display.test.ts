/** §526: the Metric Card's size, description, sparkline time range and
 * baseline (`workshop` p.326-330, p.591-592). */
import { afterEach, describe, expect, it } from "vitest";

import {
  DEFAULT_METRIC_SIZE, DEFAULT_SPARK_RANGE, METRIC_SIZES, SPARK_RANGES, baselineOf, descriptionOf,
  metricSizeOf, pageNow, resetPageNow, sparkRangeOf, sparkRangeProblem, sparkRangeTransform,
} from "./metric-card";
import { levelY, path, range, type Point } from "./sparkline";

const NOW = Date.parse("2026-09-26T12:00:00Z");

describe("size and description", () => {
  it("offers p.326's three sizes and reads anything else as Regular", () => {
    expect(METRIC_SIZES).toEqual({ compact: "Compact", regular: "Regular", large: "Large" });
    expect(DEFAULT_METRIC_SIZE).toBe("regular");
    expect(metricSizeOf("large")).toBe("large");
    expect(metricSizeOf("compact")).toBe("compact");
    expect(metricSizeOf("huge")).toBe("regular");
    expect(metricSizeOf(undefined)).toBe("regular");
  });

  it("has a description only when there is text", () => {
    expect(descriptionOf("  Doses given so far  ")).toBe("Doses given so far");
    expect(descriptionOf("   ")).toBeNull();
    expect(descriptionOf("")).toBeNull();
    expect(descriptionOf(7)).toBeNull();
  });
});

describe("the sparkline's time range", () => {
  afterEach(() => resetPageNow());

  it("offers p.330's presets and a custom range", () => {
    expect(Object.values(SPARK_RANGES)).toEqual(["All time", "Last hour", "Last day", "Last week", "Custom range", "Relative range"]);
    expect(DEFAULT_SPARK_RANGE).toBe("all");
    expect(sparkRangeOf("week")).toBe("week");
    expect(sparkRangeOf("month")).toBe("all");
  });

  it("counts a preset back from now, in UTC to the second", () => {
    expect(sparkRangeTransform("hour", null, null, NOW)).toEqual(
      { kind: "range", start: "2026-09-26T11:00:00", end: null });
    expect(sparkRangeTransform("day", null, null, NOW)).toEqual(
      { kind: "range", start: "2026-09-25T12:00:00", end: null });
    expect(sparkRangeTransform("week", null, null, NOW)).toEqual(
      { kind: "range", start: "2026-09-19T12:00:00", end: null });
  });

  it("asks for everything when it is all time, or a custom range with no ends", () => {
    expect(sparkRangeTransform("all", "2026-01-01T00:00", null, NOW)).toBeNull();
    expect(sparkRangeTransform("custom", null, "", NOW)).toBeNull();
    expect(sparkRangeTransform("custom", "", null, NOW)).toBeNull();
  });

  it("passes a custom range's ends through, either or both", () => {
    expect(sparkRangeTransform("custom", "2026-01-02T00:00", null, NOW)).toEqual(
      { kind: "range", start: "2026-01-02T00:00", end: null });
    expect(sparkRangeTransform("custom", null, "2026-01-03T00:00", NOW)).toEqual(
      { kind: "range", start: null, end: "2026-01-03T00:00" });
    expect(sparkRangeTransform("custom", "2026-01-02T00:00", "2026-01-03T00:00", NOW)).toEqual(
      { kind: "range", start: "2026-01-02T00:00", end: "2026-01-03T00:00" });
  });

  it("says when a custom range runs backwards, and only then", () => {
    expect(sparkRangeProblem("custom", "2026-01-03T00:00", "2026-01-02T00:00")).toBe("The range starts after it ends.");
    expect(sparkRangeProblem("custom", "2026-01-02T00:00", "2026-01-02T00:00")).toBeNull();
    expect(sparkRangeProblem("custom", "2026-01-03T00:00", "")).toBeNull();
    expect(sparkRangeProblem("week", "2026-01-03T00:00", "2026-01-02T00:00")).toBeNull();
  });

  it("fixes now at the first ask, until a reload (p.591)", () => {
    let t = 1000;
    const clock = () => t;
    expect(pageNow(clock)).toBe(1000);
    t = 5000;
    expect(pageNow(clock)).toBe(1000);
    resetPageNow();
    expect(pageNow(clock)).toBe(5000);
  });
});

describe("the baseline", () => {
  const points: Point[] = [
    { at: "2026-01-01T00:00:00Z", value: 10 },
    { at: "2026-01-02T00:00:00Z", value: 20 },
  ];
  const box = { width: 100, height: 20 };

  it("is a finite number or none", () => {
    expect(baselineOf(25)).toBe(25);
    expect(baselineOf("12.5")).toBe(12.5);
    expect(baselineOf(0)).toBe(0);
    expect(baselineOf("")).toBeNull();
    expect(baselineOf(null)).toBeNull();
    expect(baselineOf(undefined)).toBeNull();
    expect(baselineOf("lots")).toBeNull();
    expect(baselineOf(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it("is kept in the box with the line", () => {
    expect(range(points, 40)).toEqual({ low: 10, high: 40 });
    expect(range(points, 0)).toEqual({ low: 0, high: 20 });
    expect(range(points, 15)).toEqual({ low: 10, high: 20 });
    expect(range(points)).toEqual({ low: 10, high: 20 });
    // The line is rescaled to make room: with 40 at the top, 20 is two thirds down.
    expect(path(points, box, 40)).toBe("M0 20 L100 13.33");
  });

  it("sits where the line's values would", () => {
    expect(levelY(points, box, 15)).toBe(10);
    expect(levelY(points, box, 40)).toBe(0);
    expect(levelY(points, box, 10)).toBe(20);
    expect(levelY(points, box, null)).toBeNull();
    // No line, no baseline beside it.
    expect(levelY(points.slice(0, 1), box, 15)).toBeNull();
  });
});

describe("the secondary metric (§528)", () => {
  it("is labelled by what it computes unless it is given a label", async () => {
    const { secondaryLabelOf } = await import("./metric-card");
    expect(secondaryLabelOf("", "avg")).toBe("Average of");
    expect(secondaryLabelOf("   ", "count")).toBe("How many");
    expect(secondaryLabelOf(undefined, "max")).toBe("Maximum of");
    expect(secondaryLabelOf("  Largest site ", "max")).toBe("Largest site");
    // An aggregation this platform has not got is a count, as the primary's is.
    expect(secondaryLabelOf("", "median")).toBe("How many");
  });
});

describe("groups of metrics and their layout (§533)", () => {
  it("offers p.326's three styles and their arrangements", async () => {
    const m = await import("./metric-card");
    expect(m.LAYOUT_STYLES).toEqual({ card: "Card", tag: "Tag", list: "List" });
    expect(m.DIRECTIONS).toEqual({ horizontal: "Horizontal", vertical: "Vertical" });
    expect(m.TEMPLATES).toEqual({ stacked: "Stacked", side_by_side: "Side-by-side" });
    expect(m.layoutStyleOf("tag")).toBe("tag");
    expect(m.layoutStyleOf("grid")).toBe("card");
    expect(m.directionOf("vertical")).toBe("vertical");
    expect(m.directionOf("diagonal")).toBe("horizontal");
    expect(m.templateOf("side_by_side")).toBe("side_by_side");
    expect(m.templateOf(undefined)).toBe("stacked");
  });

  it("gives each style the settings p.326 gives it", async () => {
    const { layoutSettings } = await import("./metric-card");
    expect(layoutSettings("card")).toEqual({ direction: true, template: true });
    expect(layoutSettings("tag")).toEqual({ direction: true, template: false });
    expect(layoutSettings("list")).toEqual({ direction: false, template: true });
  });

  it("draws a sparkline only in the Card layout", async () => {
    const { sparkAllowedIn } = await import("./metric-card");
    expect(sparkAllowedIn("card")).toBe(true);
    expect(sparkAllowedIn("tag")).toBe(false);
    expect(sparkAllowedIn("list")).toBe(false);
    expect(sparkAllowedIn("unknown")).toBe(true);
  });

  it("reads the stored metrics through", async () => {
    const { extraMetricsOf } = await import("./metric-card");
    expect(extraMetricsOf(null)).toEqual([]);
    expect(extraMetricsOf([
      { id: "m2", label: "Total", aggregation: "sum", property: "capacity", valueFormat: { kind: "number" } },
      { id: "m2", label: "again" },
      { label: "no id" },
      "junk",
      { id: "m3", aggregation: "median", property: "" },
    ])).toEqual([
      { id: "m2", label: "Total", aggregation: "sum", property: "capacity", valueFormat: { kind: "number" } },
      { id: "m3", label: "", aggregation: "count", property: null, valueFormat: null },
    ]);
  });

  it("adds a count with a new id, and moves within the ends", async () => {
    const { addMetric, moveMetric, metricLabelOf } = await import("./metric-card");
    const one = addMetric([]);
    expect(one).toEqual([{ id: "m2", label: "", aggregation: "count", property: null, valueFormat: null }]);
    const two = addMetric(one);
    expect(two.map((m) => m.id)).toEqual(["m2", "m3"]);
    // An id already taken is skipped.
    expect(addMetric([{ ...one[0]!, id: "m3" }]).map((m) => m.id)).toEqual(["m3", "m4"]);
    const three = addMetric(two);
    expect(moveMetric(three, 2, -1).map((m) => m.id)).toEqual(["m2", "m4", "m3"]);
    expect(moveMetric(three, 0, 1).map((m) => m.id)).toEqual(["m3", "m2", "m4"]);
    expect(moveMetric(three, 0, -1).map((m) => m.id)).toEqual(["m2", "m3", "m4"]);
    expect(moveMetric(three, 2, 1).map((m) => m.id)).toEqual(["m2", "m3", "m4"]);
    expect(moveMetric(three, 5, -1).map((m) => m.id)).toEqual(["m2", "m3", "m4"]);
    expect(metricLabelOf({ label: "", aggregation: "sum" })).toBe("Sum of");
    expect(metricLabelOf({ label: "Total", aggregation: "sum" })).toBe("Total");
  });
});

describe("the relative range and the series baseline (§534)", () => {
  it("counts p.591's units", async () => {
    const { RELATIVE_UNITS, relativeMs } = await import("./metric-card");
    expect(Object.keys(RELATIVE_UNITS)).toEqual(["millisecond", "second", "minute", "hour", "day", "week"]);
    expect(relativeMs(2, "week")).toBe(2 * 604_800_000);
    expect(relativeMs("3", "hour")).toBe(3 * 3_600_000);
    expect(relativeMs(0, "day")).toBe(0);
    expect(relativeMs(500, "millisecond")).toBe(500);
    expect(relativeMs(1, "fortnight")).toBeNull();
    expect(relativeMs(-1, "day")).toBeNull();
    expect(relativeMs("", "day")).toBeNull();
    expect(relativeMs(null, "day")).toBeNull();
    expect(relativeMs("soon", "day")).toBeNull();
  });

  it("windows a relative range around now, either end open", async () => {
    const { sparkRangeTransform } = await import("./metric-card");
    const now = Date.parse("2026-09-26T12:00:00Z");
    expect(sparkRangeTransform("relative", null, null, now, { ago: 2, agoUnit: "week", ahead: 1, aheadUnit: "day" }))
      .toEqual({ kind: "range", start: "2026-09-12T12:00:00", end: "2026-09-27T12:00:00" });
    expect(sparkRangeTransform("relative", null, null, now, { ago: 1, agoUnit: "day" }))
      .toEqual({ kind: "range", start: "2026-09-25T12:00:00", end: null });
    expect(sparkRangeTransform("relative", null, null, now, { ahead: 3, aheadUnit: "hour" }))
      .toEqual({ kind: "range", start: null, end: "2026-09-26T15:00:00" });
    expect(sparkRangeTransform("relative", null, null, now, {})).toBeNull();
    expect(sparkRangeTransform("relative", null, null, now)).toBeNull();
  });

  it("reads the baseline's kind, with a bare number as a static one", async () => {
    const { BASELINE_KINDS, baselineKindOf } = await import("./metric-card");
    expect(Object.keys(BASELINE_KINDS)).toEqual(["none", "static", "property", "series"]);
    expect(baselineKindOf("series", null)).toBe("series");
    expect(baselineKindOf(null, 25)).toBe("static");
    expect(baselineKindOf(undefined, null)).toBe("none");
    expect(baselineKindOf("sideways", 25)).toBe("static");
    expect(baselineKindOf("none", 25)).toBe("none");
  });

  it("summarises the series for its baseline", async () => {
    const { BASELINE_SUMMARIES, summarise } = await import("./metric-card");
    expect(Object.keys(BASELINE_SUMMARIES)).toEqual(["last", "first", "avg", "min", "max"]);
    const values = [10, Number.NaN, 30, 20];
    expect(summarise(values, "last")).toBe(20);
    expect(summarise(values, "first")).toBe(10);
    expect(summarise(values, "avg")).toBe(20);
    expect(summarise(values, "min")).toBe(10);
    expect(summarise(values, "max")).toBe(30);
    expect(summarise(values, "unknown")).toBe(20);
    expect(summarise([], "last")).toBeNull();
    expect(summarise([Number.NaN], "avg")).toBeNull();
  });
});
