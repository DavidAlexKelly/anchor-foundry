import { describe, expect, it } from "vitest";
import { emptyReason, latest, path, range, toPoints, usable, type Point } from "./sparkline";

const BOX = { width: 100, height: 20 };

function at(day: number, value: number | null): Point {
  return { at: `2026-01-${String(day).padStart(2, "0")}T00:00:00Z`, value };
}

describe("which readings are drawn", () => {
  it("drops a null rather than plotting it as zero", () => {
    // "No reading" and "a reading of nothing" are different claims, and a
    // gap in a sensor's history drawn as a dive to zero is the wrong one.
    expect(usable([at(1, 5), at(2, null), at(3, 7)]).map((p) => p.value)).toEqual([5, 7]);
  });

  it("drops a value that is not a finite number", () => {
    const rough = [at(1, 5), { at: "2026-01-02T00:00:00Z", value: NaN }, at(3, 7)];
    expect(usable(rough)).toHaveLength(2);
  });

  it("drops a point whose instant cannot be read", () => {
    // These arrive from a dataset column, so §212's caution applies: the
    // engine hands back what the file held.
    expect(usable([{ at: "not a date", value: 5 }, at(2, 7)])).toHaveLength(1);
  });
});

describe("the vertical range", () => {
  it("spans the low and the high", () => {
    expect(range(usable([at(1, 2), at(2, 9), at(3, 5)]))).toEqual({ low: 2, high: 9 });
  });

  it("gives a flat series a band rather than nothing", () => {
    // **Dividing by a zero range is how every point lands on one pixel, or on
    // NaN.** A genuinely flat line should be drawn flat, through the middle.
    const flat = range(usable([at(1, 4), at(2, 4)]));
    expect(flat.high).toBeGreaterThan(flat.low);
    expect((flat.low + flat.high) / 2).toBe(4);
  });

  it("has an answer for no readings at all", () => {
    expect(range([])).toEqual({ low: 0, high: 1 });
  });
});

describe("the path", () => {
  it("starts with a move and continues with lines", () => {
    const d = path([at(1, 0), at(2, 10), at(3, 5)], BOX);
    expect(d.startsWith("M")).toBe(true);
    expect(d.split("L")).toHaveLength(3);
  });

  it("spans the full width and inverts the y axis", () => {
    // The low value sits at the bottom of the box, which is the *largest* y
    // in SVG - a path that forgot the inversion draws every series upside
    // down and still looks like a chart.
    const d = path([at(1, 0), at(2, 10)], BOX);
    expect(d).toBe("M0 20 L100 0");
  });

  it("spaces points by time rather than by index", () => {
    // A sensor quiet for a week then reporting twice in an hour: on index
    // spacing the week and the hour are the same step, which is a different
    // picture of the same history.
    // The whole path, because picking the x values out of it with a regex is
    // how the first version of this test matched the y values too and failed
    // against correct geometry. Ten days of span: the first step is one day
    // (x=10 of 100) and the last is nine (x=100).
    expect(path([at(1, 0), at(2, 10), at(11, 0)], BOX)).toBe("M0 20 L10 0 L100 20");
    // Index spacing would put the middle point halfway.
    expect(path([at(1, 0), at(2, 10), at(11, 0)], BOX)).not.toContain("L50");
  });

  it("draws nothing from a single reading", () => {
    // One reading has no shape, and a dot among lines reads as a different
    // kind of thing rather than as a shorter history.
    expect(path([at(1, 5)], BOX)).toBe("");
    expect(path([], BOX)).toBe("");
    expect(path([at(1, 5), at(2, null)], BOX)).toBe("");
  });

  it("does not divide by zero when every reading shares an instant", () => {
    const d = path([at(1, 1), at(1, 9)], BOX);
    expect(d).not.toContain("NaN");
    expect(d).toBe("M0 20 L0 0");
  });

  it("rounds, because a path is markup", () => {
    const d = path([at(1, 0), at(2, 1), at(4, 3)], BOX);
    expect(d).not.toMatch(/\d\.\d{3}/);
  });
});

describe("the latest value", () => {
  it("is the last reading", () => {
    expect(latest([at(1, 5), at(2, 7)])).toBe(7);
  });

  it("skips a trailing null rather than reporting nothing", () => {
    // A series whose final row is null still has a latest value.
    expect(latest([at(1, 5), at(2, 7), at(3, null)])).toBe(7);
  });

  it("is null when there is nothing to report", () => {
    expect(latest([])).toBeNull();
    expect(latest([at(1, null)])).toBeNull();
  });
});

describe("why a cell is empty", () => {
  it("tells no readings apart from one reading", () => {
    // Different answers: one is "this object has no series", the other is
    // "this series has a single point". An empty cell gives neither.
    expect(emptyReason([])).toBe("No readings");
    expect(emptyReason([at(1, 5)])).toBe("One reading");
    expect(emptyReason([at(1, 5), at(2, 6)])).toBeNull();
  });
});


describe("coercing what the engine returned", () => {
  it("takes a numeric string, because a CSV column is strings all the way down", () => {
    // Refusing them would empty every sparkline over an uploaded file.
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: "12.5" }]))
      .toEqual([{ at: "2026-01-01T00:00:00Z", value: 12.5 }]);
  });

  it("turns a value that is not a number into null, not NaN", () => {
    // `null` is what `usable` already drops for the right reason; `NaN` is a
    // number that has to be caught a second time.
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: "abc" }])[0]?.value).toBeNull();
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: null }])[0]?.value).toBeNull();
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: {} }])[0]?.value).toBeNull();
  });

  it("keeps an empty string out of zero", () => {
    // `Number("")` is 0 - a missing reading that would draw as a real
    // measurement, which is the whole trap this module exists around.
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: "" }])[0]?.value).toBeNull();
    expect(toPoints([{ at: "2026-01-01T00:00:00Z", value: "   " }])[0]?.value).toBeNull();
  });

  it("survives no points at all", () => {
    expect(toPoints(undefined)).toEqual([]);
    expect(toPoints([])).toEqual([]);
  });

  it("hands the result straight to the rest of the module", () => {
    // The point of one coercion: what comes out is what `usable` and `path`
    // already understand.
    const points = toPoints([
      { at: "2026-01-01T00:00:00Z", value: "0" },
      { at: "2026-01-02T00:00:00Z", value: "" },
      { at: "2026-01-03T00:00:00Z", value: 10 },
    ]);
    expect(usable(points)).toHaveLength(2);
    expect(path(points, BOX)).toBe("M0 20 L100 0");
  });
});
