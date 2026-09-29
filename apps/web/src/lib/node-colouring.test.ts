import { describe, expect, it } from "vitest";

import {
  COLOURINGS, DEFAULT_COLOURING, type ColourableNode, colouringIn, legendFor, swatchFor, RAMP, ageText, quantityOf, quarterLabel, quarterOf, scaleFor, CATEGORICAL,
} from "./node-colouring";

/** A node the graph could actually draw: every field the server sends, set.
 *  A helper that left some out would build nodes `services/pipeline.py` never
 *  produces, and a test over one of those proves nothing about the graph. */
function node(kind: string, over: Partial<ColourableNode> = {}): ColourableNode {
  return {
    kind, origin: null, repository_name: null, health_status: null, last_run_status: null,
    out_of_date: false, out_of_date_reason: null, row_count: null, built_at: null,
    build_started_at: null, build_finished_at: null, ...over,
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

  it("names a source that has not delivered, most urgent first (§583)", () => {
    const source = swatchFor(dataset({ out_of_date: true, out_of_date_reason: "source_is_behind" }),
      "out_of_date")!;
    expect(source.key).toBe("source");
    expect(source.label).toBe("Out of date with its source");
    const parent = swatchFor(dataset({ out_of_date: true, out_of_date_reason: "input_is_newer" }), "out_of_date")!;
    expect(source.token).toBe(parent.token);
    const legend = legendFor([
      dataset({ out_of_date: true, out_of_date_reason: "upstream_is_out_of_date" }),
      dataset({ out_of_date: true, out_of_date_reason: "source_is_behind" }),
    ], "out_of_date").map((entry) => entry.key);
    expect(legend).toEqual(["source", "ancestor"]);
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


describe("p.39's quantitative colourings (§622)", () => {
  const NOW = Date.parse("2026-09-28T12:00:00Z");
  const hoursAgo = (h: number) => new Date(NOW - h * 3_600_000).toISOString();
  const SIZES = [10, 20, 30, 40, 50, 60, 70, 80].map((n) => dataset({ row_count: n }));

  it("offers row count and time last built", () => {
    expect(COLOURINGS.map((c) => c.id)).toEqual(expect.arrayContaining(["rows", "built"]));
    expect(colouringIn({ colouring: "rows" })).toBe("rows");
  });

  it("measures rows on datasets only, and age on anything built", () => {
    expect(quantityOf(dataset({ row_count: 5 }), "rows", NOW)).toBe(5);
    expect(quantityOf(node("model", { row_count: 5 }), "rows", NOW)).toBeNull();
    expect(quantityOf(dataset(), "rows", NOW)).toBeNull();
    expect(quantityOf(node("model", { built_at: hoursAgo(2) }), "built", NOW)).toBe(7_200_000);
    expect(quantityOf(dataset({ built_at: "not a date" }), "built", NOW)).toBeNull();
    // A clock a little behind the server is not a negative age.
    expect(quantityOf(dataset({ built_at: hoursAgo(-1) }), "built", NOW)).toBe(0);
    expect(quantityOf(dataset({ row_count: 5 }), "health", NOW)).toBeNull();
  });

  it("splits the graph's own values into quarters", () => {
    expect(scaleFor(SIZES, "rows", NOW)).toEqual({ colouring: "rows", now: NOW, edges: [30, 50, 70] });
    expect(scaleFor([], "rows", NOW)!.edges).toEqual([]);
    expect(scaleFor(SIZES, "health", NOW)).toBeNull();
  });

  it("puts a value in the first quarter whose edge it does not reach", () => {
    expect([10, 30, 49, 50, 69, 70, 99].map((v) => quarterOf(v, [30, 50, 70])))
      .toEqual([0, 1, 1, 2, 2, 3, 3]);
  });

  it("colours more as the ramp goes, and says the bounds", () => {
    const scale = scaleFor(SIZES, "rows", NOW)!;
    expect(swatchFor(dataset({ row_count: 10 }), "rows", scale))
      .toEqual({ key: "q0", label: "Under 30 rows", token: RAMP[0] });
    expect(swatchFor(dataset({ row_count: 55 }), "rows", scale))
      .toEqual({ key: "q2", label: "50 rows to 70 rows", token: RAMP[2] });
    expect(swatchFor(dataset({ row_count: 5000 }), "rows", scale))
      .toEqual({ key: "q3", label: "70 rows or more", token: RAMP[3] });
    expect(swatchFor(node("model"), "rows", scale)).toEqual(
      { key: "none", label: "No rows counted", token: "var(--line)" });
    // Without a scale there is nothing to place a node against.
    expect(swatchFor(dataset({ row_count: 10 }), "rows")!.key).toBe("none");
    expect(swatchFor(dataset(), "built", scaleFor([], "built", NOW))!.label).toBe("Never built");
  });

  it("builds the ramp from one token, weakest first", () => {
    expect(RAMP).toHaveLength(4);
    expect(RAMP.every((t) => t.includes("var(--accent)") && t.includes("transparent"))).toBe(true);
    expect(RAMP.map((t) => Number(/(\d+)%/.exec(t)![1]))).toEqual([30, 55, 80, 100]);
  });

  it("words an age in the largest unit that fits", () => {
    expect(ageText(59 * 60_000)).toBe("59 min");
    expect(ageText(60 * 60_000)).toBe("1 h");
    expect(ageText(47 * 3_600_000)).toBe("47 h");
    expect(ageText(48 * 3_600_000)).toBe("2 days");
    expect(quarterLabel("built", 3, [3_600_000, 7_200_000, 86_400_000 * 3]))
      .toBe("3 days or more");
    expect(quarterLabel("rows", 0, [])).toBe("Any rows");
    expect(quarterLabel("built", 0, [])).toBe("Any time");
  });

  it("keys the legend most first, then what has nothing to measure", () => {
    const legend = legendFor([...SIZES, node("model")], "rows", NOW);
    expect(legend.map((e) => [e.key, e.count])).toEqual(
      [["q3", 2], ["q2", 2], ["q1", 2], ["q0", 2], ["none", 1]]);
    const ages = legendFor([node("model", { built_at: hoursAgo(1) }),
                            node("model", { built_at: hoursAgo(100) })], "built", NOW);
    expect(ages.map((e) => e.label)).toEqual(["4 days or more", "1 h to 4 days"]);
  });
});

describe("p.39's build duration (§623)", () => {
  const built = (ms: number) => dataset({
    build_started_at: "2026-09-28T10:00:00.000Z",
    build_finished_at: new Date(Date.parse("2026-09-28T10:00:00.000Z") + ms).toISOString(),
  });

  it("is the build timeline's own window, so card and bar agree", () => {
    expect(quantityOf(built(1500), "duration", 0)).toBe(1500);
    // A finish before its start is no build rather than a negative one.
    expect(quantityOf(built(-10), "duration", 0)).toBeNull();
    expect(quantityOf(dataset(), "duration", 0)).toBeNull();
  });

  it("is offered, scaled, worded as a duration and keyed most first", () => {
    expect(COLOURINGS.map((c) => c.id)).toContain("duration");
    const nodes = [built(500), built(1500), built(40_000), built(90_000), dataset()];
    const scale = scaleFor(nodes, "duration", 0)!;
    expect(scale.edges).toEqual([1500, 40_000, 90_000]);
    expect(swatchFor(built(500), "duration", scale)!.label).toBe("Under 1.5 s");
    expect(swatchFor(built(90_000), "duration", scale)!.label).toBe("1m 30s or more");
    expect(swatchFor(dataset(), "duration", scale)!.label).toBe("No build timed");
    expect(quarterLabel("duration", 0, [])).toBe("Any length");
    expect(legendFor(nodes, "duration", 0).map((e) => e.key)).toEqual(
      ["q3", "q2", "q1", "q0", "none"]);
  });
});

describe("p.38's Repository colouring (§677)", () => {
  const graph = [
    node("model", { repository_name: "pipelines" }),
    node("dataset", { repository_name: "pipelines" }),
    node("model", { repository_name: "Analytics" }),
    node("dataset", { origin: "upload" }),
    node("object_type"),
  ];

  it("is offered, after the resource overview", () => {
    const ids = COLOURINGS.map((c) => c.id);
    expect(ids.indexOf("repository")).toBe(ids.indexOf("origin") + 1);
  });

  it("colours each repository by its place among the graph's, by name", () => {
    const scale = scaleFor(graph, "repository");
    expect(scale?.repositories).toEqual(["Analytics", "pipelines"]);
    expect(swatchFor(graph[0]!, "repository", scale)).toEqual(
      { key: "repo:pipelines", label: "pipelines", token: CATEGORICAL[1] });
    expect(swatchFor(graph[2]!, "repository", scale)?.token).toBe(CATEGORICAL[0]);
    expect(swatchFor(graph[3]!, "repository", scale)).toEqual(
      { key: "none", label: "Not from a repository", token: "var(--line)" });
  });

  it("reuses the colours past the palette, and names each in the legend", () => {
    const many = Array.from({ length: CATEGORICAL.length + 1 }, (_, n) =>
      node("model", { repository_name: `r${String(n).padStart(2, "0")}` }));
    const scale = scaleFor(many, "repository");
    expect(swatchFor(many[CATEGORICAL.length]!, "repository", scale)?.token).toBe(CATEGORICAL[0]);
    expect(legendFor(many, "repository")).toHaveLength(CATEGORICAL.length + 1);
  });

  it("lists the repositories by name, then what no repository wrote", () => {
    expect(legendFor(graph, "repository").map((e) => [e.label, e.count])).toEqual([
      ["Analytics", 1], ["pipelines", 2], ["Not from a repository", 2]]);
  });
});
