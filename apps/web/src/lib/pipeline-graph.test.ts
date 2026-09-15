/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * The rule is one function because three graphs draw the same nodes, and the
 * failure it prevents is the quiet one: a kind added to the graph that two of
 * the three cannot navigate to.
 */
import { describe, expect, it } from "vitest";
import { nodePath, nodeSection } from "./pipeline-graph";

describe("where a pipeline node opens", () => {
  it("an object type goes to the Ontology Manager (p.32)", () => {
    expect(nodeSection({ kind: "object_type" })).toBe("objects");
    expect(nodePath({ kind: "object_type" }, "acme", "sales"))
      .toBe("/acme/sales/objects");
  });

  it("a model and a dataset keep going where they always did", () => {
    // The negative control: a helper that sent everything to one place would
    // satisfy the assertion above on its own.
    expect(nodeSection({ kind: "model" })).toBe("models");
    expect(nodeSection({ kind: "dataset" })).toBe("datasets");
    expect(nodePath({ kind: "model" }, "acme", "sales")).toBe("/acme/sales/models");
  });

  it("answers for every kind the graph can draw", () => {
    // `PipelineNode["kind"]` is the list, and a kind with no section here
    // would fall through to the datasets page — a wrong answer rather than a
    // missing one, which is why this asserts the three by name.
    const kinds = ["dataset", "model", "object_type"] as const;
    expect(new Set(kinds.map((kind) => nodeSection({ kind })))).toEqual(
      new Set(["datasets", "models", "objects"]),
    );
  });
});
