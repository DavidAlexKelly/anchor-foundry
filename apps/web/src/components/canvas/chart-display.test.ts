import { describe, expect, it } from "vitest";

import { chartSortOf, orientationOf, sortPoints } from "./chart-display";

const points = [
  { label: "Site 10", value: 3 },
  { label: "site 2", value: 7 },
  { label: "Site 1", value: 3 },
];

describe("sortPoints (p.283's Sort by)", () => {
  it("keeps the data's order unless told otherwise", () => {
    expect(sortPoints(points, "source")).toEqual(points);
    expect(chartSortOf(undefined)).toBe("source");
    expect(chartSortOf("sideways")).toBe("source");
    expect(chartSortOf("keyDesc")).toBe("keyDesc");
  });

  it("orders keys as a person reads them, whatever their case", () => {
    expect(sortPoints(points, "keyAsc").map((p) => p.label)).toEqual(["Site 1", "site 2", "Site 10"]);
    expect(sortPoints(points, "keyDesc").map((p) => p.label)).toEqual(["Site 10", "site 2", "Site 1"]);
  });

  it("orders by value, with a tie falling back to the key", () => {
    expect(sortPoints(points, "valueDesc").map((p) => p.label)).toEqual(["site 2", "Site 1", "Site 10"]);
    expect(sortPoints(points, "valueAsc").map((p) => p.label)).toEqual(["Site 1", "Site 10", "site 2"]);
  });

  it("does not reorder what it was given", () => {
    const copy = [...points];
    sortPoints(points, "keyAsc");
    expect(points).toEqual(copy);
  });
});

describe("orientationOf (p.284)", () => {
  it("is horizontal only for a bar chart that asks", () => {
    expect(orientationOf("horizontal", "bar")).toBe("horizontal");
    expect(orientationOf("horizontal", "line")).toBe("vertical");
    expect(orientationOf("horizontal", "scatter")).toBe("vertical");
    expect(orientationOf(undefined, "bar")).toBe("vertical");
  });
});
