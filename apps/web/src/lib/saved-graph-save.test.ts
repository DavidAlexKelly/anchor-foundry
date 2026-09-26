/** §512: saving a lineage graph over one that exists (`data-lineage` p.12). */
import { describe, expect, it } from "vitest";

import { replaceNote, saveLabel, savedNamed } from "./saved-graph-save";

const graphs = [{ id: "1", name: "Orders" }, { id: "2", name: "Refunds" }];

describe("savedNamed", () => {
  it("finds the graph a typed name collides with, trimmed, case and all", () => {
    expect(savedNamed(graphs, "Refunds")?.id).toBe("2");
    expect(savedNamed(graphs, "  Orders ")?.id).toBe("1");
    expect(savedNamed(graphs, "orders")).toBeNull();
    expect(savedNamed(graphs, "New")).toBeNull();
  });

  it("finds nothing for a blank name or before the list has loaded", () => {
    expect(savedNamed([{ id: "3", name: "" }], "   ")).toBeNull();
    expect(savedNamed(undefined, "Orders")).toBeNull();
  });
});

describe("saveLabel and replaceNote", () => {
  it("says Replace only over a graph that exists", () => {
    expect(saveLabel(null)).toBe("Save");
    expect(saveLabel(graphs[0]!)).toBe("Replace");
  });

  it("says what replacing does, and to whom", () => {
    expect(replaceNote(graphs[0]!)).toBe(
      'A saved graph called "Orders" already exists. Replacing it keeps the name and saves what '
      + "you are looking at as its view, for everybody in the project.");
  });
});
