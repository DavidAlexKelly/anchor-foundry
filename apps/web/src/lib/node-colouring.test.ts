import { describe, expect, it } from "vitest";

import {
  COLOURINGS, DEFAULT_COLOURING, type ColourableNode, legendFor, swatchFor,
} from "./node-colouring";

function dataset(over: Partial<ColourableNode> = {}): ColourableNode {
  return { kind: "dataset", origin: "model_output", ...over };
}

describe("the options on offer", () => {
  it("defaults to what the graph coloured by before there was a choice", () => {
    // A picker whose default changed the page the moment it appeared would be
    // a new feature wearing a settings control.
    expect(DEFAULT_COLOURING).toBe("status");
    expect(COLOURINGS[0]!.id).toBe("status");
  });

  it("offers p.38's first option", () => {
    expect(COLOURINGS.map((c) => c.id)).toContain("none");
  });

  it("gives every option a distinct id and a hint", () => {
    const ids = COLOURINGS.map((c) => c.id);
    expect(ids).toEqual([...new Set(ids)]);
    for (const option of COLOURINGS) {
      expect(option.label.length, option.id).toBeGreaterThan(0);
      expect(option.hint.length, option.id).toBeGreaterThan(0);
    }
  });
});

describe("swatchFor: build status", () => {
  it("colours a model by whether its run worked", () => {
    expect(swatchFor({ kind: "model", last_run_status: "succeeded" }, "status")!.key)
      .toBe("ok");
    expect(swatchFor({ kind: "model", last_run_status: "failed" }, "status")!.key)
      .toBe("failed");
  });

  it("colours an object type by its sync, not by a dataset's health", () => {
    // §351: an object type's last run *is* its last sync, and the question a
    // red node answers is "did the thing that writes this work".
    expect(swatchFor({ kind: "object_type", last_run_status: "ok" }, "status")!.key)
      .toBe("ok");
    expect(swatchFor({ kind: "object_type", last_run_status: "error" }, "status")!.key)
      .toBe("failed");
  });

  it("puts a stale dataset above its passing checks", () => {
    // §352: passing expectations on data that is behind is exactly the
    // reassuring half of the answer.
    const stale = dataset({ out_of_date: true, health_status: "pass" });
    expect(swatchFor(stale, "status")!.key).toBe("stale");
  });

  it("says nothing rather than guessing when a run has not happened", () => {
    expect(swatchFor({ kind: "model", last_run_status: null }, "status")!.key)
      .toBe("unknown");
  });
});

describe("swatchFor: out-of-date", () => {
  it("tells p.39's two reasons apart", () => {
    // "Out-of-date with parent" and "out-of-date with ancestor" send a reader
    // to different places, which is why §352 stores two values and not a flag.
    expect(swatchFor(dataset({ out_of_date: true, out_of_date_reason: "input_is_newer" }),
      "out_of_date")!.key).toBe("parent");
    expect(swatchFor(dataset({ out_of_date: true, out_of_date_reason: "upstream_is_out_of_date" }),
      "out_of_date")!.key).toBe("ancestor");
  });

  it("colours the two reasons differently", () => {
    const parent = swatchFor(dataset({ out_of_date: true, out_of_date_reason: "input_is_newer" }), "out_of_date")!;
    const ancestor = swatchFor(dataset({ out_of_date: true, out_of_date_reason: "upstream_is_out_of_date" }), "out_of_date")!;
    expect(parent.token).not.toBe(ancestor.token);
  });

  it("calls an up-to-date dataset up to date", () => {
    expect(swatchFor(dataset({ out_of_date: false }), "out_of_date")!.key).toBe("current");
  });

  it("still says stale when the reason is missing", () => {
    // §210-adjacent: out of date for an unrecorded reason is still out of
    // date, and reporting it as current would be the one wrong answer.
    expect(swatchFor(dataset({ out_of_date: true, out_of_date_reason: null }),
      "out_of_date")!.key).toBe("stale");
  });
});

describe("swatchFor: data health", () => {
  it("separates a dataset with no checks from one that passed", () => {
    // The one wrong answer here: a dataset nobody wrote an expectation for
    // has not been checked, and colouring it like a pass reports confidence
    // nobody established.
    expect(swatchFor(dataset({ health_status: null }), "health")!.key).toBe("none");
    expect(swatchFor(dataset({ health_status: "pass" }), "health")!.key).toBe("pass");
    expect(swatchFor(dataset({ health_status: null }), "health")!.token)
      .not.toBe(swatchFor(dataset({ health_status: "pass" }), "health")!.token);
  });

  it("reads warn and fail as themselves", () => {
    expect(swatchFor(dataset({ health_status: "warn" }), "health")!.key).toBe("warn");
    expect(swatchFor(dataset({ health_status: "fail" }), "health")!.key).toBe("fail");
  });
});

describe("swatchFor: kind and origin", () => {
  it("gives each resource type its own colour", () => {
    const tokens = ["dataset", "model", "object_type"]
      .map((kind) => swatchFor({ kind }, "kind")!.token);
    expect(new Set(tokens).size).toBe(3);
  });

  it("colours by how a dataset was made", () => {
    expect(swatchFor(dataset({ origin: "upload" }), "origin")!.key).toBe("upload");
    expect(swatchFor(dataset({ origin: "model_output" }), "origin")!.key).toBe("model_output");
  });

  it("says a model is not a dataset rather than calling it unknown", () => {
    // p.38's "the way the resource was created" is a dataset's question; a
    // model is not created the way its output is, and `origin` is null on one.
    expect(swatchFor({ kind: "model" }, "origin")!.key).toBe("none");
  });

  it("shows an origin it has no name for rather than dropping it", () => {
    expect(swatchFor(dataset({ origin: "conjured" }), "origin")!.label).toBe("conjured");
  });
});

describe("swatchFor: no colour and unknown options", () => {
  it("removes colouring altogether", () => {
    expect(swatchFor(dataset(), "none")).toBeNull();
  });

  it("falls back to the default rather than to no colour", () => {
    // A saved view (§360) naming a colouring a later build dropped should open
    // looking like the graph, not like one somebody switched the colour off on.
    expect(swatchFor(dataset({ health_status: "pass" }), "a_colouring_from_the_future"))
      .toEqual(swatchFor(dataset({ health_status: "pass" }), "status"));
  });
});

describe("legendFor", () => {
  const NODES: ColourableNode[] = [
    dataset({ health_status: "pass" }),
    dataset({ health_status: "pass" }),
    dataset({ health_status: "fail" }),
    dataset({ health_status: null }),
  ];

  it("counts what is on the graph", () => {
    expect(legendFor(NODES, "health")).toEqual([
      { key: "fail", label: "Failing", token: "var(--danger)", count: 1 },
      { key: "pass", label: "Passing", token: "var(--accent)", count: 2 },
      { key: "none", label: "No checks", token: "var(--line-strong)", count: 1 },
    ]);
  });

  it("reads worst first, whatever order the graph holds its nodes in", () => {
    // A key sorted by what the graph contained first reshuffles the moment a
    // dataset is added, which makes it a moving target for a reader looking
    // between the key and the cards.
    const reversed = [...NODES].reverse();
    expect(legendFor(reversed, "health").map((e) => e.key))
      .toEqual(["fail", "pass", "none"]);
  });

  it("lists only what is there, not the whole vocabulary", () => {
    // A key showing six rows over a graph with two colours on it is a key
    // nobody reads.
    expect(legendFor([dataset({ health_status: "pass" })], "health").map((e) => e.key))
      .toEqual(["pass"]);
  });

  it("is empty when colouring is off", () => {
    expect(legendFor(NODES, "none")).toEqual([]);
  });

  it("is empty for an empty graph", () => {
    expect(legendFor([], "health")).toEqual([]);
  });

  it("puts an unnamed value last rather than dropping it", () => {
    const mixed = [dataset({ origin: "conjured" }), dataset({ origin: "upload" })];
    expect(legendFor(mixed, "origin").map((e) => e.key)).toEqual(["upload", "conjured"]);
  });
});
