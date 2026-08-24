import { describe, expect, it } from "vitest";

import {
  apply, DEFINITION_TYPES, definitionTypeOf, matches, partition, SETTINGS,
} from "./variable-finder";
import type { WorkshopVariable } from "../../lib/types";

/** p.72's search, filter and partitions (Foundry `workshop` p.72–73). */

const v = (id: string, extra: Partial<WorkshopVariable> = {}): WorkshopVariable =>
  ({ id, kind: "string", label: id, ...extra } as WorkshopVariable);

const derived = (id: string, transform: string, extra: Partial<WorkshopVariable> = {}) =>
  v(id, { derivation: { transform, inputs: [] }, ...extra } as Partial<WorkshopVariable>);

describe("definitionTypeOf (p.73)", () => {
  it("calls a variable with no derivation static", () => {
    expect(definitionTypeOf(v("a"))).toBe("static");
  });

  it("calls one carrying an object set an object set definition", () => {
    // p.73: "Specifically for object set variables defined by selected object
    // types, filters, and linked objects traversals".
    const set = v("a", { object_set: { object_type_id: "t", filters: [] } } as never);
    expect(definitionTypeOf(set)).toBe("object_set_definition");
  });

  it("gives object_property and object_set_aggregation their own types", () => {
    expect(definitionTypeOf(derived("a", "object_property"))).toBe("object_property");
    expect(definitionTypeOf(derived("b", "object_set_aggregation")))
      .toBe("object_set_aggregation");
  });

  it("calls every other derivation a variable transformation", () => {
    // p.73's own catch-all: "a series of common operations, possibly
    // referencing other variables". A transform added later lands here rather
    // than in a gap, which is the point of a default arm.
    expect(definitionTypeOf(derived("a", "concat"))).toBe("variable_transformation");
    expect(definitionTypeOf(derived("b", "if_else"))).toBe("variable_transformation");
    expect(definitionTypeOf(derived("c", "brand_new_thing")))
      .toBe("variable_transformation");
  });

  it("prefers the object set when a variable somehow has both", () => {
    // The server refuses this ("two answers to where the rows come from"), so
    // reaching it means a document from elsewhere - and reporting the set is
    // the reading that matches what the panel then offers to edit.
    const both = v("a", {
      object_set: { object_type_id: "t", filters: [] },
      derivation: { transform: "concat", inputs: [] },
    } as never);
    expect(definitionTypeOf(both)).toBe("object_set_definition");
  });

  it("lists every type the filter offers", () => {
    // **The catalogue checked against its subject.** A type `definitionTypeOf`
    // can return that the filter does not offer is a variable nothing can
    // filter to; the reverse is a filter option that always finds nothing.
    const reachable = new Set([
      definitionTypeOf(v("a")),
      definitionTypeOf(v("b", { object_set: { object_type_id: "t", filters: [] } } as never)),
      definitionTypeOf(derived("c", "object_property")),
      definitionTypeOf(derived("d", "object_set_aggregation")),
      definitionTypeOf(derived("e", "concat")),
    ]);
    for (const type of reachable) expect(DEFINITION_TYPES).toContain(type);
  });
});

describe("matches (p.72's search)", () => {
  const named = v("v_abc123", { label: "Region filter", external_id: "region" });

  it("finds a variable by its name", () => {
    expect(matches(named, "region")).toBe(true);
    expect(matches(named, "REGION")).toBe(true);
    expect(matches(named, "gion fil")).toBe(true);
  });

  it("finds one by its external ID and by its internal id", () => {
    // **p.72 says "unique ID" and this system has two things that could be
    // called one.** Picking either would be right half the time and silently
    // wrong the other half; an author pasting an id from a URL or an error
    // message expects to find it.
    expect(matches(named, "region")).toBe(true);
    expect(matches(named, "abc123")).toBe(true);
  });

  it("finds nothing for a string that is in none of the three", () => {
    expect(matches(named, "zzz")).toBe(false);
  });

  it("keeps everything for an empty or blank query", () => {
    // An empty search box is not a filter that matches nothing.
    expect(matches(named, "")).toBe(true);
    expect(matches(named, "   ")).toBe(true);
  });

  it("does not fall over on a variable missing the optional fields", () => {
    expect(matches(v("v_1"), "v_1")).toBe(true);
    expect(matches(v("v_1"), "nope")).toBe(false);
  });
});

describe("SETTINGS (p.73)", () => {
  it("reads each setting off the prop that turns it on", () => {
    expect(SETTINGS.interface(v("a", { interface: {} } as never))).toBe(true);
    expect(SETTINGS.interface(v("b"))).toBe(false);
    expect(SETTINGS.routing(v("c", { url_behavior: "always" } as never))).toBe(true);
    expect(SETTINGS.state_saving(v("d", { save_state: true } as never))).toBe(true);
  });

  it("treats an absent url_behavior as routing off", () => {
    // `never` is the stored default and absence has to mean the same, or every
    // variable in an older document would filter as routed.
    expect(SETTINGS.routing(v("a"))).toBe(false);
    expect(SETTINGS.routing(v("b", { url_behavior: "never" } as never))).toBe(false);
  });
});

describe("apply", () => {
  const all = [
    v("v_static", { label: "Typed in" }),
    derived("v_concat", "concat", { label: "Joined" }),
    v("v_set", {
      label: "The set", object_set: { object_type_id: "t", filters: [] },
    } as never),
    v("v_shared", { label: "Shared", interface: {}, save_state: true } as never),
  ];

  it("keeps everything when nothing is set", () => {
    // A panel whose filters nobody has touched shows the whole module.
    expect(apply(all, {})).toHaveLength(4);
    expect(apply(all, { query: "", types: [], settings: [] })).toHaveLength(4);
  });

  it("narrows by search", () => {
    expect(apply(all, { query: "joined" }).map((x) => x.id)).toEqual(["v_concat"]);
  });

  it("ors within the type filter", () => {
    // "an object set OR a function" is a question somebody asks; "an object set
    // AND a function" is a question with no answers.
    const ids = apply(all, { types: ["static", "object_set_definition"] }).map((x) => x.id);
    expect(ids).toEqual(["v_static", "v_set", "v_shared"]);
  });

  it("ors within the settings filter", () => {
    expect(apply(all, { settings: ["interface"] }).map((x) => x.id)).toEqual(["v_shared"]);
    expect(apply(all, { settings: ["routing"] })).toEqual([]);
    expect(apply(all, { settings: ["interface", "routing"] }).map((x) => x.id))
      .toEqual(["v_shared"]);
  });

  it("ands the three conditions together", () => {
    // The normal case is a search inside a filter, not one at a time.
    expect(apply(all, { query: "shared", types: ["static"] }).map((x) => x.id))
      .toEqual(["v_shared"]);
    expect(apply(all, { query: "shared", types: ["object_set_definition"] })).toEqual([]);
  });

  it("keeps the order it was given", () => {
    // The panel sorts its own list; a filter that reorders would move a
    // variable somebody is looking at.
    expect(apply(all, { types: ["static", "variable_transformation"] }).map((x) => x.id))
      .toEqual(["v_static", "v_concat", "v_shared"]);
  });
});

describe("partition (p.72)", () => {
  const all = [v("v_a"), v("v_b"), v("v_c")];
  // v_a is used by the selected widget; v_b elsewhere on the page; v_c nowhere.
  const usedBy = (id: string) =>
    ({ v_a: ["node_widget"], v_b: ["node_other"], v_c: [] } as Record<string, string[]>)[id] ?? [];

  it("puts the selected widget's variables first", () => {
    const out = partition(all, usedBy, { widget: "node_widget" });
    expect(out.by).toBe("widget");
    expect(out.relevant.map((x) => x.id)).toEqual(["v_a"]);
  });

  it("falls back to the active page when no widget is selected", () => {
    const out = partition(all, usedBy, {
      widget: null, pageNodes: ["node_widget", "node_other"],
    });
    expect(out.by).toBe("page");
    expect(out.relevant.map((x) => x.id)).toEqual(["v_a", "v_b"]);
  });

  it("prefers the widget when both are available", () => {
    // p.72's own precedence: the page partition is what shows "when no widget
    // is selected".
    const out = partition(all, usedBy, {
      widget: "node_widget", pageNodes: ["node_widget", "node_other"],
    });
    expect(out.by).toBe("widget");
    expect(out.relevant.map((x) => x.id)).toEqual(["v_a"]);
  });

  it("keeps everything else in the list", () => {
    // **A partition is an ordering, not a filter.** Hiding the rest would make
    // the panel lie about what the module contains.
    const out = partition(all, usedBy, { widget: "node_widget" });
    expect(out.rest.map((x) => x.id)).toEqual(["v_b", "v_c"]);
    expect(out.relevant.length + out.rest.length).toBe(all.length);
  });

  it("partitions by nothing when there is no widget and no page", () => {
    const out = partition(all, usedBy, {});
    expect(out.by).toBeNull();
    expect(out.relevant).toEqual([]);
    expect(out.rest).toHaveLength(3);
  });

  it("puts a variable used nowhere in the rest, under either scope", () => {
    expect(partition(all, usedBy, { widget: "node_widget" }).rest.map((x) => x.id))
      .toContain("v_c");
    expect(partition(all, usedBy, { pageNodes: ["node_widget"] }).rest.map((x) => x.id))
      .toContain("v_c");
  });

  it("distinguishes a page with no nodes from no page at all", () => {
    // **`null` is "the caller does not know"; `[]` is "the page is empty".**
    // They are different answers and the panel needs both: an empty page
    // genuinely partitions - the heading says nothing on this page uses a
    // variable, which is information - while an unknown page has no partition
    // to draw at all. Written as one test because the pair is the point;
    // either alone reads as an arbitrary choice.
    const emptyPage = partition(all, usedBy, { pageNodes: [] });
    expect(emptyPage.by).toBe("page");
    expect(emptyPage.relevant).toEqual([]);
    expect(emptyPage.rest).toHaveLength(3);

    const noPage = partition(all, usedBy, { pageNodes: null });
    expect(noPage.by).toBeNull();
    expect(noPage.rest).toHaveLength(3);
  });
});
