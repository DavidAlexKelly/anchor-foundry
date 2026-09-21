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
  // **Set, not left off** (§421, and §419's lesson one module over): every
  // node the server builds carries these, and a helper that omitted them let
  // `!node.out_of_date` read `undefined` — which is how a fixture builds a
  // node the graph can never draw and then proves something about it.
  out_of_date: false,
  out_of_date_reason: null,
  ...over,
} as PipelineNode);

const edge = (from: string, to: string) => ({ from, to });

/*  raw ──▶ clean(model) ──▶ mid ──▶ roll(model) ──▶ out
    raw is an upload: nothing builds it.

    **Both derived datasets are out of date**, which is the state somebody
    presses Build in — and after §421 it is what makes these tests about which
    transforms a selection *resolves to* rather than about p.57's default. A
    current pipeline has its own fixture below, because "nothing to build" and
    "this selection means nothing" are different answers.                   */
const NODES = [
  node("raw", "dataset", 0),
  node("clean", "model", 1),
  node("mid", "dataset", 2, { out_of_date: true, out_of_date_reason: "input_is_newer" }),
  node("roll", "model", 3, { trigger_mode: "upstream" }),
  node("out", "dataset", 4, { out_of_date: true, out_of_date_reason: "upstream_is_out_of_date" }),
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

/*  The same pipeline with nothing behind: `mid` and `out` are current.      */
const CURRENT = NODES.map((n) =>
  n.kind === "dataset" ? node(n.id, "dataset", n.layer, {
    trigger_mode: n.trigger_mode,
  }) : n);

describe("p.57's default: only what is out of date (§421)", () => {
  it("leaves a transform alone when what it writes is current", () => {
    // > "By default, this builds only ancestors that are out of date, but you
    // >  can choose to force a re-build of up-to-date datasets."
    const plan = buildPlan(CURRENT, EDGES, ["mid", "out"]);
    expect(plan.models).toEqual([]);
    expect(plan.upToDate).toEqual(["clean", "roll"]);
  });

  it("runs it anyway when told to", () => {
    const plan = buildPlan(CURRENT, EDGES, ["mid", "out"], { force: true });
    expect(plan.models.map((m) => m.name)).toEqual(["clean", "roll"]);
    // Nothing is *skipped* under force, so nothing is named as skipped — the
    // list is what was left out, not what happened to be current.
    expect(plan.upToDate).toEqual([]);
  });

  it("builds the stale half of a mixed selection and names the other", () => {
    // The case the whole option exists for, and the one a count alone would
    // misreport: two selected, one runs.
    const half = CURRENT.map((n) =>
      n.id === "out" ? node("out", "dataset", 4, { out_of_date: true }) : n);
    const plan = buildPlan(half, EDGES, ["mid", "out"]);
    expect(plan.models.map((m) => m.name)).toEqual(["roll"]);
    expect(plan.upToDate).toEqual(["clean"]);
  });

  it("builds a transform that has never run, current or not", () => {
    // `output_dataset_id` is NULL until the first run, so a never-run model
    // has no output node at all — the one case where "nothing downstream is
    // stale" and "nothing needs building" come apart. Reading staleness off
    // the missing output would leave it unbuildable forever.
    const never = [node("raw", "dataset", 0), node("fresh", "model", 1)];
    const plan = buildPlan(never, [edge("raw", "fresh")], ["fresh"]);
    expect(plan.models.map((m) => m.name)).toEqual(["fresh"]);
    expect(plan.upToDate).toEqual([]);
  });

  it("reads the output's staleness, not the model's own", () => {
    // A model is never `out_of_date` — `services/pipeline.py` sets it false on
    // every model node and says why. Reading the flag off the model would
    // leave every transform looking current and `force` the only thing that
    // ever built anything.
    const stale = CURRENT.map((n) =>
      n.id === "clean" ? node("clean", "model", 1, { out_of_date: true }) : n);
    expect(buildPlan(stale, EDGES, ["mid"]).models).toEqual([]);
  });

  it("says a finished selection is finished, not that nothing builds it", () => {
    // §210: three empty states, and only this one has a control beside it
    // that would change the answer.
    expect(buildSummary(buildPlan(CURRENT, EDGES, ["mid", "out"])))
      .toBe("nothing to build: 2 transforms are already up to date");
    expect(buildSummary(buildPlan(CURRENT, EDGES, ["raw"])))
      .toBe("nothing here is built by a transform");
    expect(buildSummary(buildPlan(CURRENT, EDGES, [])))
      .toBe("select a dataset or a transform to build");
  });

  it("says what it left alone as well as what it will run", () => {
    const half = CURRENT.map((n) =>
      n.id === "out" ? node("out", "dataset", 4, { out_of_date: true }) : n);
    expect(buildSummary(buildPlan(half, EDGES, ["mid", "out"])))
      .toBe("build 1 transform; 1 already up to date");
  });

  it("keeps both halves of the sentence when a selection has an upload in it", () => {
    // The two notes are about different things — one is "cannot", the other
    // is "need not" — and a reader with both in their selection needs both.
    const half = CURRENT.map((n) =>
      n.id === "out" ? node("out", "dataset", 4, { out_of_date: true }) : n);
    expect(buildSummary(buildPlan(half, EDGES, ["raw", "mid", "out"])))
      .toBe("build 1 transform; 1 already up to date; 1 selected dataset is "
        + "uploaded, not built (raw)");
  });

  it("does not claim an upload is up to date", () => {
    // The wording this sentence had first was "everything selected is up to
    // date", and it was wrong the moment an upload sat in the selection
    // beside a current transform: an upload is not up to date, it is not a
    // thing that builds at all.
    expect(buildSummary(buildPlan(CURRENT, EDGES, ["raw", "mid"])))
      .toBe("nothing to build: 1 transform is already up to date");
  });

  it("does not warn about a cascade from a build that will not happen", () => {
    // §383's count is over the plan, so a plan that runs nothing sets nothing
    // off — a warning beside a disabled button is noise about a hypothetical.
    expect(cascadeCount(CURRENT, EDGES, buildPlan(CURRENT, EDGES, ["mid"]))).toBe(0);
  });
});
