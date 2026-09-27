import { describe, expect, it } from "vitest";

import {
  arrayItems, blankItem, hasItems, isBlankItem, submittedValues, withItem, withoutItem,
} from "./array-parameter";

describe("an array's rows in a form (§580)", () => {
  it("reads a list, or a list's text, and nothing else", () => {
    expect(arrayItems(["a", 1])).toEqual(["a", 1]);
    expect(arrayItems(' ["a", "b"] ')).toEqual(["a", "b"]);
    expect(arrayItems('{"a": 1}')).toEqual([]);
    expect(arrayItems("[nope")).toEqual([]);
    expect(arrayItems("a, b")).toEqual([]);
    expect(arrayItems(null)).toEqual([]);
    expect(arrayItems(3)).toEqual([]);
  });

  it("changes and removes one row, leaving the list it was given alone", () => {
    const items = ["a", "b", "c"];
    expect(withItem(items, 1, "z")).toEqual(["a", "z", "c"]);
    expect(withoutItem(items, 0)).toEqual(["b", "c"]);
    expect(items).toEqual(["a", "b", "c"]);
  });

  it("starts a row blank, never null", () => {
    expect(blankItem("string")).toBe("");
    expect(blankItem("integer")).toBe("");
    expect(blankItem("struct")).toEqual({});
  });

  it("tells a blank row from an answer", () => {
    for (const blank of ["", "  ", null, undefined, {}, { a: "", b: null }]) {
      expect(isBlankItem(blank)).toBe(true);
    }
    for (const answer of ["x", 0, false, { a: "", b: 2 }, { a: false }, []]) {
      expect(isBlankItem(answer)).toBe(false);
    }
  });

  it("answers a required array with a row that has something in it", () => {
    expect(hasItems(["a"])).toBe(true);
    expect(hasItems(["", "b"])).toBe(true);
    expect(hasItems([false])).toBe(true);
    expect(hasItems(["", " "])).toBe(false);
    expect(hasItems([])).toBe(false);
    expect(hasItems(null)).toBe(false);
    expect(hasItems('["x"]')).toBe(true);
  });

  it("drops the blank rows of array parameters only, when the form is sent", () => {
    const parameters = [
      { api_name: "tags", data_type: "array" },
      { api_name: "note", data_type: "string" },
      { api_name: "list", data_type: "array" },
    ];
    expect(submittedValues(
      { tags: ["a", "", " ", "b"], note: "", list: "[]", other: [""] }, parameters,
    )).toEqual({ tags: ["a", "b"], note: "", list: "[]", other: [""] });
  });
});
