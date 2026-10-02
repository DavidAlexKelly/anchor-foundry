import { describe, expect, it } from "vitest";

import {
  UNSUPPORTED_HINT, isUnsupported, omittedOf, valuesForHiding,
} from "./unsupported-properties";

/** p.266 and p.595's unsupported properties (§693). */

describe("unsupported properties", () => {
  const props = [
    { api_name: "name", data_type: "string" },
    { api_name: "zone", data_type: "geoshape" },
    { api_name: "where", data_type: "geopoint" },
    { api_name: "zone", data_type: "geoshape" },
  ];

  it("are the geoshapes, once each", () => {
    expect(omittedOf(props)).toEqual(["zone"]);
    expect(isUnsupported({ data_type: "geopoint" })).toBe(false);
    expect(omittedOf([])).toEqual([]);
    expect(UNSUPPORTED_HINT).toContain("Load");
  });

  it("are not hidden as null before they are loaded", () => {
    expect(valuesForHiding({ name: "x" }, ["zone"])).toEqual({ zone: true, name: "x" });
    // A loaded value is its own.
    expect(valuesForHiding({ zone: null }, ["zone"])).toEqual({ zone: null });
    expect(valuesForHiding(undefined, ["zone"])).toBeUndefined();
    const same = { name: "x" };
    expect(valuesForHiding(same, [])).toBe(same);
  });
});
