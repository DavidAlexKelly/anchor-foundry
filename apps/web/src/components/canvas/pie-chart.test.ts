import { describe, expect, it } from "vitest";

import {
  AGGREGATIONS, DEFAULT_AGGREGATION, DEFAULT_LEGEND_POSITION, LEGEND_POSITIONS,
  MAX_INNER_RADIUS, aggregationOf, aggregationRequest, arcPath, innerRadiusOf,
  legendPositionOf, needsProperty, percentLabel, pointOnCircle, segmentsOf,
  showLegendOf, visibleSlices, wedges,
} from "./pie-chart";

/** p.309-310's Pie Chart. */

const GROUPS = [
  { value: "open", count: 3 },
  { value: "closed", count: 1 },
];

describe("p.310's aggregation", () => {
  it("offers five of p.310's six", () => {
    // This read `["count"]` until §227, because a grouped sum would have been
    // computed differently by the two stores (decision 0006). §226 and §227
    // shipped the four numeric ones. `count_distinct` — p.310's "approximate
    // unique count" — stays out: per bucket it is a question about a *third*
    // property nobody has named, so the control would have nowhere to put its
    // argument.
    expect(Object.keys(AGGREGATIONS)).toEqual(["count", "sum", "avg", "min", "max"]);
    expect(DEFAULT_AGGREGATION).toBe("count");
  });

  it("falls back to counting for an aggregation nothing offers", () => {
    expect(aggregationOf("count_distinct")).toBe("count");
    expect(aggregationOf(undefined)).toBe("count");
    expect(aggregationOf("sum")).toBe("sum");
  });

  it("knows which aggregations need a property to run over", () => {
    expect(needsProperty("count")).toBe(false);
    for (const name of ["sum", "avg", "min", "max"]) {
      expect(needsProperty(name)).toBe(true);
    }
    // And an unknown one is a count, so it needs nothing - the fallback and
    // this question have to agree, or the panel shows a property field for a
    // request that will not carry one.
    expect(needsProperty("count_distinct")).toBe(false);
  });
});

describe("what the pie asks the server for", () => {
  it("sends a count with no property", () => {
    expect(aggregationRequest("count", "reading")).toEqual({
      aggregation: "count", aggregation_property: null,
    });
  });

  it("sends a numeric aggregation with the property it runs over", () => {
    expect(aggregationRequest("sum", " reading ")).toEqual({
      aggregation: "sum", aggregation_property: "reading",
    });
  });

  it("sends nothing at all while the setting is unfinished", () => {
    // A `sum` with no property yet is a 422 about property types shown in
    // place of a chart, for what is a panel somebody is still filling in.
    expect(aggregationRequest("sum", "")).toBeNull();
    expect(aggregationRequest("avg", "   ")).toBeNull();
    expect(aggregationRequest("min", null)).toBeNull();
  });
});

describe("p.310's legend", () => {
  it("has the four positions p.310 names and defaults to the right", () => {
    expect(Object.keys(LEGEND_POSITIONS).sort()).toEqual(["bottom", "left", "right", "top"]);
    expect(DEFAULT_LEGEND_POSITION).toBe("right");
    expect(legendPositionOf(undefined)).toBe("right");
    expect(legendPositionOf("bottom")).toBe("bottom");
  });

  it("falls back for a position the widget does not have", () => {
    expect(legendPositionOf("middle")).toBe("right");
    expect(legendPositionOf("constructor")).toBe("right");
    expect(legendPositionOf(4)).toBe("right");
  });

  it("is shown unless a document turns it off", () => {
    // **On by default is an argument**: a pie with no legend is coloured
    // wedges nobody can name, and every slice's identity is in it.
    expect(showLegendOf(undefined)).toBe(true);
    expect(showLegendOf(true)).toBe(true);
    expect(showLegendOf(false)).toBe(false);
    expect(showLegendOf("false")).toBe(true);
  });
});

describe("p.310's radius", () => {
  it("is a pie at zero and a donut above it", () => {
    expect(innerRadiusOf(0)).toBe(0);
    expect(innerRadiusOf(0.5)).toBe(0.5);
  });

  it("clamps what a document can name", () => {
    // A ring of zero width is not a chart.
    expect(MAX_INNER_RADIUS).toBe(0.9);
    expect(innerRadiusOf(1)).toBe(0.9);
    expect(innerRadiusOf(4)).toBe(0.9);
    expect(innerRadiusOf(-1)).toBe(0);
    expect(innerRadiusOf("abc")).toBe(0);
    expect(innerRadiusOf(undefined)).toBe(0);
  });
});

describe("p.310's segment overrides", () => {
  it("reads value, label, colour and hidden", () => {
    expect(segmentsOf([{ value: "open", label: "Open ", color: " #f00 ", hidden: true }]))
      .toEqual([{ value: "open", label: "Open", color: "#f00", hidden: true }]);
  });

  it("is empty for anything that is not a list", () => {
    expect(segmentsOf(undefined)).toEqual([]);
    expect(segmentsOf({ value: "open" })).toEqual([]);
  });

  it("drops an entry that names no segment", () => {
    // An entry with no value would otherwise override the slice whose value
    // happens to be the empty string.
    expect(segmentsOf([null, 7, { label: "x" }, { value: "" }, { value: "open" }]))
      .toEqual([{ value: "open" }]);
  });

  it("drops a blank override rather than blanking a slice's name", () => {
    expect(segmentsOf([{ value: "open", label: "  ", color: "" }]))
      .toEqual([{ value: "open" }]);
  });

  it("only hides on an actual true", () => {
    expect(segmentsOf([{ value: "open", hidden: "yes" }])).toEqual([{ value: "open" }]);
  });
});

describe("which slices are drawn", () => {
  it("keeps the server's order and names each by its value", () => {
    expect(visibleSlices(GROUPS, [])).toEqual([
      { value: "open", label: "open", count: 3, size: 3, color: null },
      { value: "closed", label: "closed", count: 1, size: 1, color: null },
    ]);
  });

  it("applies a label and a colour to the segment they name", () => {
    const slices = visibleSlices(GROUPS, [{ value: "closed", label: "Done", color: "#0f0" }]);
    expect(slices[1]).toEqual({
      value: "closed", label: "Done", count: 1, size: 1, color: "#0f0",
    });
    // And the other slice is untouched, which is what makes it an override.
    expect(slices[0]?.label).toBe("open");
    expect(slices[0]?.color).toBeNull();
  });

  it("removes a hidden segment entirely", () => {
    expect(visibleSlices(GROUPS, [{ value: "closed", hidden: true }]).map((s) => s.value))
      .toEqual(["open"]);
  });

  it("treats a negative count as nothing", () => {
    expect(visibleSlices([{ value: "odd", count: -5 }], [])[0]?.count).toBe(0);
  });

  it("draws the metric when there is one, and keeps the count beside it", () => {
    // **Two numbers, not one.** A legend reading "north — 12 objects" beside a
    // wedge sized by their total capacity tells a reader two true things;
    // overwriting `count` would make it tell them one thing twice.
    const slices = visibleSlices(
      [{ value: "north", count: 12, metric: 400 },
       { value: "south", count: 40, metric: 100 }], [],
    );
    expect(slices.map((s) => s.size)).toEqual([400, 100]);
    expect(slices.map((s) => s.count)).toEqual([12, 40]);
  });

  it("falls back to the count when no metric came back", () => {
    // p.310's count is the default, and `/object-sets/group` answers `null`
    // for the metric then - a slice of `null` would be no slice at all.
    expect(visibleSlices([{ value: "a", count: 3, metric: null }], [])[0]?.size).toBe(3);
    expect(visibleSlices([{ value: "a", count: 3 }], [])[0]?.size).toBe(3);
  });

  it("treats a negative metric as nothing to draw", () => {
    // A sum over a column of debits is a real answer and a pie is the wrong
    // picture of it: an angle has no sign, so a -40 wedge beside a 100 one
    // would either vanish or eat its neighbour. The legend's count stays true.
    const slice = visibleSlices([{ value: "owed", count: 2, metric: -40 }], [])[0];
    expect(slice?.size).toBe(0);
    expect(slice?.count).toBe(2);
  });

  it("ignores a metric that is not a finite number", () => {
    for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, "40" as unknown as number]) {
      expect(visibleSlices([{ value: "a", count: 7, metric: bad }], [])[0]?.size).toBe(7);
    }
  });
});

describe("a pie sized by a metric", () => {
  it("shares the circle by the metric, not by how many objects are in each slice", () => {
    // The assertion that separates the two: `north` has fewer objects and the
    // larger total, so a wedge drawn from the count would be the smaller one.
    const drawn = wedges(visibleSlices(
      [{ value: "north", count: 1, metric: 75 },
       { value: "south", count: 9, metric: 25 }], [],
    ));
    expect(drawn[0]?.share).toBeCloseTo(0.75);
    expect(drawn[1]?.share).toBeCloseTo(0.25);
  });
});

describe("where each slice sits", () => {
  it("starts at twelve o'clock and runs clockwise", () => {
    const drawn = wedges(visibleSlices(GROUPS, []));
    expect(drawn).toHaveLength(2);
    const [first, second] = drawn as [(typeof drawn)[0], (typeof drawn)[0]];
    expect(first.start).toBeCloseTo(-Math.PI / 2);
    // Three of four objects: three quarters of the circle.
    expect(first.share).toBeCloseTo(0.75);
    expect(first.end).toBeCloseTo(-Math.PI / 2 + 1.5 * Math.PI);
    // The next slice picks up exactly where the last one stopped — a gap or an
    // overlap here is a chart that lies by a visible amount.
    expect(second.start).toBeCloseTo(first.end);
    expect(second.end).toBeCloseTo(-Math.PI / 2 + 2 * Math.PI);
  });

  it("shares out the visible total, not the original one", () => {
    // **The reason hidden segments are dropped rather than skipped.** With
    // `closed` hidden, `open` is the whole circle — if the share were still of
    // four objects it would cover three quarters and leave a gap.
    const slices = visibleSlices(GROUPS, [{ value: "closed", hidden: true }]);
    expect(wedges(slices)[0]?.share).toBeCloseTo(1);
  });

  it("draws nothing when there is nothing to draw", () => {
    expect(wedges([])).toEqual([]);
    expect(wedges(visibleSlices([{ value: "none", count: 0 }], []))).toEqual([]);
  });
});

describe("the arc geometry", () => {
  it("puts twelve o'clock straight above the centre", () => {
    const top = pointOnCircle(100, 100, 50, -Math.PI / 2);
    expect(top.x).toBeCloseTo(100);
    expect(top.y).toBeCloseTo(50);
    // And three o'clock to its right, which pins the direction of travel.
    const right = pointOnCircle(100, 100, 50, 0);
    expect(right.x).toBeCloseTo(150);
    expect(right.y).toBeCloseTo(100);
  });

  it("draws a wedge from the centre when there is no inner radius", () => {
    const d = arcPath({ cx: 100, cy: 100, r: 50, inner: 0,
                        start: -Math.PI / 2, end: 0 });
    // Starts at the centre, so the slice is filled to the middle.
    expect(d.startsWith("M 100 100")).toBe(true);
    expect(d).toContain("L 100 50");
    expect(d).toContain("A 50 50 0 0 1 150 100");
    expect(d.endsWith("Z")).toBe(true);
  });

  it("sets the large-arc flag only past a half turn", () => {
    const small = arcPath({ cx: 0, cy: 0, r: 10, inner: 0, start: 0, end: Math.PI / 2 });
    const large = arcPath({ cx: 0, cy: 0, r: 10, inner: 0, start: 0, end: Math.PI * 1.5 });
    expect(small).toContain("A 10 10 0 0 1");
    expect(large).toContain("A 10 10 0 1 1");
  });

  it("draws a ring rather than a wedge when there is an inner radius", () => {
    const d = arcPath({ cx: 100, cy: 100, r: 50, inner: 0.5,
                        start: -Math.PI / 2, end: 0 });
    // **Never through the centre**: an annulus segment is two arcs joined, and
    // a donut whose slices met in the middle would just be a pie.
    expect(d.startsWith("M 100 50")).toBe(true);
    expect(d).not.toContain("M 100 100");
    // The inner arc is drawn back the other way — sweep 0 — or the edges cross
    // and the browser fills the shape inside out.
    expect(d).toContain("A 25 25 0 0 0");
  });

  it("draws a whole circle for a single slice", () => {
    // **An arc from a point back to itself draws nothing**, and one group is a
    // common state — every object with the same status — so the tidiest data
    // would produce an empty chart.
    const d = arcPath({ cx: 0, cy: 0, r: 10, inner: 0,
                        start: -Math.PI / 2, end: -Math.PI / 2 + Math.PI * 2 });
    expect(d).toContain("A 10 10 0 1 1");
    expect(d).not.toContain("L 0 0");
    expect(d).not.toContain("M 0 0 ");
    // **And the arc must not end where it began.** That is the whole failure
    // this case exists for, and asserting only the flag missed it: a path from
    // (0,-10) arcing back to (0,-10) contains the same `A 10 10 0 1 1` and
    // draws nothing at all. The harness said so.
    expect(d.startsWith("M 0 -10")).toBe(true);
    expect(d.endsWith("0 -10 Z")).toBe(false);
  });

  it("draws a whole ring for a single slice of a donut", () => {
    const d = arcPath({ cx: 0, cy: 0, r: 10, inner: 0.5,
                        start: -Math.PI / 2, end: -Math.PI / 2 + Math.PI * 2 });
    expect(d).toContain("A 10 10 0 1 1");
    expect(d).toContain("A 5 5 0 1 0");
  });

  it("clamps an inner radius the caller did not read through the model", () => {
    const d = arcPath({ cx: 0, cy: 0, r: 10, inner: 5, start: 0, end: 1 });
    // 0.9 of 10, not 50 — a ring wider than the chart would draw outside it.
    expect(d).toContain("A 9 9 0");
  });
});

describe("what a slice's share reads as", () => {
  it("is a percentage to one decimal place", () => {
    expect(percentLabel(0.3333333)).toBe("33.3%");
    expect(percentLabel(1)).toBe("100.0%");
    expect(percentLabel(0)).toBe("0.0%");
  });
});
