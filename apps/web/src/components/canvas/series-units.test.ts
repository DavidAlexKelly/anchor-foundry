import { describe, expect, it } from "vitest";

import { conversionProblem, convertReadings, converter, shownUnit, unitOf } from "./series-units";

/** p.394's "Allows unit conversion (for example, meters to kilometers) or
 * custom label overrides" (§733). */
describe("units (workshop p.394)", () => {
  it("reads a unit by its symbol or a name, and a custom label as none", () => {
    expect(unitOf("km")?.kind).toBe("length");
    expect(unitOf(" Kilometres ")?.symbol).toBe("km");
    expect(unitOf("celsius")?.symbol).toBe("°C");
    expect(unitOf("MB")?.symbol).toBe("MB");
    expect(unitOf("widgets per batch")).toBeNull();
    expect(unitOf("")).toBeNull();
  });

  it("converts p.394's own example, and across scales with an offset", () => {
    const close = (a: number | undefined, b: number) => expect(a).toBeCloseTo(b, 9);
    close(converter("m", "km")?.(1500), 1.5);
    close(converter("km", "m")?.(2), 2000);
    close(converter("mi", "km")?.(1), 1.609344);
    close(converter("°C", "°F")?.(100), 212);
    close(converter("°F", "°C")?.(32), 0);
    close(converter("°C", "K")?.(0), 273.15);
    close(converter("K", "°F")?.(0), -459.67);
    close(converter("kPa", "psi")?.(6.894757293168), 1);
    close(converter("h", "min")?.(1.5), 90);
    close(converter("m", "m")?.(7), 7);
  });

  it("leaves a reading exact when the two units are the same", () => {
    // Through the base scale, °F to °F gives -40.300000000000004.
    expect(converter("°F", "fahrenheit")?.(-40.3)).toBe(-40.3);
  });

  it("will not convert between different kinds, or from a custom label", () => {
    expect(converter("m", "kg")).toBeNull();
    expect(converter("bananas", "km")).toBeNull();
    expect(converter("m", "lightyears")).toBeNull();
  });

  it("says why a Display as cannot be honoured, and nothing when there is none", () => {
    expect(conversionProblem("m", "")).toBeNull();
    expect(conversionProblem("m", "km")).toBeNull();
    expect(conversionProblem("m", "parsecs")).toBe("parsecs is not a unit this axis can convert to.");
    expect(conversionProblem("widgets", "km")).toContain("needs the readings' own unit");
    expect(conversionProblem("m", "kg")).toBe("m and kg measure different things.");
  });

  it("labels the axis with the unit shown, and keeps a custom label as typed", () => {
    expect(shownUnit("m", "km")).toBe("km");
    expect(shownUnit("metres", "")).toBe("metres");
    expect(shownUnit("m", "kg")).toBe("m");
    expect(shownUnit("widgets", "")).toBe("widgets");
  });

  it("converts readings only when there is a conversion", () => {
    const readings = [{ t: 1, v: 1000 }, { t: 2, v: 2500 }];
    expect(convertReadings(readings, "m", "km")).toEqual([{ t: 1, v: 1 }, { t: 2, v: 2.5 }]);
    expect(convertReadings(readings, "m", "")).toBe(readings);
    expect(convertReadings(readings, "m", "kg")).toBe(readings);
    expect(convertReadings([{ t: 1, v: null }], "m", "km")).toEqual([{ t: 1, v: null }]);
  });
});
