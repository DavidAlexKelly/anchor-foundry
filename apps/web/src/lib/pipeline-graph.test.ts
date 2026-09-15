/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * The rule is one function because three graphs draw the same nodes, and the
 * failure it prevents is the quiet one: a kind added to the graph that two of
 * the three cannot navigate to.
 */
import { describe, expect, it } from "vitest";
import {
  columnsIn,
  DRAG_FLOOR,
  GAP_X,
  isDrag,
  NODE_W,
  nodePath,
  nodeSection,
  nodesInRect,
  outOfDateNote,
  PAD,
  relatives,
  toggleSelected,
} from "./pipeline-graph";

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

describe("selecting several nodes (p.7, p.54, §354)", () => {
  const node = (id: string, layer: number, position: number) => ({ id, layer, position });

  describe("a drag rectangle", () => {
    it("takes the nodes it is drawn over", () => {
      const nodes = [node("a", 0, 0), node("b", 0, 1), node("c", 3, 0)];
      // A rectangle down the first column, stopping short of layer 3.
      expect(nodesInRect(nodes, { x1: 0, y1: 0, x2: 200, y2: 400 })).toEqual(["a", "b"]);
    });

    it("is the same rectangle drawn from either corner", () => {
      // Dragging up-and-left is the same gesture as dragging down-and-right,
      // and a build that trusted x1 < x2 would select nothing for half of the
      // drags a person makes.
      const nodes = [node("a", 0, 0), node("b", 0, 1)];
      expect(nodesInRect(nodes, { x1: 200, y1: 400, x2: 0, y2: 0 })).toEqual(["a", "b"]);
    });

    it("takes a node it only overlaps", () => {
      // **The decision this function makes.** A rectangle ending one pixel
      // inside the card has selected it; requiring containment would mean
      // dragging past the edge of a graph to pick up the node you are looking
      // at. `nodeX(0)` is PAD, so this rect's right edge is one pixel in.
      expect(nodesInRect([node("a", 0, 0)], { x1: 0, y1: 0, x2: PAD + 1, y2: PAD + 1 }))
        .toEqual(["a"]);
    });

    it("leaves a node it misses entirely", () => {
      // The negative control: overlap that never says no is not a hit test.
      expect(nodesInRect([node("a", 0, 0)], { x1: 0, y1: 0, x2: PAD - 1, y2: 1000 }))
        .toEqual([]);
      expect(nodesInRect([node("a", 0, 0)], { x1: 0, y1: 0, x2: 1000, y2: PAD - 1 }))
        .toEqual([]);
    });

    it("separates nodes in adjacent layers", () => {
      // The gap between two layers is real space, and a rectangle in it takes
      // neither — this is the assertion that fails if NODE_W and GAP_X are
      // ever swapped.
      const nodes = [node("a", 0, 0), node("b", 1, 0)];
      const between = { x1: PAD + NODE_W + 1, y1: 0, x2: PAD + NODE_W + GAP_X - 1, y2: 1000 };
      expect(nodesInRect(nodes, between)).toEqual([]);
    });
  });

  describe("what counts as a drag", () => {
    it("a press that barely moves is a click", () => {
      expect(isDrag({ x1: 100, y1: 100, x2: 102, y2: 101 })).toBe(false);
    });

    it("movement in either direction alone is enough", () => {
      // Dragging straight down the screen is a drag, and a build that needed
      // both axes would swallow it.
      expect(isDrag({ x1: 100, y1: 100, x2: 100, y2: 100 + DRAG_FLOOR })).toBe(true);
      expect(isDrag({ x1: 100, y1: 100, x2: 100 + DRAG_FLOOR, y2: 100 })).toBe(true);
    });

    it("counts distance, not direction", () => {
      expect(isDrag({ x1: 100, y1: 100, x2: 100 - DRAG_FLOOR, y2: 100 })).toBe(true);
    });
  });

  describe("clicking a node", () => {
    it("replaces the selection", () => {
      expect(toggleSelected(["a", "b"], "c", false)).toEqual(["c"]);
    });

    it("clears when it is the one node already selected", () => {
      // The way back to nothing, which the single-selection graph already had.
      expect(toggleSelected(["a"], "a", false)).toEqual([]);
    });

    it("keeps a node that is one of several", () => {
      // **Not the same as the line above.** Clicking inside a rectangle you
      // just drew should narrow to that node, not empty the selection — a
      // build that tested `includes` rather than "the only one" would clear.
      expect(toggleSelected(["a", "b"], "a", false)).toEqual(["a"]);
    });

    it("adds and removes one node with Ctrl/Cmd held (p.54)", () => {
      expect(toggleSelected(["a"], "b", true)).toEqual(["a", "b"]);
      expect(toggleSelected(["a", "b"], "a", true)).toEqual(["b"]);
    });

    it("never repeats a node", () => {
      // Ctrl+clicking a node twice is a real gesture, and a duplicate would
      // have the histogram count one dataset twice.
      expect(toggleSelected(["a"], "a", true)).toEqual([]);
      expect(toggleSelected(toggleSelected(["a"], "b", true), "b", true)).toEqual(["a"]);
    });
  });

  describe("the histogram in a selection (p.55)", () => {
    const columns = [
      { name: "id", datasets: ["dataset:1", "dataset:2", "dataset:3"] },
      { name: "val", datasets: ["dataset:1", "dataset:2"] },
      { name: "only", datasets: ["dataset:1"] },
    ];

    it("counts columns in the selection, not on the graph", () => {
      expect(columnsIn(columns, ["dataset:2", "dataset:3"])).toEqual([
        { name: "id", datasets: ["dataset:2", "dataset:3"] },
        { name: "val", datasets: ["dataset:2"] },
      ]);
    });

    it("drops a column no selected dataset has", () => {
      // `only` is dataset:1's alone, and it is not in the answer above. Said
      // separately because that assertion would still read as a pass if the
      // narrowing merely emptied the list instead of removing the entry.
      expect(columnsIn(columns, ["dataset:2"]).map((c) => c.name)).toEqual(["id", "val"]);
    });

    it("re-orders when narrowing changes the counts", () => {
      // **Why this re-sorts rather than filters in place.** On the whole graph
      // `id` leads; in a selection of two datasets that `val` covers and `id`
      // covers only half of, the most frequent name is a different one.
      const swapped = [
        { name: "id", datasets: ["dataset:1", "dataset:9"] },
        { name: "val", datasets: ["dataset:1", "dataset:2"] },
      ];
      expect(columnsIn(swapped, ["dataset:1", "dataset:2"]).map((c) => c.name))
        .toEqual(["val", "id"]);
    });

    it("breaks a tie by name, the way the server does", () => {
      const tied = [
        { name: "zeta", datasets: ["dataset:1"] },
        { name: "alpha", datasets: ["dataset:1"] },
      ];
      expect(columnsIn(tied, ["dataset:1"]).map((c) => c.name)).toEqual(["alpha", "zeta"]);
    });

    it("an empty selection is the whole graph", () => {
      // The state the page opens in, and §353's behaviour unchanged.
      expect(columnsIn(columns, [])).toEqual(columns);
    });

    it("leaves the graph's own list alone", () => {
      // The empty case returns a copy: a sort in a later call that reached the
      // server's array would reorder the page under itself.
      const graphColumns = [
        { name: "b", datasets: ["dataset:1"] },
        { name: "a", datasets: ["dataset:1", "dataset:2"] },
      ];
      columnsIn(graphColumns, []).sort((x, y) => x.name.localeCompare(y.name));
      expect(graphColumns.map((c) => c.name)).toEqual(["b", "a"]);
    });

    it("a selection of things that are not datasets has no columns", () => {
      // The honest answer rather than a fallback to the whole graph: two
      // models have no columns between them, and showing the graph's list
      // would say they did.
      expect(columnsIn(columns, ["model:1", "object_type:1"])).toEqual([]);
    });
  });
});

describe("growing a selection along the lineage (p.7, p.52, §355)", () => {
  //   a ─┐
  //      ├─> c ──> d ──> e
  //   b ─┘
  const edges = [
    { from: "a", to: "c" },
    { from: "b", to: "c" },
    { from: "c", to: "d" },
    { from: "d", to: "e" },
  ];

  it("takes one step along the arrows (p.7)", () => {
    expect(relatives(edges, ["c"], "downstream", 1)).toEqual(["c", "d"]);
    expect(relatives(edges, ["c"], "upstream", 1)).toEqual(["c", "a", "b"]);
  });

  it("takes the whole chain when asked for it (p.52)", () => {
    // p.52's double arrow: "all of the ancestor nodes for that dataset".
    expect(relatives(edges, ["e"], "upstream", Infinity)).toEqual([
      "e", "d", "c", "a", "b",
    ]);
  });

  it("stops one step short, which is what makes a step a step", () => {
    // The negative control for the hop count: a build that always walked the
    // whole chain would satisfy the first assertion above for `c` downstream,
    // because `c` happens to have one child.
    expect(relatives(edges, ["e"], "upstream", 1)).toEqual(["e", "d"]);
    expect(relatives(edges, ["e"], "upstream", 2)).toEqual(["e", "d", "c"]);
  });

  it("keeps what was already selected", () => {
    // Growing a selection rather than replacing it is what makes pressing the
    // same button twice reach further instead of starting over.
    expect(relatives(edges, ["a", "b"], "downstream", 1)).toEqual(["a", "b", "c"]);
  });

  it("never repeats a node two paths reach", () => {
    // `c` is reachable from both `a` and `b`, and a duplicate would have the
    // histogram count one dataset twice.
    expect(relatives(edges, ["a", "b"], "downstream", Infinity)).toEqual([
      "a", "b", "c", "d", "e",
    ]);
  });

  it("goes one way at a time", () => {
    // **The distinction the two buttons are for.** Walking both directions at
    // once from a dataset in the middle of a pipeline is the whole component,
    // which is what `focus` already draws — the question here is "what feeds
    // this" or "what does this feed", and they have different answers.
    expect(relatives(edges, ["c"], "downstream", Infinity)).toEqual(["c", "d", "e"]);
    expect(relatives(edges, ["c"], "upstream", Infinity)).toEqual(["c", "a", "b"]);
  });

  it("terminates on a cycle rather than spinning", () => {
    // This graph reports cycles; it does not remove them (§352).
    const loop = [
      { from: "x", to: "y" },
      { from: "y", to: "z" },
      { from: "z", to: "x" },
    ];
    expect(relatives(loop, ["x"], "downstream", Infinity)).toEqual(["x", "y", "z"]);
  });

  it("finds nothing at the end of the line", () => {
    // The negative control: an expansion that always grew would read as
    // working on every node.
    expect(relatives(edges, ["e"], "downstream", Infinity)).toEqual(["e"]);
    expect(relatives(edges, ["a"], "upstream", Infinity)).toEqual(["a"]);
  });

  it("an empty selection grows into nothing", () => {
    expect(relatives(edges, [], "downstream", Infinity)).toEqual([]);
  });
});
