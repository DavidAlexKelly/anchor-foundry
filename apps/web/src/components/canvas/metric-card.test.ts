import { describe, expect, it } from "vitest";

import {
  AGGREGATIONS, DEFAULT_AGGREGATION, NO_VALUE,
  aggregationOf, metricRequest, needsProperty, propertiesFor, valueLabel,
} from "./metric-card";

/** p.325-330's Metric Card. */

const PROPERTIES = [
  { api_name: "name", data_type: "string" },
  { api_name: "capacity", data_type: "integer" },
  { api_name: "ratio", data_type: "float" },
  { api_name: "opened", data_type: "date" },
];

describe("what a card can show", () => {
  it("offers the six the server answers", () => {
    // This read `count` and `count_distinct` until §229, with a hint saying
    // sums needed typed properties — true when written and untrue from §220.
    expect(Object.keys(AGGREGATIONS)).toEqual([
      "count", "count_distinct", "sum", "avg", "min", "max",
    ]);
    expect(DEFAULT_AGGREGATION).toBe("count");
  });

  it("falls back to counting for anything it does not offer", () => {
    expect(aggregationOf("median")).toBe("count");
    expect(aggregationOf(undefined)).toBe("count");
    expect(aggregationOf("avg")).toBe("avg");
  });

  it("knows that only a plain count needs no property", () => {
    expect(needsProperty("count")).toBe(false);
    for (const name of ["count_distinct", "sum", "avg", "min", "max"]) {
      expect(needsProperty(name)).toBe(true);
    }
    // The fallback and this question have to agree, or the panel shows a
    // property field for a request that will not carry one.
    expect(needsProperty("median")).toBe(false);
  });
});

describe("which properties an aggregation may run over", () => {
  it("offers every property to a distinct count", () => {
    // A text-identity question: "how many distinct regions" works whatever the
    // declared type is, which is why `count_distinct` never needed §220.
    expect(propertiesFor("count_distinct", PROPERTIES).map((p) => p.api_name))
      .toEqual(["name", "capacity", "ratio", "opened"]);
  });

  it("offers only the numeric ones to arithmetic", () => {
    // **A date is orderable and not aggregatable** — the server refuses it
    // because Postgres answers a date `min` with a timestamp and OpenSearch
    // with epoch milliseconds. A picker offering `opened` to a `min` would
    // produce a sentence about arithmetic in place of a number.
    for (const name of ["sum", "avg", "min", "max"]) {
      expect(propertiesFor(name, PROPERTIES).map((p) => p.api_name))
        .toEqual(["capacity", "ratio"]);
    }
  });

  it("does not narrow the list for a plain count", () => {
    expect(propertiesFor("count", PROPERTIES)).toHaveLength(PROPERTIES.length);
  });
});

describe("what gets asked for", () => {
  it("sends a count with no property at all", () => {
    expect(metricRequest("count", "capacity")).toEqual({ aggregation: "count" });
  });

  it("sends the property an aggregation runs over", () => {
    expect(metricRequest("sum", " capacity ")).toEqual({
      aggregation: "sum", property: "capacity",
    });
    expect(metricRequest("count_distinct", "region")).toEqual({
      aggregation: "count_distinct", property: "region",
    });
  });

  it("sends nothing while the setting is unfinished", () => {
    for (const name of ["sum", "avg", "min", "max", "count_distinct"]) {
      expect(metricRequest(name, "")).toBeNull();
      expect(metricRequest(name, null)).toBeNull();
      expect(metricRequest(name, "   ")).toBeNull();
    }
  });
});

describe("the number on the card", () => {
  it("localises a number so a big one is readable", () => {
    expect(valueLabel(1200)).toBe((1200).toLocaleString());
    expect(valueLabel(0)).toBe((0).toLocaleString());
  });

  it("says there is no value rather than showing a zero", () => {
    // **The distinction §226 exists for, at the widget that most needs it.** A
    // card is one large number somebody reads at a glance and believes, so
    // "total capacity: 0" where the truth is "there are no sites" is the worst
    // possible place for the two to render identically.
    expect(valueLabel(null)).toBe(NO_VALUE);
    expect(valueLabel(undefined)).toBe(NO_VALUE);
    expect(NO_VALUE).not.toBe("0");
  });

  it("says there is no value for a number that is not one", () => {
    for (const bad of [Number.NaN, Number.POSITIVE_INFINITY, "12", {}]) {
      expect(valueLabel(bad)).toBe(NO_VALUE);
    }
  });

  it("shows a real zero as a zero", () => {
    // The other half of the same rule: a count of nothing genuinely *is* zero -
    // "how many" always has an answer - so the card must not hide it.
    expect(valueLabel(0)).not.toBe(NO_VALUE);
  });
});
