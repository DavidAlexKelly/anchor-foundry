/** Building from the lineage graph (§386; `data-lineage` p.9). */
import { describe, expect, it } from "vitest";
import type { PipelineNode } from "./types";
import { between, buildPlan, buildSummary, cascadeCount } from "./graph-builds";

const node = (
  id: string,
  kind: PipelineNode["kind"],
  layer: number,
  over: Partial<PipelineNode> = {},
): PipelineNode => ({
  id,
  kind,
  resource_id: `${id}-res`,
  name: id,
  layer,
  position: 0,
  in_cycle: false,
  is_focus: false,
  slug: null,
  origin: null,
  row_count: null,
  current_version: null,
  health_status: null,
  language: null,
  trigger_mode: null,
  last_run_status: null,
  last_run_at: null,
  updated_at: null,
  built_at: null,
  ...over,
} as PipelineNode);

const edge = (from: string, to: string) => ({ from, to });

/*  raw ──▶ clean(model) ──▶ mid ──▶ roll(model) ──▶ out
    raw is an upload: nothing builds it.                        */
const NODES = [
  node("raw", "dataset", 0),
  node("clean", "model", 1),
  node("mid", "dataset", 2),
  node("roll", "model", 3, { trigger_mode: "upstream" }),
  node("out", "dataset", 4),
];
const EDGES = [
  edge("raw", "clean"), edge("clean", "mid"),
  edge("mid", "roll"), edge("roll", "out"),
];

describe("what lies between the selected", () => {
  it("takes the whole path from one end to the other", () => {
    expect(between(EDGES, ["raw", "out"]).sort())
      .toEqual(["clean", "mid", "out", "raw", "roll"]);
  });

  it("keeps the ends themselves", () => {
    // They are the ends; a "between" that dropped them would build the middle
    // of a pipeline and neither side of it.
    //
    // **This holds because `relatives` returns its seeds**, not because
    // `between` says so separately. The first draft said so separately, and a
    // sweep could not make that clause fail — it is deleted, and this test now
    // pins the property where it actually comes from.
    const found = between(EDGES, ["clean", "roll"]);
    expect(found).toContain("clean");
    expect(found).toContain("roll");
  });

  it("does not reach past the far end", () => {
    // The negative control: `out` is downstream of `roll`, so a walk that
    // only went downstream would collect it. It is not *between*.
    expect(between(EDGES, ["raw", "roll"])).not.toContain("out");
  });

  it("is the selection itself when there is no pair to be between", () => {
    expect(between(EDGES, ["mid"])).toEqual(["mid"]);
    expect(between(EDGES, [])).toEqual([]);
  });
});

describe("what pressing Build would run", () => {
  it("runs the model that writes a selected dataset, not the dataset", () => {
    // p.9 says datasets and a build runs a transform; they meet one hop up.
    expect(buildPlan(NODES, EDGES, ["mid"]).models.map((m) => m.name)).toEqual(["clean"]);
  });

  it("runs a selected model as itself", () => {
    expect(buildPlan(NODES, EDGES, ["roll"]).models.map((m) => m.name)).toEqual(["roll"]);
  });

  it("does not reach past the model that writes it", () => {
    // The negative control for the one-hop rule: `clean` is two hops up from
    // `out`, and building it would build a different dataset.
    expect(buildPlan(NODES, EDGES, ["out"]).models.map((m) => m.name)).toEqual(["roll"]);
  });

  it("orders by layer, so upstream builds first", () => {
    expect(buildPlan(NODES, EDGES, ["out", "mid"]).models.map((m) => m.name))
      .toEqual(["clean", "roll"]);
  });

  it("counts a model once however many of its outputs are selected", () => {
    expect(buildPlan(NODES, EDGES, ["mid", "clean"]).models).toHaveLength(1);
  });

  it("names an uploaded dataset as unbuildable rather than dropping it", () => {
    // §214: a control reporting "building 2" while running 1 is worse than
    // one that says which.
    const plan = buildPlan(NODES, EDGES, ["raw", "mid"]);
    expect(plan.models.map((m) => m.name)).toEqual(["clean"]);
    expect(plan.unbuildable).toEqual(["raw"]);
  });

  it("carries the model's own id, not the graph node's", () => {
    // What `POST /models/{id}/run` takes is the resource, and a node id is
    // "model:<uuid>" — a plan that handed the node id straight to the call
    // would 404 on every build.
    expect(buildPlan(NODES, EDGES, ["roll"]).models[0]!.id).toBe("roll-res");
  });
});

describe("what the control says", () => {
  it("counts transforms, not selected cards", () => {
    expect(buildSummary(buildPlan(NODES, EDGES, ["mid", "out"])))
      .toBe("build 2 transforms");
  });

  it("says what will not be built as well as what will", () => {
    expect(buildSummary(buildPlan(NODES, EDGES, ["raw", "mid"])))
      .toBe("build 1 transform; 1 selected dataset is uploaded, not built (raw)");
  });

  it("tells an empty selection from one nothing builds", () => {
    // Two different answers, because they need different next steps: one is
    // "choose something", the other is "this is not a thing that builds".
    expect(buildSummary(buildPlan(NODES, EDGES, []))).toContain("select a dataset");
    expect(buildSummary(buildPlan(NODES, EDGES, ["raw"])))
      .toBe("nothing here is built by a transform");
  });
});

describe("what the build will set off on its own", () => {
  it("counts upstream-triggered models downstream of the plan", () => {
    // §383: building `clean` gives `mid` a version, and `roll` reacts to it
    // on the worker's next pass — more builds than the strategy named.
    const plan = buildPlan(NODES, EDGES, ["mid"]);
    expect(cascadeCount(NODES, EDGES, plan)).toBe(1);
  });

  it("does not count a model the plan already runs", () => {
    // Otherwise selecting the whole chain would warn about builds that are
    // the ones being asked for.
    const plan = buildPlan(NODES, EDGES, ["mid", "out"]);
    expect(cascadeCount(NODES, EDGES, plan)).toBe(0);
  });

  it("does not count a model that does not react to its inputs", () => {
    const manual = NODES.map((n) =>
      n.id === "roll" ? node("roll", "model", 3, { trigger_mode: "manual" }) : n);
    expect(cascadeCount(manual, EDGES, buildPlan(manual, EDGES, ["mid"]))).toBe(0);
  });

  it("is nothing when there is nothing to build", () => {
    expect(cascadeCount(NODES, EDGES, buildPlan(NODES, EDGES, ["raw"]))).toBe(0);
  });
});
