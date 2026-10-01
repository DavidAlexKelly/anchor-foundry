import { describe, expect, it } from "vitest";

import {
  MAX_SERIES, axisSides, layerKinds, mergeSeries, seriesName, seriesOf, seriesRequests,
  seriesSource, splitLayers, type SeriesSpec,
} from "./chart-series";

const ON_CHART = { objectSetVariable: null, dimension: null, kind: null };

describe("seriesOf (p.281's multiple series)", () => {
  it("reads what a saved chart holds, and nothing else", () => {
    expect(seriesOf(undefined)).toEqual([]);
    expect(seriesOf({ aggregate: "sum" })).toEqual([]);
    expect(seriesOf([null, 3, { aggregate: "sum", measure: "capacity", name: "Total" }]))
      .toEqual([{ aggregate: "sum", measure: "capacity", name: "Total", axis: "right",
                  ...ON_CHART }]);
    expect(seriesOf([{ aggregate: "median", measure: "", name: 4 }]))
      .toEqual([{ aggregate: "count", measure: null, name: "", axis: "right", ...ON_CHART }]);
    // p.280's layer input and X axis property (§625), when they are names.
    expect(seriesOf([{ objectSetVariable: "v_flights", dimension: "origin" }])[0])
      .toMatchObject({ objectSetVariable: "v_flights", dimension: "origin" });
    expect(seriesOf([{ objectSetVariable: "", dimension: 3 }])[0]).toMatchObject(ON_CHART);
  });

  it("holds the chart to six series, the Measure's among them", () => {
    const many = Array.from({ length: 9 }, () => ({ aggregate: "count" }));
    expect(seriesOf(many)).toHaveLength(MAX_SERIES - 1);
  });
});

describe("seriesName (p.282's display override)", () => {
  it("is the override, else what the series plots", () => {
    expect(seriesName(spec({ aggregate: "sum", measure: "capacity" })))
      .toBe("Sum of capacity");
    expect(seriesName(spec({ name: "  " }))).toBe("Count");
    expect(seriesName(spec({ aggregate: "avg", measure: "age", name: " Mean age " })))
      .toBe("Mean age");
  });

  it("names the set a series reads when it is not the chart's (§625)", () => {
    expect(seriesName(spec({}), "Flights")).toBe("Count · Flights");
    expect(seriesName(spec({ name: "Departures" }), "Flights")).toBe("Departures");
  });
});

describe("seriesRequests", () => {
  it("asks for each finished series, and nothing for an unfinished one", () => {
    expect(seriesRequests([
      spec({}), spec({ aggregate: "sum" }), spec({ aggregate: "max", measure: "capacity" }),
    ])).toEqual([
      { aggregation: "count", aggregation_property: null },
      null,
      { aggregation: "max", aggregation_property: "capacity" },
    ]);
  });
});

describe("seriesSource (p.280's layers, §625)", () => {
  const chart = { objectSetVariable: "v_alerts", dimension: "airport" };
  const resolved = { v_alerts: { type: "alerts" }, v_flights: { type: "flights" } };

  it("is the chart's set by the chart's property, unless the series says otherwise", () => {
    expect(seriesSource(spec({}), chart, resolved))
      .toEqual({ key: "v_alerts", definition: { type: "alerts" }, dimension: "airport" });
    expect(seriesSource(spec({ dimension: "kind" }), chart, resolved))
      .toEqual({ key: "v_alerts", definition: { type: "alerts" }, dimension: "kind" });
    expect(seriesSource(spec({ objectSetVariable: "v_flights", dimension: "origin" }),
      chart, resolved))
      .toEqual({ key: "v_flights", definition: { type: "flights" }, dimension: "origin" });
  });

  it("waits for a property of a set of its own rather than borrowing the chart's", () => {
    expect(seriesSource(spec({ objectSetVariable: "v_flights" }), chart, resolved)).toBeNull();
    // Naming the chart's own set is the chart's set, property and all.
    expect(seriesSource(spec({ objectSetVariable: "v_alerts" }), chart, resolved))
      .toEqual({ key: "v_alerts", definition: { type: "alerts" }, dimension: "airport" });
  });

  it("asks nothing of a set not yet resolved, or of no set", () => {
    expect(seriesSource(spec({ objectSetVariable: "v_gone", dimension: "x" }), chart, resolved))
      .toBeNull();
    expect(seriesSource(spec({ objectSetVariable: "v_null", dimension: "x" }), chart,
      { v_null: null })).toBeNull();
    expect(seriesSource(spec({}), { objectSetVariable: null, dimension: "airport" }, resolved))
      .toBeNull();
    expect(seriesSource(spec({}), { objectSetVariable: "v_alerts", dimension: null }, resolved))
      .toBeNull();
  });
});

describe("layerKinds (p.280's Layer type, §626)", () => {
  it("reads a series' own type, and is the chart's where it names none", () => {
    expect(seriesOf([{ kind: "line" }, { kind: "bar" }, { kind: "pie" }, {}])
      .map((s) => s.kind)).toEqual(["line", "bar", null, null]);
    expect(layerKinds("bar", [spec({ kind: "line" }), spec({})])).toEqual(["bar", "line", "bar"]);
    expect(layerKinds("line", [spec({ kind: "bar" }), spec({})])).toEqual(["line", "bar", "line"]);
    expect(layerKinds("line", [])).toEqual(["line"]);
  });
});

describe("splitLayers", () => {
  const grid = {
    categories: ["open", "closed"],
    segments: ["Count", "Hours", "Sum"],
    values: [[3, 6, 30], [1, 1, 90]],
  };

  it("keeps the bar series as a grid of their own, each remembering its place", () => {
    const split = splitLayers(grid, ["bar", "line", "bar"]);
    expect(split.bars).toEqual({
      categories: ["open", "closed"], segments: ["Count", "Sum"], values: [[3, 30], [1, 90]],
    });
    expect(split.barAt).toEqual([0, 2]);
    expect(split.lineAt).toEqual([1]);
  });

  it("draws a series with no type named as a bar, and a short row as missing", () => {
    const split = splitLayers({ ...grid, values: [[3], [1, 1, 90]] }, ["line"]);
    expect(split.lineAt).toEqual([0]);
    expect(split.barAt).toEqual([1, 2]);
    expect(split.bars.values).toEqual([[NaN, NaN], [1, 90]]);
  });
});

describe("mergeSeries", () => {
  it("lays the series side by side, the first's categories first and in its order", () => {
    const merged = mergeSeries(
      [{ label: "open", value: 3 }, { label: "closed", value: 1 }],
      [[{ label: "closed", value: 90 }, { label: "open", value: 30 }],
       [{ label: "held", value: 5 }]],
      ["Count", "Sum of capacity", "Held"],
    );
    expect(merged.categories).toEqual(["open", "closed", "held"]);
    expect(merged.segments).toEqual(["Count", "Sum of capacity", "Held"]);
    expect(merged.values).toEqual([[3, 30, NaN], [1, 90, NaN], [NaN, NaN, 5]]);
  });

  it("keeps a category two later series share once", () => {
    const merged = mergeSeries(
      [], [[{ label: "x", value: 1 }], [{ label: "x", value: 2 }]], ["a", "b", "c"]);
    expect(merged.categories).toEqual(["x"]);
    expect(merged.values).toEqual([[NaN, 1, 2]]);
  });
});

describe("axisSides (p.283's Use multiple value axes)", () => {
  const specs = seriesOf([
    { aggregate: "sum", measure: "x" }, { aggregate: "max", measure: "y", axis: "left" },
  ]);

  it("puts a further series on the right unless it says left, the first always left", () => {
    expect(specs.map((s) => s.axis)).toEqual(["right", "left"]);
    expect(axisSides(specs, true)).toEqual(["left", "right", "left"]);
  });

  it("is all left with one axis, or one series", () => {
    expect(axisSides(specs, false)).toEqual(["left", "left", "left"]);
    expect(axisSides([], true)).toEqual(["left"]);
  });
});

function spec(over: Partial<SeriesSpec>): SeriesSpec {
  return { aggregate: "count", measure: null, name: "", axis: "right", ...ON_CHART, ...over };
}
