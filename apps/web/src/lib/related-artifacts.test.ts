import { describe, expect, it } from "vitest";

import {
  EXCLUSION_NOTE, KINDS, SORTS, artifactEntries, askedFor, emptyNote, kindCounts,
  type ArtifactKind, type ArtifactSort, type RelatedArtifact,
} from "./related-artifacts";

const names = new Map([
  ["dataset:d1", "orders"],
  ["object_type:t1", "Order"],
  ["model:m1", "clean orders"],
]);

function artifact(over: Partial<RelatedArtifact>): RelatedArtifact {
  return {
    kind: "workshop_module", id: "a", name: "A", resource_id: "r-a",
    project_id: "p-sales", project_name: "Sales",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    nodes: ["dataset:d1"], ...over,
  };
}

// Names, paths, creation and modification each in a different order, so each
// sort is told apart from the others.
const FOUR = [
  artifact({ id: "b", name: "Bravo", project_id: "p-zed", project_name: "Zed",
             created_at: "2026-03-01T00:00:00Z", updated_at: "2026-03-05T00:00:00Z" }),
  artifact({ id: "a", name: "Alpha", project_name: "Sales",
             created_at: "2026-02-01T00:00:00Z", updated_at: "2026-04-01T00:00:00Z" }),
  artifact({ id: "c", name: "Charlie", kind: "code_repository", project_name: "Sales",
             nodes: ["model:m1"],
             created_at: "2026-01-01T00:00:00Z", updated_at: "2026-03-01T00:00:00Z" }),
  artifact({ id: "d", name: "Delta", project_id: "p-ads", project_name: "Ads",
             created_at: "2026-04-01T00:00:00Z", updated_at: "2026-03-03T00:00:00Z" }),
];

function order(sort: ArtifactSort, hidden: ArtifactKind[] = []): string[] {
  return artifactEntries(FOUR, {
    names, currentProject: "p-sales", sort, hidden: new Set(hidden),
  }).map((e) => e.label);
}

describe("askedFor", () => {
  it("asks about datasets, object types and transforms, in the selection's order", () => {
    expect(askedFor(["model:m1", "connection:c1", "dataset:d1", "object_type:t1"]))
      .toEqual(["model:m1", "dataset:d1", "object_type:t1"]);
  });

  it("asks about nothing for nothing, or for a source alone", () => {
    expect(askedFor([])).toEqual([]);
    expect(askedFor(["connection:c1"])).toEqual([]);
  });
});

describe("artifactEntries", () => {
  it("sorts by each of p.30's five orders", () => {
    expect(SORTS.map((s) => s.sort)).toEqual(["name", "path", "newest", "oldest", "modified"]);
    expect(order("name")).toEqual(["Alpha", "Bravo", "Charlie", "Delta"]);
    expect(order("path")).toEqual(["Delta", "Alpha", "Charlie", "Bravo"]);
    expect(order("newest")).toEqual(["Delta", "Bravo", "Alpha", "Charlie"]);
    expect(order("oldest")).toEqual(["Charlie", "Alpha", "Bravo", "Delta"]);
    expect(order("modified")).toEqual(["Alpha", "Bravo", "Delta", "Charlie"]);
  });

  it("breaks a tie by name", () => {
    const same = [artifact({ id: "y", name: "Yankee" }), artifact({ id: "x", name: "Xray" })];
    expect(artifactEntries(same, {
      names, currentProject: "p-sales", sort: "newest", hidden: new Set(),
    }).map((e) => e.label)).toEqual(["Xray", "Yankee"]);
  });

  it("leaves out the item types filtered away", () => {
    expect(KINDS.map((k) => k.kind)).toEqual(["workshop_module", "code_repository"]);
    expect(order("name", ["code_repository"])).toEqual(["Alpha", "Bravo", "Delta"]);
    expect(order("name", ["workshop_module"])).toEqual(["Charlie"]);
    expect(order("name", ["workshop_module", "code_repository"])).toEqual([]);
  });

  it("links each to its resource, names another project, and names its nodes", () => {
    const entries = artifactEntries([
      artifact({ id: "a", resource_id: "r-a", nodes: ["dataset:d1", "object_type:t1"] }),
      artifact({ id: "b", name: "B", kind: "code_repository", resource_id: "r-b",
                 project_id: "p-ops", project_name: "Ops", nodes: ["dataset:gone"] }),
    ], { names, currentProject: "p-sales", sort: "name", hidden: new Set() });
    expect(entries).toEqual([
      { key: "workshop_module:a", kind: "workshop_module", label: "A", project: null,
        href: "/r/r-a",
        nodes: [{ id: "dataset:d1", label: "orders" }, { id: "object_type:t1", label: "Order" }] },
      { key: "code_repository:b", kind: "code_repository", label: "B", project: "Ops",
        href: "/r/r-b", nodes: [{ id: "dataset:gone", label: "dataset:gone" }] },
    ]);
  });
});

describe("kindCounts", () => {
  it("counts each item type, zero for none", () => {
    expect(kindCounts(FOUR)).toEqual({ workshop_module: 3, code_repository: 1 });
    expect(kindCounts([])).toEqual({ workshop_module: 0, code_repository: 0 });
  });
});

describe("the notes", () => {
  it("says why a list is empty", () => {
    expect(emptyNote(0, 0)).toContain("Select a dataset");
    expect(emptyNote(2, 0)).toBe("Nothing off the graph links to the selection.");
    expect(emptyNote(2, 3)).toBe("Every item type is filtered out.");
    expect(EXCLUSION_NOTE).toContain("no artifact is left out");
  });
});
