/** p.225's variable-backed column visibility (§610). `workshop` pages. */
import { describe, expect, it } from "vitest";

import { unknownColumns, visibleColumns } from "./column-visibility";

const configured = ["name", "region", "revenue", "cost"];

describe("which columns a string array shows", () => {
  it("shows every configured column when the array is empty or absent", () => {
    // p.225: "If the string array is empty, all configured columns will be
    // shown in the table."
    for (const value of [[], undefined, null, "", "name", 3, { name: true }, [null, 2, " "]]) {
      expect(visibleColumns(configured, value)).toEqual(configured);
    }
  });

  it("shows only the named columns, in the array's order", () => {
    // p.225: "This array variable also controls the order that columns appear in."
    expect(visibleColumns(configured, ["revenue", "name"])).toEqual(["revenue", "name"]);
  });

  it("chooses among the configured columns and never adds one", () => {
    expect(visibleColumns(configured, ["name", "secret"])).toEqual(["name"]);
    // Names that are all unknown show none, rather than falling back to all:
    // the variable said which, and none of them is here.
    expect(visibleColumns(configured, ["secret"])).toEqual([]);
  });

  it("reads each name once, trimmed, skipping what is not a name", () => {
    expect(visibleColumns(configured, [" cost ", "cost", 7, null, "", "name"]))
      .toEqual(["cost", "name"]);
  });
});

describe("what the builder is told", () => {
  it("names the entries that are not columns", () => {
    expect(unknownColumns(configured, ["name", "secret", " other ", "secret"]))
      .toEqual(["secret", "other"]);
    expect(unknownColumns(configured, ["name"])).toEqual([]);
    expect(unknownColumns(configured, undefined)).toEqual([]);
  });
});
