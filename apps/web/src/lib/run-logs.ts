/**
 * Reading a model run (§358; `dataset-preview` p.3).
 *
 * > "On the left panel, a list of jobs appears with their statuses and
 * > durations. Upon selection, a detailed Job view appears on the right
 * > showing detailed job information, including progress, specification,
 * > **build logs**, files and the resulting schema." (p.3)
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type { ModelRun } from "@/lib/types";
import { durationText } from "./duration";

/**
 * How long a run took, or `""` when it has not finished one.
 *
 * **From `started_at`, not `queued_at`.** Time spent waiting for the worker is
 * not time the transform took, and a run that sat in the queue for a minute
 * and ran for a second is a fast transform on a busy worker — which is a
 * different problem from a slow transform, and the number has to tell them
 * apart.
 */
export function runDuration(run: Pick<ModelRun, "started_at" | "finished_at">): string {
  if (!run.started_at || !run.finished_at) return "";
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "";
  // **Which two timestamps** is this function's decision; **how a duration
  // reads** is `lib/duration`'s, shared with the action metrics that had it
  // first. Spelling it out again here is how "2m" and "2m 0s" came to be the
  // same number on two pages.
  return durationText(ms / 1000);
}

/**
 * Why there is no log to open, or `""` when there is one.
 *
 * **Every "no" gets its own sentence**, because they send a reader to
 * different places: a run still going will have one shortly, a SQL model will
 * never have one, and a Python run that printed nothing has already told you
 * everything it was going to. A single greyed-out button reading "no logs"
 * makes those look like one thing, and the second is the one people ask about.
 *
 * This is the §214 half of the feature: the control is absent with a reason
 * rather than present and empty.
 */
export function whyNoLog(
  run: Pick<ModelRun, "status" | "has_log">,
  language: string,
): string {
  if (run.has_log) return "";
  if (run.status === "queued" || run.status === "running") {
    return "this run has not finished yet";
  }
  if (language === "sql") {
    return "SQL transforms have no output to capture — this is a query, not a program";
  }
  return "this run printed nothing";
}
