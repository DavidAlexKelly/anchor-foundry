/**
 * The export form's pure half (§267).
 *
 * `apps/api/tests/test_exports.py` is what a configuration *means* and the
 * server is the authority; this is what a form may say before sending one, and
 * what a list says about whether a destination is current.
 *
 * `data-connection` pages are `p.N`.
 */
import { describe as group, expect, test } from "vitest";

import {
  DESTINATIONS,
  MODES,
  MODE_LABELS,
  REST_INSTEAD,
  blankExport,
  destinations,
  freshness,
  kindOf,
  problem,
  runLabel,
  summarise,
  toPayload,
  unexportableColumns,
  type ExportDraft,
} from "./export-form";

function draft(over: Partial<ExportDraft> = {}): ExportDraft {
  return {
    ...blankExport(),
    connection_id: "c1",
    dataset_id: "d1",
    name: "Nightly orders",
    table: "orders",
    schema: "public",
    ...over,
  };
}

const ORDERS = [
  { name: "id", data_type: "BIGINT" },
  { name: "email", data_type: "VARCHAR" },
];

const PG = { sourceType: "postgres", datasetSchema: ORDERS };

group("which sources can be a destination", () => {
  test("the map matches the server's", () => {
    // Mirrors `services/exports.DESTINATIONS`. A picker offering a source the
    // server would refuse is §258's defect: a form that can express a request
    // the API rejects.
    expect(DESTINATIONS).toEqual({ postgres: "table", mysql: "table", s3: "file" });
    expect(kindOf("postgres")).toBe("table");
    expect(kindOf("s3")).toBe("file");
    expect(kindOf("rest")).toBeNull();
    expect(kindOf("kafka")).toBeNull();
  });

  test("a REST source is refused by being pointed at webhooks", () => {
    // p.17 lists webhooks beside the export types as the other way data leaves.
    // A redirection, not an absence.
    expect(problem(draft(), { sourceType: "rest" })).toBe(REST_INSTEAD);
    expect(REST_INSTEAD).toContain("webhook");
  });

  test("a source type that cannot be a destination says so differently", () => {
    const said = problem(draft(), { sourceType: "kafka" });
    expect(said).not.toBe(REST_INSTEAD);
    expect(said).toContain("cannot be an export destination");
  });
});

group("what the picker offers", () => {
  const rows = [
    { id: "1", source_type: "postgres", exports_enabled: true },
    { id: "2", source_type: "postgres", exports_enabled: false },
    { id: "3", source_type: "rest", exports_enabled: true },
    { id: "4", source_type: "s3", exports_enabled: false },
  ];

  test("only the enabled destinations are offered", () => {
    expect(destinations(rows).usable.map((c) => c.id)).toEqual(["1"]);
  });

  test("a possible destination nobody enabled is kept and flagged", () => {
    // **p.202's switch and "this cannot be a destination" are different
    // sentences.** Dropping the disabled ones would send somebody looking for
    // the wrong fix — a connector limitation rather than an admin's decision.
    expect(destinations(rows).disabled.map((c) => c.id)).toEqual(["2", "4"]);
  });

  test("a REST source is in neither list", () => {
    const all = destinations(rows);
    expect([...all.usable, ...all.disabled].map((c) => c.id)).not.toContain("3");
  });
});

group("the modes", () => {
  test("two, and no more", () => {
    // Decision 0014 §2: the other four of p.195-196's six are defined over a
    // transaction log `dataset_versions` does not keep.
    expect([...MODES]).toEqual(["mirror", "full"]);
    expect(Object.keys(MODE_LABELS).sort()).toEqual(["full", "mirror"]);
  });

  test("full's label says what p.195 warns about", () => {
    // p.195: "This option will almost always result in duplicates in the
    // external table." Somebody choosing between two options should read the
    // consequence where they are choosing.
    expect(MODE_LABELS.full.toLowerCase()).toContain("every run");
    expect(MODE_LABELS.mirror.toLowerCase()).toContain("match");
  });

  test("the default is the mode that does not accumulate", () => {
    // A form whose untouched state quietly appends forever is a form whose
    // default is the surprising one.
    expect(blankExport().mode).toBe("mirror");
  });
});

group("what a form may refuse", () => {
  test("a complete table export is accepted", () => {
    expect(problem(draft(), PG)).toBeNull();
  });

  test("a source and a dataset are both required, and named separately", () => {
    expect(problem(draft({ connection_id: "" }), PG)).toContain("source");
    expect(problem(draft({ dataset_id: "" }), PG)).toContain("dataset");
  });

  test("a name is required and bounded", () => {
    expect(problem(draft({ name: "   " }), PG)).toContain("Name this export");
    expect(problem(draft({ name: "x".repeat(201) }), PG)).toContain("at most");
    expect(problem(draft({ name: "x".repeat(200) }), PG)).toBeNull();
  });

  test("a name this project already uses is refused before the round trip", () => {
    const said = problem(draft({ name: "Nightly" }), { ...PG, existingNames: ["Nightly"] });
    expect(said).toContain("Nightly");
    // And the presence half: a different name is fine against the same list.
    expect(problem(draft({ name: "Other" }), { ...PG, existingNames: ["Nightly"] })).toBeNull();
  });

  test("a struct column is refused with p.197 named", () => {
    const said = problem(draft(), {
      sourceType: "postgres",
      datasetSchema: [{ name: "id", data_type: "BIGINT" }, { name: "tags", data_type: "VARCHAR[]" }],
    });
    expect(said).toContain("p.197");
    expect(said).toContain("tags");
  });

  test("a table export needs a table", () => {
    expect(problem(draft({ table: "" }), PG)).toContain("table");
  });

  test("a schema is optional because not every source needs one", () => {
    // p.197: "if required by your source".
    expect(problem(draft({ schema: "" }), PG)).toBeNull();
  });

  test("something that is not an identifier is refused", () => {
    for (const table of ["orders; DROP TABLE x", "orders table", '"orders"', "1orders"]) {
      expect(problem(draft({ table }), PG)).not.toBeNull();
    }
    expect(problem(draft({ schema: "1public" }), PG)).toContain("schema");
  });

  test("a file export needs a path and may not climb out of it", () => {
    const s3 = { sourceType: "s3", datasetSchema: ORDERS };
    expect(problem(draft({ prefix: "" }), s3)).toContain("path");
    expect(problem(draft({ prefix: "../elsewhere" }), s3)).toContain("..");
    expect(problem(draft({ prefix: "exports/orders" }), s3)).toBeNull();
  });

  test("a file export does not need the table fields", () => {
    // The absence half of the table checks: without it they would fire on a
    // file export and refuse a form that is complete.
    expect(problem(draft({ table: "", schema: "", prefix: "exports/" }),
                   { sourceType: "s3", datasetSchema: ORDERS })).toBeNull();
  });
});

group("what is sent", () => {
  test("a table export carries its mode and destination", () => {
    expect(toPayload(draft({ name: "  Nightly  " }), "postgres")).toEqual({
      connection_id: "c1", dataset_id: "d1", name: "Nightly", mode: "mirror",
      destination: { schema: "public", table: "orders" },
    });
  });

  test("a file export sends a null mode, not an empty string", () => {
    // db 0069 constrains a file export to have no mode, and `""` is a value the
    // enum cast refuses — the sort of difference that reaches a person as a 500
    // quoting a constraint name.
    const sent = toPayload(draft({ prefix: "/exports/orders" }), "s3");
    expect(sent.mode).toBeNull();
    expect(sent.destination).toEqual({ prefix: "exports/orders" });
  });
});

group("what a list says", () => {
  test("a summary says which way round the mode is", () => {
    expect(summarise({ kind: "table", mode: "mirror", destination: { schema: "public", table: "orders" } }))
      .toBe("replaces public.orders");
    expect(summarise({ kind: "table", mode: "full", destination: { schema: "", table: "orders" } }))
      .toBe("appends to orders");
    expect(summarise({ kind: "file", mode: null, destination: { prefix: "exports/orders" } }))
      .toBe("files to exports/orders");
  });
});

group("p.192's question, answered on the row", () => {
  test("an export that has never run says so", () => {
    expect(freshness({ mode: "mirror", last_version: null, dataset_version: 3 }))
      .toEqual({ label: "never run", behind: true });
  });

  test("an export of a dataset with no versions is not behind", () => {
    // Nothing to be behind. The distinction matters because a red mark against
    // an export nobody could have run yet is a red mark nobody can clear.
    expect(freshness({ mode: "mirror", last_version: null, dataset_version: 0 }).behind).toBe(false);
  });

  test("up to date is said with the version, not just a tick", () => {
    expect(freshness({ mode: "mirror", last_version: 7, dataset_version: 7 }))
      .toEqual({ label: "up to date (v7)", behind: false });
  });

  test("behind counts the versions and reads as English at one", () => {
    expect(freshness({ mode: "mirror", last_version: 6, dataset_version: 7 }))
      .toEqual({ label: "one version behind", behind: true });
    expect(freshness({ mode: "mirror", last_version: 4, dataset_version: 7 }))
      .toEqual({ label: "3 versions behind", behind: true });
  });

  test("full is never behind, because behind is not a state it can be in", () => {
    // p.195's use for `full` is a destination that consumes and removes rows
    // after each run, so there is always something new to send. Marking it
    // "up to date" would be as wrong as marking it behind.
    const said = freshness({ mode: "full", last_version: 2, dataset_version: 9 });
    expect(said.behind).toBe(false);
    expect(said.label).toBe("last exported v2");
  });
});

group("the history (p.206)", () => {
  test("a skip is its own word, not a second kind of success", () => {
    // After p.192 a skip *is* a success, so a history of green ticks says
    // nothing about whether anything moved.
    expect(runLabel({ status: "succeeded", skipped: true, rows_written: 0, dataset_version: 7 }))
      .toBe("nothing new (v7)");
  });

  test("a run that wrote says how much", () => {
    expect(runLabel({ status: "succeeded", skipped: false, rows_written: 1200, dataset_version: 7 }))
      .toBe("1,200 rows");
    expect(runLabel({ status: "succeeded", skipped: false, rows_written: 1, dataset_version: 7 }))
      .toBe("1 row");
  });

  test("a failure is a failure whatever else the row says", () => {
    expect(runLabel({ status: "failed", skipped: false, rows_written: 0, dataset_version: 7 }))
      .toBe("failed");
  });
});

group("p.197's column refusal", () => {
  test("every shape DuckDB spells a nested type is caught", () => {
    for (const data_type of ["STRUCT(a INTEGER)", "INTEGER[]", "MAP(VARCHAR, INTEGER)", "UNION(a INTEGER)"]) {
      expect(unexportableColumns([{ name: "c", data_type }])).toEqual(["c"]);
    }
  });

  test("an ordinary column is not refused", () => {
    for (const data_type of ["VARCHAR", "BIGINT", "DOUBLE", "TIMESTAMP", "BOOLEAN", "DATE"]) {
      expect(unexportableColumns([{ name: "c", data_type }])).toEqual([]);
    }
  });

  test("all the refused columns are named at once", () => {
    expect(unexportableColumns([
      { name: "a", data_type: "STRUCT(x INTEGER)" },
      { name: "b", data_type: "VARCHAR" },
      { name: "c", data_type: "INTEGER[]" },
    ])).toEqual(["a", "c"]);
  });
});
