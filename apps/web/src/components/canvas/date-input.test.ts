/** §513: p.444's Date Input, single date or range. */
import { describe, expect, it } from "vitest";

import { DATE_INPUT_MODES, isDay, orderedRange, rangeDays, rangeText, shownDay } from "./date-input";

describe("isDay and shownDay", () => {
  it("accepts a real calendar day and nothing else", () => {
    expect(isDay("2026-09-26")).toBe(true);
    expect(isDay("2024-02-29")).toBe(true);
    for (const v of ["2026-02-30", "2026-13-01", "2026-9-26", "2026-09-26T00:00", "", null, 20260926]) {
      expect(isDay(v), String(v)).toBe(false);
    }
  });

  it("shows a day, and a blank for anything else", () => {
    expect(shownDay("2026-09-26")).toBe("2026-09-26");
    expect(shownDay("yesterday")).toBe("");
    expect(shownDay(undefined)).toBe("");
  });
});

describe("orderedRange", () => {
  it("keeps a range in order, swapping one picked backwards", () => {
    expect(orderedRange("2026-01-01", "2026-01-05")).toEqual(["2026-01-01", "2026-01-05"]);
    expect(orderedRange("2026-01-05", "2026-01-01")).toEqual(["2026-01-01", "2026-01-05"]);
    expect(orderedRange("2026-01-05", "2026-01-05")).toEqual(["2026-01-05", "2026-01-05"]);
  });

  it("keeps an open end open", () => {
    expect(orderedRange("2026-01-05", "")).toEqual(["2026-01-05", null]);
    expect(orderedRange("", "2026-01-01")).toEqual([null, "2026-01-01"]);
    expect(orderedRange("", "")).toEqual([null, null]);
  });
});

describe("rangeDays and rangeText", () => {
  it("counts both ends", () => {
    expect(rangeDays("2026-01-01", "2026-01-01")).toBe(1);
    expect(rangeDays("2026-01-01", "2026-01-03")).toBe(3);
    // Across a clock change: days, not hours.
    expect(rangeDays("2026-03-01", "2026-03-31")).toBe(31);
    expect(rangeDays("2026-01-01", null)).toBeNull();
  });

  it("says the length, or which end is open", () => {
    expect(rangeText("2026-01-01", "2026-01-03")).toBe("3 days, 2026-01-01 to 2026-01-03");
    expect(rangeText("2026-01-01", "2026-01-01")).toBe("1 day, 2026-01-01 to 2026-01-01");
    expect(rangeText("2026-01-01", null)).toBe("From 2026-01-01, no end");
    expect(rangeText(undefined, "2026-01-03")).toBe("Until 2026-01-03, no start");
    expect(rangeText(null, null)).toBe("");
  });

  it("offers the two modes p.444 names", () => {
    expect(DATE_INPUT_MODES).toEqual({ single: "Single date", range: "Date range" });
  });
});
