/** The affected datasets on the lineage graph (§369; `code-repositories`
 *  p.54-55). */
import { describe, expect, it } from "vitest";
import {
  missingNote,
  nodeIdFor,
  notOnGraph,
  reviewByNode,
  rowForNode,
  type AffectedRow,
} from "./pipeline-review";

const ME = "me-1";

// **Every fixture is distinguishable from every other** (§190). A file whose
// path echoed its model's name, or two rows sharing a dataset id, would let a
// build that returned the wrong one of them look right.
const affected = (n: string, dataset: string): AffectedRow => ({
  state: "affected",
  model_id: `model-${n}`,
  model_name: `Model ${n}`,
  path: `transforms/${n}.py`,
  dataset: {
    id: `ds-${dataset}`, name: `Dataset ${dataset}`, slug: `dataset-${dataset}`,
    row_count: 1, current_version: 1,
  },
});

const neverBuilt: AffectedRow = {
  state: "never_built",
  model_id: "model-nb",
  model_name: "Never built",
  path: "transforms/nb.py",
  dataset: null,
};

const mark = (id: string, verdict?: string | null) => ({
  reviewer_id: id, reviewer_email: `${id}@x`, verdict,
});

describe("where a row lands on the graph", () => {
  it("is the dataset's node, spelled the way the graph spells it", () => {
    expect(nodeIdFor(affected("a", "one"))).toBe("dataset:ds-one");
  });

  it("is nowhere when the transform has no output dataset yet", () => {
    // §364's three states: two of them have nothing to mark.
    expect(nodeIdFor(neverBuilt)).toBeNull();
  });
});

describe("p.55's indicator", () => {
  it("carries my verdict on the file that generates each dataset", () => {
    const rows = [affected("a", "one"), affected("b", "two")];
    const files = [
      { path: "transforms/a.py", read_by: [mark(ME, "approved")] },
      { path: "transforms/b.py", read_by: [mark(ME, "rejected")] },
    ];
    // Asserted whole: a build that put one file's verdict on the other
    // dataset passes any check that only looks at one of them.
    expect([...reviewByNode(rows, files, ME)]).toEqual([
      ["dataset:ds-one", "approved"],
      ["dataset:ds-two", "rejected"],
    ]);
  });

  it("is mine, not whatever anybody said", () => {
    const rows = [affected("a", "one")];
    const files = [{ path: "transforms/a.py", read_by: [mark("ada", "approved")] }];
    expect(reviewByNode(rows, files, ME).get("dataset:ds-one")).toBe("unread");
  });

  it("is unread when the proposal has no file at that path", () => {
    // The impact list and the file list are resolved from the same place, so
    // this should not happen - and "no entry" would draw no indicator at all,
    // which reads as "you have not looked at it" by accident rather than on
    // purpose. Said explicitly instead.
    const rows = [affected("a", "one")];
    expect(reviewByNode(rows, [], ME).get("dataset:ds-one")).toBe("unread");
  });

  it("has no entry for a row with no dataset", () => {
    expect(reviewByNode([neverBuilt], [], ME).size).toBe(0);
  });
});

describe("selecting a node", () => {
  it("finds the row whose dataset it is", () => {
    const rows = [affected("a", "one"), affected("b", "two")];
    expect(rowForNode(rows, "dataset:ds-two")?.path).toBe("transforms/b.py");
  });

  it("finds nothing for a node the proposal does not touch", () => {
    expect(rowForNode([affected("a", "one")], "dataset:ds-other")).toBeUndefined();
  });

  it("finds nothing when nothing is selected", () => {
    // **With a row that has no node in the list**, because that is the only
    // arrangement that can tell the guard apart from its absence: a search for
    // "the row whose node id is null" finds one of these, and would answer a
    // question about the selection with a row nobody selected.
    expect(rowForNode([affected("a", "one"), neverBuilt], null)).toBeUndefined();
  });
});

describe("what the picture leaves out", () => {
  it("is the rows with no dataset", () => {
    const missing = notOnGraph([affected("a", "one"), neverBuilt], ["dataset:ds-one"]);
    expect(missing.map((r) => r.path)).toEqual(["transforms/nb.py"]);
  });

  it("is also a dataset the graph does not contain", () => {
    // The tab is handed a graph; nothing guarantees it holds every dataset the
    // proposal changes, and a reader counting cards would come up short with
    // no way to know which ones were dropped.
    const missing = notOnGraph([affected("a", "one"), affected("b", "two")], ["dataset:ds-one"]);
    expect(missing.map((r) => r.dataset?.name)).toEqual(["Dataset two"]);
  });

  it("is nothing when every row is on the graph", () => {
    const rows = [affected("a", "one"), affected("b", "two")];
    expect(notOnGraph(rows, ["dataset:ds-one", "dataset:ds-two"])).toEqual([]);
    expect(missingNote([])).toBe("");
  });
});

describe("the sentence naming them", () => {
  it("names one in the singular", () => {
    expect(missingNote([affected("a", "one")])).toBe("Dataset one is not on this graph.");
  });

  it("names several in the plural", () => {
    expect(missingNote([affected("a", "one"), affected("b", "two")])).toBe(
      "Dataset one, Dataset two are not on this graph.",
    );
  });

  it("falls back to what the row does have", () => {
    // A row with no dataset has no dataset name, and the reason it is missing
    // is exactly that - so naming it by its model is the only way to name it.
    expect(missingNote([neverBuilt])).toBe("Never built is not on this graph.");
  });

  it("counts the rest rather than listing everything", () => {
    const many = ["one", "two", "three", "four", "five"].map((n, i) =>
      affected(String(i), n),
    );
    expect(missingNote(many)).toBe(
      "Dataset one, Dataset two, Dataset three and 2 more are not on this graph.",
    );
  });
});
