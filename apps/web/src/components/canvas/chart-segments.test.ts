import { describe, expect, it } from "vitest";

import {
  legendEntryAt, legendInset, segmentLayout, segmentLegendPositionOf, segmentModeOf, segmentName,
  segmentedFrom, sortSegmented,
  stackSegments,
} from "./chart-segments";

const data = segmentedFrom({
  rows: [{ value: "north" }, { value: "south" }, { value: "east" }],
  columns: [{ value: "open" }, { value: "closed" }],
  cells: [[3, 1], [0, 2], [0]],
});

describe("segmentedFrom", () => {
  it("reads the cross-tab as categories by segments, short rows as zeroes", () => {
    expect(data).toEqual({
      categories: ["north", "south", "east"],
      segments: ["open", "closed"],
      values: [[3, 1], [0, 2], [0, 0]],
    });
  });
});

describe("segmentLayout (p.282's Segment overrides)", () => {
  it("stacks from zero, and the axis reaches the tallest total", () => {
    const { bars, max } = segmentLayout(data, "stacked");
    expect(bars.map((b) => [b.category, b.segment, b.from, b.to, b.offset, b.width])).toEqual([
      [0, 0, 0, 3, 0, 1], [0, 1, 3, 4, 0, 1], [1, 1, 0, 2, 0, 1],
    ]);
    expect(max).toBe(4);
  });

  it("shares each category out to one, and draws nothing for an empty one", () => {
    const { bars, max } = segmentLayout(data, "percentage");
    expect(bars.map((b) => [b.category, b.from, b.to])).toEqual([
      [0, 0, 0.75], [0, 0.75, 1], [1, 0, 1],
    ]);
    expect(max).toBe(1);
    expect(segmentLayout(segmentedFrom({ rows: [{ value: "x" }], columns: [{ value: "a" }], cells: [[0]] }),
      "percentage").max).toBe(0);
  });

  it("puts segments side by side, and the axis reaches the tallest one", () => {
    const { bars, max } = segmentLayout(data, "grouped");
    expect(bars.map((b) => [b.category, b.segment, b.from, b.to, b.offset, b.width])).toEqual([
      [0, 0, 0, 3, 0, 0.5], [0, 1, 0, 1, 0.5, 0.5], [1, 1, 0, 2, 0.5, 0.5],
    ]);
    expect(max).toBe(3);
    expect(bars[0]!.value).toBe(3);
  });

  it("is stacked unless it says otherwise", () => {
    expect(segmentModeOf("grouped")).toBe("grouped");
    expect(segmentModeOf("percentage")).toBe("percentage");
    expect(segmentModeOf("pie")).toBe("stacked");
    expect(segmentModeOf(undefined)).toBe("stacked");
  });
});

describe("the segmented legend (p.284's positions, p.282's display override)", () => {
  const frame = { width: 640, height: 260 };
  const plot = { x: 48, y: 12 };

  it("is at the bottom unless placed", () => {
    expect(segmentLegendPositionOf(undefined)).toBe("bottom");
    expect(segmentLegendPositionOf("toString")).toBe("bottom");
    expect(segmentLegendPositionOf("left")).toBe("left");
    expect(segmentLegendPositionOf("top")).toBe("top");
  });

  it("takes the edge it is on: a row of six per 16px, or a 120px column", () => {
    expect(legendInset(3, "bottom")).toEqual({ top: 0, right: 0, bottom: 22, left: 0 });
    expect(legendInset(7, "bottom").bottom).toBe(38);
    expect(legendInset(6, "top")).toEqual({ top: 22, right: 0, bottom: 0, left: 0 });
    expect(legendInset(12, "left")).toEqual({ top: 0, right: 0, bottom: 0, left: 120 });
    expect(legendInset(2, "right")).toEqual({ top: 0, right: 120, bottom: 0, left: 0 });
    expect(legendInset(0, "left")).toEqual({ top: 0, right: 0, bottom: 0, left: 0 });
  });

  it("lays rows left to right from the legend's top", () => {
    // Bottom, two rows: the first row sits a row above the last.
    expect(legendEntryAt(0, 7, "bottom", plot, frame)).toEqual({ x: 48, y: 238 });
    expect(legendEntryAt(5, 7, "bottom", plot, frame)).toEqual({ x: 48 + 5 * 96, y: 238 });
    expect(legendEntryAt(6, 7, "bottom", plot, frame)).toEqual({ x: 48, y: 254 });
    expect(legendEntryAt(0, 2, "bottom", plot, frame)).toEqual({ x: 48, y: 254 });
    expect(legendEntryAt(7, 8, "top", plot, frame)).toEqual({ x: 48 + 96, y: 30 });
    expect(legendEntryAt(1, 3, "left", plot, frame)).toEqual({ x: 8, y: 38 });
    expect(legendEntryAt(2, 3, "right", plot, frame)).toEqual({ x: 528, y: 54 });
  });

  it("names a segment by its override, else its value", () => {
    const names = { north: "Northern sites", south: "  ", east: 3 };
    expect(segmentName("north", names)).toBe("Northern sites");
    expect(segmentName("south", names)).toBe("south");
    expect(segmentName("east", names)).toBe("east");
    expect(segmentName("west", names)).toBe("west");
    expect(segmentName("toString", {})).toBe("toString");
    expect(segmentName("north", null)).toBe("north");
    expect(segmentName("north", ["Northern"])).toBe("north");
    // An array is not a set of names, even where a value reads as its index.
    expect(segmentName("0", ["Zero"])).toBe("0");
    expect(segmentName("north", { north: " Up north " })).toBe("Up north");
  });
});

describe("sortSegmented (p.283's Sort by, on a segmented chart)", () => {
  const grid = {
    categories: ["Site 10", "site 2", "Site 1"],
    segments: ["a", "b"],
    values: [[1, 1], [5, 0], [0, 3]],
  };

  it("keeps the cross-tab's order unless told otherwise", () => {
    expect(sortSegmented(grid, "source")).toEqual(grid);
  });

  it("orders by each bar's whole height, its rows with it", () => {
    const tallest = sortSegmented(grid, "valueDesc");
    expect(tallest.categories).toEqual(["site 2", "Site 1", "Site 10"]);
    expect(tallest.values).toEqual([[5, 0], [0, 3], [1, 1]]);
    expect(tallest.segments).toEqual(["a", "b"]);
    expect(sortSegmented(grid, "valueAsc").categories).toEqual(["Site 10", "Site 1", "site 2"]);
  });

  it("orders by key as a person reads it", () => {
    expect(sortSegmented(grid, "keyAsc").categories).toEqual(["Site 1", "site 2", "Site 10"]);
    expect(sortSegmented(grid, "keyDesc").values).toEqual([[1, 1], [5, 0], [0, 3]]);
  });
});

describe("p.281's Stacked area (§601)", () => {
  it("draws each segment at the running total, a missing value adding nothing", () => {
    expect(stackSegments({ categories: ["a", "b"], segments: ["x", "y", "z"],
      values: [[1, 2, 3], [4, NaN, 1]] })).toEqual({
      categories: ["a", "b"], segments: ["x", "y", "z"], values: [[1, 3, 6], [4, 4, 5]] });
  });
});
