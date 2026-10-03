/** The file sync form (§751; `data-connection` p.160-164). */
import { describe, expect, it } from "vitest";
import {
  BLANK_FIELDS, INGESTIONS, describeFileSync, fieldsOf, ingestionOf, payloadOf, tookText,
} from "./file-sync-form";

const plain = { exclude_synced: { by_modified: false, by_size: false } };

describe("p.160's four modes, as two settings", () => {
  it("writes each mode's transaction type and exclusion", () => {
    const pay = (ingestion: (typeof INGESTIONS)[number]["key"], extra = {}) =>
      payloadOf({ ...BLANK_FIELDS, ingestion, ...extra });
    expect(pay("batch")).toEqual({ ok: true, file_transaction: "SNAPSHOT", file_filters: {} });
    expect(pay("append")).toEqual({ ok: true, file_transaction: "APPEND", file_filters: plain });
    expect(pay("trailing")).toEqual({ ok: true, file_transaction: "SNAPSHOT", file_filters: plain });
    expect(pay("update")).toEqual({
      ok: true, file_transaction: "UPDATE",
      file_filters: { exclude_synced: { by_modified: true, by_size: false } },
    });
    expect(pay("update", { byModified: false, bySize: true })).toMatchObject({
      file_filters: { exclude_synced: { by_modified: false, by_size: true } },
    });
  });

  it("does not let an APPEND or trailing window re-take a changed file", () => {
    // p.161's contradiction: the change options belong to UPDATE alone.
    expect(payloadOf({ ...BLANK_FIELDS, ingestion: "append", byModified: true, bySize: true }))
      .toMatchObject({ file_filters: plain });
  });

  it("refuses an UPDATE that could not see a change", () => {
    expect(payloadOf({ ...BLANK_FIELDS, ingestion: "update", byModified: false, bySize: false }))
      .toEqual({ ok: false, problem: expect.stringContaining("needs a way to see a file change") });
  });

  it("reads a stored sync back as the mode it is", () => {
    expect(ingestionOf("SNAPSHOT", {})).toBe("batch");
    expect(ingestionOf(null, null)).toBe("batch");
    expect(ingestionOf("SNAPSHOT", plain)).toBe("trailing");
    expect(ingestionOf("APPEND", plain)).toBe("append");
    expect(ingestionOf("UPDATE", { exclude_synced: { by_modified: false, by_size: true } }))
      .toBe("update");
  });

  it("round-trips the fields", () => {
    const fields = {
      ...BLANK_FIELDS, ingestion: "update" as const, byModified: false, bySize: true,
      pathMatches: "^in/", pathNotMatches: "\\.tmp$", anyPathMatches: "_SUCCESS",
      modifiedAfter: "2026-02-01", sizeMin: "0", sizeMax: "100", atLeast: "2", limit: "50",
    };
    const sent = payloadOf(fields);
    if (!sent.ok) throw new Error(sent.problem);
    expect(sent.file_filters).toEqual({
      exclude_synced: { by_modified: false, by_size: true }, path_matches: "^in/",
      path_not_matches: "\\.tmp$", any_path_matches: "_SUCCESS", modified_after: "2026-02-01",
      size_min: 0, size_max: 100, at_least: 2, limit: 50,
    });
    // The server keeps a date as a timestamp; the field shows the day.
    const stored = { ...sent.file_filters, modified_after: "2026-02-01T00:00:00.000000+0000" };
    expect(fieldsOf(sent.file_transaction, stored)).toEqual(fields);
  });

  it("fills a new form with the defaults", () => {
    expect(fieldsOf(undefined, undefined)).toEqual(BLANK_FIELDS);
  });
});

describe("the filters' own checks", () => {
  it("says what is wrong with a count", () => {
    for (const [field, value, said] of [
      ["limit", "0", "The file limit is a whole number of at least 1."],
      ["atLeast", "1.5", "At least is a whole number of at least 1."],
      ["sizeMin", "-1", "The smallest size is a whole number of at least 0."],
      ["sizeMax", "lots", "The largest size is a whole number of at least 0."],
    ] as const) {
      expect(payloadOf({ ...BLANK_FIELDS, [field]: value })).toEqual({ ok: false, problem: said });
    }
    expect(payloadOf({ ...BLANK_FIELDS, sizeMin: "9", sizeMax: "3" }))
      .toEqual({ ok: false, problem: expect.stringContaining("no file could pass") });
    expect(payloadOf({ ...BLANK_FIELDS, sizeMin: "3", sizeMax: "3" }).ok).toBe(true);
  });

  it("leaves out a filter left blank", () => {
    expect(payloadOf({ ...BLANK_FIELDS, pathMatches: "  ", limit: " " }))
      .toEqual({ ok: true, file_transaction: "SNAPSHOT", file_filters: {} });
  });
});

describe("what the dialog says", () => {
  it("describes the sync", () => {
    expect(describeFileSync({ sync_source_schema: "drops", sync_file_transaction: "APPEND",
      sync_file_filters: plain })).toBe("Incremental mirror (APPEND) of the files in drops/");
    expect(describeFileSync({ sync_source_schema: "", sync_file_transaction: "SNAPSHOT" }))
      .toBe("Batch mirror of the files in the prefix's root");
  });

  it("says what a run took", () => {
    expect(tookText([])).toBe("No files to take.");
    expect(tookText(["a.csv"])).toBe("Took 1 file: a.csv.");
    expect(tookText(["1", "2", "3", "4", "5", "6", "7"]))
      .toBe("Took 7 files: 1, 2, 3, 4, 5 and 2 more.");
  });
});
