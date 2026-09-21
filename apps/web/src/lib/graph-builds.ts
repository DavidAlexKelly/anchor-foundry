/**
 * Building from the lineage graph (§386; `data-lineage` p.9).
 *
 * > "The builds helper offers you three build strategies:
 * >  Build only selected datasets /
 * >  Build all datasets between the selected datasets /
 * >  Build the selected datasets and all of their ancestors" (p.9)
 *
 * **Two of the three selections were already on the screen**, which is what
 * sized this unit: §354's multi-select is the first, and the `All upstream`
 * chip — `relatives(edges, selected, "upstream", Infinity)`, seeds included —
 * is the third. p.9's strategies are a *selection* plus a build, and the
 * selections are the graph's existing vocabulary. So this adds the one
 * selection that was missing (`between`) and the build, rather than three
 * buttons that would each restate an expansion the bar already offers.
 *
 * That is also why the control reads "Build" over whatever is selected rather
 * than naming Foundry's three strategies: here they are three ways to *shape a
 * selection*, and the shaping is a step the reader can see happen.
 *
 * **What a build actually runs is a model**, and p.9 says datasets. The two
 * meet one hop up: a dataset is built by the model that writes it. A selected
 * model is itself; a selected dataset is the model one edge upstream of it;
 * an uploaded dataset has no such model and cannot be built at all, which is
 * the §214 case here — a control that reported "building 6" while running 4
 * would be worse than one that says which 4.
 */
import type { PipelineEdge, PipelineNode } from "./types";
import { relatives } from "./pipeline-graph";

/** Every node on a path from one selected node to another (p.9's middle
 *  strategy).
 *
 * **The intersection of two walks**, because "between A and B" means reachable
 * *from* A and reaching *to* B — and with more than two selected it is every
 * such pair at once, which the union over seeds gives without enumerating
 * pairs. Both walks come from `relatives`, so cycles terminate there rather
 * than being a second place that has to remember to.
 *
 * **The ends are between, and they come out of the walks rather than out of a
 * clause here.** The first draft added `|| selected.includes(id)` to say so,
 * and a sweep found it could not be made to fail: `relatives` returns its
 * seeds, so every selected node is in *both* sets already and the clause could
 * never change an answer. Deleted rather than covered by a test that would
 * have passed either way (§213). The property it was protecting is real and is
 * still tested — it just belongs to `relatives`, whose docstring states it.
 */
export function between(
  edges: readonly Pick<PipelineEdge, "from" | "to">[],
  selected: readonly string[],
): string[] {
  if (selected.length < 2) return [...selected];
  const downstream = new Set(relatives(edges, selected, "downstream", Infinity));
  const upstream = new Set(relatives(edges, selected, "upstream", Infinity));
  // A node is between when something selected reaches it *and* it reaches
  // something selected.
  return [...downstream].filter((id) => upstream.has(id));
}

export interface PlannedModel {
  id: string;
  name: string;
  layer: number;
  /** How this model fires today — `manual`, `cron` or `upstream`. Carried
   *  because a *schedule* control over the same selection needs it (§387),
   *  and asking which models a selection means is one question with one
   *  answer (§292). Null on a node whose graph row did not carry one. */
  trigger_mode: string | null;
}

export interface BuildPlan {
  /** Model ids to run, in the order the graph reads: upstream first. */
  models: PlannedModel[];
  /** Selected datasets nothing on this graph builds. */
  unbuildable: string[];
  /** Transforms left out because what they write is already current (§421;
   *  p.57). Named rather than counted, because a build that quietly did less
   *  than the selection is the reading §214 exists to prevent — and because
   *  with `force` on this is empty and the summary says a different thing. */
  upToDate: string[];
}

/** p.57's "Force build on up-to-date datasets". */
export interface BuildOptions {
  /** Run every transform the selection names, current or not.
   *
   * **Off by default, which is p.57's default and not a preference of this
   * build's**: "By default, this builds only ancestors that are out of date,
   * but you can choose to force a re-build of up-to-date datasets. Forcing a
   * re-build can be expensive in terms of build time and resources." */
  force?: boolean;
}

/** Whether this model has anything to do.
 *
 * **The output dataset's staleness, not the model's own.** A model is never
 * `out_of_date` — `services/pipeline.py` sets it false on every model node and
 * says why: a model is not a thing that goes out of date, its output is, and
 * that is the node one edge along. Reading the flag off the model would leave
 * every transform looking current and `force` the only thing that ever built
 * anything.
 *
 * **A model with no output node has never run**, because `output_dataset_id`
 * is NULL until the first run — so it is never up to date, whatever else is.
 * That is the one case where "nothing downstream is stale" and "nothing needs
 * building" come apart. */
function isCurrent(
  model: PipelineNode,
  edges: readonly Pick<PipelineEdge, "from" | "to">[],
  byId: Map<string, PipelineNode>,
): boolean {
  const outputs = relatives(edges, [model.id], "downstream", 1)
    .map((id) => byId.get(id))
    .filter((n): n is PipelineNode => !!n && n.kind === "dataset");
  if (outputs.length === 0) return false;
  return outputs.every((output) => !output.out_of_date);
}

/**
 * What pressing Build over this selection would do.
 *
 * **Ordered by `layer`**, which the server already computed (`_layer`, Kahn's,
 * "every edge points strictly rightwards"), so an ancestor set has a build
 * order without this working one out. Recomputing it here would be a second
 * answer to a question the response already carries.
 */
export function buildPlan(
  nodes: readonly PipelineNode[],
  edges: readonly Pick<PipelineEdge, "from" | "to">[],
  selected: readonly string[],
  options: BuildOptions = {},
): BuildPlan {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const chosen = selected.map((id) => byId.get(id)).filter((n): n is PipelineNode => !!n);
  const models = new Map<string, PipelineNode>();
  const unbuildable: string[] = [];

  for (const node of chosen) {
    if (node.kind === "model") {
      models.set(node.id, node);
      continue;
    }
    if (node.kind !== "dataset") continue;
    // One hop, not the whole chain: the model that *writes* this dataset is
    // its immediate upstream. Anything further up builds a different dataset,
    // and p.9 keeps reaching further as its own strategy.
    const producers = relatives(edges, [node.id], "upstream", 1)
      .map((id) => byId.get(id))
      .filter((n): n is PipelineNode => !!n && n.kind === "model");
    if (producers.length === 0) unbuildable.push(node.name);
    for (const producer of producers) models.set(producer.id, producer);
  }

  // p.57's default, applied after the selection has been resolved rather than
  // while resolving it: which transforms a selection *means* is one question
  // (§292 — the schedule control asks the same one), and whether they need
  // running is a second.
  const running = [...models.values()];
  const current = options.force ? [] : running.filter((m) => isCurrent(m, edges, byId));
  const skipped = new Set(current.map((m) => m.id));

  return {
    models: running
      .filter((m) => !skipped.has(m.id))
      .sort((a, b) => a.layer - b.layer || a.name.localeCompare(b.name))
      .map((m) => ({
        id: m.resource_id, name: m.name, layer: m.layer, trigger_mode: m.trigger_mode,
      })),
    unbuildable: unbuildable.sort(),
    upToDate: current.map((m) => m.name).sort(),
  };
}

/**
 * What the control says it will do, or why it will not.
 *
 * **The count is of models, not of selected nodes**, and the difference is the
 * whole point: selecting six cards and running four builds is the reading
 * §214 exists to prevent. When some of the selection cannot be built the
 * sentence says so rather than quietly running the rest.
 */
export function buildSummary(plan: BuildPlan): string {
  const { models, unbuildable, upToDate } = plan;
  if (models.length === 0) {
    // **Three empty states, not one** (§210). "Nothing to build" is the same
    // words for a selection of uploads, a selection of nothing, and a
    // selection that is simply finished — and only the last one has a control
    // beside it that would change the answer.
    if (upToDate.length > 0) {
      // **"Nothing to build" plus the reason, not "everything selected is up
      // to date"** — the first wording was wrong the moment an upload was in
      // the selection beside two current transforms, because an upload is not
      // up to date, it is not a thing that builds. This says only what it can
      // stand behind.
      return `nothing to build: ${upToDate.length} transform${
        upToDate.length === 1 ? " is" : "s are"
      } already up to date`;
    }
    return unbuildable.length > 0
      ? "nothing here is built by a transform"
      : "select a dataset or a transform to build";
  }
  const built = `build ${models.length} transform${models.length === 1 ? "" : "s"}`;
  // p.57's default said out loud. A build that ran four of six selected
  // transforms without saying which two it left alone is the reading §214
  // exists to prevent, and here the two it left alone are the reassuring ones.
  const rested = upToDate.length > 0
    ? `; ${upToDate.length} already up to date`
    : "";
  if (unbuildable.length === 0) return built + rested;
  // Named when there are few enough to name. A list of thirty is not a
  // sentence, and the count is what a reader acts on either way.
  const named = unbuildable.length <= 3 ? ` (${unbuildable.join(", ")})` : "";
  return `${built}${rested}; ${unbuildable.length} selected dataset${
    unbuildable.length === 1 ? " is" : "s are"
  } uploaded, not built${named}`;
}

/**
 * Whether building this selection will set more off on its own (§383).
 *
 * `enqueue_due_upstream_models` (worker step 2, db 0021) queues a run for
 * every `trigger_mode='upstream'` model whose inputs have gained a version.
 * So building an ancestor set makes its downstream fire again on the next
 * pass — **more builds than the strategy named**, which is worth saying
 * before the click rather than discovering in the run history.
 *
 * Counted over the *whole graph* rather than the selection, because the ones
 * that will fire are by definition the ones not selected — a count over the
 * selection would report zero in exactly the case this warns about.
 */
export function cascadeCount(
  nodes: readonly PipelineNode[],
  edges: readonly Pick<PipelineEdge, "from" | "to">[],
  plan: BuildPlan,
): number {
  if (plan.models.length === 0) return 0;
  const byResource = new Map(nodes.filter((n) => n.kind === "model").map((n) => [n.resource_id, n]));
  const seeds = plan.models.map((m) => byResource.get(m.id)?.id).filter((id): id is string => !!id);
  const planned = new Set(seeds);
  return relatives(edges, seeds, "downstream", Infinity)
    .filter((id) => !planned.has(id))
    .map((id) => nodes.find((n) => n.id === id))
    .filter((n) => n?.kind === "model" && n.trigger_mode === "upstream").length;
}
