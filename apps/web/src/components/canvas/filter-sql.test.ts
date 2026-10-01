import { describe, expect, it } from "vitest";

import { chartQuery } from "./filter-sql";

/** The dataset side of a chart's measure (ROADMAP Canvas item 2). */
describe("chartQuery's measure", () => {
  it("counts distinct values of any column, uncast (§615)", () => {
    expect(chartQuery({ kind: "bar", dimension: "region", measure: "supplier",
                        aggregate: "count_distinct" }))
      .toBe('SELECT "region" AS label, count(DISTINCT "supplier") AS value FROM dataset '
            + "GROUP BY 1 ORDER BY 2 DESC LIMIT 25");
  });

  it("needs a column to count the distinct values of", () => {
    expect(chartQuery({ kind: "bar", dimension: "region", measure: null,
                        aggregate: "count_distinct" })).toBeNull();
  });

  it("still casts the arithmetic ones and counts rows for a count", () => {
    expect(chartQuery({ kind: "pie", dimension: "region", measure: "reading",
                        aggregate: "sum" }))
      .toContain('sum(CAST("reading" AS DOUBLE)) AS value');
    expect(chartQuery({ kind: "line", dimension: "day", measure: null, aggregate: "count" }))
      .toContain("count(*) AS value");
  });
});
