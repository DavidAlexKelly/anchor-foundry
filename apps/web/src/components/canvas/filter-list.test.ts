import { describe, expect, it } from "vitest";

import {
  axisEnds, barWidth, bucketLabel, componentOf, componentsFor, defaultComponentFor, filtersOf,
  groupFilters, hasLinkOf, isBucketChosen, isPeriodChosen, keywordOf, layoutOf, linkDisplayOf,
  linkedClausesOf, linkedPillLabel, newFilterId, numberRangeSummary, periodLabel, periodOf, pillSummary, rangeOf,
  shiftDay, timelineIntervalOf, toggleValue, valuesOf, viewerFilterId, visibleFilters,
  withBucket, withHasLink, withKeyword, withLinked, withRange, withValues, withoutFilter,
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

describe("the distribution chart (§465)", () => {
  const first = { low: 1, high: 26, closed: false, count: 6 };
  const one = { low: 7, high: 8, closed: false, count: 1 };
  const last = { low: 0.75, high: 1, closed: true, count: 2 };

  it("is offered on a number, and a single date on a date", () => {
    expect(componentsFor("integer")).toContain("distribution");
    expect(componentsFor("float")).toContain("distribution");
    expect(componentsFor("string")).not.toContain("distribution");
    expect(componentsFor("date")).toEqual(expect.arrayContaining(["date", "dateRange"]));
    expect(componentsFor("date")).not.toContain("distribution");
    expect(componentsFor("integer")).not.toContain("date");
  });

  it("names a bar by the values in it", () => {
    expect(bucketLabel(first, true)).toBe("1–25");
    expect(bucketLabel(one, true)).toBe("7");
    expect(bucketLabel({ low: 0.1 + 0.2, high: 0.5, closed: false, count: 0 }, false)).toBe("0.3–0.5");
    expect(axisEnds([first, { low: 26, high: 251, closed: false, count: 1 }], true)).toEqual(["1", "250"]);
    expect(axisEnds([{ ...last, low: 0.1 + 0.2 }], false)).toEqual(["0.3", "1"]);
    expect(axisEnds([], true)).toEqual(["", ""]);
  });

  it("chooses one bar as two comparisons, and knows which it chose", () => {
    const other = { property: "region", op: "eq", value: "north" };
    const chosen = withBucket([other, { property: "n", op: "gt", value: 3 }], "n", first);
    expect(chosen).toEqual([other,
      { property: "n", op: "gte", value: 1 }, { property: "n", op: "lt", value: 26 }]);
    expect(isBucketChosen(chosen, "n", first)).toBe(true);
    expect(isBucketChosen(chosen, "n", one)).toBe(false);
    expect(isBucketChosen(chosen, "m", first)).toBe(false);
    // The last float bar holds its high end, so it is lte.
    const closed = withBucket([], "n", last);
    expect(closed[1]).toEqual({ property: "n", op: "lte", value: 1 });
    expect(isBucketChosen(closed, "n", last)).toBe(true);
    expect(isBucketChosen(closed, "n", { ...last, closed: false })).toBe(false);
    // Bounds read back from a document arrive as whatever JSON held.
    expect(isBucketChosen([{ property: "n", op: "gte", value: "1" },
      { property: "n", op: "lt", value: "26" }], "n", first)).toBe(true);
    expect(withBucket(chosen, "n", null)).toEqual([other]);
  });

  it("says what a chosen range is in a pill", () => {
    expect(numberRangeSummary(withBucket([], "n", first), "n")).toBe("≥ 1, < 26");
    expect(numberRangeSummary(withBucket([], "n", last), "n")).toBe("≥ 0.75, ≤ 1");
    expect(numberRangeSummary([{ property: "n", op: "gte", value: 5 }], "n")).toBe("≥ 5");
    expect(numberRangeSummary([{ property: "n", op: "lt", value: 5 }], "n")).toBe("< 5");
    expect(numberRangeSummary([], "n")).toBe("");
    expect(pillSummary({ id: "f", property: "n", component: "distribution" },
      withBucket([], "n", first))).toBe("≥ 1, < 26");
    expect(pillSummary({ id: "f", property: "at", component: "date" },
      withRange([], "at", { from: "2024-03-05", to: "2024-03-05" }))).toBe("2024-03-05");
    expect(withoutFilter(withBucket([], "n", first), { id: "f", property: "n", component: "distribution" }))
      .toEqual([]);
    expect(withoutFilter(withRange([], "at", { from: "2024-03-05", to: "2024-03-05" }),
      { id: "f", property: "at", component: "date" })).toEqual([]);
  });
});

describe("the timeline (§466)", () => {
  it("is offered on a date", () => {
    expect(componentsFor("timestamp")).toContain("timeline");
    expect(componentsFor("integer")).not.toContain("timeline");
    expect(componentsFor("string")).not.toContain("timeline");
  });

  it("covers a whole day, week or month, both ends in", () => {
    expect(periodOf("2024-03-05T00:00:00Z", "day")).toEqual({ from: "2024-03-05", to: "2024-03-05" });
    expect(periodOf("2024-03-04T00:00:00+00:00", "week"))
      .toEqual({ from: "2024-03-04", to: "2024-03-10" });
    // February 2024 has 29 days, and December rolls the year.
    expect(periodOf("2024-02-01T00:00:00Z", "month")).toEqual({ from: "2024-02-01", to: "2024-02-29" });
    expect(periodOf("2024-12-01T00:00:00Z", "month")).toEqual({ from: "2024-12-01", to: "2024-12-31" });
    expect(periodOf("junk", "day")).toEqual({ from: "", to: "" });
  });

  it("names a period by its day, week or month", () => {
    expect(periodLabel("2024-03-05T00:00:00Z", "day")).toBe("2024-03-05");
    expect(periodLabel("2024-03-04T00:00:00Z", "week")).toBe("week of 2024-03-04");
    expect(periodLabel("2024-03-01T00:00:00Z", "month")).toBe("2024-03");
  });

  it("knows which period the clauses choose", () => {
    const march = withRange([], "at", periodOf("2024-03-01T00:00:00Z", "month"));
    expect(isPeriodChosen(march, "at", "2024-03-01T00:00:00Z", "month")).toBe(true);
    expect(isPeriodChosen(march, "at", "2024-04-01T00:00:00Z", "month")).toBe(false);
    // The same first day at a finer interval is a different period.
    expect(isPeriodChosen(march, "at", "2024-03-01T00:00:00Z", "day")).toBe(false);
    expect(isPeriodChosen([], "at", "junk", "day")).toBe(false);
    expect(timelineIntervalOf("week")).toBe("week");
    expect(timelineIntervalOf("fortnight")).toBe("day");
    expect(pillSummary({ id: "f", property: "at", component: "timeline" }, march))
      .toBe("2024-03-01 – 2024-03-31");
    expect(withoutFilter(march, { id: "f", property: "at", component: "timeline" })).toEqual([]);
  });
});

describe("the advanced keyword search (p.452, §543)", () => {
  it("keeps a filter's search type, and only the advanced one", () => {
    expect(filtersOf([
      { id: "f_1", property: "region", component: "keyword", syntax: "advanced" },
      { id: "f_2", property: "status", component: "keyword", syntax: "fancy" },
    ], "")).toEqual([
      { id: "f_1", property: "region", component: "keyword", syntax: "advanced" },
      { id: "f_2", property: "status", component: "keyword" },
    ]);
    expect("syntax" in filtersOf([{ id: "f_2", property: "s", component: "keyword" }], "")[0]!)
      .toBe(false);
  });

  it("writes a query in place of a prefix on the property, and reads either back", () => {
    const plain = withKeyword([{ property: "status", op: "eq", value: "open" }], "region", "nor");
    const advanced = withKeyword(plain, "region", "north OR south", true);
    expect(advanced).toEqual([
      { property: "status", op: "eq", value: "open" },
      { property: "region", op: "keyword_query", value: "north OR south" },
    ]);
    expect(keywordOf(advanced, "region")).toBe("north OR south");
    expect(keywordOf(plain, "region")).toBe("nor");
    expect(withKeyword(advanced, "region", "  ", true)).toEqual([
      { property: "status", op: "eq", value: "open" },
    ]);
    expect(withKeyword(advanced, "region", "sou")).toEqual([
      { property: "status", op: "eq", value: "open" },
      { property: "region", op: "starts_with", value: "sou" },
    ]);
  });
});

describe("filters on linked objects (p.451, §545)", () => {
  const LINK = "link-1";
  const kept = { property: "status", op: "eq", value: "open" };

  it("keeps a filter's link, and only with the type it reaches", () => {
    expect(filtersOf([
      { id: "f_1", property: "", component: "histogram", link: LINK, linkTo: "t2" },
      { id: "f_2", property: "title", component: "keyword", link: LINK, linkTo: "t2" },
      { id: "f_3", property: "", component: "histogram", link: LINK },
      { id: "f_4", property: "name", component: "keyword", link: LINK },
    ], "")).toEqual([
      { id: "f_1", property: "", component: "histogram", link: LINK, linkTo: "t2" },
      { id: "f_2", property: "title", component: "keyword", link: LINK, linkTo: "t2" },
      { id: "f_4", property: "name", component: "keyword" },
    ]);
  });

  it("writes Has link as its own clause, beside the rest", () => {
    const on = withHasLink([kept], LINK, true);
    expect(on).toEqual([kept, { property: LINK, op: "has_link", value: { filters: [] } }]);
    expect(hasLinkOf(on, LINK)).toBe(true);
    expect(hasLinkOf(on, "other")).toBe(false);
    expect(withHasLink(on, LINK, false)).toEqual([kept]);
  });

  it("puts the linked type's values in one clause, apart from Has link", () => {
    const far = [{ property: "title", op: "starts_with", value: "Ada" }];
    const both = withLinked(withHasLink([kept], LINK, true), LINK, far);
    expect(both).toEqual([
      kept,
      { property: LINK, op: "has_link", value: { filters: [] } },
      { property: LINK, op: "has_link", value: { filters: far } },
    ]);
    expect(linkedClausesOf(both, LINK)).toEqual(far);
    expect(hasLinkOf(both, LINK)).toBe(true);
    // Clearing the values keeps a Has link somebody ticked.
    expect(withLinked(both, LINK, [])).toEqual([
      kept, { property: LINK, op: "has_link", value: { filters: [] } },
    ]);
    expect(hasLinkOf(withLinked([kept], LINK, far), LINK)).toBe(false);
  });

  it("removes and summarises a linked filter inside its link", () => {
    const far = [{ property: "title", op: "starts_with", value: "Ada" }];
    const clauses = withLinked(withHasLink([kept], LINK, true), LINK, far);
    const keyword = { id: "f_2", property: "title", component: "keyword" as const,
      link: LINK, linkTo: "t2" };
    const has = { id: "f_1", property: "", component: "histogram" as const,
      link: LINK, linkTo: "t2" };
    expect(pillSummary(keyword, clauses)).toBe("starts with “Ada”");
    expect(pillSummary(has, clauses)).toBe("has a link");
    expect(pillSummary(has, [kept])).toBe("");
    expect(withoutFilter(clauses, keyword)).toEqual([
      kept, { property: LINK, op: "has_link", value: { filters: [] } },
    ]);
    expect(withoutFilter(clauses, has)).toEqual([
      kept, { property: LINK, op: "has_link", value: { filters: far } },
    ]);
  });
});

describe("p.451's display options for linked filters (§546)", () => {
  const own = { id: "f_1", property: "name", component: "keyword" as const };
  const a1 = { id: "f_2", property: "", component: "histogram" as const, link: "a", linkTo: "t" };
  const b = { id: "f_3", property: "x", component: "histogram" as const, link: "b", linkTo: "u" };
  const a2 = { id: "f_4", property: "y", component: "keyword" as const, link: "a", linkTo: "t" };
  const aOther = { id: "f_5", property: "", component: "histogram" as const, link: "a",
    linkTo: "s" };

  it("is inline unless grouped", () => {
    expect(linkDisplayOf(undefined)).toBe("inline");
    expect(linkDisplayOf("sideways")).toBe("inline");
    expect(linkDisplayOf("grouped")).toBe("grouped");
  });

  it("draws inline filters in the order they were added", () => {
    expect(groupFilters([own, a1, b, a2], "inline"))
      .toEqual([{ link: null, linkTo: null, specs: [own, a1, b, a2] }]);
  });

  it("groups a link's filters after the set's own, a section per link and end", () => {
    expect(groupFilters([a1, own, b, a2, aOther], "grouped")).toEqual([
      { link: null, linkTo: null, specs: [own] },
      { link: "a", linkTo: "t", specs: [a1, a2] },
      { link: "b", linkTo: "u", specs: [b] },
      { link: "a", linkTo: "s", specs: [aOther] },
    ]);
  });
});

describe("a linked filter's pill (§621)", () => {
  it("names the linked type, then the property by its display name", () => {
    expect(linkedPillLabel({ property: "priority" }, "Issue", "Priority")).toBe("Issue · Priority");
    expect(linkedPillLabel({ property: "priority" }, "Issue", null)).toBe("Issue · priority");
  });

  it("says Has link for p.451's link-only filter", () => {
    expect(linkedPillLabel({ property: "" }, "Issue")).toBe("Issue · Has link");
  });

  it("says Linked objects until the type has loaded", () => {
    expect(linkedPillLabel({ property: "" }, null)).toBe("Linked objects · Has link");
  });
});

describe("a regular expression keyword filter (§728; ontology p.130)", () => {
  it("is kept as a search type, and writes matches_regex in place of the other two", () => {
    expect(filtersOf([{ id: "f_1", property: "code", component: "keyword", syntax: "regex" }], "")).toEqual([
      { id: "f_1", property: "code", component: "keyword", syntax: "regex" }]);
    const plain = withKeyword([], "code", "SN");
    const regex = withKeyword(plain, "code", "SN-\\d+", "regex");
    expect(regex).toEqual([{ property: "code", op: "matches_regex", value: "SN-\\d+" }]);
    expect(keywordOf(regex, "code")).toBe("SN-\\d+");
    // One box, one search: the regex replaces the prefix, and blank removes it.
    expect(withKeyword(regex, "code", " ", "regex")).toEqual([]);
    expect(withKeyword(regex, "code", "north OR south", true)).toEqual([
      { property: "code", op: "keyword_query", value: "north OR south" }]);
  });
});
