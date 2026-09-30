/**
 * p.169's linked columns beside p.170's column math (§605): how a module's
 * declarations are read, what an expression may reference, and what a table
 * has to ask the server for. `workshop` pages are `p.N`.
 */
import { describe as group, expect, test } from "vitest";

import {
  columnsFor, derivedInputs, linkedSummary, problem, type DerivedColumn,
} from "./derived-columns";
import type { Derivation } from "@/lib/types";

const CHAIN: Derivation = {
  links: [{ link_type_id: "l1", far_type_id: "t2" }],
  far_type_id: "t2",
  aggregate: "avg",
  property: "total",
};

group("reading a module's declarations", () => {
  test("a linked column is kept only with a chain to follow", () => {
    const got = columnsFor({
      t: [
        { api_name: "avg_total", kind: "linked", derivation: CHAIN, display_name: "Avg" },
        { api_name: "unbuilt", kind: "linked", derivation: null },
        { api_name: "no_links", kind: "linked", derivation: { links: [] } },
        { api_name: "listy", kind: "linked", derivation: [CHAIN] },
        { api_name: "", kind: "linked", derivation: CHAIN },
        { api_name: "other", kind: "mystery", derivation: CHAIN },
        { api_name: "margin", kind: "column_math", expression: "a - b" },
      ],
    }, "t");
    expect(got).toEqual([
      { api_name: "avg_total", display_name: "Avg", kind: "linked", derivation: CHAIN },
      { api_name: "margin", kind: "column_math", expression: "a - b" },
    ]);
  });

  test("a repeated name is dropped whichever kind it is", () => {
    const got = columnsFor({
      t: [
        { api_name: "x", kind: "linked", derivation: CHAIN },
        { api_name: "x", kind: "column_math", expression: "a" },
      ],
    }, "t");
    expect(got.map((c) => c.kind)).toEqual(["linked"]);
  });
});

group("p.170: what column math may reference", () => {
  const known = [{ api_name: "revenue" }];
  const others: DerivedColumn[] = [
    { api_name: "avg_total", kind: "linked", derivation: CHAIN },
    { api_name: "margin", kind: "column_math", expression: "revenue - 1" },
  ];

  test("a linked column, which is an aggregation", () => {
    expect(problem("revenue / avg_total", known, others)).toBeNull();
  });

  test("not another column-math column", () => {
    expect(problem("margin * 2", known, others)).toContain("another calculated column");
  });
});

group("what a table asks the server for", () => {
  const properties = [
    { api_name: "name", derivation: null },
    { api_name: "orders", derivation: { links: [] } },
    { api_name: "spend", derivation: { links: [] } },
    { api_name: "unused", derivation: { links: [] } },
  ];
  const columns: DerivedColumn[] = [
    { api_name: "avg_total", kind: "linked", derivation: CHAIN },
    { api_name: "hidden_linked", kind: "linked", derivation: CHAIN },
    { api_name: "unbuilt", kind: "linked", derivation: null },
    { api_name: "per_order", kind: "column_math", expression: "spend / orders + avg_total" },
    { api_name: "broken", kind: "column_math", expression: "spend +" },
  ];

  test("what is shown, and what a shown expression references", () => {
    expect(derivedInputs(["name", "per_order"], properties, columns)).toEqual({
      properties: ["orders", "spend"],
      derivations: { avg_total: CHAIN },
    });
  });

  test("a shown linked column, and nothing hidden", () => {
    expect(derivedInputs(["avg_total", "orders"], properties, columns)).toEqual({
      properties: ["orders"],
      derivations: { avg_total: CHAIN },
    });
  });

  test("an unbuilt chain and an unreadable expression ask for nothing", () => {
    expect(derivedInputs(["unbuilt", "broken"], properties, columns)).toEqual({
      properties: [],
      derivations: {},
    });
  });
});

group("a linked column's row in the panel", () => {
  test("says what it takes and how far it walks", () => {
    expect(linkedSummary(null)).toBe("not built yet");
    expect(linkedSummary(CHAIN)).toBe("avg of total over 1 link");
    expect(linkedSummary({ links: [{}, {}], aggregate: "count" } as never))
      .toBe("count over 2 links");
    expect(linkedSummary({ links: [{}], property: "name" } as never)).toBe("name over 1 link");
  });
});
