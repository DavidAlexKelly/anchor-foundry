/**
 * Where a pipeline node opens (§351; `data-lineage` p.32).
 *
 * The rule is one function because three graphs draw the same nodes, and the
 * failure it prevents is the quiet one: a kind added to the graph that two of
 * the three cannot navigate to.
 */
import { describe, expect, it } from "vitest";
import {
  DRAG_FLOOR, GAP_X, GRAPH_KINDS, NODE_W, PAD, columnsIn, foundByColumn, isDrag, kindsIn, nodePath, nodeSection, nodesInRect, outOfDateNote, relatives, search, toggleSelected, viewOf,
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

describe("finding nodes on the graph (p.8, §356)", () => {
  const nodes = [
    { id: "dataset:1", kind: "dataset", name: "Orders raw", slug: "orders-raw" },
    { id: "model:1", kind: "model", name: "Clean orders", slug: "clean-orders" },
    { id: "dataset:2", kind: "dataset", name: "Clean orders", slug: "clean-orders-out" },
    { id: "object_type:1", kind: "object_type", name: "Customer", slug: "customer" },
    // **A name and a slug that share nothing**, which is the only arrangement
    // that can tell "searched the name" from "searched the slug": everywhere
    // else in this repo a slug is derived from the name, so a build reading
    // only one of the two finds the same nodes as a build reading both.
    { id: "dataset:3", kind: "dataset", name: "Refunds", slug: "rf-2024" },
  ] as const;

  it("matches part of a name, in any case", () => {
    expect(search(nodes, "orders")).toEqual(["dataset:1", "model:1", "dataset:2"]);
    expect(search(nodes, "ORDERS")).toEqual(["dataset:1", "model:1", "dataset:2"]);
    expect(search(nodes, "  orders  ")).toEqual(["dataset:1", "model:1", "dataset:2"]);
  });

  it("matches the slug as well as the name", () => {
    // The slug is what somebody writing a transform against an object type
    // types, and it is the line the card already shows them (§351). Searched
    // on a node whose *name* cannot match, so a build reading only the name
    // fails here.
    expect(search(nodes, "orders-raw")).toEqual(["dataset:1"]);
    expect(search(nodes, "rf-2024")).toEqual(["dataset:3"]);
  });

  it("matches the name as well as the slug", () => {
    // The other direction, and not the same assertion: `Refunds` is nowhere
    // in `rf-2024`, so a build that searched only slugs finds nothing here.
    expect(search(nodes, "refunds")).toEqual(["dataset:3"]);
    expect(search(nodes, "customer")).toEqual(["object_type:1"]);
  });

  it("finds nothing when nothing matches", () => {
    // The negative control: a search that always returned everything would
    // satisfy both assertions above.
    expect(search(nodes, "invoices")).toEqual([]);
  });

  it("says nothing at all before it has been asked anything", () => {
    // **The state the page opens in.** A search that starts by highlighting
    // the whole graph has said nothing, and would dim nothing while claiming
    // to have found forty things.
    expect(search(nodes, "")).toEqual([]);
    expect(search(nodes, "   ")).toEqual([]);
  });

  it("narrows to the kinds asked for (p.8's Advanced tab)", () => {
    expect(search(nodes, "orders", ["model"])).toEqual(["model:1"]);
    expect(search(nodes, "orders", ["dataset"])).toEqual(["dataset:1", "dataset:2"]);
  });

  it("takes several kinds at once", () => {
    expect(search(nodes, "orders", ["dataset", "model"]))
      .toEqual(["dataset:1", "model:1", "dataset:2"]);
  });

  it("treats no kind chosen as no restriction", () => {
    // Not as "match nothing": a reader who has not touched the filter means
    // all of them, and an empty array is what that looks like in state.
    expect(search(nodes, "orders", [])).toEqual(["dataset:1", "model:1", "dataset:2"]);
  });

  it("answers a kind on its own, with no text", () => {
    // "Show me the models" is a question even with the box empty — which is
    // why the nothing-matches-nothing rule above is about *both* being empty
    // rather than about the query alone.
    expect(search(nodes, "", ["object_type"])).toEqual(["object_type:1"]);
  });

  it("returns results in the graph's own order", () => {
    // The nodes arrive in the layer order the server sorted them into, so
    // "the first match" is the one furthest upstream. Asserted against a
    // shuffled input so a build that re-sorted by name or by id fails.
    const shuffled = [nodes[2], nodes[0], nodes[1]];
    expect(search(shuffled, "orders")).toEqual(["dataset:2", "dataset:1", "model:1"]);
  });
});

describe("the view a graph is saved or shared at (p.12, §360)", () => {
  it("carries what was chosen", () => {
    expect(viewOf({
      selected: ["dataset:1"], column: "id", query: "orders", kinds: ["model"], colouring: "status",
    })).toEqual({
      selected: ["dataset:1"], column: "id", query: "orders", kinds: ["model"],
    });
  });

  it("leaves out the parts nobody chose", () => {
    // **Omitted, not empty.** A view carrying `query: ""` and `selected: []`
    // saves as a filter nobody set and reopens looking deliberate.
    expect(viewOf({ selected: [], column: null, query: "", kinds: [], colouring: "status" })).toEqual({});
  });

  it("treats a blank search as no search", () => {
    expect(viewOf({ selected: [], column: null, query: "   ", kinds: [], colouring: "status" })).toEqual({});
  });

  it("copies rather than aliasing what it was given", () => {
    // The caller's arrays are React state; a view holding a reference to them
    // is a saved graph that changes after it was saved.
    const selected = ["dataset:1"];
    const view = viewOf({ selected, column: null, query: "", kinds: [], colouring: "status" });
    selected.push("dataset:2");
    expect(view.selected).toEqual(["dataset:1"]);
  });

  it("carries a colouring somebody chose", () => {
    // p.38's colouring is part of what was being looked at (§419): a graph
    // shared to show what is out of date and reopened on build status says
    // something else.
    expect(viewOf({
      selected: [], column: null, query: "", kinds: [], colouring: "out_of_date",
    })).toEqual({ colouring: "out_of_date" });
  });

  it("leaves out the colouring nobody changed", () => {
    // The default is the state somebody who never opened the picker is in.
    // Storing it would make a graph saved before §419 and one saved with the
    // picker untouched two different records of the same view.
    expect(viewOf({
      selected: [], column: null, query: "", kinds: [], colouring: "status",
    })).toEqual({});
  });

  it("carries 'no colour', which is a choice and not a default", () => {
    // The one value that looks like emptiness and is not: p.38's first option
    // is somebody deciding the colours were in the way.
    expect(viewOf({
      selected: [], column: null, query: "", kinds: [], colouring: "none",
    })).toEqual({ colouring: "none" });
  });

  it("keeps a column that is there and drops one that is not", () => {
    // The negative control: `column` is the one field whose empty value is
    // `null` rather than a length, so it needs saying separately.
    expect(viewOf({ selected: [], column: "id", query: "", kinds: [], colouring: "status" }))
      .toEqual({ column: "id" });
  });
});

describe("the kinds a stored view names", () => {
  it("keeps the ones this graph draws", () => {
    expect(kindsIn({ kinds: ["dataset", "object_type"] }))
      .toEqual(["dataset", "object_type"]);
  });

  it("drops one this build does not draw", () => {
    // **A view saved by a later build**, or by one that drew a kind since
    // removed, would otherwise put a filter on the graph matching nothing,
    // with no way to see that it had.
    expect(kindsIn({ kinds: ["dataset", "sandwich"] })).toEqual(["dataset"]);
  });

  it("reads a view with no kinds, and no view at all, as no filter", () => {
    expect(kindsIn({})).toEqual([]);
    expect(kindsIn(undefined)).toEqual([]);
  });

  it("names every kind the graph can draw", () => {
    // `PipelineNode["kind"]` is the list, and a kind missing here is one a
    // saved view could never filter to (§191's direction: guard the mirror
    // against the thing it mirrors).
    expect(new Set(GRAPH_KINDS))
      .toEqual(new Set(["dataset", "model", "object_type", "connection"]));
  });

  it("opens a data source where a connection is configured (§420)", () => {
    // Not the dataset it filled: the question a source node raises is "where
    // is this data coming from, and is it still pointed at the right table",
    // and that is answered on the connections page.
    expect(nodeSection({ kind: "connection" })).toBe("connections");
    expect(nodePath({ kind: "connection" }, "acme", "sales"))
      .toBe("/acme/sales/connections");
  });
});

describe("finding by column name (p.11; §417)", () => {
  const NODES = [
    { id: "d1", kind: "dataset" as const, name: "Sites", slug: "sites" },
    { id: "d2", kind: "dataset" as const, name: "Shipments", slug: "shipments" },
    { id: "d3", kind: "dataset" as const, name: "Weather", slug: "weather" },
    { id: "m1", kind: "model" as const, name: "Site risk", slug: "site-risk" },
  ];
  const COLUMNS = [
    { name: "site_id", datasets: ["d1", "d2"] },
    { name: "recorded_at", datasets: ["d3"] },
  ];

  it("finds the datasets that have the column", () => {
    // p.11: "you can either search for the name of the node or column names in
    // datasets". `Shipments` contains no "site" in its own name.
    expect(search(NODES, "site_id", [], COLUMNS)).toEqual(["d1", "d2"]);
  });

  it("still finds by name and slug", () => {
    // The other half of p.11's sentence, and the half that already worked —
    // one box answers both, so neither may quietly stop working.
    expect(search(NODES, "weather", [], COLUMNS)).toEqual(["d3"]);
    expect(search(NODES, "site-risk", [], COLUMNS)).toEqual(["m1"]);
  });

  it("returns a node once when both its name and a column match", () => {
    // `Sites` matches by name and holds `site_id`. Two reasons is still one
    // card, and a duplicate id would make "5 of 40" count it twice.
    const found = search(NODES, "site", [], COLUMNS);
    expect(found).toEqual([...new Set(found)]);
    expect(found).toEqual(["d1", "d2", "m1"]);
  });

  it("keeps the graph's own order", () => {
    // The layer order the server sorted into, so "the first match" means the
    // one furthest upstream — column matches must not be appended at the end.
    expect(search(NODES, "site", [], COLUMNS)).toEqual(["d1", "d2", "m1"]);
  });

  it("applies the kind filter to column matches too", () => {
    // p.8's Advanced tab. "Models with a column called site_id" is answered by
    // nothing, because only datasets have columns — and answering it with the
    // datasets would ignore the filter the reader set.
    expect(search(NODES, "site_id", ["model"], COLUMNS)).toEqual([]);
    expect(search(NODES, "site_id", ["dataset"], COLUMNS)).toEqual(["d1", "d2"]);
  });

  it("matches a column by part of its name, like a node", () => {
    expect(search(NODES, "_id", [], COLUMNS)).toEqual(["d1", "d2"]);
  });

  it("finds nothing extra when no column matches", () => {
    expect(search(NODES, "nothing", [], COLUMNS)).toEqual([]);
  });

  it("matches nothing for an empty query, columns or not", () => {
    // The page opens in this state, and a search that starts by highlighting
    // the whole graph has said nothing.
    expect(search(NODES, "", [], COLUMNS)).toEqual([]);
    expect(search(NODES, "   ", [], COLUMNS)).toEqual([]);
  });

  it("is name and slug only when no columns are supplied", () => {
    // Every caller written before §417, and every saved view (§360): a search
    // that silently started matching columns would change what an existing
    // saved graph resolves to.
    expect(search(NODES, "site_id")).toEqual([]);
    expect(search(NODES, "site_id", [])).toEqual([]);
  });
});

describe("foundByColumn (p.11; §417)", () => {
  const NODES = [
    { id: "d1", kind: "dataset" as const, name: "Sites", slug: "sites" },
    { id: "d2", kind: "dataset" as const, name: "Shipments", slug: "shipments" },
  ];
  const COLUMNS = [{ name: "site_id", datasets: ["d1", "d2"] }];

  it("names the results that would otherwise be unexplained", () => {
    // §214: a card that lights up for a reason nobody can see is worse than
    // one that does not light up. **Both** of these are unexplained for this
    // query — `Sites` contains no "site_id" either, which is the case that
    // makes the explanation worth having: a reader who typed a column name
    // sees two cards light up and neither says the words they typed.
    expect(foundByColumn(NODES, "site_id", COLUMNS)).toEqual(["d1", "d2"]);
  });

  it("leaves out a result whose own name already explains it", () => {
    // `Sites` matches by name too, so it needs no explaining — counting it
    // would make the explanation bigger than the surprise it covers.
    expect(foundByColumn(NODES, "site", COLUMNS)).toEqual(["d2"]);
  });

  it("is empty when nothing matched by column", () => {
    expect(foundByColumn(NODES, "shipments", COLUMNS)).toEqual([]);
    expect(foundByColumn(NODES, "", COLUMNS)).toEqual([]);
    expect(foundByColumn(NODES, "site_id", [])).toEqual([]);
  });
});
