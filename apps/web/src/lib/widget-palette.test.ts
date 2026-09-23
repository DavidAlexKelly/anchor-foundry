import { describe, expect, it } from "vitest";

import {
  CATEGORIES, CATEGORY_OF, emptyNote, grouped, matching, type Entry,
} from "./widget-palette";
import { readFileSync } from "node:fs";

import { PALETTE } from "../components/canvas/widget-list";

const entry = (key: string, label: string, hint = ""): Entry => ({ key, label, hint });

describe("the two lists agree", () => {
  it("gives every widget in the palette a category", () => {
    // **The check the fallback exists to make unnecessary.** A widget with no
    // category still appears, under Other — so without this, adding one and
    // forgetting to place it is invisible until somebody goes looking.
    const missing = PALETTE.map((p) => p.key).filter((key) => !(key in CATEGORY_OF));
    expect(missing).toEqual([]);
  });

  it("holds the same keys the resolver does", () => {
    // `widgets.tsx` narrows this list to the resolver's key union with a cast,
    // which TypeScript cannot check across the file boundary — a widget listed
    // under a name the resolver does not have would be a palette item that
    // creates nothing. The names are the claim, and this is where it is made.
    expect(PALETTE.every((p) => p.key.startsWith("Canvas"))).toBe(true);
    expect(new Set(PALETTE.map((p) => p.key)).size).toBe(PALETTE.length);
  });

  it("categorises nothing that is not in the palette", () => {
    // The other direction: a stale entry here is a line nobody reads and
    // nothing removes.
    const keys = new Set(PALETTE.map((p) => p.key));
    expect(Object.keys(CATEGORY_OF).filter((key) => !keys.has(key))).toEqual([]);
  });

  it("uses only categories that exist", () => {
    const ids = new Set(CATEGORIES.map((c) => c.id));
    expect(Object.values(CATEGORY_OF).filter((id) => !ids.has(id))).toEqual([]);
  });

  it("has something in every category it offers", () => {
    // A heading with nothing under it is a heading (§226).
    const used = new Set(Object.values(CATEGORY_OF));
    expect(CATEGORIES.map((c) => c.id).filter((id) => !used.has(id))).toEqual([]);
  });
});

/**
 * Where each widget is placed, read out of the document that placed it.
 *
 * **Not a literal copy of `CATEGORY_OF`.** A list written here by hand would
 * agree with the map because both were typed from the same reading, and the
 * mutation that moved Markdown from Visualization to Core display survived
 * exactly that — every other test here is about the map being *total* and
 * *consistent*, and none of them is about it being *right*.
 *
 * `docs/parity/workshop.md` lists every widget in a table under the Foundry
 * page its category comes from, which is what this module's categories are.
 * So the specification is read, and the map is checked against it — the same
 * move `test_the_browser_reads_the_same_settings_file_the_server_does` makes
 * across languages (§441), applied across a document and its code.
 */
function placedBySpec(): Map<string, string> {
  const heading: Record<string, string> = {
    "Filtering": "filtering",
    "Core display": "display",
    "Visualization": "visualization",
    "Event-trigger and navigational": "events",
  };
  const spec = readFileSync(
    new URL("../../../../docs/parity/workshop.md", import.meta.url), "utf8",
  ).split("\n");
  const placed = new Map<string, string>();
  let category: string | undefined;
  for (const line of spec) {
    if (line.startsWith("### ")) {
      const named = Object.keys(heading).find((h) => line.slice(4).startsWith(h));
      category = named ? heading[named] : undefined;
      continue;
    }
    if (!category || !line.startsWith("| ")) continue;
    // **The first name on the row, and the first row that names it.** A row
    // is `| Foundry | Ours | Notes |`, so the component this row is *about*
    // comes before any the note mentions in passing — and a widget is placed
    // by the table that gives it a row, not by a later cross-reference. The
    // Markdown row names `CanvasText` in its prose, which is how this was
    // found.
    const first = line.match(/Canvas[A-Za-z]+/)?.[0];
    if (first && !placed.has(first)) placed.set(first, category);
  }
  return placed;
}

describe("the categories are the specification's", () => {
  const placed = placedBySpec();

  it("read enough of the document to be a check at all", () => {
    // §226: agreeing with an empty expectation is not agreement. If the
    // document's headings are reworded, this fails rather than passing on
    // nothing.
    expect(placed.size).toBeGreaterThan(25);
  });

  it("places every widget where workshop.md places it", () => {
    const wrong = [...placed]
      .filter(([key]) => key in CATEGORY_OF)
      .filter(([key, category]) => CATEGORY_OF[key] !== category)
      .map(([key, category]) => `${key}: ours says ${CATEGORY_OF[key]}, the spec says ${category}`);
    expect(wrong).toEqual([]);
  });

  it("does not leave a widget the document places out of the map", () => {
    const keys = new Set(PALETTE.map((p) => p.key));
    expect([...placed.keys()].filter((key) => keys.has(key) && !(key in CATEGORY_OF)))
      .toEqual([]);
  });
});

describe("grouped", () => {
  const entries = [
    entry("CanvasSection", "Section"),
    entry("CanvasChart", "Chart"),
    entry("CanvasFilterList", "Filter list"),
  ];

  it("lists layout first and other last", () => {
    // A module with no section has nowhere to put anything else; Other is the
    // group that means "not one of Foundry's".
    expect(CATEGORIES[0]!.id).toBe("layout");
    expect(CATEGORIES[CATEGORIES.length - 1]!.id).toBe("other");
  });

  it("puts each widget under its own category, in CATEGORIES order", () => {
    expect(grouped(entries).map((g) => g.category.id))
      .toEqual(["layout", "filtering", "visualization"]);
  });

  it("drops a category with nothing in it", () => {
    // What makes a filtered list readable rather than a list of headings.
    expect(grouped([entry("CanvasChart", "Chart")]).map((g) => g.category.id))
      .toEqual(["visualization"]);
  });

  it("keeps a widget with no category rather than losing it", () => {
    const rogue = grouped([entry("CanvasSomethingNew", "New")]);
    expect(rogue.map((g) => g.category.id)).toEqual(["other"]);
    expect(rogue[0]!.items.map((i) => i.label)).toEqual(["New"]);
  });

  it("keeps the order the palette gave within a group", () => {
    // Re-sorting alphabetically would move the answer under somebody's finger
    // every time the library grew.
    const many = [
      entry("CanvasChart", "Chart"),
      entry("CanvasMap", "Map"),
      entry("CanvasPieChart", "Pie chart"),
    ];
    expect(grouped(many)[0]!.items.map((i) => i.label))
      .toEqual(["Chart", "Map", "Pie chart"]);
  });

  it("names where each grouping comes from", () => {
    // p.444, p.220, p.276, p.480 — so a builder can go and read it.
    const sources = Object.fromEntries(CATEGORIES.map((c) => [c.id, c.source]));
    expect(sources.filtering).toBe("p.444");
    expect(sources.display).toBe("p.220");
    expect(sources.visualization).toBe("p.276");
    expect(sources.events).toBe("p.480");
  });
});

describe("matching", () => {
  const entries = [
    entry("CanvasChart", "Chart", "Bar, line, pie or scatter over a dataset"),
    entry("CanvasDatasetTable", "Dataset table", "Preview rows from a dataset"),
    entry("CanvasMap", "Map", "Pins from a geopoint property"),
  ];

  it("keeps everything when nothing has been typed", () => {
    expect(matching(entries, "").map((e) => e.label)).toHaveLength(3);
    expect(matching(entries, "   ").map((e) => e.label)).toHaveLength(3);
  });

  it("matches the label", () => {
    expect(matching(entries, "map").map((e) => e.label)).toEqual(["Map"]);
  });

  it("matches the hint, which is where the word somebody thought of lives", () => {
    // "dataset" finds the Chart too, because the Chart's hint says it is over
    // one — which is the whole reason the hints are searched.
    expect(matching(entries, "dataset").map((e) => e.label))
      .toEqual(["Chart", "Dataset table"]);
  });

  it("ignores case", () => {
    expect(matching(entries, "GEOPOINT").map((e) => e.label)).toEqual(["Map"]);
  });

  it("matches anywhere in the word, not only at the start", () => {
    // Somebody types the part they remember.
    expect(matching(entries, "catter").map((e) => e.label)).toEqual(["Chart"]);
  });

  it("answers nothing rather than everything when nothing matches", () => {
    expect(matching(entries, "zzz")).toEqual([]);
  });

  it("hands back a new array rather than the one it was given", () => {
    // The caller renders it and the palette is a module constant; handing the
    // original back invites a sort in place that reorders the library.
    expect(matching(entries, "")).not.toBe(entries);
  });
});

describe("emptyNote", () => {
  it("names the query", () => {
    expect(emptyNote(" tabel ")).toBe("No widget matches “tabel”");
  });
});
