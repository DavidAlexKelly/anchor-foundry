import { describe, expect, it } from "vitest";
import { clausesOf, extractUsed, refOf, usedUpdates, usedVariables } from "./filter-default";

const RANGE = [
  { property: "ppg", op: "gte", value: { variable: "v_low" } },
  { property: "ppg", op: "lte", value: { variable: "v_high" } },
];

describe("a filter default whose values are variables (§592, p.146-148)", () => {
  it("reads a reference only when it is one and nothing else", () => {
    expect(refOf({ variable: "v_a" })).toBe("v_a");
    expect(refOf({ variable: "v_a", other: 1 })).toBeNull();
    expect(refOf({ variable: 3 })).toBeNull();
    expect(refOf(["v_a"])).toBeNull();
    expect(refOf("v_a")).toBeNull();
    expect(refOf(null)).toBeNull();
  });

  it("reads clauses from the panel's JSON text or a list", () => {
    expect(clausesOf(JSON.stringify(RANGE))).toEqual(RANGE);
    expect(clausesOf(RANGE)).toEqual(RANGE);
    expect(clausesOf("not json")).toBeNull();
    expect(clausesOf("{}")).toBeNull();
    expect(clausesOf([{ op: "eq" }])).toBeNull();
    expect(clausesOf([null])).toBeNull();
  });

  it("lists each used variable once, in clause order", () => {
    expect(usedVariables(JSON.stringify([
      { property: "a", op: "eq", value: { variable: "v_2" } },
      { property: "b", op: "eq", value: "inline" },
      { property: "c", op: "gte", value: { variable: "v_1" } },
      { property: "c", op: "lt", value: { variable: "v_2" } },
    ]))).toEqual(["v_2", "v_1"]);
    expect(usedVariables(undefined)).toEqual([]);
  });

  it("p.148: a histogram's bar fills the range's two variables", () => {
    // The Filter List writes `lt` for every bar but the last (withBucket).
    expect(extractUsed(RANGE, [
      { property: "ppg", op: "gte", value: 10 }, { property: "ppg", op: "lt", value: 20 },
    ])).toEqual({ v_low: 10, v_high: 20 });
    // In either order.
    expect(extractUsed(RANGE, [
      { property: "ppg", op: "lte", value: 30 }, { property: "ppg", op: "gt", value: 25 },
    ])).toEqual({ v_low: 25, v_high: 30 });
  });

  it("does nothing for a filter of another shape", () => {
    for (const filter of [
      [{ property: "ppg", op: "gte", value: 10 }],
      [{ property: "ppg", op: "gte", value: 10 }, { property: "ppg", op: "gte", value: 20 }],
      [{ property: "ppg", op: "gte", value: 10 }, { property: "age", op: "lt", value: 20 }],
      [{ property: "ppg", op: "gte", value: 10 }, { property: "ppg", op: "lt", value: 20 },
        { property: "team", op: "eq", value: "x" }],
      [{ property: "ppg", op: "eq", value: 10 }, { property: "ppg", op: "lt", value: 20 }],
      "garbage",
    ]) {
      expect(extractUsed(RANGE, filter)).toBeNull();
    }
    expect(extractUsed("garbage", [])).toBeNull();
  });

  it("a single choice and several are one shape, each read as the default holds it", () => {
    const one = [{ property: "type", op: "eq", value: { variable: "v_t" } }];
    expect(extractUsed(one, [{ property: "type", op: "eq", value: "fire" }])).toEqual({ v_t: "fire" });
    expect(extractUsed(one, [{ property: "type", op: "in", value: ["fire"] }])).toEqual({ v_t: "fire" });
    expect(extractUsed(one, [{ property: "type", op: "in", value: ["fire", "flood"] }])).toBeNull();
    expect(extractUsed(one, [{ property: "type", op: "in", value: "fire" }])).toBeNull();
    const many = [{ property: "type", op: "in", value: { variable: "v_ts" } }];
    expect(extractUsed(many, [{ property: "type", op: "eq", value: "fire" }])).toEqual({ v_ts: ["fire"] });
    expect(extractUsed(many, [{ property: "type", op: "in", value: ["a", "b"] }]))
      .toEqual({ v_ts: ["a", "b"] });
  });

  it("an inline value is part of the shape but writes nothing", () => {
    const mixed = [
      { property: "team", op: "eq", value: "north" },
      { property: "ppg", op: "gte", value: { variable: "v_low" } },
    ];
    expect(extractUsed(mixed, [
      { property: "ppg", op: "gte", value: 7 }, { property: "team", op: "eq", value: "south" },
    ])).toEqual({ v_low: 7 });
  });
});

describe("usedUpdates", () => {
  const declared = {
    f: { kind: "object_set_filter", default: JSON.stringify(RANGE), update_used_variables: true },
    off: { kind: "object_set_filter", default: JSON.stringify(RANGE) },
    v_low: { kind: "number" },
    v_high: { kind: "number" },
  };

  it("writes what a changed filter holds, once per change", () => {
    const seen: Record<string, string> = {};
    expect(usedUpdates(declared, {}, seen)).toEqual({});
    const filter = [{ property: "ppg", op: "gte", value: 1 }, { property: "ppg", op: "lt", value: 5 }];
    expect(usedUpdates(declared, { f: filter }, seen)).toEqual({ v_low: 1, v_high: 5 });
    // Written by somebody else since: the unchanged filter does not take it back.
    expect(usedUpdates(declared, { f: filter, v_low: 3 }, seen)).toEqual({});
    // Only what differs is written.
    const next = [{ property: "ppg", op: "gte", value: 3 }, { property: "ppg", op: "lt", value: 9 }];
    expect(usedUpdates(declared, { f: next, v_low: 3, v_high: 5 }, seen)).toEqual({ v_high: 9 });
  });

  it("writes nothing without the setting, or for a filter back on its default", () => {
    const filter = [{ property: "ppg", op: "gte", value: 1 }, { property: "ppg", op: "lt", value: 5 }];
    expect(usedUpdates(declared, { off: filter }, {})).toEqual({});
    const seen = { f: JSON.stringify(filter) };
    expect(usedUpdates(declared, {}, seen)).toEqual({});
    expect(seen.f).toBe("null");
  });

  it("never writes a variable the module does not declare, or a derived one", () => {
    const filter = [{ property: "ppg", op: "gte", value: 1 }, { property: "ppg", op: "lt", value: 5 }];
    expect(usedUpdates({ f: declared.f, v_high: { kind: "number", derivation: {} } },
      { f: filter }, {})).toEqual({});
  });
});
