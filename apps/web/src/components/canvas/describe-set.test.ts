import { describe, expect, it } from "vitest";

import { describeSet } from "./filter-clause";

describe("describeSet", () => {
  it("says each clause in its own operator's words", () => {
    expect(describeSet(4, "Site", [
      { property: "region", op: "in", value: ["north", "south"] },
      { property: "at", op: "gte", value: "2024-03-01" },
      { property: "at", op: "lt", value: "2024-04-01" },
      { property: "name", op: "starts_with", value: "No" },
    ])).toBe(
      "4 Sites where region is one of north, south and at is at least 2024-03-01"
      + " and at is less than 2024-04-01 and name starts with No");
  });

  it("reads a clause with no operator as an equality, and counts in the singular", () => {
    expect(describeSet(1, "Site", [{ property: "region", value: "north" }]))
      .toBe("1 Site where region is north");
    expect(describeSet(2, undefined, [])).toBe("2 objects");
  });
});
