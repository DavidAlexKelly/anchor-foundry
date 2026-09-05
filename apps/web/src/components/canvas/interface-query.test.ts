import { describe, expect, it } from "vitest";

import { interfaceQuery } from "./routing";

describe("p.165's Open Workshop module query", () => {
  it("carries a mapped variable's current value", () => {
    expect(interfaceQuery({ region: "v_a" }, { v_a: "north" }))
      .toEqual({ region: "north" });
  });

  it("keys on the target's external ID, not on the source variable", () => {
    // The whole point of the mapping: the two modules name the same idea
    // differently, which is why an interface exists at all.
    expect(interfaceQuery({ chosen_region: "v_a" }, { v_a: "north" }))
      .toEqual({ chosen_region: "north" });
  });

  it("stringifies the way the URL writer does", () => {
    expect(interfaceQuery({ n: "v_n", b: "v_b" }, { v_n: 7, v_b: true }))
      .toEqual({ n: "7", b: "true" });
  });

  it("leaves out a variable holding nothing", () => {
    // **Not an empty parameter.** One would arrive at the target as a
    // deliberate blank and override the default it declares, which is exactly
    // what an unset variable must not do.
    expect(interfaceQuery({ a: "v_a", b: "v_b" }, { v_a: "", v_b: "x" }))
      .toEqual({ b: "x" });
    expect(interfaceQuery({ a: "v_a" }, {})).toEqual({});
    expect(interfaceQuery({ a: "v_a" }, { v_a: null })).toEqual({});
  });

  it("passes a false and a zero, which are values", () => {
    // The emptiness rule is `undefined | null | ""`, and `false` is none of
    // them - a boolean interface variable set to false is set.
    expect(interfaceQuery({ b: "v_b", n: "v_n" }, { v_b: false, v_n: 0 }))
      .toEqual({ b: "false", n: "0" });
  });

  it("survives whatever the document holds", () => {
    expect(interfaceQuery(null, { v_a: "x" })).toEqual({});
    expect(interfaceQuery(undefined, { v_a: "x" })).toEqual({});
    expect(interfaceQuery({ a: "" }, { v_a: "x" })).toEqual({});
    expect(interfaceQuery({ "": "v_a" }, { v_a: "x" })).toEqual({});
  });
});
