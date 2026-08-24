import { describe, expect, it } from "vitest";

import {
  canPark, ensureUnusedNode, isParked, move, park, UNUSED_NAME, unusedIds, unusedNode,
} from "./unused";
import type { LayoutNodes } from "../../lib/workshop-module";

/** p.68's *Unused widgets* area (Foundry `workshop` p.68).
 *
 * The claim this has to protect hardest is that placing a parked widget is a
 * **move, not a copy**: ids survive, so the variables it reads and the events
 * triggered from it come along untouched. A version that minted new ids would
 * look identical on screen and quietly unbind everything.
 */

const node = (name: string, parent: string | null, kids: string[] = []) => ({
  type: { resolvedName: name },
  isCanvas: true,
  props: {},
  parent,
  nodes: kids,
  linkedNodes: {},
});

const widget = (parent: string, props: Record<string, unknown> = {}) => ({
  type: { resolvedName: "CanvasText" }, props, parent, nodes: [],
});

/** A page with one section holding one widget. */
function doc(extra: Record<string, unknown> = {}, rootKids = ["p1"]): LayoutNodes {
  return {
    ROOT: node("CanvasContainer", null, rootKids),
    p1: node("CanvasPage", "ROOT", ["s1"]),
    s1: node("CanvasSection", "p1", ["w1"]),
    w1: widget("s1", { text: "one" }),
    ...extra,
  } as unknown as LayoutNodes;
}

const minter = () => {
  let n = 0;
  return () => `u${++n}`;
};

const kidsOf = (layout: LayoutNodes, id: string) =>
  ((layout[id] as { nodes?: string[] })?.nodes ?? []);

const parentOf = (layout: LayoutNodes, id: string) =>
  (layout[id] as { parent?: string | null })?.parent ?? null;

describe("unusedNode", () => {
  it("is null for a document that has never parked anything", () => {
    // Not created on demand: asking the question should not change the answer.
    expect(unusedNode(doc())).toBeNull();
  });

  it("finds the holding node under ROOT", () => {
    const layout = doc({ h: node(UNUSED_NAME, "ROOT", []) }, ["p1", "h"]);
    expect(unusedNode(layout)).toBe("h");
  });

  it("ignores a holding node that is not under ROOT", () => {
    // A document from a raw-JSON edit could nest one. The panel reads ROOT's
    // children, so a nested one would be a list nothing shows.
    const layout = doc({ h: node(UNUSED_NAME, "s1", []) });
    expect(unusedNode(layout)).toBeNull();
  });
});

describe("unusedIds", () => {
  it("lists what is parked, in order", () => {
    const layout = doc(
      { h: node(UNUSED_NAME, "ROOT", ["w2", "w3"]), w2: widget("h"), w3: widget("h") },
      ["p1", "h"],
    );
    expect(unusedIds(layout)).toEqual(["w2", "w3"]);
  });

  it("is empty when there is no holding node", () => {
    expect(unusedIds(doc())).toEqual([]);
  });
});

describe("isParked", () => {
  const layout = doc(
    { h: node(UNUSED_NAME, "ROOT", ["s2"]), s2: node("CanvasSection", "h", ["w2"]),
      w2: widget("s2") },
    ["p1", "h"],
  );

  it("is true for a parked widget", () => {
    expect(isParked(layout, "s2")).toBe(true);
  });

  it("is true for a node inside a parked section", () => {
    // **Walks up, not one level.** A parked section has children, and every
    // one of them is equally not-on-a-page - a check of the immediate parent
    // would list them in the main tree.
    expect(isParked(layout, "w2")).toBe(true);
  });

  it("is false for a widget on a page", () => {
    expect(isParked(layout, "w1")).toBe(false);
    expect(isParked(layout, "p1")).toBe(false);
  });

  it("does not hang on a parent cycle", () => {
    // A layout is a tree and should not contain one, but this reads documents
    // that can arrive from anywhere.
    const cyclic = { a: node("CanvasSection", "b"), b: node("CanvasSection", "a") };
    expect(isParked(cyclic as unknown as LayoutNodes, "a")).toBe(false);
  });
});

describe("move", () => {
  const layout = doc({ h: node(UNUSED_NAME, "ROOT", []) }, ["p1", "h"]);

  it("takes the node out of its old parent and puts it in the new one", () => {
    const out = move(layout, "w1", "h");
    expect(kidsOf(out, "s1")).toEqual([]);
    expect(kidsOf(out, "h")).toEqual(["w1"]);
  });

  it("repoints the moved node's parent", () => {
    // Craft believes the parent pointer, so a document whose child list and
    // parent pointer disagree renders one way and comes back another.
    expect(parentOf(move(layout, "w1", "h"), "w1")).toBe("h");
  });

  it("keeps the id, so bindings survive", () => {
    // **The claim that separates this from a paste.** A move that minted a
    // new id would look identical on screen and silently unbind every event
    // triggered from the widget and every usage counted against it.
    const out = move(layout, "w1", "h");
    expect(out.w1).toBeDefined();
    expect((out.w1 as { props: Record<string, unknown> }).props.text).toBe("one");
  });

  it("appends rather than replacing what is already there", () => {
    const withOne = move(layout, "w1", "h");
    const withTwo = move(withOne, "s1", "h");
    expect(kidsOf(withTwo, "h")).toEqual(["w1", "s1"]);
  });

  it("refuses to move a node into its own subtree", () => {
    // Both would leave the document, and nothing would say so.
    expect(move(layout, "s1", "w1")).toBe(layout);
    expect(move(layout, "p1", "s1")).toBe(layout);
  });

  it("refuses a node that is not there, and ROOT", () => {
    expect(move(layout, "nope", "h")).toBe(layout);
    expect(move(layout, "w1", "nope")).toBe(layout);
    expect(move(layout, "ROOT", "h")).toBe(layout);
  });

  it("is a no-op when the node is already in that parent", () => {
    expect(move(layout, "w1", "s1")).toBe(layout);
  });

  it("leaves every other node alone", () => {
    const out = move(layout, "w1", "h");
    expect(kidsOf(out, "ROOT")).toEqual(["p1", "h"]);
    expect(kidsOf(out, "p1")).toEqual(["s1"]);
  });
});

describe("ensureUnusedNode", () => {
  it("adds a holding node under ROOT", () => {
    const result = ensureUnusedNode(doc(), minter())!;
    expect(result.id).toBe("u1");
    expect(kidsOf(result.layout, "ROOT")).toEqual(["p1", "u1"]);
    expect(parentOf(result.layout, "u1")).toBe("ROOT");
  });

  it("returns the existing one rather than a second", () => {
    // Two would split the list and hide whichever the panel did not read.
    const layout = doc({ h: node(UNUSED_NAME, "ROOT", []) }, ["p1", "h"]);
    const result = ensureUnusedNode(layout, minter())!;
    expect(result.id).toBe("h");
    expect(result.layout).toBe(layout);
  });

  it("is null for a document with no ROOT", () => {
    expect(ensureUnusedNode({} as LayoutNodes, minter())).toBeNull();
  });
});

describe("canPark", () => {
  const layout = doc({ h: node(UNUSED_NAME, "ROOT", []),
                       o1: node("CanvasOverlay", "ROOT", []) }, ["p1", "h", "o1"]);

  it("allows a widget and a section", () => {
    expect(canPark(layout, "w1")).toBe(true);
    expect(canPark(layout, "s1")).toBe(true);
  });

  it("refuses a page and an overlay", () => {
    // p.68 is about widgets. Parking a page takes its whole contents off the
    // module in a click, and a page in the holding area has nowhere to go back
    // to except ROOT - a different operation wearing the same button.
    expect(canPark(layout, "p1")).toBe(false);
    expect(canPark(layout, "o1")).toBe(false);
  });

  it("refuses the holding node itself and anything unknown", () => {
    expect(canPark(layout, "h")).toBe(false);
    expect(canPark(layout, "nope")).toBe(false);
  });
});

describe("park", () => {
  it("creates the holding node on the way", () => {
    // One action from the author's side, not two.
    const out = park(doc(), "w1", minter());
    expect(unusedIds(out)).toEqual(["w1"]);
    expect(parentOf(out, "w1")).toBe("u1");
  });

  it("reuses the holding node the second time", () => {
    const once = park(doc(), "w1", minter());
    const twice = park(once, "s1", minter());
    expect(unusedIds(twice)).toEqual(["w1", "s1"]);
    expect(kidsOf(twice, "ROOT").filter((id) => id.startsWith("u"))).toHaveLength(1);
  });

  it("refuses what canPark refuses, rather than half-doing it", () => {
    const layout = doc();
    expect(park(layout, "p1", minter())).toBe(layout);
    expect(park(layout, "ROOT", minter())).toBe(layout);
    expect(park(layout, "nope", minter())).toBe(layout);
  });

  it("round-trips: park then place puts it back with its id", () => {
    // **The whole feature in one sequence.** Each step can be right alone
    // while the pair loses the binding, which is what the id assertion is for.
    const parked = park(doc(), "w1", minter());
    expect(isParked(parked, "w1")).toBe(true);

    const placed = move(parked, "w1", "s1");
    expect(isParked(placed, "w1")).toBe(false);
    expect(kidsOf(placed, "s1")).toEqual(["w1"]);
    expect((placed.w1 as { props: Record<string, unknown> }).props.text).toBe("one");
  });
});
