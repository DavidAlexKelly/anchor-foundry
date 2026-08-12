import { describe, expect, it } from "vitest";
import { plot } from "./series-plot";

const BOX = { width: 100, height: 100, padding: 0 };

describe("plot", () => {
  it("returns null when there is nothing to draw", () => {
    // Distinct from a flat line: an empty chart and a chart of nothing are
    // different sentences, and the caller says a different one for each.
    expect(plot([], BOX)).toBeNull();
  });

  it("spreads points across the box by time and value", () => {
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: 0 },
        { at: "2026-01-03T00:00:00Z", value: 10 },
      ],
      BOX,
    )!;
    expect(laid.points[0]!.x).toBe(0);
    expect(laid.points[1]!.x).toBe(100);
    // SVG's y grows downward, so the larger value gets the smaller y.
    expect(laid.points[0]!.y).toBe(100);
    expect(laid.points[1]!.y).toBe(0);
  });

  it("puts a flat series in the middle rather than dividing by zero", () => {
    // A sensor reading the same number all week is the most ordinary series
    // there is, and (v - min) / (max - min) is 0/0 for every point of it.
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: 7 },
        { at: "2026-01-02T00:00:00Z", value: 7 },
      ],
      BOX,
    )!;
    expect(laid.points.every((p) => p.y === 50)).toBe(true);
    expect(laid.points.every((p) => Number.isFinite(p.y))).toBe(true);
  });

  it("draws a single reading rather than skipping it", () => {
    // One reading is a fact; an empty chart would say there were none.
    const laid = plot([{ at: "2026-01-01T00:00:00Z", value: 3 }], BOX)!;
    expect(laid.points).toHaveLength(1);
    expect(laid.points[0]!.x).toBe(50);
    expect(laid.points[0]!.y).toBe(50);
  });

  it("drops a point that will not parse rather than plotting it as zero", () => {
    // A gap in a line is honest; a zero is a reading that never happened.
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: 5 },
        { at: "not a date", value: 9 },
        { at: "2026-01-02T00:00:00Z", value: null },
        { at: "2026-01-03T00:00:00Z", value: 15 },
      ],
      BOX,
    )!;
    expect(laid.points.map((p) => p.value)).toEqual([5, 15]);
  });

  it("accepts numeric strings, which is how they arrive from the query", () => {
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: "5" },
        { at: "2026-01-02T00:00:00Z", value: "15" },
      ],
      BOX,
    )!;
    expect(laid.min).toBe(5);
    expect(laid.max).toBe(15);
  });

  it("builds a path that moves once and then lines", () => {
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: 1 },
        { at: "2026-01-02T00:00:00Z", value: 2 },
        { at: "2026-01-03T00:00:00Z", value: 3 },
      ],
      BOX,
    )!;
    expect(laid.path.startsWith("M")).toBe(true);
    expect(laid.path.match(/M/g)).toHaveLength(1);
    expect(laid.path.match(/L/g)).toHaveLength(2);
  });

  it("keeps every point inside the box once padding is applied", () => {
    const laid = plot(
      [
        { at: "2026-01-01T00:00:00Z", value: 0 },
        { at: "2026-01-02T00:00:00Z", value: 100 },
      ],
      { width: 100, height: 100, padding: 10 },
    )!;
    for (const point of laid.points) {
      expect(point.x).toBeGreaterThanOrEqual(10);
      expect(point.x).toBeLessThanOrEqual(90);
      expect(point.y).toBeGreaterThanOrEqual(10);
      expect(point.y).toBeLessThanOrEqual(90);
    }
  });

  it("reports the range it drew", () => {
    const laid = plot(
      [
        { at: "2026-01-02T00:00:00Z", value: 4 },
        { at: "2026-01-01T00:00:00Z", value: 9 },
      ],
      BOX,
    )!;
    expect([laid.min, laid.max]).toEqual([4, 9]);
    expect(laid.first).toBeLessThan(laid.last);
  });
});
