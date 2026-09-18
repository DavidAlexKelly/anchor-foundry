import { describe, expect, it } from "vitest";
import { visibleNodes } from "./visible-nodes";

function node(name: string, nodes: string[] = [], props: Record<string, unknown> = {}) {
  return { type: { resolvedName: name }, nodes, props };
}

/** ROOT holds a header, two pages, an overlay and the Unused area. */
const LAYOUT = {
  ROOT: node("CanvasContainer", ["head", "p1", "p2", "ov", "CanvasUnused"]),
  head: node("CanvasHeader", ["title"]),
  title: node("CanvasText"),
  p1: node("CanvasPage", ["w1"]),
  w1: node("CanvasParameterControl"),
  p2: node("CanvasPage", ["w2"]),
  w2: node("CanvasParameterControl"),
  ov: node("CanvasOverlay", ["w3"]),
  w3: node("CanvasParameterControl"),
  CanvasUnused: node("CanvasUnused", ["parked"]),
  parked: node("CanvasParameterControl"),
} as unknown;

describe("which page is on screen", () => {
  it("includes the current page and not the other one", () => {
    const seen = visibleNodes(LAYOUT, { page: "p1" });
    expect(seen.has("w1")).toBe(true);
    expect(seen.has("p2")).toBe(false);
    expect(seen.has("w2")).toBe(false);
  });

  it("includes the other page when that is the one showing", () => {
    // The counterweight. A walk that never reached any page would pass the
    // assertion above and be useless.
    const seen = visibleNodes(LAYOUT, { page: "p2" });
    expect(seen.has("w2")).toBe(true);
    expect(seen.has("w1")).toBe(false);
  });

  it("never falls into a page from its parent", () => {
    // The bug this module exists to remove: ROOT lists every page, so a plain
    // descent would mark all of them on screen and the lazy rule would be a
    // rule that never says no.
    const seen = visibleNodes(LAYOUT, { page: null });
    expect(seen.has("w1")).toBe(false);
    expect(seen.has("w2")).toBe(false);
  });
});

describe("the header and the Unused area", () => {
  it("counts the header, which is above every page rather than on one", () => {
    const seen = visibleNodes(LAYOUT, { page: "p1" });
    expect(seen.has("head")).toBe(true);
    expect(seen.has("title")).toBe(true);
  });

  it("never counts a parked widget", () => {
    // Decision 0010: the holding node renders nothing, in both modes. It sits
    // under ROOT, so a walk that did not skip it would put every parked widget
    // on screen — and the variable of a parked Filter List would be recomputed
    // forever for a widget nobody can see.
    const seen = visibleNodes(LAYOUT, { page: "p1" });
    expect(seen.has("parked")).toBe(false);
    expect(seen.has("CanvasUnused")).toBe(false);
  });
});

describe("overlays", () => {
  it("leaves a closed overlay out", () => {
    expect(visibleNodes(LAYOUT, { page: "p1" }).has("w3")).toBe(false);
  });

  it("adds an open one to the page underneath rather than replacing it", () => {
    // p.75 names overlays alongside pages; an overlay opens *over* the page,
    // which is still there behind it.
    const seen = visibleNodes(LAYOUT, { page: "p1", overlay: "ov" });
    expect(seen.has("w3")).toBe(true);
    expect(seen.has("w1")).toBe(true);
  });
});

describe("tabs", () => {
  const TABBED = {
    ROOT: node("CanvasContainer", ["p1"]),
    p1: node("CanvasPage", ["sec"]),
    sec: node("CanvasSection", ["a", "b"], { direction: "tabs", tabs: "One,Two" }),
    a: node("CanvasParameterControl"),
    b: node("CanvasParameterControl"),
  } as unknown;

  it("shows the first tab when nothing has chosen one", () => {
    // `activeTab`'s own default, and the renderer's. A module opens on tab one.
    const seen = visibleNodes(TABBED, { page: "p1" });
    expect(seen.has("a")).toBe(true);
    expect(seen.has("b")).toBe(false);
  });

  it("follows a click to the other tab", () => {
    const seen = visibleNodes(TABBED, {
      page: "p1", tabs: { sec: { name: "Two", against: null } },
    });
    expect(seen.has("b")).toBe(true);
    expect(seen.has("a")).toBe(false);
  });

  it("follows p.84's backing variable", () => {
    const backed = {
      ...(TABBED as Record<string, unknown>),
      sec: node("CanvasSection", ["a", "b"],
                { direction: "tabs", tabs: "One,Two", tabVariable: "v_tab" }),
    } as unknown;
    const seen = visibleNodes(backed, { page: "p1", values: { v_tab: "Two" } });
    expect(seen.has("b")).toBe(true);
    expect(seen.has("a")).toBe(false);
  });

  it("settles on the first tab while the backing variable is still unresolved", () => {
    // The one-round-trip case. The section is on the page, so `v_tab` is
    // referenced by a visible node and *is* computed — this is only what the
    // first frame looks like, and it must be the first tab rather than
    // nothing, or the widget on tab one waits for a value nobody asked for.
    const backed = {
      ...(TABBED as Record<string, unknown>),
      sec: node("CanvasSection", ["a", "b"],
                { direction: "tabs", tabs: "One,Two", tabVariable: "v_tab" }),
    } as unknown;
    const seen = visibleNodes(backed, { page: "p1", values: {} });
    expect(seen.has("sec")).toBe(true);
    expect(seen.has("a")).toBe(true);
  });

  it("includes every part of a section that is not tabbed", () => {
    // A plain rows/columns section shows all of its children at once, so
    // treating one as tabbed would hide a widget that is on screen — and the
    // variable behind it would never be computed.
    const plain = {
      ...(TABBED as Record<string, unknown>),
      sec: node("CanvasSection", ["a", "b"], { direction: "rows" }),
    } as unknown;
    const seen = visibleNodes(plain, { page: "p1" });
    expect(seen.has("a")).toBe(true);
    expect(seen.has("b")).toBe(true);
  });
});

describe("documents that arrived from anywhere", () => {
  it("answers nothing for a layout that is not a map", () => {
    expect(visibleNodes(null, { page: "p1" }).size).toBe(0);
    expect(visibleNodes("nope", { page: "p1" }).size).toBe(0);
  });

  it("does not hang on a cycle", () => {
    const looped = {
      ROOT: node("CanvasContainer", ["x"]),
      x: node("CanvasSection", ["y"]),
      y: node("CanvasSection", ["x"]),
    } as unknown;
    expect(visibleNodes(looped, { page: null }).has("y")).toBe(true);
  });

  it("ignores a page id the document does not have", () => {
    expect(visibleNodes(LAYOUT, { page: "p9" }).has("w1")).toBe(false);
  });
});
