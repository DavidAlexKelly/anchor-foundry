import { describe, expect, it } from "vitest";

import {
  extentOf, instantOf, positionAt, selectedTimeOf, selectedTimeText, trackShape,
} from "./map-tracks";

const track = [
  { at: "2026-01-01T00:00:00", lat: 51.5, lon: -0.12 },
  { at: "2026-01-01T01:00:00", lat: 52.5, lon: -1.12 },
  { at: "2026-01-01T02:00:00", lat: 53.5, lon: -2.12 },
];
const hour = (h: number) => Date.parse(`2026-01-01T0${h}:00:00Z`);

describe("p.303's timeline over tracks (§557)", () => {
  it("reads a track's zoneless instant as UTC", () => {
    expect(instantOf("2026-01-01T01:00:00")).toBe(hour(1));
    expect(instantOf("2026-01-01T01:00:00+01:00")).toBe(hour(0));
    expect(instantOf("2026-01-01T01:00:00Z")).toBe(hour(1));
  });

  it("reads a selected time from a timestamp or a date variable", () => {
    expect(selectedTimeOf("2026-01-01T01:30:00Z")).toBe(hour(1) + 30 * 60_000);
    expect(selectedTimeOf("2026-01-01")).toBe(hour(0));
    expect(selectedTimeOf(" ")).toBeNull();
    expect(selectedTimeOf(null)).toBeNull();
    expect(selectedTimeOf("not a time")).toBeNull();
    expect(selectedTimeText(hour(1))).toBe("2026-01-01T01:00:00.000Z");
  });

  it("draws a track of two or more fixes as a line, in GeoJSON's order", () => {
    expect(trackShape(track.slice(0, 2))).toEqual({
      type: "LineString", coordinates: [[-0.12, 51.5], [-1.12, 52.5]] });
    expect(trackShape(track.slice(0, 1))).toBeNull();
  });

  it("puts the object at its last fix at or before the selected time", () => {
    expect(positionAt(track, hour(1) + 1)).toBe(track[1]);
    expect(positionAt(track, hour(1))).toBe(track[1]);
    expect(positionAt(track, hour(0) - 1)).toBeNull();
    expect(positionAt(track, hour(5))).toBe(track[2]);
    // No selected time is "View latest".
    expect(positionAt(track, null)).toBe(track[2]);
    expect(positionAt([], null)).toBeNull();
  });

  it("spans the timeline from the first fix of any track to the last", () => {
    expect(extentOf([track, [{ at: "2025-12-31T23:00:00", lat: 0, lon: 0 }]]))
      .toEqual({ start: hour(0) - 3_600_000, end: hour(2) });
    expect(extentOf([[], []])).toBeNull();
  });
});
