import { describe, expect, it } from "vitest";

import { diffModules, isEmptyChangelog } from "./changelog";

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
