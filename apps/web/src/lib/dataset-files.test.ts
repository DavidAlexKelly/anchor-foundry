/** Files uploaded into an existing dataset (§746; `dataset-preview` p.10). */
import { describe, expect, it } from "vitest";
import { safeFilename, uploadIntent, uploadedText } from "./dataset-files";

describe("the name a file is stored under", () => {
  it("is the server's", () => {
    expect(safeFilename("january.csv")).toBe("january.csv");
    expect(safeFilename("C:\\exports\\Sales Q1 (final).csv")).toBe("Sales_Q1_final_.csv");
    expect(safeFilename("dir/sub/feb.csv")).toBe("feb.csv");
    expect(safeFilename("._hidden.csv_")).toBe("hidden.csv");
    expect(safeFilename("???")).toBe("upload");
    expect(safeFilename(`${"a".repeat(130)}.csv`)).toHaveLength(120);
  });
});

describe("what an upload will do", () => {
  it("replaces a file of the same stored name", () => {
    const intent = uploadIntent(["january.csv", "february.csv"], "january.csv");
    expect(intent.mode).toBe("update");
    expect(intent.text).toBe(
      "Replaces january.csv with this file. Its columns must be the same as the one it replaces.",
    );
  });

  it("compares the stored name, not the picked one", () => {
    expect(uploadIntent(["Sales_Q1.csv"], "Sales Q1.csv").mode).toBe("update");
  });

  it("adds a file of a new name, saying beside what", () => {
    expect(uploadIntent(["january.csv"], "february.csv")).toEqual({
      mode: "append",
      filename: "february.csv",
      text: "Adds february.csv beside january.csv. Its columns must be the same as theirs.",
    });
    expect(uploadIntent(["a.csv", "b.csv"], "c.csv").text).toBe(
      "Adds c.csv beside 2 files. Its columns must be the same as theirs.",
    );
  });

  it("refuses a file of another kind, whatever its name", () => {
    const intent = uploadIntent(["january.csv"], "January.JSONL");
    expect(intent.mode).toBe("refused");
    expect(intent.text).toBe("This dataset's files are .csv files, so January.JSONL cannot join them.");
    // The extension compared without case.
    expect(uploadIntent(["a.CSV"], "b.csv").mode).toBe("append");
    expect(uploadIntent(["a.csv"], "noextension").mode).toBe("refused");
  });

  it("refuses when there is nothing to add to", () => {
    expect(uploadIntent([], "a.csv").mode).toBe("refused");
  });
});

describe("what an upload did", () => {
  it("names the file, the version and the rows", () => {
    expect(uploadedText({
      mode: "update", filename: "january.csv", dataset: { row_count: 4, current_version: 3 },
    })).toBe("Replaced january.csv. The dataset is version 3, 4 rows.");
    expect(uploadedText({
      mode: "append", filename: "b.csv", dataset: { row_count: 1, current_version: 2 },
    })).toBe("Added b.csv. The dataset is version 2, 1 row.");
  });
});
