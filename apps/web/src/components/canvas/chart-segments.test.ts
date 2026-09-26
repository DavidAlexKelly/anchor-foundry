import { describe, expect, it } from "vitest";

import { segmentLayout, segmentModeOf, segmentedFrom } from "./chart-segments";

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
