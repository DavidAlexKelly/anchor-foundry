import { describe, expect, it } from "vitest";

import {
  changeDetail, changeTree, diffModules, fieldChanges, isEmptyChangelog,
} from "./changelog";

/** The Changelog panel's arithmetic (Foundry `workshop` p.193).
 *
 * > "The Changelog panel highlights additions, deletions, changes, moves, and
 * > newly unused elements."
 *
 * Five kinds, and the tests below are arranged around the ones that are easy
 * to conflate: a move is not a change, and a variable nothing reads any more is
 * not a deletion.
 */

const node = (type: string, props: object = {}, over: object = {}) => ({
  type: { resolvedName: type },
  props,
  nodes: [],
  ...over,
});

function module(layout: object, over: object = {}) {
  return { format: 2, layout, variables: {}, events: {}, ...over };
}

describe("diffModules", () => {
  it("reports an added and a deleted widget", () => {
    const before = module({ a: node("CanvasText") });
    const after = module({ b: node("CanvasButton") });
    const { widgets } = diffModules(before, after);
    expect(widgets).toEqual([
      { id: "b", label: "CanvasButton", kind: "added" },
      { id: "a", label: "CanvasText", kind: "deleted" },
    ]);
  });

  it("reports a prop edit as changed", () => {
    const before = module({ a: node("CanvasText", { text: "before" }) });
    const after = module({ a: node("CanvasText", { text: "after" }) });
    expect(diffModules(before, after).widgets).toEqual([
      { id: "a", label: "CanvasText", kind: "changed" },
    ]);
  });

  it("says nothing about a widget that did not move or change", () => {
    const before = module({ a: node("CanvasText", { text: "same" }) });
    expect(diffModules(before, structuredClone(before)).widgets).toEqual([]);
    expect(isEmptyChangelog(diffModules(before, structuredClone(before)))).toBe(true);
  });

  it("calls a widget dragged into another section moved, not changed", () => {
    // **The distinction p.193 draws and a deep comparison cannot.** A node
    // stores its parent inside the same object as its props, so comparing the
    // whole node calls every move a change.
    const before = module({
      s1: node("CanvasSection", {}, { nodes: ["a"], isCanvas: true }),
      s2: node("CanvasSection", {}, { nodes: [], isCanvas: true }),
      a: node("CanvasText", { text: "same" }, { parent: "s1" }),
    });
    const after = module({
      s1: node("CanvasSection", {}, { nodes: [], isCanvas: true }),
      s2: node("CanvasSection", {}, { nodes: ["a"], isCanvas: true }),
      a: node("CanvasText", { text: "same" }, { parent: "s2" }),
    });
    const moved = diffModules(before, after).widgets.filter((c) => c.id === "a");
    expect(moved).toEqual([{ id: "a", label: "CanvasText", kind: "moved" }]);
  });

  it("calls a reorder within one parent moved", () => {
    // The other half of "moved": same parent, different position. Without the
    // index check this is silence, and a reordered page reads as no change.
    const before = module({
      s: node("CanvasSection", {}, { nodes: ["a", "b"], isCanvas: true }),
      a: node("CanvasText", {}, { parent: "s" }),
      b: node("CanvasButton", {}, { parent: "s" }),
    });
    const after = module({
      s: node("CanvasSection", {}, { nodes: ["b", "a"], isCanvas: true }),
      a: node("CanvasText", {}, { parent: "s" }),
      b: node("CanvasButton", {}, { parent: "s" }),
    });
    const kinds = Object.fromEntries(
      diffModules(before, after).widgets.map((c) => [c.id, c.kind]),
    );
    expect(kinds.a).toBe("moved");
    expect(kinds.b).toBe("moved");
  });

  it("prefers changed over moved when a widget did both", () => {
    // One entry per widget, and the prop edit is the more informative of the
    // two - a move is visible on the canvas, a changed prop is not.
    const before = module({
      s1: node("CanvasSection", {}, { nodes: ["a"], isCanvas: true }),
      s2: node("CanvasSection", {}, { nodes: [], isCanvas: true }),
      a: node("CanvasText", { text: "before" }, { parent: "s1" }),
    });
    const after = module({
      s1: node("CanvasSection", {}, { nodes: [], isCanvas: true }),
      s2: node("CanvasSection", {}, { nodes: ["a"], isCanvas: true }),
      a: node("CanvasText", { text: "after" }, { parent: "s2" }),
    });
    expect(diffModules(before, after).widgets.filter((c) => c.id === "a")).toEqual([
      { id: "a", label: "CanvasText", kind: "changed" },
    ]);
  });

  it("reads a bare string node type as well as the builder's object form", () => {
    const before = module({});
    const after = module({ a: { type: "CanvasText", props: {}, nodes: [] } });
    expect(diffModules(before, after).widgets).toEqual([
      { id: "a", label: "CanvasText", kind: "added" },
    ]);
  });
});

describe("variables", () => {
  const withVariable = (layout: object, label = "Region") =>
    module(layout, { variables: { v_region: { id: "v_region", label, kind: "string" } } });

  it("reports added, deleted and edited variables by label", () => {
    const before = withVariable({});
    const after = module({}, {
      variables: { v_region: { id: "v_region", label: "Region", kind: "number" } },
    });
    expect(diffModules(before, after).variables).toEqual([
      { id: "v_region", label: "Region", kind: "changed" },
    ]);
    expect(diffModules(module({}), before).variables).toEqual([
      { id: "v_region", label: "Region", kind: "added" },
    ]);
    expect(diffModules(before, module({})).variables).toEqual([
      { id: "v_region", label: "Region", kind: "deleted" },
    ]);
  });

  it("reports a variable nothing reads any more as newly unused", () => {
    // p.193's fifth kind, and the one with no other way to notice it: the
    // variable is still declared and still valid, and the widget that read it
    // is gone.
    const before = withVariable({ a: node("CanvasTable", { objectSetVariable: "v_region" }) });
    const after = withVariable({});
    const variables = diffModules(before, after).variables;
    expect(variables).toEqual([{ id: "v_region", label: "Region", kind: "unused" }]);
  });

  it("does not call a variable unused when something still reads it", () => {
    const before = withVariable({ a: node("CanvasTable", { objectSetVariable: "v_region" }) });
    const after = withVariable({ b: node("CanvasChart", { objectSetVariable: "v_region" }) });
    expect(diffModules(before, after).variables).toEqual([]);
  });

  it("counts a {{v_id}} interpolation as reading the variable", () => {
    // Text and action values read variables without naming them in a prop, so
    // a scan that only looked at prop values would report a variable used by
    // a heading as unused.
    const before = withVariable({ a: node("CanvasText", { text: "Site {{v_region}}" }) });
    const after = withVariable({ a: node("CanvasText", { text: "Site" }) });
    expect(diffModules(before, after).variables).toEqual([
      { id: "v_region", label: "Region", kind: "unused" },
    ]);
  });

  it("counts an event as reading a variable", () => {
    const layout = { a: node("CanvasButton") };
    const before = module(layout, {
      variables: { v_region: { id: "v_region", label: "Region" } },
      events: {
        e: { id: "e", trigger: { node: "a", on: "click" },
             effects: [{ type: "set_variable", config: { variable: "v_region", value: "x" } }] },
      },
    });
    const after = module(layout, {
      variables: { v_region: { id: "v_region", label: "Region" } },
      events: {},
    });
    const kinds = diffModules(before, after).variables.map((c) => c.kind);
    expect(kinds).toEqual(["unused"]);
  });

  it("does not report a variable that was already unused as newly unused", () => {
    // "Newly" is the word p.193 uses, and it is doing work: a module full of
    // variables nothing has ever read would otherwise flag all of them on
    // every save.
    const before = module({}, { variables: { v: { id: "v", label: "V" } } });
    const after = module({ a: node("CanvasText") }, { variables: { v: { id: "v", label: "V" } } });
    expect(diffModules(before, after).variables).toEqual([]);
  });
});

describe("events", () => {
  it("reports an added event by its first effect", () => {
    const before = module({});
    const after = module({}, {
      events: { e: { id: "e", effects: [{ type: "run_action", config: {} }] } },
    });
    expect(diffModules(before, after).events).toEqual([
      { id: "e", label: "run_action", kind: "added" },
    ]);
  });
});

describe("shape", () => {
  it("survives a document with nothing in it", () => {
    expect(isEmptyChangelog(diffModules(null, undefined))).toBe(true);
    expect(isEmptyChangelog(diffModules({}, { format: 2 }))).toBe(true);
  });
});

// ---- p.193's other two halves (§183) ----------------------------------------

describe("fieldChanges", () => {
  it("names the leaf that changed, not the object around it", () => {
    // p.193's "the exact modifications". A widget whose title changed should
    // report the title, not "props".
    expect(
      fieldChanges({ title: "Sites", pageSize: 25 }, { title: "All sites", pageSize: 25 }),
    ).toEqual([{ path: "title", kind: "changed", before: "Sites", after: "All sites" }]);
  });

  it("reports an added and a removed key separately from a changed one", () => {
    expect(fieldChanges({ a: 1 }, { a: 1, b: 2 })).toEqual([
      { path: "b", kind: "added", after: 2 },
    ]);
    expect(fieldChanges({ a: 1, b: 2 }, { a: 1 })).toEqual([
      { path: "b", kind: "removed", before: 2 },
    ]);
  });

  it("indexes into arrays", () => {
    expect(fieldChanges({ columns: ["id", "name"] }, { columns: ["id", "region"] })).toEqual([
      { path: "columns[1]", kind: "changed", before: "name", after: "region" },
    ]);
  });

  it("reports the elements an array gained or lost", () => {
    // **Walking to the shorter of the two lengths passes every test above**,
    // because they all compare arrays of equal length - and a column added to
    // a table is the single most ordinary edit this panel has to describe.
    expect(fieldChanges({ columns: ["id"] }, { columns: ["id", "region"] })).toEqual([
      { path: "columns[1]", kind: "added", after: "region" },
    ]);
    expect(fieldChanges({ columns: ["id", "region"] }, { columns: ["id"] })).toEqual([
      { path: "columns[1]", kind: "removed", before: "region" },
    ]);
  });

  it("descends through nesting", () => {
    expect(
      fieldChanges({ set: { filters: [{ op: "eq" }] } }, { set: { filters: [{ op: "in" }] } }),
    ).toEqual([{ path: "set.filters[0].op", kind: "changed", before: "eq", after: "in" }]);
  });

  it("calls a change of shape one change, not a teardown and a rebuild", () => {
    // An object replaced by a string is "this became a string", and listing a
    // removal per leaf underneath would describe work nobody did.
    expect(fieldChanges({ a: { b: 1, c: 2 } }, { a: "x" })).toEqual([
      { path: "a", kind: "changed", before: { b: 1, c: 2 }, after: "x" },
    ]);
  });

  it("says nothing when nothing differs", () => {
    expect(fieldChanges({ a: 1, b: [2, { c: 3 }] }, { a: 1, b: [2, { c: 3 }] })).toEqual([]);
    // Absent and null are the same stored value, which is the comparison
    // `diffModules` already makes - the two must agree, or a widget could be
    // reported as changed with an empty detail.
    expect(fieldChanges({ a: null }, {})).toEqual([]);
  });
});

describe("changeDetail", () => {
  const before = module(
    { ROOT: { nodes: ["a"] }, a: node("CanvasText", { text: "Hi" }, { parent: "ROOT" }) },
    { variables: { v: { id: "v", label: "One" } } },
  );

  it("compares a widget on its props", () => {
    const after = module(
      { ROOT: { nodes: ["a"] }, a: node("CanvasText", { text: "Hello" }, { parent: "ROOT" }) },
      { variables: { v: { id: "v", label: "One" } } },
    );
    const change = diffModules(before, after).widgets[0]!;
    expect(changeDetail(before, after, change, "widgets")).toEqual([
      { path: "text", kind: "changed", before: "Hi", after: "Hello" },
    ]);
  });

  it("reports a move as the position it moved to", () => {
    // **A move with an empty detail would read as a panel that failed.** Its
    // props are identical by definition - that is what makes it a move - so
    // the position is the only modification there is to show.
    const after = module({
      ROOT: { nodes: ["s"] },
      s: node("CanvasSection", {}, { parent: "ROOT", nodes: ["a"] }),
      a: node("CanvasText", { text: "Hi" }, { parent: "s" }),
    });
    const change = diffModules(before, after).widgets.find((c) => c.id === "a")!;
    expect(change.kind).toBe("moved");
    expect(changeDetail(before, after, change, "widgets")).toEqual([
      { path: "parent", kind: "changed", before: "ROOT", after: "s" },
    ]);
  });

  it("compares a variable whole, because it has no props to single out", () => {
    const after = module(
      { ROOT: { nodes: ["a"] }, a: node("CanvasText", { text: "Hi" }, { parent: "ROOT" }) },
      { variables: { v: { id: "v", label: "Two" } } },
    );
    const change = diffModules(before, after).variables[0]!;
    expect(changeDetail(before, after, change, "variables")).toEqual([
      { path: "label", kind: "changed", before: "One", after: "Two" },
    ]);
  });
});

describe("changeTree", () => {
  /** A section holding two widgets, which is the smallest layout where
   * "nested components" means anything. */
  const layout = (over: Record<string, object> = {}) => ({
    ROOT: { nodes: ["s"] },
    s: node("CanvasSection", {}, { parent: "ROOT", nodes: ["a", "b"] }),
    a: node("CanvasText", { text: "Hi" }, { parent: "s" }),
    b: node("CanvasButton", { label: "Go" }, { parent: "s" }),
    ...over,
  });

  it("keeps the unchanged parent that a changed child hangs off", () => {
    // **The whole point of p.193's hierarchy.** A flat list would say
    // "CanvasText changed" and lose the section it is in.
    const before = module(layout());
    const after = module(layout({ a: node("CanvasText", { text: "Hello" }, { parent: "s" }) }));
    const tree = changeTree(before, after, diffModules(before, after).widgets);
    expect(tree).toEqual([
      {
        id: "s",
        label: "CanvasSection",
        kind: null,
        children: [{ id: "a", label: "CanvasText", kind: "changed", children: [] }],
      },
    ]);
  });

  it("prunes the branches nothing changed in", () => {
    // The unpruned tree is the whole module, and a changelog that redraws the
    // module buries the one thing that moved. `b` is untouched and absent.
    const before = module(layout());
    const after = module(layout({ a: node("CanvasText", { text: "Hello" }, { parent: "s" }) }));
    const tree = changeTree(before, after, diffModules(before, after).widgets);
    expect(tree[0]!.children.map((child) => child.id)).toEqual(["a"]);
  });

  it("is empty when nothing changed", () => {
    const before = module(layout());
    expect(changeTree(before, structuredClone(before), [])).toEqual([]);
  });

  it("shows a deleted node where it used to be", () => {
    // **The one kind of change with no node left to hang off.** Building the
    // tree from the after-document alone would drop deletions entirely, which
    // is the change somebody most wants placed.
    //
    // The *last* child is the one deleted, deliberately: removing `a` would
    // shift `b` from index 1 to index 0, and §132 reports that as a move -
    // correctly, since its position did change. Two kinds in a fixture built
    // to show one is a test that passes for a reason it did not state.
    const before = module(layout());
    const after = module({
      ROOT: { nodes: ["s"] },
      s: node("CanvasSection", {}, { parent: "ROOT", nodes: ["a"] }),
      a: node("CanvasText", { text: "Hi" }, { parent: "s" }),
    });
    const tree = changeTree(before, after, diffModules(before, after).widgets);
    expect(tree).toEqual([
      {
        id: "s",
        label: "CanvasSection",
        kind: null,
        children: [{ id: "b", label: "CanvasButton", kind: "deleted", children: [] }],
      },
    ]);
  });

  it("does not draw ROOT as a node of its own", () => {
    // Craft.js's container. "The module changed" is not news, and a permanent
    // single root wastes the indentation the hierarchy exists to spend.
    const before = module(layout());
    const after = module(layout({ a: node("CanvasText", { text: "Hello" }, { parent: "s" }) }));
    const tree = changeTree(before, after, diffModules(before, after).widgets);
    expect(tree.map((node_) => node_.id)).not.toContain("ROOT");
  });

  it("still places a node whose parent is missing", () => {
    // A document this panel did not write. Dropping its changes silently is
    // the failure worth avoiding; showing it at the top is the fallback.
    const before = module({ orphan: node("CanvasText", { text: "Hi" }, { parent: "gone" }) });
    const after = module({ orphan: node("CanvasText", { text: "Ho" }, { parent: "gone" }) });
    const tree = changeTree(before, after, diffModules(before, after).widgets);
    expect(tree).toEqual([
      { id: "orphan", label: "CanvasText", kind: "changed", children: [] },
    ]);
  });
});
