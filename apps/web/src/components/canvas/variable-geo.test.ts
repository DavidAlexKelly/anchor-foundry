/** §568: p.142's geospatial operations, as the panel offers them. */
import { describe, expect, it } from "vitest";

import { geohashPrecisionOf, isGeo } from "./variable-geo";

describe("the panel's geospatial operations", () => {
  it("knows p.142's four", () => {
    for (const t of ["geohash", "latitude", "longitude", "mgrs"]) expect(isGeo(t)).toBe(true);
    expect(isGeo("add")).toBe(false);
  });

  it("takes a geohash precision the server takes, and nothing else", () => {
    expect(geohashPrecisionOf("1")).toBe(1);
    expect(geohashPrecisionOf("12")).toBe(12);
    expect(geohashPrecisionOf("0")).toBeNull();
    expect(geohashPrecisionOf("13")).toBeNull();
    expect(geohashPrecisionOf("2.5")).toBeNull();
    expect(geohashPrecisionOf("")).toBeNull();
  });
});
