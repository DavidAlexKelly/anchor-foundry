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
      // Ids, since §444: p.115's setting makes the editor insert one, and a
      // fixture without them cannot tell a list that inserts the name from
      // one that inserts the id.
      id: "11111111-1111-1111-1111-111111111111",
      name: "raw_orders",
      columns: [
        { name: "id", type: "BIGINT" },
        { name: "total", type: "DOUBLE" },
        { name: "placed_at", type: "TIMESTAMP" },
      ],
    },
    { id: "22222222-2222-2222-2222-222222222222", name: "raw_returns",
      columns: [{ name: "id", type: "BIGINT" }] },
    { id: "33333333-3333-3333-3333-333333333333", name: "customers", columns: [] },
    // **Capitals, because names here are free text** and a matcher that
    // lower-cased only the query would answer "ord" with nothing.
    { id: "44444444-4444-4444-4444-444444444444", name: "Orders_Q1",
      columns: [{ name: "Total", type: "DOUBLE" }] },
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

// ---- p.115's dataset aliases (§444) -----------------------------------------
const ID = "11111111-1111-1111-1111-111111111111";

describe("p.115's dataset references", () => {
  const at = (line: string, opts?: { preferIds?: boolean }) =>
    completionsFor(line, line, vocabulary, opts);

  it("inserts the name by default", () => {
    // Every repository here was written before the setting, and their
    // declarations name datasets by name.
    const [first] = at("-- input: raw = raw_ord");
    expect(first!.label).toBe("raw_orders");
    expect(first!.insert).toBe("raw_orders");
  });

  it("inserts the id and still shows the name when the repository asks", () => {
    // p.115: "the editor will present the dataset name over the RID".
    const [first] = at("-- input: raw = raw_ord", { preferIds: true });
    expect(first!.label).toBe("raw_orders");
    expect(first!.insert).toBe(ID);
  });

  it("matches what was typed against the name, not the id", () => {
    // Typing four letters of a name must find it however the editor is set;
    // nobody types the first four characters of a UUID.
    expect(at("-- input: raw = ord", { preferIds: true }).map((c) => c.label))
      .toContain("raw_orders");
  });

  it("leaves aliases and columns inserting what they show", () => {
    // The setting is about *dataset references*. An alias is this file's own
    // word and a column is the table's.
    const alias = at("SELECT x FROM ra", { preferIds: true });
    expect(alias.every((c) => c.insert === c.label)).toBe(true);
  });

  it("offers a file's columns when the input was declared by id", () => {
    // **The case p.115 recommends**, and the one that breaks if the lookup is
    // by name alone: a file full of ids would get no column completions at all.
    const file = [`-- input: raw = ${ID}`, "SELECT raw."].join("\n");
    expect(completionsFor("SELECT raw.", file, vocabulary).map((c) => c.label))
      .toEqual(["id", "total", "placed_at"]);
  });

  it("names the dataset an alias points at, even when the file used an id", () => {
    // `raw — aabbccdd-…` tells nobody which table they are about to write a
    // column of.
    const file = [`-- input: raw = ${ID}`, "SELECT x FROM ra"].join("\n");
    const [alias] = completionsFor("SELECT x FROM ra", file, vocabulary);
    expect(alias!.detail).toBe("raw_orders");
  });

  it("prefers the id over a name that happens to match it", () => {
    // Exactness first: a project where somebody named a dataset after
    // another's id would otherwise resolve to whichever came first.
    const odd: Vocabulary = {
      datasets: [
        { id: "aaaaaaaa-0000-0000-0000-000000000000", name: ID,
          columns: [{ name: "wrong", type: "TEXT" }] },
        ...vocabulary.datasets,
      ],
    };
    const file = [`-- input: raw = ${ID}`, "SELECT raw."].join("\n");
    expect(completionsFor("SELECT raw.", file, odd).map((c) => c.label))
      .toEqual(["id", "total", "placed_at"]);
  });
});
