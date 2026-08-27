import { describe, expect, it } from "vitest";

import {
  buildGraph, childrenOf, clear, collapse, expand, hasMore, initial, layers,
  parentsOf, PROP_DIRECTION, redo, showAll, step, undo,
} from "./variable-lineage";
import { REFERENCE_PROPS } from "../../lib/workshop-module";
import type { WorkshopVariable } from "../../lib/types";

/** p.77–78's variable lineage graph (Foundry `workshop` p.77, p.78). */

const v = (id: string, extra: Partial<WorkshopVariable> = {}): WorkshopVariable =>
  ({ id, kind: "string", label: id, ...extra } as WorkshopVariable);

const widget = (name: string, props: Record<string, unknown>) =>
  ({ type: { resolvedName: name }, props });

/** **Every prop, pinned by hand — and by hand is the whole point.**
 *
 * The obvious test walks `PROP_DIRECTION` and checks each entry against itself,
 * which agrees with whatever the module happens to say. This is a second
 * opinion written out separately, so flipping one entry in the module makes
 * exactly one line here disagree. §200's harness needed this: with only three
 * spot checks, `drilldownVariable: "write" → "read"` survived, and a survivor
 * there points an arrow the wrong way in the one view whose purpose is being
 * trusted while debugging.
 *
 * The reasoning per prop is on `PROP_DIRECTION` itself; p.69's split is the
 * rule — an *output variable* is a write, an *input variable* a read.
 */
const EXPECTED_DIRECTION: Record<string, "read" | "write"> = {
  name: "write",
  filterParameter: "write",
  searchParameter: "write",
  drilldownVariable: "write",
  variable: "read",
  objectSetVariable: "read",
  enabledVariable: "read",
  visibleWhen: "read",
  subjectVariable: "read",
  seriesVariable: "read",
  collapsedWhen: "read",
  tabVariable: "read",
  arrayVariable: "read",
  optionsVariable: "read",
};

describe("PROP_DIRECTION", () => {
  it("classifies every reference prop", () => {
    // **The guard this catalogue exists for.** A prop missing here is an edge
    // the graph silently omits: the widget and the variable both appear,
    // unconnected, and nothing says why. Fourth instance of the shape §190,
    // §191 and §193 were each caught by — so it is checked against
    // `REFERENCE_PROPS` rather than against a second copy of itself. The type
    // now refuses this too; the test stays because a type can be loosened in
    // one edit and this says out loud what the loosening would cost.
    const unclassified = REFERENCE_PROPS.filter((p) => !(p in PROP_DIRECTION));
    expect(unclassified).toEqual([]);
  });

  it("classifies nothing that is not a reference prop", () => {
    // The other direction: a classification for a prop nothing reads is a
    // rule with no subject, and it would hide the fact that the real prop is
    // spelled differently.
    const extra = Object.keys(PROP_DIRECTION)
      .filter((p) => !(REFERENCE_PROPS as readonly string[]).includes(p));
    expect(extra).toEqual([]);
  });

  it("has a hand-written expectation for every reference prop", () => {
    // Otherwise a new prop would be classified in the module and pinned
    // nowhere, and the table below would quietly stop being complete.
    expect(Object.keys(EXPECTED_DIRECTION).sort())
      .toEqual([...REFERENCE_PROPS].sort());
  });

  it.each(Object.entries(EXPECTED_DIRECTION))(
    "calls %s a %s",
    (prop, direction) => {
      expect(PROP_DIRECTION[prop as keyof typeof PROP_DIRECTION]).toBe(direction);
    },
  );
});

describe("buildGraph", () => {
  const variables = { v_in: v("v_in"), v_out: v("v_out", {
    derivation: { transform: "concat", inputs: ["v_in"] },
  } as never) };

  it("points a derivation edge from the input to the output", () => {
    const g = buildGraph(variables, {});
    expect(parentsOf(g, "v_out")).toEqual(["v_in"]);
    expect(childrenOf(g, "v_in")).toEqual(["v_out"]);
  });

  it("puts a widget that reads a variable downstream of it", () => {
    const g = buildGraph(variables, {
      table: widget("CanvasObjectTable", { objectSetVariable: "v_in" }),
    });
    expect(childrenOf(g, "v_in")).toContain("table");
    expect(parentsOf(g, "table")).toEqual(["v_in"]);
  });

  it("puts a widget that writes a variable upstream of it", () => {
    // **The direction that makes the graph worth trusting.** A control feeds
    // its variable; getting this backwards points the arrow the wrong way,
    // which is worse than not drawing it in a view for debugging.
    const g = buildGraph(variables, {
      control: widget("CanvasParameterControl", { name: "v_in" }),
    });
    expect(parentsOf(g, "v_in")).toEqual(["control"]);
    expect(childrenOf(g, "control")).toEqual(["v_in"]);
  });

  it("records why each edge exists", () => {
    const g = buildGraph(variables, {
      table: widget("CanvasObjectTable", { objectSetVariable: "v_in" }),
    });
    expect(g.edges.find((e) => e.to === "table")?.via).toBe("objectSetVariable");
    expect(g.edges.find((e) => e.to === "v_out")?.via).toBe("derivation");
  });

  it("leaves out a widget that references nothing", () => {
    // p.77's graph is of things that "depend on one another"; a module's
    // fortieth Text widget is noise in a view for finding a relationship.
    const g = buildGraph(variables, {
      plain: widget("CanvasText", { text: "hello" }),
    });
    expect(g.nodes.has("plain")).toBe(false);
    expect(g.nodes.has("v_in")).toBe(true);
  });

  it("ignores a reference to a variable that is not declared", () => {
    // A stale binding, which the panel already reports elsewhere. An edge to a
    // node that does not exist would draw an arrow into nothing.
    const g = buildGraph(variables, {
      table: widget("CanvasObjectTable", { objectSetVariable: "v_gone" }),
    });
    expect(g.nodes.has("table")).toBe(false);
    expect(g.edges.every((e) => e.from !== "v_gone" && e.to !== "v_gone")).toBe(true);
  });

  it("ignores ROOT", () => {
    const g = buildGraph(variables, {
      ROOT: widget("CanvasContainer", { objectSetVariable: "v_in" }),
    });
    expect(g.nodes.has("ROOT")).toBe(false);
  });

  it("gives a widget the name the Layout panel gives it", () => {
    // So a node and a tree row are recognisably the same thing.
    const g = buildGraph(variables, {
      w: { ...widget("CanvasObjectTable", { objectSetVariable: "v_in", title: "Orders" }) },
    });
    expect(g.nodes.get("w")?.label).toBe("Orders");
    const renamed = buildGraph(variables, {
      w: {
        ...widget("CanvasObjectTable", { objectSetVariable: "v_in", title: "Orders" }),
        custom: { displayName: "Renamed" },
      },
    });
    expect(renamed.nodes.get("w")?.label).toBe("Renamed");
  });

  it("draws one node per widget however many variables it references", () => {
    const g = buildGraph(
      { a: v("a"), b: v("b") },
      { w: widget("CanvasObjectTable", { objectSetVariable: "a", visibleWhen: "b" }) },
    );
    expect([...g.nodes.keys()].filter((k) => k === "w")).toHaveLength(1);
    expect(parentsOf(g, "w").sort()).toEqual(["a", "b"]);
  });
});

describe("expand and collapse (p.78's chevrons)", () => {
  //   control -> v_in -> v_out -> table
  const variables = {
    v_in: v("v_in"),
    v_out: v("v_out", { derivation: { transform: "concat", inputs: ["v_in"] } } as never),
  };
  const graph = buildGraph(variables, {
    control: widget("CanvasParameterControl", { name: "v_in" }),
    table: widget("CanvasObjectTable", { objectSetVariable: "v_out" }),
  });

  it("expands parents and children one step", () => {
    const fromOut = expand(graph, new Set(["v_out"]), "v_out", "parents");
    expect([...fromOut].sort()).toEqual(["v_in", "v_out"]);
    const down = expand(graph, new Set(["v_out"]), "v_out", "children");
    expect([...down].sort()).toEqual(["table", "v_out"]);
  });

  it("expands every missing neighbour, not just the first", () => {
    // **One chevron, one step, all of it.** p.78's arrow expands "a node's
    // parents", plural — revealing one of two would draw a graph that is not
    // wrong so much as incomplete, and the missing edge is invisible: the
    // chevron stays, so it reads as a node with more behind it rather than as
    // a node whose expansion dropped something.
    const two = buildGraph({ a: v("a"), b: v("b") }, {
      w: widget("CanvasObjectTable", { objectSetVariable: "a", visibleWhen: "b" }),
    });
    expect([...expand(two, new Set(["w"]), "w", "parents")].sort())
      .toEqual(["a", "b", "w"]);
  });

  it("returns the same set when there is nothing left to reveal", () => {
    // Identity, so a click that reveals nothing costs no history entry - undo
    // would otherwise step through actions that changed nothing.
    const shown = new Set(["v_in", "v_out"]);
    expect(expand(graph, shown, "v_out", "parents")).toBe(shown);
  });

  it("says whether a chevron has anything behind it", () => {
    // p.78: "Nodes with dependencies have chevron arrows", so a node with none
    // must draw no chevron rather than one that does nothing.
    expect(hasMore(graph, new Set(["v_out"]), "v_out", "parents")).toBe(true);
    expect(hasMore(graph, new Set(["v_in", "v_out"]), "v_out", "parents")).toBe(false);
    expect(hasMore(graph, new Set(["control"]), "control", "parents")).toBe(false);
  });

  it("collapses a node's neighbours back out", () => {
    const shown = new Set(["v_in", "v_out"]);
    expect([...collapse(graph, shown, "v_out", "parents")]).toEqual(["v_out"]);
  });

  it("keeps a neighbour another visible node also depends on", () => {
    // **The rule that stops a collapse taking away an edge somebody is
    // reading.** `v_in` is shown because of `v_out`, and `control` writes it -
    // so collapsing `v_out`'s parents must not remove a node `control` holds.
    const shown = new Set(["control", "v_in", "v_out"]);
    expect(collapse(graph, shown, "v_out", "parents")).toBe(shown);
  });

  it("never removes the node being collapsed", () => {
    const shown = new Set(["v_in", "v_out"]);
    expect(collapse(graph, shown, "v_out", "parents").has("v_out")).toBe(true);
  });

  it("never removes the node being collapsed when it is its own neighbour", () => {
    // **The case that separates the guard from the rest of the filter**, and
    // the reason it is a case at all: `layers` already carries a cycle guard
    // whose comment says a document can arrive with a loop in it. The server
    // refuses a cyclic *derivation* at save, but `buildGraph` is handed
    // whatever document reaches the browser, and a variable listing itself as
    // an input makes a node its own parent. Collapsing then has to keep it —
    // dropping it would leave a lineage graph that erased the node the author
    // clicked, with nothing on screen to say why.
    const looped = buildGraph(
      { v_self: v("v_self", { derivation: { transform: "concat", inputs: ["v_self"] } } as never) },
      {},
    );
    expect(parentsOf(looped, "v_self")).toEqual(["v_self"]);
    const shown = new Set(["v_self"]);
    expect(collapse(looped, shown, "v_self", "parents")).toBe(shown);
  });
});

describe("showAll and clear (p.78)", () => {
  const graph = buildGraph({ a: v("a"), b: v("b") }, {
    w: widget("CanvasObjectTable", { objectSetVariable: "a" }),
  });

  it("shows every node", () => {
    expect([...showAll(graph)].sort()).toEqual(["a", "b", "w"]);
  });

  it("clears to nothing", () => {
    expect([...clear()]).toEqual([]);
  });
});

describe("undo and redo (p.78)", () => {
  it("steps backward and forward through expansions", () => {
    let h = initial(new Set(["a"]));
    h = step(h, { shown: new Set(["a", "b"]) });
    h = step(h, { shown: new Set(["a", "b", "c"]) });
    expect([...h.present.shown]).toHaveLength(3);

    h = undo(h);
    expect([...h.present.shown]).toHaveLength(2);
    h = undo(h);
    expect([...h.present.shown]).toEqual(["a"]);

    h = redo(h);
    expect([...h.present.shown]).toHaveLength(2);
  });

  it("steps through selection too", () => {
    // p.78: "expand, collapse, and **selection** actions".
    let h = initial(new Set(["a"]));
    h = step(h, { selected: "a" });
    expect(h.present.selected).toBe("a");
    expect(undo(h).present.selected).toBeNull();
  });

  it("tells an explicit deselection apart from no opinion", () => {
    // **`undefined` and `null` are different answers here**, and Clear is what
    // makes the difference reachable: it steps with `{ shown: clear(),
    // selected: null }`, meaning *nothing is selected any more*. Read as "no
    // opinion", the selection survives an emptied graph and the next node to
    // land in that id lights up as selected — a highlight nobody asked for, on
    // a node nobody has clicked.
    let h = initial(new Set(["a"]));
    h = step(h, { selected: "a" });
    expect(step(h, { shown: new Set(["a", "b"]) }).present.selected).toBe("a");
    expect(step(h, { selected: null }).present.selected).toBeNull();
  });

  it("drops a step that changed nothing", () => {
    // p.78 ties undo to *actions*, and an action that changed no state is not
    // one — so undo never appears to do nothing.
    const h = initial(new Set(["a"]));
    const same = step(h, { shown: h.present.shown });
    expect(same).toBe(h);
    expect(same.past).toHaveLength(0);
  });

  it("discards the future when a new step is taken", () => {
    let h = initial(new Set(["a"]));
    h = step(h, { shown: new Set(["a", "b"]) });
    h = undo(h);
    h = step(h, { shown: new Set(["a", "c"]) });
    expect(h.future).toHaveLength(0);
    expect(redo(h)).toBe(h);
  });

  it("is a no-op at either end", () => {
    const h = initial(new Set(["a"]));
    expect(undo(h)).toBe(h);
    expect(redo(h)).toBe(h);
  });
});

describe("layers", () => {
  const variables = {
    v_in: v("v_in"),
    v_out: v("v_out", { derivation: { transform: "concat", inputs: ["v_in"] } } as never),
  };
  const graph = buildGraph(variables, {
    table: widget("CanvasObjectTable", { objectSetVariable: "v_out" }),
  });

  it("puts upstream nodes in lower layers", () => {
    const l = layers(graph, new Set(["v_in", "v_out", "table"]));
    expect(l.get("v_in")).toBe(0);
    expect(l.get("v_out")).toBe(1);
    expect(l.get("table")).toBe(2);
  });

  it("counts only the shown subgraph", () => {
    // **So a layer does not jump when an unrelated branch opens** and move
    // everything the author was reading.
    const l = layers(graph, new Set(["v_out", "table"]));
    expect(l.get("v_out")).toBe(0);
    expect(l.get("table")).toBe(1);
  });

  it("does not hang on a cycle", () => {
    // The server refuses a cyclic *derivation*, but a widget can read one
    // variable and write another that feeds back - and a view for debugging is
    // the worst place to hang.
    const cyclic = buildGraph({ a: v("a"), b: v("b") }, {
      w1: widget("CanvasParameterControl", { name: "a", visibleWhen: "b" }),
      w2: widget("CanvasParameterControl", { name: "b", visibleWhen: "a" }),
    });
    const l = layers(cyclic, new Set(["a", "b", "w1", "w2"]));
    expect(l.size).toBe(4);
  });

  it("ignores an id that is not in the graph", () => {
    expect(layers(graph, new Set(["nope"])).size).toBe(0);
  });
});
