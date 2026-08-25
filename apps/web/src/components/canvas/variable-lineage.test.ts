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

describe("PROP_DIRECTION", () => {
  it("classifies every reference prop", () => {
    // **The guard this catalogue exists for.** A prop missing here is an edge
    // the graph silently omits: the widget and the variable both appear,
    // unconnected, and nothing says why. Fourth instance of the shape §190,
    // §191 and §193 were each caught by — so it is checked against
    // `REFERENCE_PROPS` rather than against a second copy of itself.
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

  it("calls a parameter control's output a write", () => {
    // p.69: "Output variables define the data passed out of a given widget".
    expect(PROP_DIRECTION.name).toBe("write");
    expect(PROP_DIRECTION.filterParameter).toBe("write");
  });

  it("calls the set a table draws a read", () => {
    expect(PROP_DIRECTION.objectSetVariable).toBe("read");
  });
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
