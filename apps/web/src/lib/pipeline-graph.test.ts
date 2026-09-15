/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * The rule is one function because three graphs draw the same nodes, and the
 * failure it prevents is the quiet one: a kind added to the graph that two of
 * the three cannot navigate to.
 */
import { describe, expect, it } from "vitest";
import { nodePath, nodeSection, outOfDateNote } from "./pipeline-graph";

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

describe("what an out-of-date node says (p.51, §352)", () => {
  const node = (over: Record<string, unknown> = {}) => ({
    out_of_date: true,
    out_of_date_reason: "input_is_newer",
    ...over,
  });

  it("names this dataset when its own input is newer", () => {
    expect(outOfDateNote(node())).toBe("its input is newer");
  });

  it("points further up when the problem is upstream", () => {
    // **The distinction the whole feature turns on.** One sentence names the
    // dataset to rebuild; the other says the thing to rebuild is somewhere
    // else, and a single "out of date" would send somebody to the wrong one.
    expect(outOfDateNote(node({ out_of_date_reason: "upstream_is_out_of_date" })))
      .toBe("an upstream is out of date");
  });

  it("says nothing at all about a current node", () => {
    // The negative control: a note that fired on everything would satisfy
    // both assertions above.
    expect(outOfDateNote({ out_of_date: false, out_of_date_reason: null })).toBe("");
    // And `out_of_date` is what decides it, not the reason — a stale node whose
    // reason went missing still needs to say so.
    expect(outOfDateNote({ out_of_date: false,
                           out_of_date_reason: "input_is_newer" })).toBe("");
  });

  it("still says something for a reason this build has not heard of", () => {
    // A server that grows a third reason should not silently draw nothing;
    // "something is stale" is the half that is still true.
    expect(outOfDateNote(node({ out_of_date_reason: "source_is_late" })))
      .toBe("its input is newer");
  });
});
