import { describe, expect, it } from "vitest";

import {
  barWidth, componentOf, componentsFor, defaultComponentFor, filtersOf, keywordOf, layoutOf,
  newFilterId, pillSummary, rangeOf, shiftDay, toggleValue, valuesOf, viewerFilterId,
  visibleFilters, withKeyword, withRange, withValues, withoutFilter,
} from "./filter-list";

describe("filtersOf", () => {
  it("keeps what names an id and a property, with p.449's component", () => {
    expect(filtersOf([
      { id: "f_1", property: "region", component: "keyword" },
      { id: "f_2", property: "status", component: "pie" },
      { id: "", property: "x" }, { id: "f_3" }, { id: "f_4", property: "" }, "junk", null,
    ], "ignored")).toEqual([
      { id: "f_1", property: "region", component: "keyword" },
      // Not a component, so the default rather than a filter that draws nothing.
      { id: "f_2", property: "status", component: "histogram" },
    ]);
  });

  it("turns a Filter List saved before §463 into histograms", () => {
    expect(filtersOf(undefined, " region, status ,,")).toEqual([
      { id: "f_1", property: "region", component: "histogram" },
      { id: "f_2", property: "status", component: "histogram" },
    ]);
    expect(filtersOf(undefined, undefined)).toEqual([]);
    // An empty list is a choice, not a missing one.
    expect(filtersOf([], "region")).toEqual([]);
  });

  it("offers a date range only on a date", () => {
    expect(componentsFor("date")).toContain("dateRange");
    expect(componentsFor("timestamp")).toContain("dateRange");
    expect(componentsFor("string")).not.toContain("dateRange");
    expect(componentsFor(undefined)).toEqual(
      ["histogram", "singleSelect", "multiSelect", "keyword"]);
    expect(componentOf("multiSelect")).toBe("multiSelect");
  });

  it("gives a new filter the first f_N not taken", () => {
    expect(newFilterId([])).toBe("f_1");
    expect(newFilterId([{ id: "f_2", property: "a", component: "keyword" }])).toBe("f_3");
  });
});

const region = { property: "region", op: "eq", value: "north" };
const prefix = { property: "region", op: "starts_with", value: "no" };
const other = { property: "status", op: "in", value: ["open", "held"] };

describe("values", () => {
  it("reads eq and in, and nothing else", () => {
    expect(valuesOf([region, prefix, other], "region")).toEqual(["north"]);
    expect(valuesOf([region, prefix, other], "status")).toEqual(["open", "held"]);
    expect(valuesOf([], "status")).toEqual([]);
  });

  it("writes one value as eq and several as in, leaving other clauses alone", () => {
    expect(withValues([prefix, other], "region", ["north"])).toEqual([prefix, other, region]);
    expect(withValues([region, prefix], "region", ["north", "south"])).toEqual([
      prefix, { property: "region", op: "in", value: ["north", "south"] }]);
    // None is no clause: an empty `in` would match nothing.
    expect(withValues([region, other], "region", [])).toEqual([other]);
  });

  it("toggles a value on and off", () => {
    expect(toggleValue([region], "region", "south")).toEqual([
      { property: "region", op: "in", value: ["north", "south"] }]);
    expect(toggleValue([region], "region", "north")).toEqual([]);
  });
});

describe("keyword", () => {
  it("is a prefix on its property, and blank is none", () => {
    expect(withKeyword([region], "region", "so")).toEqual([
      region, { property: "region", op: "starts_with", value: "so" }]);
    expect(keywordOf([region, prefix], "region")).toBe("no");
    expect(keywordOf([region], "region")).toBe("");
    expect(withKeyword([prefix, other], "region", "  ")).toEqual([other]);
  });
});

describe("date range", () => {
  it("shifts a day, and refuses what is not one", () => {
    expect(shiftDay("2024-02-28", 1)).toBe("2024-02-29");
    expect(shiftDay("2024-03-01", -1)).toBe("2024-02-29");
    expect(shiftDay("2024-12-31", 1)).toBe("2025-01-01");
    expect(shiftDay("2024-12-31", 0)).toBe("2024-12-31");
    expect(shiftDay("", 1)).toBeNull();
    expect(shiftDay("2024-13-45", 1)).toBeNull();
    expect(shiftDay("24-1-5", 1)).toBeNull();
    // A month parses as a date on its own, so the shape check is what refuses it.
    expect(shiftDay("2024-03", 1)).toBeNull();
  });

  it("includes both ends, as gte the first and lt the day after the last", () => {
    // Not lte the last: a bare date is midnight, so lte would drop the rest of it.
    expect(withRange([other], "at", { from: "2024-03-01", to: "2024-03-31" })).toEqual([
      other,
      { property: "at", op: "gte", value: "2024-03-01" },
      { property: "at", op: "lt", value: "2024-04-01" },
    ]);
    expect(rangeOf(withRange([], "at", { from: "2024-03-01", to: "2024-03-31" }), "at"))
      .toEqual({ from: "2024-03-01", to: "2024-03-31" });
  });

  it("writes an open end as no clause, and replaces rather than stacks", () => {
    const once = withRange([], "at", { from: "2024-03-01", to: "" });
    expect(once).toEqual([{ property: "at", op: "gte", value: "2024-03-01" }]);
    expect(withRange(once, "at", { from: "", to: "2024-01-09" })).toEqual([
      { property: "at", op: "lt", value: "2024-01-10" }]);
    // Any ordered clause on the property is the picker's, including one a
    // default wrote with lte.
    expect(withRange([{ property: "at", op: "lte", value: "2024-01-01" },
      { property: "at", op: "gt", value: "2023-01-01" }], "at", { from: "", to: "" })).toEqual([]);
    expect(rangeOf([other], "at")).toEqual({ from: "", to: "" });
  });
});

describe("barWidth", () => {
  it("is a share of the largest, and never vanishes for a value with rows", () => {
    expect(barWidth(50, 100)).toBe(50);
    expect(barWidth(100, 100)).toBe(100);
    expect(barWidth(1, 1000)).toBe(2);
    expect(barWidth(0, 10)).toBe(0);
    expect(barWidth(3, 0)).toBe(0);
  });
});

describe("layouts and a viewer's filters (§464)", () => {
  const hist = { id: "f_1", property: "region", component: "histogram" as const };
  const kw = { id: "f_2", property: "name", component: "keyword" as const };
  const dates = { id: "f_3", property: "at", component: "dateRange" as const };

  it("is vertical unless it is pills", () => {
    expect(layoutOf("pills")).toBe("pills");
    expect(layoutOf("vertical")).toBe("vertical");
    expect(layoutOf(undefined)).toBe("vertical");
    expect(layoutOf("grid")).toBe("vertical");
  });

  it("adds a date as a range and anything else as a histogram", () => {
    expect(defaultComponentFor("timestamp")).toBe("dateRange");
    expect(defaultComponentFor("date")).toBe("dateRange");
    expect(defaultComponentFor("integer")).toBe("histogram");
    expect(defaultComponentFor(undefined)).toBe("histogram");
  });

  it("removes a filter's own clauses and nobody else's", () => {
    const clauses = [
      { property: "region", op: "in", value: ["north", "south"] },
      { property: "region", op: "starts_with", value: "no" },
      { property: "name", op: "starts_with", value: "So" },
      { property: "at", op: "gte", value: "2024-03-01" },
      { property: "at", op: "lt", value: "2024-04-01" },
    ];
    expect(withoutFilter(clauses, hist)).toEqual(clauses.slice(1));
    expect(withoutFilter(clauses, kw)).toEqual([...clauses.slice(0, 2), ...clauses.slice(3)]);
    expect(withoutFilter(clauses, dates)).toEqual(clauses.slice(0, 3));
    expect(withoutFilter(clauses, { ...hist, component: "multiSelect" }))
      .toEqual(clauses.slice(1));
  });

  it("shows the module's filters less the removed, plus the added", () => {
    expect(visibleFilters([hist, kw], [dates], new Set(["f_1"]))).toEqual([kw, dates]);
    expect(visibleFilters([hist], [], new Set())).toEqual([hist]);
  });

  it("gives a viewer's filter an id no configured one has", () => {
    expect(viewerFilterId([hist])).toBe("u_1");
    expect(viewerFilterId([hist, { ...kw, id: "u_1" }])).toBe("u_2");
  });

  it("says what a pill applies", () => {
    const clauses = [
      { property: "region", op: "in", value: ["north", "south"] },
      { property: "name", op: "starts_with", value: "So" },
      { property: "at", op: "gte", value: "2024-03-01" },
      { property: "at", op: "lt", value: "2024-04-01" },
    ];
    expect(pillSummary(hist, clauses)).toBe("north, south");
    expect(pillSummary(kw, clauses)).toBe("starts with “So”");
    expect(pillSummary(dates, clauses)).toBe("2024-03-01 – 2024-03-31");
    expect(pillSummary(dates, clauses.slice(0, 3))).toBe("from 2024-03-01");
    expect(pillSummary(dates, [clauses[3]!])).toBe("to 2024-03-31");
    expect(pillSummary(dates, [])).toBe("");
    expect(pillSummary(kw, [])).toBe("");
    expect(pillSummary(hist, [])).toBe("");
  });
});
