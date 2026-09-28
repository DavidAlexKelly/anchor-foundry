/** §535: filtering an interface set from its dialog. */
import { describe, expect, it } from "vitest";

import {
  ORDERABLE_TYPES, OP_LABELS, blankFilter, filterProblem, filtersPayload, opsFor, withProperty,
} from "./interface-filters";

describe("what each type is offered", () => {
  it("offers a prefix to strings and order to what the server can order", () => {
    expect(opsFor("string")).toEqual(["eq", "neq", "starts_with"]);
    expect(opsFor("integer")).toEqual(["eq", "neq", "gt", "gte", "lt", "lte"]);
    expect(opsFor("float")).toEqual(["eq", "neq", "gt", "gte", "lt", "lte"]);
    expect(opsFor("date")).toEqual(["eq", "neq", "gt", "gte", "lt", "lte"]);
    expect(opsFor("timestamp")).toEqual(["eq", "neq", "gt", "gte", "lt", "lte"]);
    expect(opsFor("boolean")).toEqual(["eq", "neq"]);
    expect(opsFor(undefined)).toEqual(["eq", "neq"]);
    expect([...ORDERABLE_TYPES]).toEqual(["integer", "float", "date", "timestamp"]);
    expect(Object.keys(OP_LABELS)).toEqual(["eq", "neq", "starts_with", "gt", "gte", "lt", "lte"]);
  });

  it("keeps an operator the new property can be asked, and resets one it cannot", () => {
    const ordered = { property: "mileage", op: "gt", value: "10" };
    expect(withProperty(ordered, "odometer", "integer")).toEqual({ property: "odometer", op: "gt", value: "10" });
    expect(withProperty(ordered, "name", "string")).toEqual({ property: "name", op: "eq", value: "10" });
    expect(blankFilter()).toEqual({ property: "", op: "eq", value: "" });
    expect(blankFilter("name")).toEqual({ property: "name", op: "eq", value: "" });
  });
});

describe("a row's problems", () => {
  it("says a number is not one", () => {
    expect(filterProblem({ property: "mileage", op: "gt", value: "lots" }, "float"))
      .toBe("mileage is a number, and lots is not one.");
    expect(filterProblem({ property: "count", op: "eq", value: "1.5" }, "integer"))
      .toBe("count is a whole number, and 1.5 is not one.");
    expect(filterProblem({ property: "count", op: "eq", value: " 2 " }, "integer")).toBeNull();
    expect(filterProblem({ property: "flag", op: "eq", value: "yes" }, "boolean")).toBe("flag is true or false.");
    expect(filterProblem({ property: "flag", op: "eq", value: "true" }, "boolean")).toBeNull();
  });

  it("has none while unfinished", () => {
    expect(filterProblem({ property: "", op: "eq", value: "lots" }, "float")).toBeNull();
    expect(filterProblem({ property: "mileage", op: "eq", value: "  " }, "float")).toBeNull();
    expect(filterProblem({ property: "flag", op: "eq", value: "  " }, "boolean")).toBeNull();
  });
});

describe("what is sent", () => {
  const types = { name: "string", mileage: "float", count: "integer", flag: "boolean", seen: "date" };
  it("sends finished, sound rows in their property's type", () => {
    expect(filtersPayload([
      { property: "name", op: "starts_with", value: " Van " },
      { property: "mileage", op: "gt", value: "10.5" },
      { property: "count", op: "eq", value: "3" },
      { property: "flag", op: "eq", value: "false" },
      { property: "seen", op: "gte", value: "2026-01-01" },
    ], types)).toEqual([
      { property: "name", op: "starts_with", value: "Van" },
      { property: "mileage", op: "gt", value: 10.5 },
      { property: "count", op: "eq", value: 3 },
      { property: "flag", op: "eq", value: false },
      { property: "seen", op: "gte", value: "2026-01-01" },
    ]);
  });

  it("leaves out an unfinished or unsound row rather than sending it", () => {
    expect(filtersPayload([
      { property: "", op: "eq", value: "x" },
      { property: "name", op: "eq", value: "" },
      { property: "mileage", op: "gt", value: "lots" },
    ], types)).toEqual([]);
  });
});
