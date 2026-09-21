/** p.11's Layout menu, and the hit test that has to agree with it (§424). */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_LAYOUT, GAP_X, GAP_Y, LAYOUTS, NODE_H, NODE_W, PAD, layoutIn,
  layoutOf, nodesInRect, type PlacedNode,
} from "./graph-layout";

const node = (
  id: string, layer: number, position: number, group?: string | null,
): PlacedNode => ({ id, layer, position, group });

/** Where the level layout puts these — the arrangement every test that is not
 *  about arrangements assumes, because it is the one the graph opens on. */
const level = (nodes: readonly PlacedNode[]) => layoutOf(nodes, "level").at;

describe("the menu", () => {
  it("opens on what the graph drew before there was a choice", () => {
    expect(LAYOUTS[0]!.id).toBe(DEFAULT_LAYOUT);
    expect(DEFAULT_LAYOUT).toBe("level");
  });

  it("gives every option a label and a reason", () => {
    for (const option of LAYOUTS) {
      expect(option.label.length, option.id).toBeGreaterThan(0);
      expect(option.hint.length, option.id).toBeGreaterThan(0);
    }
  });

  it("keeps a stored layout this build offers and drops one it does not", () => {
    expect(layoutIn({ layout: "vertical" })).toBe("vertical");
    expect(layoutIn({ layout: "spiral" })).toBe(DEFAULT_LAYOUT);
    expect(layoutIn({})).toBe(DEFAULT_LAYOUT);
    expect(layoutIn(undefined)).toBe(DEFAULT_LAYOUT);
  });

  it("narrows to something the picker can show", () => {
    for (const named of ["vertical", "spiral", "", "colour"]) {
      expect(LAYOUTS.map((o) => o.id)).toContain(layoutIn({ layout: named }));
    }
  });
});

describe("by level (p.11's automatic layout)", () => {
  it("runs the layers left to right and the positions down", () => {
    const at = level([node("a", 0, 0), node("b", 0, 1), node("c", 1, 0)]);
    expect(at.get("a")).toEqual({ x: PAD, y: PAD });
    expect(at.get("b")).toEqual({ x: PAD, y: PAD + NODE_H + GAP_Y });
    expect(at.get("c")).toEqual({ x: PAD + NODE_W + GAP_X, y: PAD });
  });

  it("is what an unknown layout falls back to", () => {
    // A saved view naming a layout a later build dropped should open looking
    // like the graph, not like a blank canvas.
    const nodes = [node("a", 1, 1)];
    expect(layoutOf(nodes, "spiral").at).toEqual(level(nodes));
  });
});

describe("vertical (p.11)", () => {
  it("runs the layers down the page and the positions across", () => {
    const at = layoutOf([node("a", 0, 0), node("b", 1, 0)], "vertical").at;
    expect(at.get("a")).toEqual({ x: PAD, y: PAD });
    expect(at.get("b")!.y).toBeGreaterThan(at.get("a")!.y);
    expect(at.get("b")!.x).toBe(at.get("a")!.x);
  });

  it("keeps a card's width and height apart from the gaps around it", () => {
    // **The mistake this layout invites**: reusing each gap on its own axis
    // puts 26px between stacked cards that are 74 tall, and 88px between
    // neighbours that are 190 wide. The gaps swap with the axes.
    const at = layoutOf([node("a", 0, 0), node("b", 0, 1)], "vertical").at;
    expect(at.get("b")!.x - at.get("a")!.x).toBe(NODE_W + GAP_Y);
    const down = layoutOf([node("a", 0, 0), node("b", 1, 0)], "vertical").at;
    expect(down.get("b")!.y - down.get("a")!.y).toBe(NODE_H + GAP_X);
  });

  it("is a different arrangement from the level one", () => {
    // The negative control: a "vertical" that came out identical would be a
    // menu entry that does nothing (§214).
    const nodes = [node("a", 0, 0), node("b", 1, 0)];
    expect(layoutOf(nodes, "vertical").at).not.toEqual(level(nodes));
  });
});

describe("by colour group (p.11)", () => {
  it("puts each group in a row of its own", () => {
    const at = layoutOf([
      node("a", 0, 0, "failed"), node("b", 1, 0, "failed"),
      node("c", 0, 0, "ok"),
    ], "colour").at;
    // The two failing ones share a row; the passing one is below them.
    expect(at.get("a")!.y).toBe(at.get("b")!.y);
    expect(at.get("c")!.y).toBeGreaterThan(at.get("a")!.y);
  });

  it("keeps the layers running left to right inside a row", () => {
    // Which is what makes this readable at all: a reader can see every
    // failing dataset together *and* still read which feeds which.
    const at = layoutOf([
      node("a", 0, 0, "failed"), node("b", 2, 0, "failed"),
    ], "colour").at;
    expect(at.get("b")!.x).toBeGreaterThan(at.get("a")!.x);
  });

  it("stacks two nodes that share a group and a layer", () => {
    const at = layoutOf([
      node("a", 0, 0, "ok"), node("b", 0, 1, "ok"),
    ], "colour").at;
    expect(at.get("a")!.x).toBe(at.get("b")!.x);
    expect(at.get("b")!.y).toBe(at.get("a")!.y + NODE_H + GAP_Y);
  });

  it("puts the ungrouped in a row of their own, at the end", () => {
    // §210: no verdict is not the same verdict as everybody else's, and
    // folding it into the first group would say it was.
    const at = layoutOf([
      node("plain", 0, 0, null), node("a", 0, 1, "ok"),
    ], "colour").at;
    expect(at.get("plain")!.y).toBeGreaterThan(at.get("a")!.y);
  });

  it("orders rows by first appearance, not by name", () => {
    // The server's ordering, so the rows do not reshuffle between renders —
    // a key a reader is looking between has to stay still.
    const at = layoutOf([
      node("z", 0, 0, "zeta"), node("a", 0, 1, "alpha"),
    ], "colour").at;
    expect(at.get("z")!.y).toBeLessThan(at.get("a")!.y);
  });

  it("gives a row as much height as its deepest stack", () => {
    // **The row that has two cards in one layer is the one that overlaps its
    // neighbour if the row height is a constant.** A sweep found both halves
    // of this untested: fixing the row height, and fixing the stack depth at
    // one, each left every test green while drawing the groups on top of one
    // another.
    const at = layoutOf([
      node("a", 0, 0, "ok"), node("b", 0, 1, "ok"), node("c", 0, 0, "failed"),
    ], "colour").at;
    const deepest = Math.max(at.get("a")!.y, at.get("b")!.y);
    expect(at.get("c")!.y).toBeGreaterThanOrEqual(deepest + NODE_H + GAP_Y);
  });

  it("keeps a clear gap between rows however deep they are", () => {
    // The property, said over a stack of three: no card of the second group
    // may be drawn where a card of the first one is.
    const at = layoutOf([
      node("a", 0, 0, "ok"), node("b", 0, 1, "ok"), node("c", 0, 2, "ok"),
      node("z", 0, 0, "failed"),
    ], "colour").at;
    const first = ["a", "b", "c"].map((id) => at.get(id)!.y);
    expect(at.get("z")!.y).toBeGreaterThan(Math.max(...first) + NODE_H);
  });

  it("is one row when every node shares a group", () => {
    const at = layoutOf([
      node("a", 0, 0, "ok"), node("b", 1, 0, "ok"), node("c", 2, 0, "ok"),
    ], "colour").at;
    expect(new Set([...at.values()].map((p) => p.y)).size).toBe(1);
  });
});

describe("the canvas each layout needs", () => {
  it("is the canvas the graph had before there were layouts", () => {
    // **A gap's worth of room past the last card, not a padding's.** §424
    // gathered this arithmetic and briefly tidied it to a tight box plus PAD;
    // a browser test caught the difference, because the canvas decides the
    // viewport's height and where a drag past the last card lands. The unit
    // changes which arrangement is drawn and nothing else.
    const one = layoutOf([node("a", 2, 3)], "level");
    expect(one.width).toBe(PAD + 3 * (NODE_W + GAP_X));
    expect(one.height).toBe(PAD * 2 + 4 * (NODE_H + GAP_Y));
  });

  it("is big enough for the furthest card", () => {
    const { width, height } = layoutOf([node("far", 5, 4)], "level");
    expect(width).toBeGreaterThanOrEqual(PAD + 5 * (NODE_W + GAP_X) + NODE_W);
    expect(height).toBeGreaterThanOrEqual(PAD + 4 * (NODE_H + GAP_Y) + NODE_H);
  });

  it("has a floor rather than hugging nothing", () => {
    // §214: a viewport sized to nothing is a panel a reader would call broken,
    // and an empty project is an ordinary thing to open.
    const { width, height } = layoutOf([], "level");
    expect(width).toBeGreaterThanOrEqual(400);
    expect(height).toBeGreaterThan(0);
  });

  it("grows downward for vertical and rightward for level", () => {
    const deep = [node("a", 0, 0), node("b", 1, 0), node("c", 2, 0)];
    expect(layoutOf(deep, "level").width)
      .toBeGreaterThan(layoutOf(deep, "vertical").width);
    expect(layoutOf(deep, "vertical").height)
      .toBeGreaterThan(layoutOf(deep, "level").height);
  });
});

describe("selecting several nodes (p.7, p.54, §354)", () => {
  describe("a drag rectangle", () => {
    it("takes the nodes it is drawn over", () => {
      const nodes = [node("a", 0, 0), node("b", 0, 1), node("c", 3, 0)];
      // A rectangle down the first column, stopping short of layer 3.
      expect(nodesInRect(nodes, { x1: 0, y1: 0, x2: 200, y2: 400 }, level(nodes))).toEqual(["a", "b"]);
    });

    it("is the same rectangle drawn from either corner", () => {
      // Dragging up-and-left is the same gesture as dragging down-and-right,
      // and a build that trusted x1 < x2 would select nothing for half of the
      // drags a person makes.
      const nodes = [node("a", 0, 0), node("b", 0, 1)];
      expect(nodesInRect(nodes, { x1: 200, y1: 400, x2: 0, y2: 0 }, level(nodes))).toEqual(["a", "b"]);
    });

    it("takes a node it only overlaps", () => {
      // **The decision this function makes.** A rectangle ending one pixel
      // inside the card has selected it; requiring containment would mean
      // dragging past the edge of a graph to pick up the node you are looking
      // at. The first card sits at PAD, so this rect's right edge is one pixel in.
      const one = [node("a", 0, 0)];
      expect(nodesInRect(one, { x1: 0, y1: 0, x2: PAD + 1, y2: PAD + 1 }, level(one)))
        .toEqual(["a"]);
    });

    it("takes a node it overlaps from the right, not only from the left", () => {
      // **The half a left-anchored rectangle cannot show.** A hit test that
      // compared the card's *left* edge against the rectangle's left edge,
      // rather than its right edge, passes every test drawn from the origin
      // — and drops every card a person selects by dragging leftwards into.
      const one = [node("a", 0, 0)];
      expect(nodesInRect(one, {
        x1: PAD + NODE_W - 1, y1: PAD + 1, x2: 2000, y2: 2000,
      }, level(one))).toEqual(["a"]);
      expect(nodesInRect(one, {
        x1: PAD + 1, y1: PAD + NODE_H - 1, x2: 2000, y2: 2000,
      }, level(one))).toEqual(["a"]);
    });

    it("leaves a node it misses entirely", () => {
      // The negative control: overlap that never says no is not a hit test.
      const one = [node("a", 0, 0)];
      expect(nodesInRect(one, { x1: 0, y1: 0, x2: PAD - 1, y2: 1000 }, level(one)))
        .toEqual([]);
      expect(nodesInRect(one, { x1: 0, y1: 0, x2: 1000, y2: PAD - 1 }, level(one)))
        .toEqual([]);
    });

    it("separates nodes in adjacent layers", () => {
      // The gap between two layers is real space, and a rectangle in it takes
      // neither — this is the assertion that fails if NODE_W and GAP_X are
      // ever swapped.
      const nodes = [node("a", 0, 0), node("b", 1, 0)];
      const between = { x1: PAD + NODE_W + 1, y1: 0, x2: PAD + NODE_W + GAP_X - 1, y2: 1000 };
      expect(nodesInRect(nodes, between, level(nodes))).toEqual([]);
    });
  });
  it("asks the layout in force, not the one it was written against", () => {
    // **The reason this function moved here** (§424). A marquee that kept
    // asking where a card would be under the level layout would, on a vertical
    // graph, select the node beside the one it was drawn around — and nothing
    // on the screen says which copy of the arithmetic is wrong (§191).
    const nodes = [node("a", 0, 0), node("b", 1, 0)];
    const down = layoutOf(nodes, "vertical").at;
    // A band across the top of a vertical graph takes only the first layer.
    const band = { x1: 0, y1: 0, x2: 1000, y2: PAD + NODE_H };
    expect(nodesInRect(nodes, band, down)).toEqual(["a"]);
    // The same band over the level layout takes both, because there they sit
    // side by side — which is the difference a shared hit test has to see.
    expect(nodesInRect(nodes, band, level(nodes))).toEqual(["a", "b"]);
  });

  it("leaves out a node the layout did not place", () => {
    // §210 again: no place is not the origin. A node drawn nowhere must not
    // be selected by a rectangle that happens to cover 0,0.
    const nodes = [node("a", 0, 0)];
    expect(nodesInRect([...nodes, node("ghost", 0, 0)], {
      x1: 0, y1: 0, x2: 1000, y2: 1000,
    }, level(nodes))).toEqual(["a"]);
  });
});
