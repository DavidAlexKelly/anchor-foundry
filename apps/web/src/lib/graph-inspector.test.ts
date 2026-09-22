import { describe, expect, it } from "vitest";

import {
  columnsNote, fileHref, keepTab, narrow, noCodeNote, previewNote, producerOf, tabsFor,
} from "./graph-inspector";
import type { PipelineGraph, PipelineNode, TabularResult } from "./types";

const node = (over: Partial<PipelineNode> & Pick<PipelineNode, "id" | "kind">): PipelineNode => ({
  resource_id: "r", name: "n", layer: 0, position: 0, in_cycle: false, is_focus: false,
  slug: null, origin: null, row_count: null, current_version: null, health_status: null,
  language: null, trigger_mode: null, last_run_status: null, last_run_at: null,
  updated_at: null, built_at: null, out_of_date: false, out_of_date_reason: null,
  ...over,
});

const DS = node({ id: "dataset:out", kind: "dataset" });
const SRC = node({ id: "dataset:src", kind: "dataset" });
const MODEL = node({ id: "model:m", kind: "model" });
const TYPE = node({ id: "object_type:t", kind: "object_type" });
const CONN = node({ id: "connection:c", kind: "connection" });

const graph = (edges: { from: string; to: string }[]): PipelineGraph => ({
  nodes: [SRC, MODEL, DS, TYPE, CONN],
  edges: edges.map((e) => ({ ...e, label: null })),
  links: [], columns: [], cycles: [], layer_count: 1,
});

const BUILT = graph([
  { from: "dataset:src", to: "model:m" },
  { from: "model:m", to: "dataset:out" },
]);
const UPLOADED = graph([]);

const result = (
  names: string[], rows: unknown[][], over: Partial<TabularResult> = {},
): TabularResult => ({
  columns: names.map((name) => ({ name, data_type: "text" })),
  rows,
  total_rows: rows.length,
  truncated: false,
  ...over,
});

describe("producerOf", () => {
  it("finds the transform that writes a dataset", () => {
    expect(producerOf(BUILT, "dataset:out")?.id).toBe("model:m");
  });

  it("answers null for a dataset nothing builds", () => {
    // p.47: "Uploaded and writeback datasets do not have associated code."
    expect(producerOf(UPLOADED, "dataset:out")).toBeNull();
  });

  it("does not take an upstream dataset for a producer", () => {
    // Every edge into a model comes from a dataset. Without the kind check a
    // model node would report its own input as what builds it.
    expect(producerOf(BUILT, "model:m")).toBeNull();
  });

  it("reads the direction of the edge", () => {
    // `dataset:src` feeds the model; nothing writes it. An implementation that
    // matched either end would call the model its producer.
    expect(producerOf(BUILT, "dataset:src")).toBeNull();
  });
});

describe("tabsFor", () => {
  it("offers both tabs on a dataset a transform writes", () => {
    expect(tabsFor(DS, BUILT)).toEqual(["preview", "code"]);
  });

  it("offers Preview alone on an uploaded dataset", () => {
    expect(tabsFor(DS, UPLOADED)).toEqual(["preview"]);
  });

  it("offers Code alone on a transform", () => {
    expect(tabsFor(MODEL, BUILT)).toEqual(["code"]);
  });

  it("offers nothing on an object type or a data source", () => {
    // Neither holds rows of its own here and neither is written by a
    // transform, so both tabs would open onto an apology.
    expect(tabsFor(TYPE, BUILT)).toEqual([]);
    expect(tabsFor(CONN, BUILT)).toEqual([]);
  });

  it("puts Preview first, which is where p.45 starts", () => {
    expect(tabsFor(DS, BUILT)[0]).toBe("preview");
  });
});

describe("keepTab", () => {
  it("keeps the open tab when the next node has it", () => {
    // The workflow p.45 describes: hop down the pipeline reading rows.
    expect(keepTab(["preview", "code"], "preview")).toBe("preview");
    expect(keepTab(["preview", "code"], "code")).toBe("code");
  });

  it("falls back to the first when the next node has no such tab", () => {
    // Selecting an uploaded dataset while Code is open. Keeping "code" would
    // highlight a tab that is not there and render nothing.
    expect(keepTab(["preview"], "code")).toBe("preview");
  });

  it("opens the first tab when nothing was open", () => {
    expect(keepTab(["preview", "code"], null)).toBe("preview");
  });

  it("answers null when the node offers no tabs", () => {
    expect(keepTab([], "preview")).toBeNull();
    expect(keepTab([], null)).toBeNull();
  });
});

describe("noCodeNote", () => {
  it("names both ways a dataset gets here without a transform", () => {
    const said = noCodeNote(DS);
    expect(said).toContain("uploaded");
    expect(said).toContain("data source");
  });

  it("says nothing about a node that is not a dataset", () => {
    // A transform has its own code and an object type is not built at all;
    // explaining an absent Code tab there would explain the wrong absence.
    expect(noCodeNote(MODEL)).toBeNull();
    expect(noCodeNote(TYPE)).toBeNull();
  });
});

describe("narrow", () => {
  const rows = result(["town", "county", "population"], [["Ely", "Cambs", 20112]]);

  it("keeps the columns whose names match, and their cells with them", () => {
    const only = narrow(rows, "co");
    expect(only.columns.map((c) => c.name)).toEqual(["county"]);
    expect(only.rows).toEqual([["Cambs"]]);
  });

  it("matches a substring anywhere in the name, ignoring case", () => {
    expect(narrow(rows, "LAT").columns.map((c) => c.name)).toEqual(["population"]);
  });

  it("hands back the very same object when the query is empty", () => {
    // A new object every keystroke re-renders three hundred rows for nothing.
    expect(narrow(rows, "")).toBe(rows);
    expect(narrow(rows, "   ")).toBe(rows);
  });

  it("keeps each row's cells lined up with the columns it kept", () => {
    // The failure worth catching: filtering the header and not the body puts
    // every value under the wrong name, which reads as corrupt data.
    const wide = result(
      ["a", "town", "b"],
      [["skip", "Ely", "skip"], ["skip", "Wells", "skip"]],
    );
    expect(narrow(wide, "town").rows).toEqual([["Ely"], ["Wells"]]);
  });

  it("answers no columns rather than all of them when nothing matches", () => {
    expect(narrow(rows, "zzz").columns).toEqual([]);
    expect(narrow(rows, "zzz").rows).toEqual([[]]);
  });
});

describe("columnsNote", () => {
  const rows = result(["town", "county", "population"], [["Ely", "Cambs", 20112]]);

  it("says nothing when nobody has searched", () => {
    expect(columnsNote(rows, "")).toBeNull();
  });

  it("says nothing when the search hid nothing", () => {
    // Three of three is a count that tells a reader only that they typed.
    expect(columnsNote(rows, "o")).toBeNull();
  });

  it("counts what is left against what there was", () => {
    expect(columnsNote(rows, "county")).toBe("1 of 3 columns");
  });

  it("says so rather than leaving an empty table to be read", () => {
    // §226: a table of no columns looks exactly like a dataset with none.
    expect(columnsNote(rows, "zzz")).toBe("No column matches “zzz”");
  });
});

describe("previewNote", () => {
  it("says a whole small dataset is whole", () => {
    expect(previewNote(result(["a"], [[1], [2]]))).toBe("2 rows");
    expect(previewNote(result(["a"], [[1]]))).toBe("1 row");
  });

  it("says a window is a window, and how big the dataset is", () => {
    // p.47: "the first 300 rows of the selected dataset". A reader who
    // scrolls to the bottom has to know whether that was the end.
    expect(previewNote(result(["a"], [[1], [2]], { truncated: true, total_rows: 41234 })))
      .toBe("First 2 of 41,234 rows");
  });
});

describe("fileHref", () => {
  it("opens the file in the repository application", () => {
    // `/r/{id}` is the address that survives a rename (§435), and `?file=` is
    // the one §428's palette already navigates by.
    expect(fileHref({ resource_id: "res-1" }, "transforms/daily.sql"))
      .toBe("/r/res-1?file=transforms%2Fdaily.sql");
  });

  it("is null when the transform is authored directly", () => {
    // db 0038 holds the repository and the path together, but this is a
    // browser reading JSON and the constraint is not here.
    expect(fileHref({ resource_id: "res-1" }, null)).toBeNull();
    expect(fileHref(null, "transforms/daily.sql")).toBeNull();
    expect(fileHref(undefined, "transforms/daily.sql")).toBeNull();
  });
});
