/** Reading an uploaded file again with different options (§362). */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_OPTIONS,
  describeOptions,
  parseNullMarkers,
  whyNotParseable,
} from "./parse-options";

describe("whether a dataset can be parsed again", () => {
  it("allows an upload whose file is still named", () => {
    expect(whyNotParseable({ origin: "upload", original_filename: "a.csv" })).toBe("");
  });

  it("says a model output is rebuilt rather than re-read", () => {
    const why = whyNotParseable({ origin: "model_output", original_filename: null });
    expect(why).toContain("rebuilt by whatever produces it");
    expect(why).toContain("model_output");
  });

  it("says the same of a sync, naming the sync", () => {
    // The origin is in the sentence, so the reader is told which of their
    // datasets this is rather than a generic refusal.
    expect(whyNotParseable({ origin: "sync", original_filename: null })).toContain("sync");
  });

  it("gives an upload with no recorded name its own reason and a way out", () => {
    // A different situation from the one above and a different sentence: this
    // one is a gap in our own history (db 0090), and it can be fixed.
    const why = whyNotParseable({ origin: "upload", original_filename: null });
    expect(why).toContain("before the original file was recorded");
    expect(why).toContain("Uploading the file again");
  });

  it("treats an absent filename the same as a null one", () => {
    // `original_filename` is optional on the type, so a response that omits it
    // must not read as a dataset that can be parsed again — the server would
    // refuse a moment later with nothing on screen explaining it.
    expect(whyNotParseable({ origin: "upload" })).toContain("cannot be parsed again");
  });
});

describe("what the options say they will do", () => {
  it("says nothing when nothing was changed", () => {
    expect(describeOptions(DEFAULT_OPTIONS)).toEqual([]);
  });

  it("names the delimiter and the quote character as typed", () => {
    const said = describeOptions({ ...DEFAULT_OPTIONS, delimiter: "^", quote: "|" });
    expect(said).toContain('fields split on "^"');
    expect(said).toContain('fields quoted with "|"');
  });

  it("describes a header that is not there", () => {
    expect(describeOptions({ ...DEFAULT_OPTIONS, header: false })).toContain(
      "the first row is data, not column names",
    );
  });

  it("counts skipped lines in the singular and the plural", () => {
    // Exact, not `toContain`: "1 lines" contains "1 line", so the substring
    // assertion this started as passed whatever the code did — the mutation
    // sweep caught it, which is the whole argument for running one.
    expect(describeOptions({ ...DEFAULT_OPTIONS, skip_lines: 1 })).toEqual([
      "the first 1 line skipped",
    ]);
    expect(describeOptions({ ...DEFAULT_OPTIONS, skip_lines: 3 })).toEqual([
      "the first 3 lines skipped",
    ]);
  });

  it("does not describe skipping nothing", () => {
    expect(describeOptions({ ...DEFAULT_OPTIONS, skip_lines: 0 })).toEqual([]);
  });

  it("lists every null marker rather than counting them", () => {
    // The markers are the decision; "2 null markers" would make somebody open
    // the field again to find out which.
    const said = describeOptions({ ...DEFAULT_OPTIONS, null_values: ["NA", "-"] });
    expect(said[0]).toContain('"NA"');
    expect(said[0]).toContain('"-"');
  });

  it("does not describe an empty marker list", () => {
    expect(describeOptions({ ...DEFAULT_OPTIONS, null_values: [] })).toEqual([]);
  });

  it("mentions an encoding only when it is not the default", () => {
    expect(describeOptions({ ...DEFAULT_OPTIONS, encoding: "utf-8" })).toEqual([]);
    expect(describeOptions({ ...DEFAULT_OPTIONS, encoding: "latin-1" })).toContain(
      "decoded as latin-1",
    );
  });

  it("names each added column separately", () => {
    // Three switches, three sentences: a single "columns added" would not say
    // which, and they are the part of a re-parse that changes the schema.
    const said = describeOptions({
      ...DEFAULT_OPTIONS,
      add_file_path: true,
      add_imported_at: true,
      add_row_number: true,
    });
    expect(said).toHaveLength(3);
    expect(said.join(" ")).toContain("file path");
    expect(said.join(" ")).toContain("import time");
    expect(said.join(" ")).toContain("row number");
  });

  it("says dropping rows out loud, because it loses data", () => {
    expect(describeOptions({ ...DEFAULT_OPTIONS, drop_bad_rows: true })).toContain(
      "rows that do not fit are dropped",
    );
  });
});

describe("null markers, one per line", () => {
  it("takes one per line and trims them", () => {
    expect(parseNullMarkers("NA\n  -  \nNULL")).toEqual(["NA", "-", "NULL"]);
  });

  it("drops blank lines rather than sending an empty marker", () => {
    // `nullstr` containing "" is a real instruction — treat empty as null —
    // and not what pressing Enter twice meant.
    expect(parseNullMarkers("NA\n\n\n-\n")).toEqual(["NA", "-"]);
  });

  it("is empty for an empty box", () => {
    expect(parseNullMarkers("")).toEqual([]);
    expect(parseNullMarkers("   \n  ")).toEqual([]);
  });

  it("keeps a marker that is a comma", () => {
    // The reason this is a textarea and not a comma-separated field.
    expect(parseNullMarkers(",")).toEqual([","]);
  });
});
