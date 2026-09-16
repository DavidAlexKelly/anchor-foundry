/** A lineage graph's view, in the address bar (§360; `data-lineage` p.12). */
import { describe, expect, it } from "vitest";
import { fromParams, toParams } from "./graph-link";

describe("a view as a link", () => {
  it("carries what was chosen", () => {
    expect(toParams({
      focus: "dataset:1", column: "id", query: "orders",
      kinds: ["model"], selected: ["dataset:1", "dataset:2"],
    })).toEqual({
      focus: "dataset:1", col: "id", q: "orders",
      kind: ["model"], sel: ["dataset:1", "dataset:2"],
    });
  });

  it("removes the parts nobody chose rather than leaving them blank", () => {
    // `undefined` is `useUrlState().set`'s "delete this key". A key whose
    // value is its default has no business in a shared link.
    expect(toParams({})).toEqual({
      focus: undefined, col: undefined, q: undefined,
      kind: undefined, sel: undefined,
    });
  });

  it("drops an empty list rather than sending an empty key", () => {
    // The boundary the line above does not cover: `[]` is not `undefined`, and
    // a build that passed it through would leave `?sel=` in every link.
    expect(toParams({ kinds: [], selected: [] })).toMatchObject({
      kind: undefined, sel: undefined,
    });
  });
});

describe("a view from a link", () => {
  const of = (qs: string) => fromParams(new URLSearchParams(qs));

  it("reads back what was written", () => {
    const view = {
      focus: "dataset:1", column: "id", query: "orders",
      kinds: ["model"], selected: ["dataset:1", "dataset:2"],
    };
    expect(of("focus=dataset:1&col=id&q=orders&kind=model&sel=dataset:1&sel=dataset:2"))
      .toEqual(view);
  });

  it("round-trips a view through a URL", () => {
    // **The property that matters.** The two halves are written apart and a
    // key renamed on one side alone would be a link that loses a parameter
    // quietly — which is the failure a share link cannot afford.
    const view = {
      focus: "model:abc", column: "val", query: "x",
      kinds: ["dataset", "object_type"], selected: ["dataset:9"],
    };
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(toParams(view))) {
      if (Array.isArray(value)) for (const v of value) params.append(key, v);
      else if (value !== undefined) params.set(key, value);
    }
    expect(fromParams(params)).toEqual(view);
  });

  it("is an empty view when the link says nothing", () => {
    expect(of("")).toEqual({});
    expect(of("tab=preview")).toEqual({});
  });

  it("ignores a key it does not recognise", () => {
    // A URL is typed by hand and pasted by people; the graph draws what it
    // understood rather than refusing to draw.
    expect(of("focus=dataset:1&nonsense=1")).toEqual({ focus: "dataset:1" });
  });

  it("does not read a blank value as a choice", () => {
    // `?col=` is what a careless build leaves behind, and reading it as a
    // highlighted column called "" would dim every node on the graph.
    //
    // `kind=` is here for the repeatable keys' own reason rather than for
    // completeness: a blank one survives into a *list*, so the filter is not
    // empty — it is a filter for a kind called "", which hides the whole graph
    // while the kind buttons show nothing chosen.
    expect(of("col=&q=&sel=&kind=")).toEqual({});
    expect(of("kind=&kind=dataset")).toEqual({ kinds: ["dataset"] });
  });
});
