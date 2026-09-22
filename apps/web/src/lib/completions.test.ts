/** Completions over the platform's own names (§434; `code-repositories` p.2). */
import { describe, expect, it } from "vitest";
import type { Vocabulary } from "./completions";
import {
  columnSummary,
  completionsFor,
  contextAt,
  declaredInputs,
} from "./completions";

const vocabulary: Vocabulary = {
  datasets: [
    {
      name: "raw_orders",
      columns: [
        { name: "id", type: "BIGINT" },
        { name: "total", type: "DOUBLE" },
        { name: "placed_at", type: "TIMESTAMP" },
      ],
    },
    { name: "raw_returns", columns: [{ name: "id", type: "BIGINT" }] },
    { name: "customers", columns: [] },
    // **Capitals, because names here are free text** and a matcher that
    // lower-cased only the query would answer "ord" with nothing.
    { name: "Orders_Q1", columns: [{ name: "Total", type: "DOUBLE" }] },
  ],
};

const FILE = [
  "-- output: daily_orders",
  "-- input: raw = raw_orders",
  "-- input: ret = raw_returns",
  "SELECT raw.id FROM raw",
].join("\n");

const labels = (found: { label: string }[]) => found.map((c) => c.label);

describe("declaredInputs", () => {
  it("reads every declared input", () => {
    expect(declaredInputs(FILE)).toEqual([
      { alias: "raw", dataset: "raw_orders" },
      { alias: "ret", dataset: "raw_returns" },
    ]);
  });

  it("reads Python's comment prefix too", () => {
    // One declaration syntax, two prefixes — the whole asymmetry between the
    // languages (`transform_declarations.py`).
    expect(declaredInputs("# input: raw = raw_orders\n"))
      .toEqual([{ alias: "raw", dataset: "raw_orders" }]);
  });

  it("ignores a line that is not a declaration", () => {
    expect(declaredInputs("SELECT 'input: x = y' AS note\n")).toEqual([]);
  });

  it("ignores a declaration-shaped trailing comment", () => {
    // The real reader anchors at the start of the line and stops at the first
    // non-comment (`transform_declarations.py`), so a remark at the end of a
    // query is not a declaration — and a browser that thought it was would
    // offer aliases the server has never heard of.
    expect(declaredInputs("SELECT 1 -- input: raw = raw_orders\n")).toEqual([]);
  });

  it("reads the whole file rather than the lines above the cursor", () => {
    // Somebody writing the body and then adding the input at the top is the
    // ordinary way this goes.
    expect(declaredInputs("SELECT 1\n-- input: late = customers"))
      .toEqual([{ alias: "late", dataset: "customers" }]);
  });

  it("is empty for a file that declares nothing", () => {
    expect(declaredInputs("SELECT 1\n")).toEqual([]);
  });
});

describe("contextAt", () => {
  it("wants a dataset after an input declaration's equals sign", () => {
    expect(contextAt("-- input: raw = ")).toEqual({ kind: "dataset", prefix: "" });
    expect(contextAt("-- input: raw = raw_o"))
      .toEqual({ kind: "dataset", prefix: "raw_o" });
  });

  it("wants an alias after FROM and after JOIN", () => {
    expect(contextAt("SELECT * FROM ")).toEqual({ kind: "alias", prefix: "" });
    expect(contextAt("SELECT * FROM a JOIN r")).toEqual({ kind: "alias", prefix: "r" });
  });

  it("wants a column after an alias and a dot", () => {
    expect(contextAt("SELECT raw.")).toEqual({
      kind: "column", prefix: "", alias: "raw",
    });
    expect(contextAt("SELECT raw.to")).toEqual({
      kind: "column", prefix: "to", alias: "raw",
    });
  });

  it("does not offer columns inside a FROM clause", () => {
    // `raw.` after FROM is a schema qualifier, not a column, and offering
    // columns there would be wrong in the one place somebody names a table.
    expect(contextAt("SELECT 1 FROM raw.")?.kind).not.toBe("column");
  });

  it("has no opinion in the middle of ordinary code", () => {
    // Monaco's own suggestions stand where this has nothing to add.
    expect(contextAt("SELECT cou")).toBe(null);
    expect(contextAt("")).toBe(null);
    expect(contextAt("-- a comment")).toBe(null);
  });

  it("ignores case in the keywords", () => {
    expect(contextAt("select * from ")?.kind).toBe("alias");
    expect(contextAt("-- INPUT: raw = ")?.kind).toBe("dataset");
  });

  it("does not fire on a completed declaration", () => {
    // The cursor is at the end of a line that is already finished; there is
    // nothing being typed.
    expect(contextAt("-- input: raw = raw_orders ")).toBe(null);
  });
});

describe("completionsFor", () => {
  it("offers the project's datasets where one belongs", () => {
    expect(labels(completionsFor("-- input: raw = ", FILE, vocabulary)))
      .toEqual(["raw_orders", "raw_returns", "customers", "Orders_Q1"]);
  });

  it("narrows by what has already been typed", () => {
    expect(labels(completionsFor("-- input: raw = raw_", FILE, vocabulary)))
      .toEqual(["raw_orders", "raw_returns"]);
  });

  it("ignores case when narrowing", () => {
    expect(labels(completionsFor("-- input: raw = RAW_O", FILE, vocabulary)))
      .toEqual(["raw_orders"]);
  });

  it("ignores case in the name as well as in what was typed", () => {
    // Lower-casing only the query finds nothing here, and dataset names are
    // free text.
    expect(labels(completionsFor("-- input: raw = Q1", FILE, vocabulary)))
      .toEqual(["Orders_Q1"]);
    expect(labels(completionsFor("-- input: raw = q1", FILE, vocabulary)))
      .toEqual(["Orders_Q1"]);
  });

  it("matches the middle of a name, not only its start", () => {
    // "orders" is how somebody refers to `raw_orders`, and a prefix matcher
    // answers it with nothing.
    expect(labels(completionsFor("-- input: raw = orders", FILE, vocabulary)))
      .toEqual(["raw_orders", "Orders_Q1"]);
  });

  it("says what is in a dataset rather than only its name", () => {
    // "Is this the table I mean" is the question, and the column names answer
    // it where a bare name does not.
    const [first] = completionsFor("-- input: raw = raw_o", FILE, vocabulary);
    expect(first!.detail).toContain("total");
  });

  it("offers this file's aliases after FROM", () => {
    expect(labels(completionsFor("SELECT * FROM ", FILE, vocabulary)))
      .toEqual(["raw", "ret"]);
  });

  it("says which dataset an alias points at", () => {
    const [first] = completionsFor("SELECT * FROM r", FILE, vocabulary);
    expect(first!.detail).toBe("raw_orders");
  });

  it("offers the columns of the dataset an alias points at", () => {
    expect(labels(completionsFor("SELECT raw.", FILE, vocabulary)))
      .toEqual(["id", "total", "placed_at"]);
  });

  it("offers a column's type, which is why somebody is looking", () => {
    const [id] = completionsFor("SELECT raw.i", FILE, vocabulary);
    expect(id!.detail).toBe("BIGINT");
  });

  it("offers a different alias's columns, not the first one's", () => {
    expect(labels(completionsFor("SELECT ret.", FILE, vocabulary))).toEqual(["id"]);
  });

  it("offers nothing for an alias this file has not declared", () => {
    // The reader typed a name; answering a different question than the one
    // they asked is worse than answering none.
    expect(completionsFor("SELECT nope.", FILE, vocabulary)).toEqual([]);
  });

  it("offers nothing for an alias pointing at a dataset that is gone", () => {
    expect(completionsFor(
      "SELECT old.", "-- input: old = deleted_thing\n", vocabulary,
    )).toEqual([]);
  });

  it("offers nothing where it has nothing to add", () => {
    expect(completionsFor("SELECT cou", FILE, vocabulary)).toEqual([]);
  });

  it("offers no aliases in a file that declares none", () => {
    expect(completionsFor("SELECT * FROM ", "SELECT 1\n", vocabulary)).toEqual([]);
  });

  it("keeps the datasets in the order they were given", () => {
    // The listing arrives sorted; re-sorting here would move the answer under
    // somebody's finger between one keystroke and the next.
    expect(labels(completionsFor("-- input: x = ", FILE, vocabulary)))
      .toEqual(vocabulary.datasets.map((d) => d.name));
  });
});

describe("columnSummary", () => {
  it("names the first few columns", () => {
    expect(columnSummary([{ name: "a" }, { name: "b" }])).toBe("a, b");
  });

  it("counts the rest rather than listing them", () => {
    expect(columnSummary(
      ["a", "b", "c", "d", "e", "f"].map((name) => ({ name })),
    )).toBe("a, b, c, d and 2 more");
  });

  it("does not say 'and 0 more' when the list ends exactly", () => {
    // Four columns and four shown: the boundary, and the one place an
    // off-by-one reads as a bug on the screen.
    expect(columnSummary(["a", "b", "c", "d"].map((name) => ({ name }))))
      .toBe("a, b, c, d");
  });

  it("says so when there are none", () => {
    // A dataset that has never been written has no columns, and an empty
    // string would read as a rendering bug.
    expect(columnSummary([])).toBe("no columns yet");
  });
});
