import { describe, expect, it } from "vitest";

import {
  clip, paste, pasteTarget, referencedVariables, subtreeIds, withoutSubtree,
} from "./clipboard";
import type { Clipping } from "./clipboard";
import type { WorkshopEvent, WorkshopVariable } from "../../lib/types";

/** Cut, copy and paste (Foundry `workshop` p.55, p.68-69).
 *
 * p.55's two paste modes are the design question; the rest is a subtree walk
 * and a remap. What makes the remap worth testing this hard is that getting it
 * wrong is invisible: a paste that rewrote one reference too few produces a
 * copy that shares state with its original, and nothing says so until somebody
 * edits one and watches the other move.
 */

const variable = (id: string, extra: Partial<WorkshopVariable> = {}): WorkshopVariable =>
  ({ id, kind: "string", label: id, ...extra } as WorkshopVariable);

/** A page holding a section, the section holding a filter and a table. The
 * filter writes `v_region`; the table reads it. */
function fixture() {
  const layout = {
    ROOT: { type: { resolvedName: "CanvasContainer" }, isCanvas: true, nodes: ["page"] },
    page: {
      type: { resolvedName: "CanvasPage" }, isCanvas: true, parent: "ROOT",
      nodes: ["sec"], props: { title: "Overview" },
    },
    sec: {
      type: { resolvedName: "CanvasSection" }, isCanvas: true, parent: "page",
      nodes: ["filter", "table"], props: { direction: "columns" },
    },
    filter: {
      type: { resolvedName: "CanvasFilter" }, parent: "sec",
      props: { name: "v_region" },
    },
    table: {
      type: { resolvedName: "CanvasObjectTable" }, parent: "sec",
      props: { objectSetVariable: "v_set", visibleWhen: "v_region" },
    },
  };
  const variables = {
    v_region: variable("v_region", { label: "Region" }),
    v_set: variable("v_set", { kind: "object_set", label: "All sites" }),
    v_elsewhere: variable("v_elsewhere", { label: "Elsewhere" }),
  };
  const events: Record<string, WorkshopEvent> = {
    e_1: {
      id: "e_1",
      trigger: { node: "filter", on: "change" },
      effects: [{ type: "navigate", config: { page: "page" } }],
    },
    e_outside: {
      id: "e_outside",
      trigger: { node: "table", on: "row_click" },
      effects: [{ type: "navigate", config: { page: "elsewhere" } }],
    },
  };
  return { layout, variables, events };
}

/** Deterministic minting, so a test asserts on names rather than on a regex. */
function minters() {
  let n = 0; let v = 0; let e = 0;
  return {
    mintNode: () => `n${++n}`,
    mintVariable: () => `v_new${++v}`,
    mintEvent: () => `e_new${++e}`,
  };
}

describe("subtreeIds", () => {
  it("takes the node and everything under it", () => {
    const { layout } = fixture();
    expect(subtreeIds(layout, "sec").sort()).toEqual(["filter", "sec", "table"]);
  });

  it("follows linkedNodes as well as nodes", () => {
    // **A Page's children hang off `linkedNodes`.** A walk that missed them
    // would paste an empty page and lose its contents with nothing to see.
    const layout = {
      a: { isCanvas: true, linkedNodes: { slot: "b" } },
      b: { parent: "a", nodes: ["c"] },
      c: { parent: "b" },
    };
    expect(subtreeIds(layout, "a").sort()).toEqual(["a", "b", "c"]);
  });

  it("does not hang on a document that contains a cycle", () => {
    // Not reachable through the builder; reachable through the raw-JSON editor
    // and through any older writer, and the cost of the guard is a Set.
    const layout = { a: { nodes: ["b"] }, b: { nodes: ["a"] } };
    expect(subtreeIds(layout, "a").sort()).toEqual(["a", "b"]);
  });

  it("is empty for a node that is not there", () => {
    expect(subtreeIds(fixture().layout, "gone")).toEqual([]);
  });
});

describe("referencedVariables", () => {
  it("finds every reference prop, across every node", () => {
    const { layout } = fixture();
    const nodes = { filter: layout.filter, table: layout.table };
    expect(referencedVariables(nodes)).toEqual(["v_region", "v_set"]);
  });

  it("sees a section's collapse and tab bindings", () => {
    // The two §191 added. A clipping that missed them would paste a section
    // whose collapse followed a variable the duplicate no longer owns.
    const nodes = {
      sec: { props: { collapsedWhen: "v_shut", tabVariable: "v_tab" } },
    };
    expect(referencedVariables(nodes)).toEqual(["v_shut", "v_tab"]);
  });
});

describe("clip", () => {
  it("carries the subtree, its variables and its events", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    expect(Object.keys(clipping.nodes).sort()).toEqual(["filter", "sec", "table"]);
    expect(Object.keys(clipping.variables).sort()).toEqual(["v_region", "v_set"]);
    // `v_elsewhere` is declared and unreferenced, so it is not this section's.
    expect(clipping.variables.v_elsewhere).toBeUndefined();
  });

  it("carries the events triggered from inside, and only those", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "filter", "Filter") as Clipping;
    // p.55 does not mention events, and leaving them behind would have been
    // defensible - but a copied Button with no on-click silently does less
    // than the thing it copied.
    expect(Object.keys(clipping.events)).toEqual(["e_1"]);
  });

  it("refuses ROOT and anything absent", () => {
    const { layout, variables, events } = fixture();
    // Copying the whole document is a paste nobody can complete: the only
    // place it could go is inside itself.
    expect(clip(layout, variables, events, "ROOT", "x")).toBe(null);
    expect(clip(layout, variables, events, "gone", "x")).toBe(null);
  });
});

describe("withoutSubtree", () => {
  it("removes the subtree and closes the parent's list", () => {
    const { layout } = fixture();
    const next = withoutSubtree(layout, "sec");
    expect(Object.keys(next).sort()).toEqual(["ROOT", "page"]);
    expect((next.page as { nodes: string[] }).nodes).toEqual([]);
  });

  it("leaves a layout alone when asked for ROOT or a stranger", () => {
    const { layout } = fixture();
    expect(withoutSubtree(layout, "ROOT")).toBe(layout);
    expect(withoutSubtree(layout, "gone")).toBe(layout);
  });
});

describe("pasteTarget", () => {
  it("uses the selected node when it can hold children", () => {
    expect(pasteTarget(fixture().layout, "sec")).toBe("sec");
  });

  it("walks up from a widget to the nearest canvas", () => {
    // A widget cannot hold children, so pasting "into" one means beside it.
    // Walking up is what makes Paste work wherever the author is, rather than
    // being disabled most of the time with no explanation.
    expect(pasteTarget(fixture().layout, "table")).toBe("sec");
  });

  it("falls back to the document when nothing is selected", () => {
    expect(pasteTarget(fixture().layout, null)).toBe("ROOT");
    expect(pasteTarget(fixture().layout, "gone")).toBe("ROOT");
  });

  it("does not hang on a parent cycle", () => {
    const layout = { a: { parent: "b" }, b: { parent: "a" }, ROOT: { isCanvas: true } };
    expect(pasteTarget(layout, "a")).toBe("ROOT");
  });
});

describe("paste in `same` mode (p.55)", () => {
  it("reuses the copied widget's input variables", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "same", ...minters() });

    // p.55: "reuses the copied section's or widget's input variables".
    expect(Object.keys(out.variables).sort())
      .toEqual(["v_elsewhere", "v_region", "v_set"]);
    const pastedTable = Object.values(out.layout).find(
      (n) => (n as { type?: { resolvedName?: string } }).type?.resolvedName
        === "CanvasObjectTable"
        && (n as { parent?: string }).parent !== "sec",
    ) as { props: Record<string, unknown> };
    expect(pastedTable.props.objectSetVariable).toBe("v_set");
    expect(pastedTable.props.visibleWhen).toBe("v_region");
  });

  it("gives every pasted node a fresh id and rewires the subtree", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "same", ...minters() });

    expect(out.root).toBe("n1");
    // The original is untouched and the copy is a sibling of it.
    expect((out.layout.page as { nodes: string[] }).nodes).toEqual(["sec", "n1"]);
    const copied = out.layout.n1 as { parent: string; nodes: string[] };
    expect(copied.parent).toBe("page");
    // Its children are the *new* ids, not the ones they had. This is the
    // assertion that fails when a remap misses `nodes`, and the symptom in the
    // builder is a copy that shares its children with the original.
    expect(copied.nodes).toEqual(["n2", "n3"]);
    for (const child of copied.nodes) {
      expect((out.layout[child] as { parent: string }).parent).toBe("n1");
    }
  });

  it("does not disturb the document it was copied from", () => {
    const { layout, variables, events } = fixture();
    const before = JSON.stringify(layout);
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    paste(layout, variables, events, clipping, { into: "page", mode: "same", ...minters() });
    expect(JSON.stringify(layout)).toBe(before);
  });
});

describe("paste in `duplicate` mode (p.55)", () => {
  it("mints a new variable per input and points the copy at it", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "duplicate", ...minters() });

    // p.55: "newly created input variables that match the copied section's or
    // widget's input variables".
    expect(Object.keys(out.variables).sort())
      .toEqual(["v_elsewhere", "v_new1", "v_new2", "v_region", "v_set"]);
    const pastedTable = out.layout.n3 as { props: Record<string, unknown> };
    expect(pastedTable.props.objectSetVariable).toBe("v_new2");
    expect(pastedTable.props.visibleWhen).toBe("v_new1");
    // And the original still points at the originals.
    expect((out.layout.table as { props: Record<string, unknown> }).props.objectSetVariable)
      .toBe("v_set");
  });

  it("copies the definition, renames it, and keeps its kind", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "duplicate", ...minters() });

    // "match the copied … input variables" - same kind, or the copy would not
    // bind to the same widget.
    expect(out.variables.v_new2!.kind).toBe("object_set");
    // Two variables called "Region" is a Variables panel nobody can use, and
    // the panel is exactly where an author goes next to re-point the copy.
    expect(out.variables.v_new1!.label).toBe("Region copy");
  });

  it("drops the external ID rather than copying it", () => {
    // **The one that would make a paste unsaveable.** An external ID is what a
    // URL and an embedding module address, and the server refuses two
    // variables that share one - so a copy that kept it would be refused on
    // the next save, for a reason pointing at the wrong variable.
    const { layout, events } = fixture();
    const variables = {
      v_region: variable("v_region", { label: "Region", external_id: "region" }),
      v_set: variable("v_set", { kind: "object_set", label: "All" }),
    };
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "duplicate", ...minters() });
    expect(out.variables.v_new1!.external_id).toBeUndefined();
    expect(out.variables.v_region!.external_id).toBe("region");
  });

  it("leaves a derivation pointing at the originals", () => {
    // **The judgement call, asserted so it is a decision rather than a
    // side effect.** p.55's "input variables" are the widget's own, not the
    // whole graph behind them - and duplicating the graph would clone the
    // object set a filter narrows, which is the thing an author duplicating a
    // filter wants to keep shared.
    const { layout, events } = fixture();
    const variables = {
      v_region: variable("v_region", { label: "Region" }),
      v_set: variable("v_set", {
        kind: "object_set", label: "Narrowed",
        derivation: { transform: "narrow_set", inputs: ["v_region"] },
      } as Partial<WorkshopVariable>),
    };
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "duplicate", ...minters() });
    expect(out.variables.v_new2!.derivation?.inputs).toEqual(["v_region"]);
  });
});

describe("paste and events", () => {
  it("remaps a trigger to the node that now exists", () => {
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "same", ...minters() });

    expect(out.events.e_new1!.trigger.node).toBe("n2");
    // The originals are still there and still point at the originals.
    expect(out.events.e_1!.trigger.node).toBe("filter");
  });

  it("leaves an effect pointing outside the clipping alone", () => {
    // **The distinction that matters.** A `navigate` to a page that was not
    // copied still names a page that is there; rewriting it would break a
    // working link. One that *was* copied has a new id and must follow.
    const { layout, variables, events } = fixture();
    const clipping = clip(layout, variables, events, "page", "Page") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "ROOT", mode: "same", ...minters() });

    const copiedFilterEvent = Object.values(out.events).find(
      (e) => e.id.startsWith("e_new") && e.trigger.on === "change",
    ) as WorkshopEvent;
    // The page came with the clipping, so the navigate follows the copy.
    expect(copiedFilterEvent.effects[0]!.config?.page).toBe("n1");

    const copiedTableEvent = Object.values(out.events).find(
      (e) => e.id.startsWith("e_new") && e.trigger.on === "row_click",
    ) as WorkshopEvent;
    // "elsewhere" was never in the clipping, so it is left where it pointed.
    expect(copiedTableEvent.effects[0]!.config?.page).toBe("elsewhere");
  });

  it("remaps a set_variable effect in duplicate mode", () => {
    const { layout, variables } = fixture();
    const events: Record<string, WorkshopEvent> = {
      e_1: {
        id: "e_1",
        trigger: { node: "filter", on: "change" },
        effects: [{ type: "set_variable", config: { variable: "v_region", value: "x" } }],
      },
    };
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "duplicate", ...minters() });
    // The copy's event writes the copy's variable. Without this, two widgets
    // that look independent share one, which is the silent-sharing failure
    // duplicate mode exists to avoid.
    expect(out.events.e_new1!.effects[0]!.config?.variable).toBe("v_new1");
  });

  it("does not rewrite a config value that merely looks like a node id", () => {
    // `value` is a string somebody typed. Rewriting it because a node happens
    // to share the name would corrupt the copy with nothing to report.
    const { layout, variables } = fixture();
    const events: Record<string, WorkshopEvent> = {
      e_1: {
        id: "e_1",
        trigger: { node: "filter", on: "change" },
        effects: [{ type: "set_variable", config: { variable: "v_region", value: "sec" } }],
      },
    };
    const clipping = clip(layout, variables, events, "sec", "Section") as Clipping;
    const out = paste(layout, variables, events, clipping,
      { into: "page", mode: "same", ...minters() });
    expect(out.events.e_new1!.effects[0]!.config?.value).toBe("sec");
  });
});
