/** §567: p.142-143's array operations, as the panel offers them. */
import { describe, expect, it } from "vitest";

import { INDEXED, arrayArity, arraySlotLabel, indexOf, isArrayOp } from "./variable-arrays";

describe("the panel's array operations", () => {
  it("knows each of p.142-143's", () => {
    expect(isArrayOp("array_intersection")).toBe(true);
    expect(isArrayOp("is_empty")).toBe(false);
    expect([...INDEXED]).toEqual(["array_update_element", "array_get_element"]);
  });

  it("takes as many arrays or values as are wanted, or a fixed number", () => {
    expect(arrayArity("array_compose")).toBe("many");
    expect(arrayArity("array_contains")).toBe("many");
    expect(arrayArity("array_update_element")).toBe(2);
    expect(arrayArity("array_length")).toBe(1);
  });

  it("names the inputs", () => {
    expect([0, 1].map((i) => arraySlotLabel("array_compose", i))).toEqual(["Array 1", "Array 2"]);
    expect([0, 1].map((i) => arraySlotLabel("array_update_element", i))).toEqual(["Array", "New value"]);
    expect([0, 1].map((i) => arraySlotLabel("array_is_subset_of", i))).toEqual(["Array", "Of"]);
    expect([0, 1].map((i) => arraySlotLabel("array_does_not_contain", i))).toEqual(["Array", "Value"]);
    expect(arraySlotLabel("array_length", 0)).toBe("Array");
  });

  it("takes an index the server takes, and nothing else", () => {
    expect(indexOf("0")).toBe(0);
    expect(indexOf("10000")).toBe(10000);
    expect(indexOf("10001")).toBeNull();
    expect(indexOf("-1")).toBeNull();
    expect(indexOf("1.5")).toBeNull();
    expect(indexOf("")).toBeNull();
  });
});
