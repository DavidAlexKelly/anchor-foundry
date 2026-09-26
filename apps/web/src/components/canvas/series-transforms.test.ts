/** §524: time series transforms on a series variable (p.583-586). */
import { describe, expect, it } from "vitest";

import {
  INTEGRATION_METHODS, KIND_LABELS, MAX_SPAN, WINDOW_TYPES, MAX_TRANSFORMS, TIME_UNITS, TRANSFORM_KINDS, WINDOW_AGGREGATES,
  blankTransform, transformProblem, transformText, transformsProblem, transformsText, withKind,
  type SeriesTransform,
} from "./series-transforms";

describe("the vocabulary", () => {
  it("is p.583-586's, as the server takes it", () => {
    expect([...TRANSFORM_KINDS]).toEqual(["cumulative", "periodic", "rolling", "derivative", "integral", "shift", "range"]);
    expect([...WINDOW_TYPES]).toEqual(["start", "end"]);
    expect([...INTEGRATION_METHODS]).toEqual(["linear", "left", "right"]);
    expect([...WINDOW_AGGREGATES]).toEqual(["sum", "avg", "min", "max", "count", "stddev"]);
    expect([...TIME_UNITS]).toEqual(["second", "minute", "hour", "day", "week"]);
    expect([MAX_TRANSFORMS, MAX_SPAN]).toEqual([10, 100_000]);
    expect(KIND_LABELS.derivative).toBe("Rate of change");
  });

  it("starts each kind ready to use", () => {
    expect(blankTransform("cumulative")).toEqual({ kind: "cumulative", aggregate: "sum" });
    expect(blankTransform("rolling")).toEqual({ kind: "rolling", aggregate: "stddev", window: 3, unit: "day" });
    expect(blankTransform("derivative")).toEqual({ kind: "derivative", unit: "day" });
    expect(blankTransform("periodic")).toEqual({
      kind: "periodic", aggregate: "avg", window: 2, unit: "week", align: null, window_type: "start" });
    expect(blankTransform("integral")).toEqual({ kind: "integral", unit: "hour", method: "linear" });
    expect(blankTransform("shift")).toEqual({ kind: "shift", by: 1, unit: "day" });
    expect(blankTransform("range")).toEqual({ kind: "range", start: null, end: null });
  });

  it("keeps a transform whose kind did not change, and starts afresh when it did", () => {
    const rolling: SeriesTransform = { kind: "rolling", aggregate: "max", window: 9, unit: "hour" };
    expect(withKind(rolling, "rolling")).toBe(rolling);
    expect(withKind(rolling, "shift")).toEqual({ kind: "shift", by: 1, unit: "day" });
  });
});

describe("in words", () => {
  it("says each transform", () => {
    expect(transformText({ kind: "cumulative", aggregate: "sum" })).toBe("running sum");
    expect(transformText({ kind: "cumulative", aggregate: "stddev" })).toBe("running standard deviation");
    expect(transformText({ kind: "rolling", aggregate: "avg", window: 1, unit: "week" }))
      .toBe("average over the last 1 week");
    expect(transformText({ kind: "rolling", aggregate: "min", window: 3, unit: "day" }))
      .toBe("minimum over the last 3 days");
    expect(transformText({ kind: "derivative", unit: "hour" })).toBe("change per hour");
    expect(transformText({ kind: "periodic", aggregate: "avg", window: 2, unit: "week", align: null, window_type: "start" }))
      .toBe("average per 2 weeks");
    expect(transformText({ kind: "periodic", aggregate: "sum", window: 1, unit: "day", align: "2026-01-01T06:00", window_type: "end" }))
      .toBe("sum per 1 day, stamped at each window's end, aligned to 2026-01-01T06:00");
    expect(transformText({ kind: "integral", unit: "hour", method: "linear" })).toBe("area in hours");
    expect(transformText({ kind: "integral", unit: "day", method: "left" })).toBe("area in days (left-hand sum)");
    expect(transformText({ kind: "shift", by: 2, unit: "day" })).toBe("shifted 2 days later");
    expect(transformText({ kind: "shift", by: -1, unit: "minute" })).toBe("shifted 1 minute earlier");
    expect(transformText({ kind: "range", start: "2026-01-01T00:00", end: "2026-01-02T00:00" }))
      .toBe("from 2026-01-01T00:00 to 2026-01-02T00:00");
    expect(transformText({ kind: "range", start: "2026-01-01T00:00", end: null })).toBe("from 2026-01-01T00:00");
    expect(transformText({ kind: "range", start: null, end: "2026-01-02T00:00" })).toBe("until 2026-01-02T00:00");
    expect(transformText({ kind: "cumulative", aggregate: "count" })).toBe("running count");
    expect(transformText({ kind: "cumulative", aggregate: "max" })).toBe("running maximum");
  });

  it("says the chain in order, and nothing for none", () => {
    expect(transformsText(undefined)).toBe("");
    expect(transformsText([])).toBe("");
    expect(transformsText([{ kind: "cumulative", aggregate: "sum" }, { kind: "derivative", unit: "day" }]))
      .toBe("running sum, then change per day");
  });
});

describe("what is wrong with one", () => {
  it("allows the ends of a window's and a shift's range", () => {
    expect(transformProblem({ kind: "rolling", aggregate: "sum", window: 1, unit: "day" })).toBeNull();
    expect(transformProblem({ kind: "rolling", aggregate: "sum", window: 100_000, unit: "day" })).toBeNull();
    expect(transformProblem({ kind: "shift", by: -100_000, unit: "day" })).toBeNull();
    expect(transformProblem({ kind: "shift", by: 100_000, unit: "day" })).toBeNull();
    expect(transformProblem({ kind: "cumulative", aggregate: "sum" })).toBeNull();
    expect(transformProblem({ kind: "derivative", unit: "day" })).toBeNull();
  });

  it("refuses a window or shift that is not a whole number in range", () => {
    const window = "The window must be a whole number from 1 to 100,000.";
    for (const bad of [0, 100_001, 1.5, Number.NaN]) {
      expect(transformProblem({ kind: "rolling", aggregate: "sum", window: bad, unit: "day" })).toBe(window);
      expect(transformProblem({ kind: "periodic", aggregate: "sum", window: bad, unit: "day", align: null, window_type: "start" }))
        .toBe(window);
    }
    expect(transformProblem({ kind: "periodic", aggregate: "sum", window: 1, unit: "day", align: null, window_type: "end" }))
      .toBeNull();
    expect(transformProblem({ kind: "integral", unit: "day", method: "right" })).toBeNull();
    const shift = "The shift must be a whole number, not zero, and at most 100,000 either way.";
    for (const bad of [0, 100_001, -100_001, 0.5, Number.NaN]) {
      expect(transformProblem({ kind: "shift", by: bad, unit: "day" })).toBe(shift);
    }
  });

  it("needs a range to have an end, and to run forwards", () => {
    expect(transformProblem({ kind: "range", start: null, end: null })).toBe("A time range needs a start, an end or both.");
    expect(transformProblem({ kind: "range", start: "2026-01-02T00:00", end: "2026-01-01T00:00" }))
      .toBe("The time range starts after it ends.");
    expect(transformProblem({ kind: "range", start: "2026-01-01T00:00", end: "2026-01-01T00:00" })).toBeNull();
    expect(transformProblem({ kind: "range", start: null, end: "2026-01-01T00:00" })).toBeNull();
  });

  it("names the first problem by its place in the chain", () => {
    expect(transformsProblem([{ kind: "cumulative", aggregate: "sum" }, { kind: "range", start: null, end: null }]))
      .toBe("Transform 2: A time range needs a start, an end or both.");
    expect(transformsProblem([])).toBeNull();
    expect(transformsProblem(Array.from({ length: 10 }, () => blankTransform("derivative")))).toBeNull();
    expect(transformsProblem(Array.from({ length: 11 }, () => blankTransform("derivative"))))
      .toBe("A series takes at most 10 transforms.");
  });
});
