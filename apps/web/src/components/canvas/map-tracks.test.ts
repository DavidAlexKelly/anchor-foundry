import { describe, expect, it } from "vitest";

import {
  extentOf, instantOf, nextPlayback, pauseCrossed, pausesOf, positionAt, selectedTimeOf,
  selectedTimeText, timeLabel, timelineControls, timelineSpan, trackShape, windowOf, withinWindow,
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

describe("the rest of p.303's time configuration (§558)", () => {
  it("reads a window from two variables, either end open", () => {
    expect(windowOf("2026-01-01T01:00:00Z", "")).toEqual({ start: hour(1), end: null });
    expect(windowOf(null, "2026-01-01")).toEqual({ start: null, end: hour(0) });
  });

  it("keeps a track's fixes inside the window, ends included", () => {
    expect(withinWindow(track, { start: hour(1), end: null })).toEqual(track.slice(1));
    expect(withinWindow(track, { start: null, end: hour(1) })).toEqual(track.slice(0, 2));
    expect(withinWindow(track, { start: null, end: null })).toEqual(track);
  });

  it("spans the window where it says and the tracks where it does not", () => {
    const extent = { start: hour(0), end: hour(2) };
    expect(timelineSpan(extent, { start: hour(1), end: null })).toEqual({ start: hour(1), end: hour(2) });
    expect(timelineSpan(null, { start: hour(1), end: hour(3) })).toEqual({ start: hour(1), end: hour(3) });
    expect(timelineSpan(null, { start: hour(1), end: null })).toBeNull();
    expect(timelineSpan(extent, { start: hour(3), end: hour(1) })).toBeNull();
  });

  it("plays across the span in steps, from the start, and stops at the end", () => {
    const span = { start: 0, end: 2000 };
    expect(nextPlayback(null, span)).toEqual({ time: 10, done: false });
    expect(nextPlayback(1000, span)).toEqual({ time: 1010, done: false });
    expect(nextPlayback(1995, span)).toEqual({ time: 2000, done: true });
    // From the end, playing again starts over.
    expect(nextPlayback(2000, span)).toEqual({ time: 10, done: false });
    expect(nextPlayback(null, { start: 5, end: 5 })).toEqual({ time: 5, done: true });
  });

  it("pauses at the first auto-pause time a step crosses", () => {
    expect(pauseCrossed(100, 200, [150, 180, 300])).toBe(150);
    expect(pauseCrossed(100, 200, [100])).toBeNull();
    expect(pauseCrossed(100, 200, [200])).toBe(200);
    expect(pauseCrossed(null, 50, [0, 60])).toBe(0);
    expect(pausesOf(["2026-01-01T01:00:00Z", "nope", 3])).toEqual([hour(1)]);
    expect(pausesOf("2026-01-01")).toEqual([]);
  });

  it("labels the time in UTC as stored, or in the reader's zone and format", () => {
    expect(timeLabel(hour(1))).toBe("2026-01-01T01:00:00Z");
    expect(timeLabel(hour(1), "local", "24")).not.toMatch(/AM|PM/);
    expect(timeLabel(hour(1) + 12 * 3_600_000, "local", "12")).toMatch(/AM|PM/);
    expect(timeLabel(hour(1), "local", "local")).not.toBe("2026-01-01T01:00:00Z");
  });
});

describe("p.303's user controls on the timeline (§576)", () => {
  it("offers the cursor and View latest unless turned off", () => {
    expect(timelineControls(undefined, undefined)).toEqual({ cursor: true, latest: true });
    expect(timelineControls(true, true)).toEqual({ cursor: true, latest: true });
    expect(timelineControls(true, false)).toEqual({ cursor: true, latest: false });
  });

  it("offers no View latest without the cursor, which p.303 nests it under", () => {
    expect(timelineControls(false, true)).toEqual({ cursor: false, latest: false });
    expect(timelineControls(false, undefined)).toEqual({ cursor: false, latest: false });
  });
});
