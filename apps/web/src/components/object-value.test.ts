import { describe, expect, it } from "vitest";

import { displayValue } from "./object-value";

describe("displayValue", () => {
  it("renders a geopoint object readably rather than as [object Object]", () => {
    // The defect this exists for. `String({lat, lon})` is "[object Object]",
    // which is the same string for every geopoint in the table.
    expect(displayValue({ lat: 51.5, lon: -0.12 })).toBe("51.5, -0.12");
  });

  it("reads the dataset form of a geopoint too", () => {
    // A geopoint round-trips through a dataset column as "lat,lon".
    expect(displayValue("51.5,-0.12")).toBe("51.5, -0.12");
  });

  it("leaves ordinary strings alone, commas and all", () => {
    // The guard against the fix being worse than the bug: "Smith, Ada" is not
    // a coordinate pair, and must not be reformatted as one.
    expect(displayValue("Smith, Ada")).toBe("Smith, Ada");
  });

  it("keeps scalars exactly as they read", () => {
    expect(displayValue("open")).toBe("open");
    expect(displayValue(42)).toBe("42");
    expect(displayValue(false)).toBe("false");
    // Zero is a value, not an absence — the check has to be for null/undefined
    // rather than for falsiness.
    expect(displayValue(0)).toBe("0");
  });

  it("marks null, undefined and empty string as absent", () => {
    expect(displayValue(null)).toBe("∅");
    expect(displayValue(undefined)).toBe("∅");
    expect(displayValue("")).toBe("∅");
  });

  it("joins an array instead of printing its JSON", () => {
    expect(displayValue(["north", "south"])).toBe("north, south");
    expect(displayValue([])).toBe("∅");
  });

  it("falls back to compact JSON for anything else structured", () => {
    expect(displayValue({ code: "ENG", size: 4 })).toBe('{"code":"ENG","size":4}');
  });
});
