/**
 * What an action's numbers say (§323; `action-types` p.164-166).
 *
 *     "Action metrics display the near real-time usage of an action type over
 *      the last 30 days… Success/failure metrics: Monitor the current status
 *      of your actions with success and failure counts… P95 duration metric:
 *      Track the 95th percentile (P95) execution duration for each action
 *      type, which highlights the upper range of execution times, helping you
 *      detect performance bottlenecks." (p.164)
 *
 *     "Action metrics have a variety of categories of failures that may be
 *      displayed." (p.165)
 *
 * The server counts; this file decides what the counts *mean*. Same division
 * as `usage-metrics.ts` and `object-type-issues.ts`: the server owns what is
 * true, a pure module owns the wording, and the component only draws.
 *
 * **p.166's category names are translated here and nowhere else.** They arrive
 * as the identifiers db 0079 stores, which are p.165-166's own headings with
 * the spaces taken out — and a screen printing `invalid_parameter` at somebody
 * is a screen that made them learn a database's vocabulary to read a chart.
 */
import type { ActionFailureCount, ActionMetrics } from "./types";

/**
 * p.165-166's categories in English, and the sentence under each.
 *
 * The gloss matters more than the name: "scale limit failure" tells a reader
 * nothing they can act on, and "affected more than the permitted number of
 * objects" tells them to submit fewer. p.166's own wording, shortened.
 */
export const FAILURE_LABELS: Readonly<Record<string, { label: string; hint: string }>> = {
  invalid_parameter: {
    label: "Invalid parameter",
    hint: "Submitted with a parameter that isn't valid for this action.",
  },
  authentication: {
    label: "Authentication",
    hint: "Didn't pass the action's submission criteria.",
  },
  scale_limit: {
    label: "Scale limit",
    hint: "Affected more than the permitted number of objects.",
  },
  side_effect: {
    label: "Side effect",
    hint: "A webhook or side effect failed or is misconfigured.",
  },
  conflict: {
    label: "Conflict",
    hint: "A conflict, such as a concurrent modification.",
  },
  unclassified: {
    label: "Unclassified",
    hint: "Failed for a reason this platform can't name more precisely.",
  },
};

/**
 * A category's name for the screen.
 *
 * **An unknown identifier comes back readable rather than hidden.** db 0079's
 * CHECK constraint means one cannot arrive today — but the two categories
 * p.166 reserves for function-backed actions are waiting to be added, and a
 * lookup that returned "" for anything unrecognised would quietly drop a whole
 * bar out of a chart that still added up to the failure count beside it.
 */
export function failureLabel(category: string): string {
  return FAILURE_LABELS[category]?.label ?? humanise(category);
}

export function failureHint(category: string): string {
  return FAILURE_LABELS[category]?.hint ?? "";
}

function humanise(category: string): string {
  const words = category.replace(/_/g, " ").trim();
  if (!words) return "Unclassified";
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Nothing has been submitted in the window. p.164's metrics are "near
 * real-time usage", and an action nobody has run has no usage to show. */
export function isIdle(metrics: ActionMetrics): boolean {
  return metrics.total === 0;
}

export function idleMessage(metrics: ActionMetrics): string {
  return `Nobody has run this action in the last ${metrics.window_days} days.`;
}

/**
 * p.164's success rate, as a percentage of the runs that **finished**.
 *
 * **Running runs are excluded from the denominator, not counted as failures.**
 * A run still going has not succeeded or failed, and folding it into either
 * makes the rate move when nothing happened — a long action would show a
 * falling success rate simply for being slow, which is the opposite of what
 * p.164's reader is looking for.
 *
 * `null` when nothing has finished: a rate over no runs is not 0% (which reads
 * as "everything is broken") or 100% (which reads as "all is well"), and both
 * are claims the numbers do not support.
 */
export function successRate(metrics: ActionMetrics): number | null {
  const finished = metrics.succeeded + metrics.failed;
  if (finished === 0) return null;
  return (metrics.succeeded / finished) * 100;
}

/** The rate as it is printed, or a dash when there is nothing to print. */
export function successText(metrics: ActionMetrics): string {
  const rate = successRate(metrics);
  if (rate === null) return "—";
  // One decimal, because the difference between 99.9% and 100% is the whole
  // question for an action that runs thousands of times, and rounding to a
  // whole number would report a broken action as perfect.
  return `${rate.toFixed(1)}%`;
}

/**
 * Whether the failures are worth somebody's attention now.
 *
 * **A count, not only a rate.** One failure out of two is 50% and is probably
 * somebody testing; forty failures out of four thousand is 1% and is forty
 * people who could not do their job. Either alone would be quiet at exactly
 * the wrong moment, so this asks both and takes the union.
 */
export function needsAttention(metrics: ActionMetrics): boolean {
  if (metrics.failed === 0) return false;
  const rate = successRate(metrics);
  return metrics.failed >= 10 || (rate !== null && rate < 95);
}

/**
 * p.164's P95, as a duration somebody can read.
 *
 * Seconds under a minute, and minutes above — an action taking "212.4s" is one
 * the reader has to do arithmetic on to know it is nearly four minutes.
 */
export function durationText(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return rest === 0 ? `${mins}m` : `${mins}m ${rest}s`;
}

/**
 * The failure breakdown with each category's share, biggest first.
 *
 * **The share is over the failures, not over all runs.** p.165 introduces the
 * categories as a breakdown of *why it failed*, and a percentage of every run
 * would make a healthy action's one bad day render as a row of 0%s that say
 * nothing about which kind of bad day it was.
 */
export function breakdown(
  failures: readonly ActionFailureCount[],
): { category: string; label: string; hint: string; failures: number; share: number }[] {
  const total = failures.reduce((sum, f) => sum + f.failures, 0);
  return [...failures]
    .sort((a, b) => b.failures - a.failures || a.category.localeCompare(b.category))
    .map((f) => ({
      category: f.category,
      label: failureLabel(f.category),
      hint: failureHint(f.category),
      failures: f.failures,
      // Guarded, because a breakdown of nothing is an empty list rather than a
      // division by zero — and `0/0` is `NaN`, which renders as the word.
      share: total === 0 ? 0 : (f.failures / total) * 100,
    }));
}

/**
 * How one run in p.164's history reads.
 *
 * A failed run is named by its *category* rather than by its message: the
 * message is the engine's or the criterion's own words and can be a paragraph,
 * and the history is a list somebody scans. The message is still there to open.
 */
export function runSummary(run: {
  status: string;
  failure_category: string | null;
}): string {
  if (run.status === "succeeded") return "Succeeded";
  if (run.status === "running") return "Running";
  return run.failure_category ? `Failed — ${failureLabel(run.failure_category)}` : "Failed";
}
