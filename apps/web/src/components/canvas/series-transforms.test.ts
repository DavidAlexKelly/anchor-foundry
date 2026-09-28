/** §524: time series transforms on a series variable (p.583-586). */
import { describe, expect, it } from "vitest";

import {
  FORMULA_FUNCTIONS, INTEGRATION_METHODS, KIND_LABELS, MAX_FORMULA, MAX_SPAN, WINDOW_TYPES, MAX_TRANSFORMS, TIME_UNITS, TRANSFORM_KINDS, WINDOW_AGGREGATES,
  blankTransform, readableTransforms, transformProblem, transformText, transformsByColumn,
  transformsProblem, transformsText, withColumnTransforms, withKind,
  MAX_FORMULA_INPUTS, seriesDerivationInputs, seriesInputs, withInput, withoutInput,
  type SeriesTransform,
} from "./series-transforms";

describe("the vocabulary", () => {
  it("is p.583-586's, as the server takes it", () => {
    expect([...TRANSFORM_KINDS]).toEqual(["cumulative", "periodic", "rolling", "derivative", "integral", "shift", "range", "formula", "filter", "sample", "combine", "event_statistics"]);
    expect([...FORMULA_FUNCTIONS]).toEqual(["abs", "sqrt", "ln", "log10", "exp", "floor", "ceil", "round"]);
    expect(MAX_FORMULA).toBe(200);
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
    expect(blankTransform("formula")).toEqual({ kind: "formula", expression: "x * 2 + 5" });
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
    expect(transformText({ kind: "formula", expression: "  x * 2 + 5 " })).toBe("x → x * 2 + 5");
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
    expect(transformProblem({ kind: "formula", expression: "x / 2" })).toBeNull();
    expect(transformProblem({ kind: "formula", expression: "   " })).toBe("A formula needs an expression.");
    expect(transformProblem({ kind: "formula", expression: "x".repeat(200) })).toBeNull();
    expect(transformProblem({ kind: "formula", expression: "x".repeat(201) })).toBe("A formula is at most 200 characters.");
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

describe("an Object Table's transforms by column (§555)", () => {
  const sum = { kind: "cumulative", aggregate: "sum" } as SeriesTransform;
  const broken = { kind: "formula", expression: "" } as SeriesTransform;

  it("reads the stored map defensively", () => {
    expect(transformsByColumn({ readings: [sum], other: "x", empty: [] }))
      .toEqual({ readings: [sum] });
    expect(transformsByColumn(null)).toEqual({});
    expect(transformsByColumn([sum])).toEqual({});
  });

  it("reads a column through its chain only while the chain has no problem", () => {
    expect(readableTransforms({ readings: [sum] }, "readings")).toEqual([sum]);
    expect(readableTransforms({ readings: [sum, broken] }, "readings")).toEqual([]);
    expect(readableTransforms({ readings: [sum] }, "other")).toEqual([]);
  });

  it("replaces one column's chain, and drops an emptied one", () => {
    expect(withColumnTransforms({ a: [sum] }, "b", [sum])).toEqual({ a: [sum], b: [sum] });
    expect(withColumnTransforms({ a: [sum] }, "a", [])).toBeNull();
    expect(withColumnTransforms({ a: [sum], b: [sum] }, "a", [])).toEqual({ b: [sum] });
  });
});

describe("a formula's other inputs (§561)", () => {
  type Formula = Extract<SeriesTransform, { kind: "formula" }>;
  const f = (inputs?: Record<string, unknown>): Formula =>
    ({ kind: "formula", expression: "x - y", ...(inputs ? { inputs } : {}) });

  it("adds inputs under the next free name, up to the cap", () => {
    expect(withInput(f())).toEqual(f({ y: "" }));
    expect(withInput(f({ y: "v_1" }))).toEqual(f({ y: "v_1", z: "" }));
    expect(withInput(f({ z: "v_1" }))).toEqual(f({ z: "v_1", y: "" }));
    let full: Formula = f();
    for (let i = 0; i < MAX_FORMULA_INPUTS + 1; i++) full = withInput(full) as Formula;
    expect(Object.keys(full.inputs!)).toEqual(["y", "z", "a", "b"]);
  });

  it("removes one, and none left is no inputs at all", () => {
    expect(withoutInput(f({ y: "v_1", z: "v_2" }), "y")).toEqual(f({ z: "v_2" }));
    expect(withoutInput(f({ y: "v_1" }), "y")).toEqual(f());
  });

  it("names the inputs in words, and asks for a series not chosen", () => {
    expect(transformText(f({ y: "v_1", z: "v_2" }))).toBe("x, y, z → x - y");
    expect(transformText(f({ y: { object_type_id: "t" } }))).toBe("x, y → x - y");
    expect(transformProblem(f({ y: "" }))).toBe("Choose a series for y.");
    expect(transformProblem(f({ y: "v_1" }))).toBeNull();
  });

  it("gives the derivation its object, then each series named, once, in order", () => {
    const chain: SeriesTransform[] = [
      f({ y: "v_2", z: "v_1" }), { kind: "cumulative", aggregate: "sum" }, f({ y: "v_1", z: "" }),
    ];
    expect(seriesInputs(chain)).toEqual(["v_2", "v_1"]);
    expect(seriesDerivationInputs("v_obj", chain)).toEqual(["v_obj", "v_2", "v_1"]);
    expect(seriesDerivationInputs("v_obj", [])).toEqual(["v_obj"]);
    expect(seriesDerivationInputs("", chain)).toEqual(["", "v_2", "v_1"]);
    expect(seriesDerivationInputs("", [])).toEqual([]);
  });
});

describe("p.393's Filter time series and Sample (§648)", () => {
  it("starts each with a working default", () => {
    expect(blankTransform("filter")).toEqual({ kind: "filter", op: "gt", value: 0, keep: true });
    expect(blankTransform("sample")).toEqual({ kind: "sample", every: 1, unit: "hour", method: "previous" });
    expect(transformProblem(blankTransform("filter"))).toBeNull();
    expect(transformProblem(blankTransform("sample"))).toBeNull();
  });

  it("says what each does", () => {
    expect(transformText({ kind: "filter", op: "gte", value: 5, keep: true })).toBe("only readings at least 5");
    expect(transformText({ kind: "filter", op: "neq", value: 0, keep: false }))
      .toBe("without readings not equal to 0");
    expect(transformText({ kind: "sample", every: 1, unit: "day", method: "previous" }))
      .toBe("sampled every 1 day");
    expect(transformText({ kind: "sample", every: 15, unit: "minute", method: "linear" }))
      .toBe("sampled every 15 minutes, interpolated");
  });

  it("refuses what the server would", () => {
    expect(transformProblem({ kind: "filter", op: "gt", value: Number.NaN, keep: true }))
      .toBe("A filter compares with a number.");
    for (const every of [0, 1.5, 100_001]) {
      expect(transformProblem({ kind: "sample", every, unit: "day", method: "previous" }))
        .toMatch(/^The step must be a whole number from 1/);
    }
    expect(transformProblem({ kind: "sample", every: 100_000, unit: "day", method: "linear" })).toBeNull();
  });
});

describe("p.393's Combine time series (§650)", () => {
  const combine = (inputs?: Record<string, unknown>) =>
    ({ kind: "combine" as const, aggregate: "max" as const, ...(inputs ? { inputs } : {}) });

  it("starts with one input to choose, and says what it does", () => {
    expect(blankTransform("combine")).toEqual({ kind: "combine", aggregate: "avg", inputs: { y: "" } });
    expect(transformText(combine({ y: "v1", z: "v2" }))).toBe("combined with y, z, maximum where they meet");
    expect(transformText(combine())).toBe("combined with nothing, maximum where they meet");
  });

  it("needs another series, chosen", () => {
    expect(transformProblem(combine())).toBe("Combining needs at least one other series.");
    expect(transformProblem(combine({ y: "" }))).toBe("Choose a series for y.");
    expect(transformProblem(combine({ y: "v1" }))).toBeNull();
  });

  it("adds and removes inputs as a formula does, and names its variables", () => {
    const one = withInput(combine({ y: "v1" }) as never);
    expect(Object.keys((one as { inputs: object }).inputs)).toEqual(["y", "z"]);
    expect(withoutInput(combine({ y: "v1", z: "v2" }) as never, "y")).toEqual(combine({ z: "v2" }));
    expect(seriesInputs([combine({ y: "v1" }), { kind: "formula", expression: "x", inputs: { y: "v2" } }]))
      .toEqual(["v1", "v2"]);
  });
});

describe("p.393's Event statistics (§652)", () => {
  const stats = (inputs?: Record<string, unknown>, value = 5) =>
    ({ kind: "event_statistics" as const, aggregate: "max" as const, op: "gte" as const, value,
      ...(inputs ? { inputs } : {}) });

  it("starts with the searched series to choose, and says what it does", () => {
    expect(blankTransform("event_statistics")).toEqual({ kind: "event_statistics", aggregate: "avg",
      op: "gt", value: 0, inputs: { e: "" } });
    expect(transformText(stats({ e: "v1" }))).toBe("maximum over each time e is at least 5");
  });

  it("needs exactly one searched series, chosen, and a number", () => {
    expect(transformProblem(stats())).toBe("Event statistics needs the one series its events are found in.");
    expect(transformProblem(stats({ e: "v1", f: "v2" })))
      .toBe("Event statistics needs the one series its events are found in.");
    expect(transformProblem(stats({ e: "" }))).toBe("Choose the series the events are found in.");
    expect(transformProblem(stats({ e: "v1" }, Number.NaN))).toBe("The events are found by comparing with a number.");
    expect(transformProblem(stats({ e: "v1" }))).toBeNull();
    expect(seriesInputs([stats({ e: "v9" })])).toEqual(["v9"]);
  });
});
