/**
 * What the Build helper says about building the current file (§385; p.13-14).
 *
 * > "If you select a dataset source file […] you can click the [build] button
 * >  to build a new version of your output dataset after running automatic
 * >  checks on your code. Clicking the button will trigger a build on all
 * >  output datasets of the current file; **if the current file does not
 * >  generate any datasets, no build is triggered**." (p.13)
 *
 * > "The Build helper lets you trigger dataset builds and **view the progress**
 * >  for your builds." (p.14)
 *
 * p.14 says in its own sentence that these are one feature — *"Clicking the
 * Build button at the top right corner of the Code Repositories interface is
 * equivalent to triggering a build from the Build helper"* — which is why the
 * trigger and the progress view are built together. A button that fires and
 * never reports is §214's control that looks like it works, and §384 found
 * this platform's checklist carrying the two halves as separate ○ rows that
 * disagreed about whether either was worth doing.
 *
 * **One file publishes to one model here** (db 0038's partial unique index on
 * `(source_repo_id, source_path)`, "one file publishes to one model"), so
 * p.13's *all output datasets of the current file* is at most one model and
 * its one output. That is a translation difference rather than a missing half:
 * Foundry's file can define several transforms, and ours cannot.
 *
 * The server owns what is *legal* (`routes/models.run_model` refuses a model
 * with no code or no inputs, and the refusal names which), the worker owns
 * what happened (`model_runs`), and this owns what to **say** — the division
 * `test-runs.ts` and `run-logs.ts` already take. Pure, and in `lib/` rather
 * than beside the component, because vitest cannot parse `.tsx`: a rule that
 * lives in a component is a rule with no unit test.
 */
import type { Model, ModelRun } from "./types";

/**
 * The model this file publishes to, or `undefined` when it publishes to none.
 *
 * **Keyed on the pair, not on the path alone.** `source_path` is
 * repository-relative, so two repositories in one project can both hold
 * `transforms/daily.py` — matching on the path by itself would build the
 * other repository's transform from this one's editor, which is the kind of
 * wrong that looks right on screen.
 */
export function modelForFile(
  models: readonly Model[] | undefined,
  repoId: string,
  path: string | undefined,
): Model | undefined {
  if (!models || path === undefined) return undefined;
  return models.find((m) => m.source_repo_id === repoId && m.source_path === path);
}

/**
 * Why this file cannot be built, or `""` when it can.
 *
 * **p.13's no-op rule, said rather than performed.** Foundry's answer to a
 * file that generates no datasets is that "no build is triggered" — a button
 * that quietly does nothing. Said out loud it is a better answer to the same
 * fact, because the reason a reader needs is *why*: an unpublished file is one
 * publish away from being buildable, and nothing on the screen otherwise says
 * so.
 *
 * A file that is not a transform at all gets a different sentence from one
 * that is a transform and has not been published, because they send a reader
 * to different places — and telling them apart is exactly what the checklist's
 * own wording ("does not generate any datasets") elides.
 */
export function whyNoBuild(
  model: Model | undefined,
  { isSourceFile }: { isSourceFile: boolean },
): string {
  if (!model) {
    if (!isSourceFile) return "only a transform file builds a dataset";
    return "this file has not been published yet, so nothing builds from it";
  }
  // **The one refusal worth knowing before the click.** `run_model` rejects a
  // model with no inputs — "add at least one input dataset before running" —
  // and a Build button that is always going to earn that is §214's control
  // that looks like it works. The listing carries `inputs`, so the panel can
  // say it instead of discovering it.
  //
  // **The server stays the authority.** This is the wording, not the rule: a
  // refusal for any other reason still arrives from `run_model` and is shown
  // as it came. Two writers of one rule is what §191 is about, and this is
  // deliberately not that — it is a *subset*, stated early, that the server
  // re-decides every time.
  if (model.inputs.length === 0) {
    return `${model.name} has no input datasets yet, so there is nothing to build from`;
  }
  return "";
}

/** Whether this run has finished, either way. */
export function isSettled(run: Pick<ModelRun, "status">): boolean {
  return run.status !== "queued" && run.status !== "running";
}

/**
 * Whether the panel should keep asking.
 *
 * **The panel polls because there is nothing to push to it**, the same reason
 * `test-runs.shouldPoll` gives: a build is a job, so the only way to learn it
 * finished is to ask, and the only thing that ever stops the asking is this
 * going false. A named rule rather than an inline comparison for that reason.
 */
export function shouldPoll(run: ModelRun | undefined): boolean {
  return run !== undefined && !isSettled(run);
}

/**
 * The newest run of this model, or `undefined`.
 *
 * **By `queued_at`, not by position.** The history endpoint's order is its
 * own decision and this one does not depend on it — §298's rule, since a
 * shared assumption is exactly what a differential test cannot catch.
 */
export function latestRun(runs: readonly ModelRun[] | undefined): ModelRun | undefined {
  if (!runs || runs.length === 0) return undefined;
  return runs.reduce((newest, run) =>
    new Date(run.queued_at).getTime() > new Date(newest.queued_at).getTime() ? run : newest,
  );
}

/** What the button says, which is also whether pressing it would do anything. */
export function buildLabel(run: ModelRun | undefined): string {
  if (run === undefined) return "Build";
  if (run.status === "queued") return "Queued…";
  if (run.status === "running") return "Building…";
  return "Build again";
}

/**
 * What the panel reports about the last build, in one line.
 *
 * **A run nobody has started is not a failure and not a success**, and saying
 * "never built" rather than nothing is the difference between a panel that has
 * answered and one that has not loaded.
 */
export function buildVerdict(run: ModelRun | undefined): string {
  if (run === undefined) return "never built";
  switch (run.status) {
    case "queued":
      return "queued";
    case "running":
      return "building";
    case "cancelled":
      return "cancelled";
    case "failed":
      return run.error_message ? `failed: ${run.error_message}` : "failed";
    default:
      return run.rows_produced === null
        ? "built"
        : `built ${run.rows_produced.toLocaleString()} rows`;
  }
}

/** Whether the last build is something to draw attention to. */
export function buildIsAProblem(run: ModelRun | undefined): boolean {
  return run !== undefined && (run.status === "failed" || run.status === "cancelled");
}
