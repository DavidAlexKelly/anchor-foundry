import { describe, expect, it } from "vitest";

import { chosenProperties, editOrderOf, editSummary, valueText } from "./edit-history";

describe("edit history (p.403)", () => {
  it("is newest first unless told otherwise", () => {
    expect(editOrderOf("oldest")).toBe("oldest");
    expect(editOrderOf("newest")).toBe("newest");
    expect(editOrderOf(undefined)).toBe("newest");
    expect(editOrderOf("sideways")).toBe("newest");
  });

  it("reads an empty property choice as all of them", () => {
    expect(chosenProperties(" email, name ,,")).toEqual(["email", "name"]);
    expect(chosenProperties("")).toBeNull();
    expect(chosenProperties(undefined)).toBeNull();
  });

  it("says empty rather than drawing a blank", () => {
    expect(valueText(null)).toBe("(empty)");
    expect(valueText(undefined)).toBe("(empty)");
    expect(valueText("")).toBe("(empty)");
    expect(valueText(0)).toBe("0");
    expect(valueText(false)).toBe("false");
    expect(valueText({ a: 1 })).toBe('{"a":1}');
    expect(valueText(["x", "y"])).toBe('["x","y"]');
  });

  it("summarises an edit in a line", () => {
    const label = (p: string) => (p === "email" ? "Email" : p);
    expect(editSummary({ kind: "modify", property: "email", before: "a@x", after: null }, label))
      .toBe("Email: a@x → (empty)");
    expect(editSummary({ kind: "create", property: null, before: null, after: {} }, label))
      .toBe("Created");
    expect(editSummary({ kind: "delete", property: null, before: {}, after: null }, label))
      .toBe("Deleted");
  });
});
