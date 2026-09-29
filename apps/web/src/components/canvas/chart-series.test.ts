import { describe, expect, it } from "vitest";

import { MAX_SERIES, mergeSeries, seriesName, seriesOf, seriesRequests } from "./chart-series";

describe("seriesOf (p.281's multiple series)", () => {
  it("reads what a saved chart holds, and nothing else", () => {
    expect(seriesOf(undefined)).toEqual([]);
    expect(seriesOf({ aggregate: "sum" })).toEqual([]);
    expect(seriesOf([null, 3, { aggregate: "sum", measure: "capacity", name: "Total" }]))
      .toEqual([{ aggregate: "sum", measure: "capacity", name: "Total" }]);
    expect(seriesOf([{ aggregate: "median", measure: "", name: 4 }]))
      .toEqual([{ aggregate: "count", measure: null, name: "" }]);
  });

  it("holds the chart to six series, the Measure's among them", () => {
    const many = Array.from({ length: 9 }, () => ({ aggregate: "count" }));
    expect(seriesOf(many)).toHaveLength(MAX_SERIES - 1);
  });
});

describe("seriesName (p.282's display override)", () => {
  it("is the override, else what the series plots", () => {
    expect(seriesName({ aggregate: "sum", measure: "capacity", name: "" })).toBe("Sum of capacity");
    expect(seriesName({ aggregate: "count", measure: null, name: "  " })).toBe("Count");
    expect(seriesName({ aggregate: "avg", measure: "age", name: " Mean age " })).toBe("Mean age");
  });
});

describe("seriesRequests", () => {
  it("asks for each finished series, and nothing for an unfinished one", () => {
    expect(seriesRequests([
      { aggregate: "count", measure: null, name: "" },
      { aggregate: "sum", measure: null, name: "" },
      { aggregate: "max", measure: "capacity", name: "" },
    ])).toEqual([
      { aggregation: "count", aggregation_property: null },
      null,
      { aggregation: "max", aggregation_property: "capacity" },
    ]);
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
    const merged = mergeSeries([], [[{ label: "x", value: 1 }], [{ label: "x", value: 2 }]], ["a", "b", "c"]);
    expect(merged.categories).toEqual(["x"]);
    expect(merged.values).toEqual([[NaN, 1, 2]]);
  });
});
