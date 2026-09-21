import { describe, expect, it } from "vitest";

import {
  COLOURINGS, DEFAULT_COLOURING, type ColourableNode, colouringIn, legendFor,
  swatchFor,
} from "./node-colouring";

/** A node the graph could actually draw: every field the server sends, set.
 *  A helper that left some out would build nodes `services/pipeline.py` never
 *  produces, and a test over one of those proves nothing about the graph. */
function node(kind: string, over: Partial<ColourableNode> = {}): ColourableNode {
  return {
    kind, origin: null, health_status: null, last_run_status: null,
    out_of_date: false, out_of_date_reason: null, ...over,
  };
}

function dataset(over: Partial<ColourableNode> = {}): ColourableNode {
  return node("dataset", { origin: "model_output", ...over });
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
    expect(swatchFor(node("model", { last_run_status: "succeeded" }), "status")!.key)
      .toBe("ok");
    expect(swatchFor(node("model", { last_run_status: "failed" }), "status")!.key)
      .toBe("failed");
  });

  it("colours an object type by its sync, not by a dataset's health", () => {
    // §351: an object type's last run *is* its last sync, and the question a
    // red node answers is "did the thing that writes this work".
    expect(swatchFor(node("object_type", { last_run_status: "ok" }), "status")!.key)
      .toBe("ok");
    expect(swatchFor(node("object_type", { last_run_status: "error" }), "status")!.key)
      .toBe("failed");
  });

  it("puts a stale dataset above its passing checks", () => {
    // §352: passing expectations on data that is behind is exactly the
    // reassuring half of the answer.
    const stale = dataset({ out_of_date: true, health_status: "pass" });
    expect(swatchFor(stale, "status")!.key).toBe("stale");
  });

  it("says nothing rather than guessing when a run has not happened", () => {
    expect(swatchFor(node("model", { last_run_status: null }), "status")!.key)
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
      .map((kind) => swatchFor(node(kind), "kind")!.token);
    expect(new Set(tokens).size).toBe(3);
  });

  it("colours by how a dataset was made", () => {
    expect(swatchFor(dataset({ origin: "upload" }), "origin")!.key).toBe("upload");
    expect(swatchFor(dataset({ origin: "model_output" }), "origin")!.key).toBe("model_output");
  });

  it("says a model is not a dataset rather than calling it unknown", () => {
    // p.38's "the way the resource was created" is a dataset's question; a
    // model is not created the way its output is, and `origin` is null on one.
    expect(swatchFor(node("model"), "origin")!.key).toBe("none");
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

describe("swatchFor: p.42's data source (§420)", () => {
  it("colours a source by its last sync, not by a connection test", () => {
    // §351's rule read from the other end: the question a red node answers is
    // "did the thing that writes this work", and for a data source that thing
    // is the sync.
    expect(swatchFor(node("connection", { last_run_status: "succeeded" }), "status")!.key)
      .toBe("ok");
    expect(swatchFor(node("connection", { last_run_status: "failed" }), "status")!.key)
      .toBe("failed");
  });

  it("reads `sync_runs` vocabulary rather than an object type's", () => {
    // The reason it is its own branch: db 0011's statuses are
    // running/succeeded/failed and db 0003's are ok/error/syncing, and a
    // source scored against the wrong list reads as never having run.
    expect(swatchFor(node("connection", { last_run_status: "running" }), "status")!.key)
      .toBe("warn");
    expect(swatchFor(node("connection", { last_run_status: "ok" }), "status")!.key)
      .toBe("unknown");
  });

  it("is its own resource type rather than an unknown one", () => {
    expect(swatchFor(node("connection"), "kind")!.key).toBe("connection");
  });

  it("has no origin of its own, the way a model has none", () => {
    // p.38's "the way the resource was created" is a dataset's question.
    expect(swatchFor(node("connection"), "origin")!.key).toBe("none");
  });

  it("sorts after the three kinds it feeds", () => {
    const mixed = [node("connection"), node("model"), node("dataset")];
    expect(legendFor(mixed, "kind").map((e) => e.key))
      .toEqual(["dataset", "model", "connection"]);
  });
});

describe("p.80-84's Permissions (§422)", () => {
  const seen = (access: ColourableNode["access"]) =>
    swatchFor({ ...dataset(), access }, "permissions")!;

  it("says nobody has been chosen rather than nobody can see it", () => {
    // §210, and the state this colouring opens in: a graph drawn before
    // anybody is named would otherwise report a permissions problem nobody
    // has.
    expect(seen(undefined).key).toBe("unasked");
    expect(seen(null).key).toBe("unasked");
  });

  it("tells no access from a role", () => {
    expect(seen({ role: null, via: "project" }).key).toBe("none");
    expect(seen({ role: "viewer", via: "project" }).key).toBe("viewer");
    expect(seen({ role: "owner", via: "project" }).key).toBe("owner");
  });

  it("names the door as well as the verdict", () => {
    // p.84: "Roles do not correspond to data lineage the same way that data
    // access does." A refusal without the scope is useless to somebody
    // debugging *why* — and two nodes can hold the same role from two doors.
    expect(seen({ role: null, via: "workspace" }).label).toBe("No access (workspace)");
    expect(seen({ role: "viewer", via: "project" }).label).toBe("Viewer (project)");
  });

  it("colours a role this build does not name rather than dropping it", () => {
    // `effective_project_role` could grow a level; an unnamed one is still
    // access, and colouring it as a refusal would be the worse of two guesses.
    const swatch = seen({ role: "steward", via: "project" });
    expect(swatch.key).toBe("steward");
    expect(swatch.label).toBe("steward (project)");
  });

  it("reads worst first and puts 'nobody chosen' last", () => {
    const mixed = [
      { ...dataset(), access: { role: "owner", via: "project" } },
      { ...dataset(), access: { role: null, via: "workspace" } },
      { ...dataset(), access: { role: "viewer", via: "project" } },
    ];
    expect(legendFor(mixed, "permissions").map((e) => e.key))
      .toEqual(["none", "viewer", "owner"]);
  });

  it("is an option the picker offers", () => {
    expect(COLOURINGS.map((o) => o.id)).toContain("permissions");
  });
});

describe("the colouring a stored view names (§360)", () => {
  it("keeps one this build offers", () => {
    expect(colouringIn({ colouring: "health" })).toBe("health");
  });

  it("keeps 'none', which is an option and not an absence", () => {
    // The value most likely to be swallowed by a falsy check on the way
    // through: p.38's first option is a choice somebody made.
    expect(colouringIn({ colouring: "none" })).toBe("none");
  });

  it("falls back for a view that names nothing", () => {
    expect(colouringIn({})).toBe(DEFAULT_COLOURING);
    expect(colouringIn(undefined)).toBe(DEFAULT_COLOURING);
  });

  it("falls back for a colouring this build dropped", () => {
    // A view saved by a later build. `swatchFor` would draw the default
    // anyway; narrowing here is what stops the picker from showing an
    // unrelated option beside cards drawn by a different rule (§214).
    expect(colouringIn({ colouring: "spark_usage" })).toBe(DEFAULT_COLOURING);
  });

  it("narrows to something the picker can actually show", () => {
    // The point of the fallback, said as the property rather than as one id:
    // whatever comes back is an option the `<select>` has.
    for (const named of ["health", "spark_usage", "", "none"]) {
      expect(COLOURINGS.map((o) => o.id)).toContain(colouringIn({ colouring: named }));
    }
  });
});
