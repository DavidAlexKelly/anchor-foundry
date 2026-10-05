/** A Pivot Table drawn from a function (Workshop p.335-340; §774). */
import { describe, expect, it } from "vitest";

import {
  cellKey, fieldsOf, pivotFrom, pivotProblem, rowKey, shown, visibleRows, type PivotFields,
} from "./function-pivot";
import type { FunctionResult } from "@/lib/types";

function table(names: string[], rows: unknown[][]): FunctionResult {
  return { kind: "table", version: "1.0.0",
    columns: names.map((name) => ({ name, data_type: "VARCHAR" })), rows };
}

const SALES = table(["region", "kind", "year", "total", "estimate"], [
  ["EU", "Clothing", "2021", 10, 11],
  ["EU", "Clothing", "2022", 20, 19],
  ["US", "Food", "2021", 5, 6],
  // p.338's totals: a row with the column field left out is its row's total,
  ["EU", "Clothing", null, 30, 30],
  // one with the row fields left out its column's,
  [null, null, "2021", 15, 17],
  // and one with all of them left out the grand total.
  [null, null, null, 35, 36],
  // A subtotal by region alone has no line here (p.340's expandable rows).
  ["EU", null, null, 30, 30],
]);
const FIELDS: PivotFields = { rows: ["region", "kind"], column: "year", values: ["total"] };

describe("the grid", () => {
  it("places each point by its grouping fields, in the order they came", () => {
    const grid = pivotFrom(SALES, FIELDS);
    expect(grid.rowKeys).toEqual([["EU", "Clothing"], ["US", "Food"]]);
    expect(grid.columnKeys).toEqual(["2021", "2022"]);
    expect(grid.cells.get(cellKey(["EU", "Clothing"], "2022"))).toEqual({ total: 20 });
    expect(grid.cells.get(cellKey(["US", "Food"], "2022"))).toBeUndefined();
  });

  it("reads p.338's totals from the fields left out", () => {
    const grid = pivotFrom(SALES, { ...FIELDS, values: ["total", "estimate"] });
    expect(grid.rowTotals.get(rowKey(["EU", "Clothing"]))).toEqual({ total: 30, estimate: 30 });
    expect(grid.rowTotals.get(rowKey(["US", "Food"]))).toBeUndefined();
    expect(grid.columnTotals.get("2021")).toEqual({ total: 15, estimate: 17 });
    expect(grid.grand).toEqual({ total: 35, estimate: 36 });
    expect(grid.unplaced).toBe(1);
  });

  it("without a column field, has one column and a total row", () => {
    const grid = pivotFrom(table(["region", "n"], [["EU", 3], ["US", 4], [null, 7]]),
                           { rows: ["region"], column: null, values: ["n"] });
    expect(grid.rowKeys).toEqual([["EU"], ["US"]]);
    expect(grid.columnKeys).toEqual([""]);
    expect(grid.cells.get(cellKey(["US"], ""))).toEqual({ n: 4 });
    expect(grid.columnTotals.get("")).toEqual({ n: 7 });
    expect(grid.grand).toBeNull();
  });

  it("without row fields, is one line across the top", () => {
    const grid = pivotFrom(table(["year", "n"], [["2021", 3], ["2022", 4], [null, 7]]),
                           { rows: [], column: "year", values: ["n"] });
    expect(grid.rowKeys).toEqual([[]]);
    expect(grid.cells.get(cellKey([], "2022"))).toEqual({ n: 4 });
    expect(grid.grand).toEqual({ n: 7 });
    expect(pivotFrom(table(["year", "n"], []), { rows: [], column: "year", values: ["n"] })
      .rowKeys).toEqual([]);
  });

  it("labels a grouping value as text", () => {
    const grid = pivotFrom(table(["y", "n"], [[2021, 1]]), { rows: ["y"], column: null,
                                                             values: ["n"] });
    expect(grid.rowKeys).toEqual([["2021"]]);
  });
});

describe("p.340's expandable rows", () => {
  // p.341's three levels: region alone, then product type, then product name,
  // in the order a ROLLUP may give them - deepest first.
  const LEVELS = table(["region", "type", "name", "year", "total"], [
    ["NA", "Electronics", "A", "2021", 5],
    ["NA", "Electronics", null, "2021", 150],
    ["NA", "Clothing", null, "2021", 90],
    ["NA", null, null, "2021", 300],
    ["EU", null, null, "2021", 40],
    ["NA", null, null, null, 300],
    ["NA", "Electronics", null, null, 150],
    // An expandable field without the one it opens from has no line.
    ["NA", null, "A", "2021", 5],
    // Nor does an expansion of no row.
    [null, "Clothing", null, "2021", 9],
    [null, null, null, "2021", 340],
  ]);
  const DEEP: PivotFields = { rows: ["region"], column: "year", values: ["total"],
                              expandable: ["type", "name"] };

  it("puts each line under the line it opens from", () => {
    const grid = pivotFrom(LEVELS, DEEP);
    expect(grid.rowKeys).toEqual([
      ["NA"], ["NA", "Electronics"], ["NA", "Electronics", "A"], ["NA", "Clothing"], ["EU"]]);
    expect([...grid.parents]).toEqual([rowKey(["NA"]), rowKey(["NA", "Electronics"])]);
    expect(grid.cells.get(cellKey(["NA", "Electronics"], "2021"))).toEqual({ total: 150 });
    expect(grid.cells.get(cellKey(["NA"], "2021"))).toEqual({ total: 300 });
    expect(grid.rowTotals.get(rowKey(["NA", "Electronics"]))).toEqual({ total: 150 });
    expect(grid.columnTotals.get("2021")).toEqual({ total: 340 });
    expect(grid.unplaced).toBe(2);
  });

  it("shows a deeper line only when every line it opens from is open", () => {
    const grid = pivotFrom(LEVELS, DEEP);
    expect(visibleRows(grid, 1, new Set())).toEqual([["NA"], ["EU"]]);
    expect(visibleRows(grid, 1, new Set([rowKey(["NA"])])))
      .toEqual([["NA"], ["NA", "Electronics"], ["NA", "Clothing"], ["EU"]]);
    expect(visibleRows(grid, 1, new Set([rowKey(["NA", "Electronics"])])))
      .toEqual([["NA"], ["EU"]]);
    expect(visibleRows(grid, 1, new Set([rowKey(["NA"]), rowKey(["NA", "Electronics"])])))
      .toHaveLength(5);
  });

  it("draws a line the function left out, so its children open from it", () => {
    const grid = pivotFrom(table(["region", "type", "n"], [["NA", "Food", 3], ["EU", null, 1]]),
                           { rows: ["region"], column: null, values: ["n"],
                             expandable: ["type"] });
    expect(grid.rowKeys).toEqual([["NA"], ["NA", "Food"], ["EU"]]);
    expect(grid.cells.get(cellKey(["NA"], ""))).toBeUndefined();
    expect(grid.parents.has(rowKey(["NA"]))).toBe(true);
  });

  it("needs a row field to open from, and fields the function gives", () => {
    expect(pivotProblem(LEVELS, DEEP)).toBeNull();
    expect(pivotProblem(LEVELS, { ...DEEP, rows: [] }))
      .toBe("Expandable rows open from a row field; choose one (Workshop p.340).");
    expect(pivotProblem(LEVELS, { ...DEEP, expandable: ["type", "colour"] }))
      .toBe("The function gives no field colour.");
  });
});

describe("what the pivot needs", () => {
  it("is a table with the fields the builder named", () => {
    expect(pivotProblem(undefined, FIELDS)).toBeNull();
    expect(pivotProblem(SALES, FIELDS)).toBeNull();
    expect(pivotProblem({ kind: "value", version: "1", value: 3 }, FIELDS))
      .toBe("The function returns value; a pivot table reads a table (Workshop p.335).");
    expect(pivotProblem(SALES, { rows: [], column: null, values: ["total"] }))
      .toBe("Choose a field to group by.");
    expect(pivotProblem(SALES, { rows: [], column: "year", values: ["total"] })).toBeNull();
    expect(pivotProblem(SALES, { ...FIELDS, values: [] })).toBe("Choose a value field.");
    expect(pivotProblem(SALES, { ...FIELDS, rows: ["region", "colour"] }))
      .toBe("The function gives no field colour.");
    expect(pivotProblem(SALES, { ...FIELDS, column: "month" }))
      .toBe("The function gives no field month.");
    expect(pivotProblem(SALES, { ...FIELDS, values: ["profit"] }))
      .toBe("The function gives no field profit.");
  });

  it("reads its fields from the comma-separated settings", () => {
    expect(fieldsOf(" region, kind ,, ")).toEqual(["region", "kind"]);
    expect(fieldsOf(null)).toEqual([]);
  });

  it("shows a number as the locale writes it, and nothing as nothing", () => {
    expect(shown(1234)).toBe((1234).toLocaleString());
    expect(shown(null)).toBe("");
    expect(shown(undefined)).toBe("");
    expect(shown("x")).toBe("x");
    expect(shown(false)).toBe("false");
  });
});
