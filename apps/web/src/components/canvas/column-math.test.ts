import { describe, expect, it } from "vitest";

import { MathError, evaluate, parse, references } from "./column-math";
import { columnsFor, problem, valueFor } from "./derived-columns";

/** p.170's Column math, and p.168's per-type declaration around it. */

const ROW = { revenue: 100, cost: 40, ratio: "2.5", note: "n/a", blank: "" };
const at = (source: string, row: Record<string, unknown> = ROW) =>
  evaluate(parse(source), row);

describe("the arithmetic", () => {
  it("combines properties, which is p.170's whole sentence", () => {
    expect(at("revenue - cost")).toBe(60);
    expect(at("revenue + cost")).toBe(140);
    expect(at("revenue * 2")).toBe(200);
    expect(at("revenue / cost")).toBe(2.5);
  });

  it("gets precedence and brackets right", () => {
    // The one thing a hand-rolled parser is most likely to get wrong, and the
    // difference between "margin" and nonsense.
    expect(at("revenue - cost * 2")).toBe(20);
    expect(at("(revenue - cost) * 2")).toBe(120);
    expect(at("revenue / cost / 2")).toBe(1.25);
    expect(at("revenue - cost - 10")).toBe(50);
  });

  it("handles unary minus, including in front of a bracket", () => {
    expect(at("-cost")).toBe(-40);
    expect(at("-(revenue - cost)")).toBe(-60);
    expect(at("revenue * -1")).toBe(-100);
    expect(at("--cost")).toBe(40);
  });

  it("reads a number stored as text, because properties are stored untyped", () => {
    expect(at("ratio * 2")).toBe(5);
  });
});

describe("what makes the answer nothing", () => {
  it("propagates a missing property rather than treating it as zero", () => {
    // **The trap §149 caught in a chart and §226 in an aggregation**, and it
    // compounds here: `revenue - cost` over a row with no cost would report
    // the whole revenue as profit.
    expect(at("revenue - missing")).toBeNull();
    expect(at("missing * 0")).toBeNull();
  });

  it("propagates a property that is not a number", () => {
    expect(at("revenue - note")).toBeNull();
    // `Number("")` is 0, which is exactly the coercion that must not happen.
    expect(at("revenue - blank")).toBeNull();
  });

  it("answers nothing for a division by zero rather than Infinity", () => {
    // "∞" in a cell is a figure somebody reads as a result.
    expect(at("revenue / 0")).toBeNull();
    expect(at("revenue / (cost - 40)")).toBeNull();
  });
});

describe("expressions it refuses", () => {
  const refuses = (source: string, match: RegExp) =>
    expect(() => parse(source)).toThrowError(match);

  it("names a character it cannot use rather than skipping it", () => {
    // Silently dropped, `revenue + cost;` would mean `revenue + cost` and the
    // author would never learn the `;` did nothing.
    refuses("revenue + cost;", /is not something this can use/);
    refuses("revenue > cost", /is not something this can use/);
  });

  it("refuses an expression that stops in the middle", () => {
    refuses("revenue +", /stops in the middle/);
    refuses("", /needs an expression/);
    refuses("   ", /needs an expression/);
  });

  it("refuses an unclosed bracket and a stray one", () => {
    refuses("(revenue - cost", /bracket is left open/);
    refuses("revenue - cost)", /left over at the end/);
  });

  it("refuses two values with nothing between them", () => {
    refuses("revenue cost", /left over at the end/);
  });
});

describe("which properties an expression reads", () => {
  it("lists them once, in the order they appear", () => {
    expect(references(parse("revenue - cost + revenue / 2"))).toEqual(["revenue", "cost"]);
  });

  it("finds them inside brackets and behind a minus", () => {
    expect(references(parse("-(a * (b + 3))"))).toEqual(["a", "b"]);
  });
});

describe("p.170's rule about what may be referenced", () => {
  const known = [{ api_name: "revenue" }, { api_name: "cost" }];
  const others = [{ api_name: "margin", kind: "column_math" as const, expression: "revenue - cost" }];

  it("accepts the object type's own properties", () => {
    expect(problem("revenue - cost", known)).toBeNull();
  });

  it("refuses another calculated column, which is p.170's own restriction", () => {
    // "Note that other column math type derived properties may not be used."
    // This is what stops a chain of expressions — and with it the questions of
    // evaluation order and what a cycle means.
    expect(problem("margin * 2", known, others)).toMatch(/another calculated column/);
  });

  it("refuses a property the type does not have", () => {
    expect(problem("revenue - profit", known)).toMatch(/no property called profit/);
  });

  it("refuses an expression that reads no property at all", () => {
    // p.170 is "combine values from multiple properties". A constant is a
    // column of the same number on every row.
    expect(problem("2 + 2", known)).toMatch(/at least one property/);
  });

  it("passes the parser's own sentence through", () => {
    expect(problem("revenue +", known)).toMatch(/stops in the middle/);
  });
});

describe("reading the stored declarations", () => {
  const stored = {
    "type-a": [
      { api_name: "margin", kind: "column_math", expression: "revenue - cost" },
      { api_name: "", kind: "column_math", expression: "revenue" },
      { api_name: "bad_kind", kind: "linked", expression: "revenue" },
      { api_name: "no_expression", kind: "column_math" },
      { api_name: "margin", kind: "column_math", expression: "revenue" },
      "nonsense",
    ],
    "type-b": [{ api_name: "each", kind: "column_math", expression: "cost / 2" }],
  };

  it("keeps only the usable ones, for the type asked about", () => {
    expect(columnsFor(stored, "type-a").map((c) => c.api_name)).toEqual(["margin"]);
    expect(columnsFor(stored, "type-b").map((c) => c.api_name)).toEqual(["each"]);
  });

  it("drops a repeat rather than letting it shadow", () => {
    // Two columns with one name is a table where which one you get depends on
    // order, and the second is the one nobody meant.
    const got = columnsFor(stored, "type-a");
    expect(got).toHaveLength(1);
    expect(got[0]!.expression).toBe("revenue - cost");
  });

  it("refuses one at a time, unlike a rule list", () => {
    // §405 drops a whole conditional-format list because first-match-wins
    // makes it ordered. These are independent columns, so a broken one is one
    // missing column rather than a different set of them.
    expect(columnsFor({ t: [
      { api_name: "ok", kind: "column_math", expression: "a" },
      { api_name: "", kind: "column_math", expression: "b" },
      { api_name: "also_ok", kind: "column_math", expression: "c" },
    ] }, "t").map((c) => c.api_name)).toEqual(["ok", "also_ok"]);
  });

  it("is empty for a type with nothing, and for anything that is not a map", () => {
    expect(columnsFor(stored, "type-z")).toEqual([]);
    for (const raw of [null, undefined, [], "x", 3]) expect(columnsFor(raw, "t")).toEqual([]);
  });
});

describe("one row's value", () => {
  const margin = { api_name: "margin", kind: "column_math" as const, expression: "revenue - cost" };

  it("is the arithmetic over that row", () => {
    expect(valueFor(margin, ROW)).toBe(60);
  });

  it("is nothing when the expression cannot be read at all", () => {
    // §212: a document can hold an expression this build cannot parse. A
    // column of blanks is the honest answer; the sentence belongs in the
    // panel, where somebody can act on it.
    expect(valueFor({ ...margin, expression: "revenue +" }, ROW)).toBeNull();
  });
});

describe("the error type", () => {
  it("is its own, so a caller can tell a refusal from a crash", () => {
    let caught: unknown;
    try { parse("a >"); } catch (error) { caught = error; }
    expect(caught).toBeInstanceOf(MathError);
  });
});
