/** §564: p.140-141's math operations and comparisons, as the panel offers them. */
import { describe, expect, it } from "vitest";

import { MATH_ARITY, isMath, mathArity, mathSlotLabel, precisionOf } from "./variable-math";

describe("the panel's math operations", () => {
  it("knows each of p.140-141's operations", () => {
    expect(Object.keys(MATH_ARITY)).toHaveLength(17);
    expect(isMath("round_up")).toBe(true);
    expect(isMath("concat")).toBe(false);
  });

  it("offers a fixed number of slots, or as many as are wanted", () => {
    expect(mathArity("divide")).toBe(2);
    expect(mathArity("negate")).toBe(1);
    expect(mathArity("add")).toBe("many");
    expect(mathArity("less_than")).toBe("many");
    expect(mathArity("concat")).toBe(1);
  });

  it("names each input for what the operation does with it", () => {
    expect([0, 1, 2].map((i) => mathSlotLabel("less_than", i))).toEqual(["Value", "Compared with", "Compared with"]);
    expect([0, 1].map((i) => mathSlotLabel("subtract", i))).toEqual(["From", "Take away"]);
    expect([0, 1].map((i) => mathSlotLabel("divide", i))).toEqual(["Divide", "By"]);
    expect(mathSlotLabel("absolute", 0)).toBe("Value");
    expect([0, 1].map((i) => mathSlotLabel("add", i))).toEqual(["Value 1", "Value 2"]);
  });

  it("takes a precision the server takes, and nothing else", () => {
    expect(precisionOf("2")).toBe(2);
    expect(precisionOf("-2")).toBe(-2);
    expect(precisionOf("10")).toBe(10);
    expect(precisionOf("11")).toBeNull();
    expect(precisionOf("1.5")).toBeNull();
    expect(precisionOf("")).toBeNull();
    expect(precisionOf("x")).toBeNull();
  });
});
