import { describe, expect, it } from "vitest";

import {
  NESTED_REFERENCE_PROPS, REFERENCE_PROPS,
  referencesOf, remapReferences, usagesOf,
} from "./workshop-module";

/** The reference walk every browser-side scan shares.
 *
 * Four callers read this - `usagesOf` here, the lineage graph, a clipping's
 * referenced variables and a page's bindings - and before §219 each had its
 * own copy of the loop. Four copies is four chances for a binding to count as
 * a usage in one place and be invisible in another, which is the drift the
 * whole §191 guard family exists to refuse.
 */

describe("referencesOf", () => {
  it("finds a top-level binding", () => {
    expect(referencesOf({ objectSetVariable: "v_a" }))
      .toEqual([{ prop: "objectSetVariable", ref: "v_a" }]);
  });

  it("finds one named inside a list prop, with its index", () => {
    // §219's Stepper: the index is what makes the answer usable, because
    // "used by the Stepper" is not enough to find which step to unbind.
    expect(referencesOf({ steps: [{ label: "One" }, { label: "Two", completedVariable: "v_b" }] }))
      .toEqual([{ prop: "steps[1].completedVariable", ref: "v_b" }]);
  });

  it("finds both at once", () => {
    const found = referencesOf({
      visibleWhen: "v_show",
      steps: [{ label: "One", completedVariable: "v_b" }],
    });
    expect(found).toEqual([
      { prop: "visibleWhen", ref: "v_show" },
      { prop: "steps[0].completedVariable", ref: "v_b" },
    ]);
  });

  it("ignores an empty string", () => {
    // The settings panel's "Never completed" option writes `""`, and counting
    // that as a reference would make an unbound step a usage of nothing.
    expect(referencesOf({ variable: "", steps: [{ label: "One", completedVariable: "" }] }))
      .toEqual([]);
  });

  it("ignores a nested key nothing catalogues", () => {
    // A step's label holding the text `v_done` is a label. Counting it would
    // be the mirror of the bug this walk exists to fix.
    expect(referencesOf({ steps: [{ label: "v_done", icon: "v_done" }] })).toEqual([]);
  });

  it("survives whatever a saved document holds", () => {
    expect(referencesOf(undefined)).toEqual([]);
    expect(referencesOf("nonsense")).toEqual([]);
    expect(referencesOf({ steps: "not a list" })).toEqual([]);
    expect(referencesOf({ steps: [null, 7, {}, { completedVariable: 3 }] })).toEqual([]);
  });
});

describe("remapReferences", () => {
  const swap = new Map([["v_old", "v_new"]]);

  it("rewrites a top-level binding", () => {
    expect(remapReferences({ objectSetVariable: "v_old" }, swap))
      .toEqual({ objectSetVariable: "v_new" });
  });

  it("rewrites one inside a list prop", () => {
    // A paste into another module mints new ids; a nested binding left
    // pointing at the old one is a dangling reference the moment it is saved.
    expect(remapReferences({ steps: [{ label: "One", completedVariable: "v_old" }] }, swap))
      .toEqual({ steps: [{ label: "One", completedVariable: "v_new" }] });
  });

  it("leaves a binding with no replacement alone", () => {
    // A paste in `same` mode keeps the ids it has, and rewriting an unmapped
    // one to `undefined` would unbind every widget it copied.
    expect(remapReferences({ steps: [{ completedVariable: "v_kept" }], variable: "v_kept" }, swap))
      .toEqual({ steps: [{ completedVariable: "v_kept" }], variable: "v_kept" });
  });

  it("does not mutate what it was given", () => {
    // Craft's node props are shared with the editor's state; rewriting in
    // place would change the document being copied *from*.
    const props = { steps: [{ label: "One", completedVariable: "v_old" }] };
    remapReferences(props, swap);
    expect(props.steps[0]?.completedVariable).toBe("v_old");
  });

  it("keeps the other keys of a step", () => {
    expect(remapReferences({ steps: [{ label: "One", icon: "check", completedVariable: "v_old" }] }, swap))
      .toEqual({ steps: [{ label: "One", icon: "check", completedVariable: "v_new" }] });
  });
});

describe("usagesOf", () => {
  const definition = (layout: Record<string, unknown>) =>
    ({ format: 2, layout, variables: {}, events: {} });

  it("counts a step's completion variable", () => {
    // The half that bites quietly: a usage nothing counts is a variable the
    // panel offers to delete, after which every step reads as never completed.
    expect(usagesOf(definition({ w1: { props: { steps: [{ completedVariable: "v_d" }] } } }), "v_d"))
      .toEqual([{ node: "w1", prop: "steps[0].completedVariable" }]);
  });

  it("counts a top-level binding", () => {
    expect(usagesOf(definition({ w1: { props: { visibleWhen: "v_d" } } }), "v_d"))
      .toEqual([{ node: "w1", prop: "visibleWhen" }]);
  });

  it("finds nothing for a variable nothing binds", () => {
    expect(usagesOf(definition({ w1: { props: { steps: [{ completedVariable: "v_x" }] } } }), "v_d"))
      .toEqual([]);
  });
});

describe("the two catalogues", () => {
  it("do not overlap", () => {
    // A prop in both would be walked twice and reported as two usages of one
    // binding, so the panel would say "used by 2 widgets" about one widget.
    const nested = Object.keys(NESTED_REFERENCE_PROPS);
    expect(nested.filter((p) => (REFERENCE_PROPS as readonly string[]).includes(p))).toEqual([]);
  });

  it("names the Stepper's steps", () => {
    // Pinned by hand: a catalogue that quietly became empty would make every
    // completeness check above it pass over nothing.
    expect(NESTED_REFERENCE_PROPS.steps).toEqual(["completedVariable"]);
  });
});
