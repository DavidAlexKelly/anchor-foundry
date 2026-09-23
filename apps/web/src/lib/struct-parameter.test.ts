import { describe, expect, it } from "vitest";

import {
  asStruct, fieldLabel, isFilled, setField, unknownFieldsNote,
} from "./struct-parameter";
import type { StructField } from "./types";

// The shared shape, so the fixture cannot drift from what db 0064 stores.
const field = (over: Partial<StructField> & { api_name: string }): StructField => ({
  display_name: "", description: "", data_type: "string", ...over,
});

describe("asStruct", () => {
  it("passes an object through", () => {
    const value = { summary: "done" };
    expect(asStruct(value)).toBe(value);
  });

  it("reads anything else as empty", () => {
    // A parameter nobody has touched is null; one whose stored value predates
    // the schema may be anything at all.
    expect(asStruct(null)).toEqual({});
    expect(asStruct(undefined)).toEqual({});
    expect(asStruct("not a struct")).toEqual({});
    expect(asStruct(7)).toEqual({});
  });

  it("reads an array as empty rather than as an object", () => {
    // `typeof [] === "object"`, so without the check the field inputs would
    // read indices off a list.
    expect(asStruct([1, 2])).toEqual({});
  });
});

describe("setField", () => {
  it("sets one field and keeps the others", () => {
    expect(setField({ summary: "a", owner: "b" }, "owner", "c"))
      .toEqual({ summary: "a", owner: "c" });
  });

  it("returns a new object, because React compares by identity", () => {
    const before = { summary: "a" };
    expect(setField(before, "owner", "b")).not.toBe(before);
    expect(before).toEqual({ summary: "a" });
  });

  it("starts from nothing when there is no value yet", () => {
    expect(setField(null, "summary", "a")).toEqual({ summary: "a" });
  });

  it("removes a field cleared back to blank rather than storing an empty string", () => {
    // An empty string sent for an integer field is a coercion failure where
    // "the reader left it alone" is what happened.
    expect(setField({ summary: "a", hours: 2 }, "hours", "")).toEqual({ summary: "a" });
    expect(setField({ summary: "a" }, "summary", null)).toEqual({});
    expect(setField({ summary: "a" }, "summary", undefined)).toEqual({});
  });

  it("keeps false and zero, which are answers", () => {
    // The trap `hasValue` and `workshop_variables._truthy` both record.
    expect(setField({}, "flag", false)).toEqual({ flag: false });
    expect(setField({}, "hours", 0)).toEqual({ hours: 0 });
  });
});

describe("isFilled", () => {
  it("is false for a struct nobody has touched", () => {
    expect(isFilled(null)).toBe(false);
    expect(isFilled({})).toBe(false);
  });

  it("is true once a field has a value", () => {
    expect(isFilled({ summary: "a" })).toBe(true);
  });

  it("is true for a field answered with false or zero", () => {
    expect(isFilled({ flag: false })).toBe(true);
    expect(isFilled({ hours: 0 })).toBe(true);
  });
});

describe("fieldLabel", () => {
  it("qualifies the field with its parameter", () => {
    // A form may hold two structs with a `summary` each.
    expect(fieldLabel("Resolution", field({ api_name: "summary" })))
      .toBe("Resolution — summary");
  });

  it("prefers the field's display name", () => {
    expect(fieldLabel("Resolution", field({
      api_name: "summary", display_name: "What happened",
    }))).toBe("Resolution — What happened");
  });

  it("falls back when the display name is blank", () => {
    expect(fieldLabel("Resolution", field({
      api_name: "summary", display_name: "   ",
    }))).toBe("Resolution — summary");
  });
});

describe("unknownFieldsNote", () => {
  it("names the parameter and says what is missing", () => {
    // Not a text box: a struct typed into one input can essentially never be
    // valid, which is the control §214 is about.
    expect(unknownFieldsNote("Resolution")).toContain("Resolution");
    // **The cause, not the symptom.** The only way to reach this note is a
    // definition that has gone stale against the ontology — a struct property
    // retyped after the action was wired to it — so the sentence has to point
    // at the rule, which is where somebody can act.
    expect(unknownFieldsNote("Resolution")).toContain("rule");
  });
});
