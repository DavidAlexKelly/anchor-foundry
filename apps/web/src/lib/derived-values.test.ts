/**
 * A table's derived columns (§604): the three states a cell can be in.
 */
import { describe as group, expect, test } from "vitest";

import { derivedCell, derivedNames, plainValue } from "./derived-values";

group("derived columns", () => {
  test("only the derived properties, in column order", () => {
    expect(
      derivedNames([
        { api_name: "b", derivation: { links: [] } },
        { api_name: "name", derivation: null },
        { api_name: "a", derivation: { links: [] } },
        { api_name: "plain" },
      ]),
    ).toEqual(["b", "a"]);
  });

  const page = {
    rows: [
      { primary_key: "C1", values: { total: 61, orders: 3 } },
      { primary_key: "C2", values: { total: null, orders: 0 } },
    ],
    errors: { products: "this page's rows reach more than 5000 objects" },
  };

  test("not yet answered is pending, not empty", () => {
    expect(derivedCell(undefined, "C1", "total")).toEqual({ state: "pending" });
  });

  test("a value, including a zero and a null, is the row's own", () => {
    expect(derivedCell(page, "C1", "total")).toEqual({ state: "value", value: 61 });
    expect(derivedCell(page, "C2", "orders")).toEqual({ state: "value", value: 0 });
    expect(derivedCell(page, "C2", "total")).toEqual({ state: "value", value: null });
  });

  test("a column the page could not answer says why, for every row", () => {
    for (const key of ["C1", "C2"]) {
      expect(derivedCell(page, key, "products")).toEqual({
        state: "error",
        reason: "this page's rows reach more than 5000 objects",
      });
    }
  });

  test("a row the answer does not mention has no value", () => {
    expect(derivedCell(page, "gone", "total")).toEqual({ state: "value", value: null });
  });
});

group("a value with no property to format it (§605)", () => {
  test("nothing is nothing, and an empty collection is nothing too", () => {
    expect(plainValue(null)).toBeNull();
    expect(plainValue(undefined)).toBeNull();
    expect(plainValue([])).toBeNull();
  });

  test("a collection is a list, a number is the reader's, the rest is text", () => {
    expect(plainValue(["Anvil", "Bolt"])).toBe("Anvil, Bolt");
    expect(plainValue(1234.5)).toBe((1234.5).toLocaleString());
    expect(plainValue(0)).toBe("0");
    expect(plainValue(true)).toBe("true");
    expect(plainValue([1, null, "x"])).toBe("1, , x");
  });
});
