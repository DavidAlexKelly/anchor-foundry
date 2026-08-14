/** Workshop routing, the outbound half (p.195–199).
 *
 * These are rules about *which* values belong in a link, which is arithmetic
 * over a document — the sort of thing `pure.ts`'s docstring says a browser is
 * a wasteful and imprecise way to ask. Whether the address bar actually
 * changes when a filter moves is `e2e/test_routing.py`.
 */
import { describe, expect, it } from "vitest";

import {
  PAGE_PARAM, ROUTABLE_KINDS, defaultPageNode, pageIdOf, pageNodeFor, routingParams,
  variablesOnPage,
} from "./routing";

/** An interface variable configured to appear in the URL. */
function routed(id: string, extra: Record<string, unknown> = {}) {
  return {
    id, kind: "string", external_id: id.replace(/^v_/, ""),
    interface: true, url_behavior: "always", ...extra,
  };
}

const layout = {
  ROOT: { type: { resolvedName: "CanvasContainer" }, nodes: ["p1", "p2"] },
  p1: {
    type: { resolvedName: "CanvasPage" },
    props: { title: "One", pageId: "overview" },
    nodes: ["tbl"],
  },
  tbl: {
    type: { resolvedName: "CanvasObjectTable" },
    props: { objectSetVariable: "v_set", searchParameter: "v_region" },
  },
  p2: {
    type: { resolvedName: "CanvasPage" },
    props: { title: "Two" },
    nodes: ["cht"],
  },
  cht: {
    type: { resolvedName: "CanvasChart" },
    props: { objectSetVariable: "v_set", filterParameter: "v_status" },
  },
};

describe("variablesOnPage", () => {
  it("finds what the widgets on that page are bound to, at any depth", () => {
    expect(variablesOnPage(layout, "p1")).toEqual(new Set(["v_set", "v_region"]));
  });

  it("does not find what another page is bound to", () => {
    // The whole meaning of "used in a widget or layout that appears in the
    // current view" (p.198). A filter on page two is not on screen, and a URL
    // carrying its value would share a view the recipient does not get.
    expect(variablesOnPage(layout, "p1").has("v_status")).toBe(false);
    expect(variablesOnPage(layout, "p2")).toEqual(new Set(["v_set", "v_status"]));
  });

  it("finds nothing for a page that is not there", () => {
    expect(variablesOnPage(layout, "nope")).toEqual(new Set());
    expect(variablesOnPage(layout, null)).toEqual(new Set());
  });

  it("survives a layout that points at itself", () => {
    // The document arrives from anywhere. A hang in the viewer is a worse
    // answer than a partial one.
    const looped = {
      a: { type: { resolvedName: "CanvasPage" }, props: { variable: "v_x" }, nodes: ["b"] },
      b: { type: { resolvedName: "CanvasContainer" }, nodes: ["a"] },
    };
    expect(variablesOnPage(looped, "a")).toEqual(new Set(["v_x"]));
  });
});

describe("routingParams", () => {
  const base = {
    enabled: true,
    variables: { v_region: routed("v_region") },
    values: { v_region: "north" },
  };

  it("writes a chosen value under its external ID", () => {
    expect(routingParams(base)).toEqual({ region: "north" });
  });

  it("writes nothing at all when routing is off", () => {
    // p.195 puts the whole feature behind one toggle. A module whose author
    // has not enabled routing must not put anything in the address bar,
    // whatever its variables say.
    expect(routingParams({ ...base, enabled: false })).toEqual({});
  });

  it("leaves out a value that is still the default", () => {
    // p.198, both behaviours. Otherwise a module with twenty routed variables
    // would fill the address bar before anybody touched anything.
    const variables = { v_region: routed("v_region", { default: "north" }) };
    expect(routingParams({ ...base, variables })).toEqual({});
    expect(routingParams({ ...base, variables, values: { v_region: "south" } }))
      .toEqual({ region: "south" });
  });

  it("treats cleared, unset and never-set as the same nothing", () => {
    for (const value of [undefined, null, ""]) {
      expect(routingParams({ ...base, values: { v_region: value } })).toEqual({});
    }
  });

  it("only writes a when_visible variable when it is on the page", () => {
    const variables = { v_region: routed("v_region", { url_behavior: "when_visible" }) };
    expect(routingParams({ ...base, variables })).toEqual({});
    expect(routingParams({ ...base, variables, visible: new Set(["v_region"]) }))
      .toEqual({ region: "north" });
  });

  it("writes an always variable whether or not it is on the page", () => {
    // The difference between the two behaviours, asserted rather than assumed:
    // a mutation making them the same has to fail somewhere.
    expect(routingParams({ ...base, visible: new Set() })).toEqual({ region: "north" });
  });

  it("never writes a variable that is not routed", () => {
    for (const url_behavior of ["never", undefined, "sometimes"]) {
      const variables = { v_region: routed("v_region", { url_behavior }) };
      expect(routingParams({ ...base, variables })).toEqual({});
    }
  });

  it("never writes a variable that is not on the module interface", () => {
    // The server refuses this at save; applied again here because a document
    // can arrive from anywhere and a viewer is the wrong person to find out
    // that one did. A written value with no reader is a link that restores
    // everything except the thing it was shared for.
    for (const extra of [{ interface: undefined }, { external_id: null }]) {
      const variables = { v_region: routed("v_region", extra) };
      expect(routingParams({ ...base, variables })).toEqual({});
    }
  });

  it("never writes a kind the URL cannot be read back into", () => {
    // p.199. The list is `seedFromQuery`'s vocabulary: a kind is routable
    // exactly when the other end can parse it.
    for (const kind of ["object_set", "single_object", "time_series_set", "array"]) {
      expect(ROUTABLE_KINDS).not.toContain(kind);
      const variables = { v_region: routed("v_region", { kind }) };
      expect(routingParams({ ...base, variables })).toEqual({});
    }
    for (const kind of ROUTABLE_KINDS) {
      const variables = { v_region: routed("v_region", { kind }) };
      expect(routingParams({ ...base, variables })).toEqual({ region: "north" });
    }
  });

  it("writes the current page's ID, and nothing when it has none", () => {
    expect(routingParams({ ...base, pageId: "overview" })[PAGE_PARAM]).toBe("overview");
    expect(routingParams({ ...base, pageId: null })).not.toHaveProperty(PAGE_PARAM);
    expect(routingParams({ ...base, pageId: undefined })).not.toHaveProperty(PAGE_PARAM);
  });
});

describe("pageIdOf, defaultPageNode and pageNodeFor", () => {
  it("reads the ID an author gave a page, not the node id", () => {
    // A Craft.js node id is generated and changes when a page is recreated, so
    // a link built from one would expire for a reason nobody could see.
    expect(pageIdOf(layout, "p1")).toBe("overview");
    expect(pageIdOf(layout, "p1")).not.toBe("p1");
  });

  it("says a page nobody named has no ID to share", () => {
    expect(pageIdOf(layout, "p2")).toBe(null);
    expect(pageIdOf(layout, "gone")).toBe(null);
  });

  it("finds the page a link names", () => {
    expect(pageNodeFor(layout, "overview")).toBe("p1");
  });

  it("falls back to the default page rather than erroring", () => {
    // p.197 gives all three the same answer: no page ID, an unassigned one,
    // and one whose page has since been deleted. A link that outlived its page
    // should open the module.
    expect(pageNodeFor(layout, null)).toBe(null);
    expect(pageNodeFor(layout, "deleted-page")).toBe(null);
  });

  it("will not mistake a widget for a page", () => {
    // Every node has props; only a `CanvasPage` is a page. Without the type
    // check a widget someone gave a `pageId` prop would answer a link.
    const odd = {
      w: { type: { resolvedName: "CanvasChart" }, props: { pageId: "overview" } },
    };
    expect(pageNodeFor(odd, "overview")).toBe(null);
  });

  it("opens on the first page under ROOT, which is the one that renders", () => {
    // `CanvasPage` shows the first page before anybody navigates. Two answers
    // to "which is the default" would put a page ID in the address bar for a
    // page the reader is not looking at.
    expect(defaultPageNode(layout)).toBe("p1");
  });

  it("skips a non-page sitting above the first page", () => {
    const withHeader = {
      ROOT: { type: { resolvedName: "CanvasContainer" }, nodes: ["hdr", "p1"] },
      hdr: { type: { resolvedName: "CanvasHeader" } },
      p1: { type: { resolvedName: "CanvasPage" }, props: { pageId: "a" } },
    };
    expect(defaultPageNode(withHeader)).toBe("p1");
    expect(defaultPageNode({ ROOT: { nodes: [] } })).toBe(null);
  });
});
