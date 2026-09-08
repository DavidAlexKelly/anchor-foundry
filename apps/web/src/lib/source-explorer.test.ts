/**
 * The source explorer's pure half (§269).
 *
 * `apps/api/tests/test_source_preview.py` is what a preview *is* and the
 * server is the authority; this is what the screen may say about one before
 * anybody reads a number off it wrong.
 *
 * **Most of these assert sentences**, which is unusual for this project and is
 * the point: a sample of fifty rows with no caption is a table somebody will
 * treat as the data, and every string below exists to stop one specific wrong
 * conclusion.
 *
 * `data-connection` pages are `p.N`.
 */
import { describe as group, expect, test } from "vitest";

import type { DiscoveredTable, SourcePreview } from "./types";
import {
  KEY_SEP,
  bySchema,
  cell,
  defaultDatasetName,
  isSyncable,
  matchNote,
  sampleCaveat,
  sampleSummary,
  search,
  shortenedNote,
  syncBlockedReason,
  tableKey,
  tableLabel,
} from "./source-explorer";

function table(over: Partial<DiscoveredTable> = {}): DiscoveredTable {
  return {
    schema_name: "public",
    name: "orders",
    kind: "table",
    columns: [
      { name: "id", data_type: "bigint", nullable: false, is_primary_key: true },
      { name: "customer_email", data_type: "text", nullable: false, is_primary_key: false },
    ],
    ...over,
  };
}

function preview(over: Partial<SourcePreview> = {}): SourcePreview {
  return {
    columns: ["id", "customer_email"],
    rows: [
      ["1", "ada@example.com"],
      ["2", null],
    ],
    more: false,
    truncated_cells: 0,
    ...over,
  };
}

/** The first match, refusing an empty list.
 *
 * `noUncheckedIndexedAccess` is on, so `found[0]` is `Match | undefined` — and
 * the honest fix is not a `!` but a check, because "the search returned
 * nothing" is a real way for these tests to be wrong and one that would
 * otherwise surface as a confusing property error three lines later.
 */
function first<T>(items: readonly T[]): T {
  const [head] = items;
  if (head === undefined) throw new Error("expected at least one match, got none");
  return head;
}

group("identity", () => {
  test("a table's key survives a schema containing a dot", () => {
    // An object-storage "schema" is a folder, so `a.b/orders` is ordinary and
    // "split on the first dot" would resolve to the wrong entry.
    const nested = table({ schema_name: "raw.v2", name: "orders" });
    expect(tableKey(nested)).toBe(`raw.v2${KEY_SEP}orders`);
    expect(tableKey(nested)).not.toBe(tableKey(table({ schema_name: "raw", name: "v2.orders" })));
  });

  test("a file at the root of a prefix is shown without a leading slash", () => {
    expect(tableLabel(table({ schema_name: "", name: "orders.csv" }))).toBe("orders.csv");
    expect(tableLabel(table({ schema_name: "nested", name: "regions.csv" }))).toBe(
      "nested/regions.csv",
    );
  });
});

group("p.143's free-text helper", () => {
  // Only `people` carries `customer_email`, so the column search below has
  // exactly one right answer. The default fixture gives every table that
  // column, which would make "found it by column" indistinguishable from
  // "found everything".
  const plain = [{ name: "id", data_type: "bigint", nullable: false, is_primary_key: true }];
  const tables = [
    table({ schema_name: "public", name: "orders", columns: plain }),
    table({ schema_name: "staging", name: "stg_customer_orders", columns: plain }),
    table({
      schema_name: "public",
      name: "people",
      columns: [
        ...plain,
        { name: "customer_email", data_type: "text", nullable: true, is_primary_key: false },
      ],
    }),
  ];

  test("an empty query is every table, not none", () => {
    expect(search(tables, "").map((m) => m.table.name)).toEqual([
      "orders",
      "stg_customer_orders",
      "people",
    ]);
    expect(search(tables, "   ").length).toBe(3);
  });

  test("a substring matches, because a name is rarely a prefix", () => {
    // `stg_customer_orders` is the case: nobody types the prefix.
    expect(search(tables, "orders").map((m) => m.table.name)).toEqual([
      "orders",
      "stg_customer_orders",
    ]);
  });

  test("case does not matter", () => {
    expect(search(tables, "ORDERS").length).toBe(2);
  });

  test("a column name finds the table holding it", () => {
    // The question people actually arrive with, and the half a name-only
    // search cannot answer.
    const found = search(tables, "customer_email");
    expect(found.map((m) => m.table.name)).toEqual(["people"]);
    expect(first(found).kind).toBe("column");
    expect(first(found).via).toBe("customer_email");
  });

  test("a table whose name matches is never reported as a column match", () => {
    // True and useless: `stg_customer_orders` contains "orders" in its name,
    // and saying "matched column …" would send somebody looking at columns.
    const found = search(tables, "orders");
    expect(found.every((m) => m.kind === "name")).toBe(true);
  });

  test("a folder matches, and says so", () => {
    const found = search(tables, "staging");
    expect(found.map((m) => m.table.name)).toEqual(["stg_customer_orders"]);
    expect(matchNote(first(found))).toBe("matched folder staging");
  });

  test("nothing matching is an empty list rather than everything", () => {
    expect(search(tables, "zzz")).toEqual([]);
  });

  test("a name match needs no explanation and a column match does", () => {
    expect(matchNote(first(search(tables, "orders")))).toBeNull();
    expect(matchNote(first(search(tables, "customer_email")))).toBe(
      "matched column customer_email",
    );
  });

  test("each table appears once even when several columns match", () => {
    const wide = table({
      name: "events",
      columns: [
        { name: "user_id", data_type: "bigint", nullable: false, is_primary_key: false },
        { name: "user_email", data_type: "text", nullable: true, is_primary_key: false },
      ],
    });
    expect(search([wide], "user").length).toBe(1);
  });
});

group("the tree", () => {
  test("tables are grouped under their schema, in the order they arrived", () => {
    const grouped = bySchema(
      search(
        [
          table({ schema_name: "public", name: "orders" }),
          table({ schema_name: "staging", name: "raw" }),
          table({ schema_name: "public", name: "people" }),
        ],
        "",
      ),
    );
    expect(grouped.map(([schema]) => schema)).toEqual(["public", "staging"]);
    expect(first(grouped)[1].map((m) => m.table.name)).toEqual(["orders", "people"]);
  });

  test("a file at the prefix root groups under the empty folder", () => {
    const grouped = bySchema(search([table({ schema_name: "", name: "orders.csv" })], ""));
    expect(grouped.map(([schema]) => schema)).toEqual([""]);
  });
});

group("what can be synced from here", () => {
  test("a view can be previewed and cannot be synced", () => {
    // Not an inconsistency: a view is exactly the thing somebody wants to look
    // at before finding out they cannot sync it (p.143 says "tables and
    // views"; this platform has always said tables for syncs).
    const view = table({ kind: "view" });
    expect(isSyncable(view)).toBe(false);
    expect(syncBlockedReason(view)).toContain("this is a view");
  });

  test("a table and a file are both syncable and neither is explained", () => {
    for (const kind of ["table", "file"] as const) {
      expect(isSyncable(table({ kind }))).toBe(true);
      expect(syncBlockedReason(table({ kind }))).toBeNull();
    }
  });

  test("the dataset a sync would default to drops the folder", () => {
    // `nested/regions.csv` as a dataset name is one nobody could find.
    expect(defaultDatasetName(table({ schema_name: "nested", name: "regions.csv" }))).toBe(
      "regions.csv",
    );
  });
});

group("what the screen says about the sample", () => {
  test("a complete table says so", () => {
    expect(sampleSummary(preview())).toBe("all 2 rows, 2 columns.");
  });

  test("a truncated sample never reads as a row count", () => {
    // **The assertion this group exists for.** "50 rows" beside fifty rows
    // reads as the table having fifty rows, which is the wrong conclusion and
    // the one somebody carries into a decision about a sync.
    const summary = sampleSummary(preview({ more: true }));
    expect(summary).toBe("2 of more than 2 rows, 2 columns.");
    expect(summary).not.toBe("all 2 rows, 2 columns.");
  });

  test("one row is not one rows", () => {
    expect(sampleSummary(preview({ rows: [["1", "a"]] }))).toBe("all 1 row, 2 columns.");
  });

  test("an empty table says the columns are there", () => {
    // "The sync found nothing" and "the sync could not run" are the two
    // outcomes this screen separates, and an empty table is the first.
    expect(sampleSummary(preview({ rows: [] }))).toBe(
      "No rows. The 2 columns are there; the table is empty.",
    );
  });

  test("nothing at all is its own sentence", () => {
    expect(sampleSummary(preview({ rows: [], columns: [] }))).toContain("nothing at all");
  });

  test("the caveat is said only when there is a subset to be wrong about", () => {
    // Decision 0015 §5. With every row on screen there is no sample, so the
    // sentence would be noise — and a caveat that is always there is one
    // nobody reads by the third time.
    expect(sampleCaveat(preview({ more: true }))).toContain("not the first rows");
    expect(sampleCaveat(preview({ more: false }))).toBeNull();
  });

  test("shortening is reported, counted, and silent when it did not happen", () => {
    expect(shortenedNote(preview())).toBeNull();
    expect(shortenedNote(preview({ truncated_cells: 1 }))).toBe(
      "1 long value shortened to fit — the sync stores it whole.",
    );
    expect(shortenedNote(preview({ truncated_cells: 3 }))).toBe(
      "3 long values shortened to fit — the sync stores them whole.",
    );
  });
});

group("cells", () => {
  test("a null is a word and an empty string is not", () => {
    // The server sends `null` rather than `""` precisely so an empty column
    // can be told from a missing one; rendering both blank throws that away at
    // the last step.
    expect(cell(null)).toEqual({ text: "null", isNull: true });
    expect(cell("")).toEqual({ text: "", isNull: false });
  });

  test("an ordinary value passes through untouched", () => {
    expect(cell("ada@example.com")).toEqual({ text: "ada@example.com", isNull: false });
  });
});
