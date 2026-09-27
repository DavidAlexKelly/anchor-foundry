/** §566: p.142's string and boolean comparisons, as the panel offers them. */
import { describe, expect, it } from "vitest";

import { checkArity, checkSlotLabel, isCheck } from "./variable-checks";

describe("the panel's string and boolean checks", () => {
  it("knows each of p.142's", () => {
    for (const t of ["string_is", "string_is_not", "string_contains", "string_does_not_contain",
      "string_starts_with", "string_ends_with", "is_true", "is_false", "is_null", "is_not_null"]) {
      expect(isCheck(t)).toBe(true);
    }
    expect(isCheck("is_empty")).toBe(false);
  });

  it("takes many texts to compare, and one value to check", () => {
    expect(checkArity("string_contains")).toBe("many");
    expect(checkArity("is_null")).toBe(1);
  });

  it("names the inputs", () => {
    expect([0, 1, 2].map((i) => checkSlotLabel("string_starts_with", i)))
      .toEqual(["Text", "Compared with", "Compared with"]);
    expect(checkSlotLabel("is_true", 0)).toBe("Value");
  });
});
