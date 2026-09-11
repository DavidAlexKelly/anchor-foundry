/**
 * A branch's unit test runs, on the Checks tab (§296; p.19).
 *
 * Foundry: *"The Checks tab will also include the output of any unit tests
 * that have been defined for your repo."*
 *
 * **The two lists on that tab are not the same kind of thing here, and that is
 * a divergence worth saying out loud.** §285 recorded the first half: ours are
 * checks *on a proposal*, because a schema check asks what the code would do
 * to this project's datasets and a commit nobody has proposed has not said
 * which change it means. A test run is different again — it belongs to a
 * **branch and a working set** (db 0071), because the question it answers is
 * "does what I just typed pass". So one tab shows two things with two scopes,
 * and the honest thing is to label them rather than to merge them into a list
 * that implies a scope neither has.
 *
 * This module is what the tab says about the test half. `branch-checks.ts`
 * still owns the proposal half.
 */
import type { CodeTestRun } from "./types";
import { tally } from "./test-runs";

/**
 * The runs worth showing on the tab: the most recent per branch is what a
 * reader means by "did the tests pass".
 *
 * **One, not all of them.** The Checks tab answers "what is the state of this
 * branch", and a history of every run somebody pressed the button on is a
 * different question with its own home (the panel). A list here would also
 * make the tab grow without bound for a branch somebody is actively working
 * on, which is precisely the branch whose state matters most.
 */
export function mostRecent(runs: readonly CodeTestRun[]): CodeTestRun | undefined {
  return runs[0];
}

/**
 * The one-line status the tab shows for the test half.
 *
 * Deliberately the *same vocabulary* the proposal checks use — `passed`,
 * `failed`, `pending` — because they sit in one list under one heading, and a
 * reader who had to learn two sets of words for two kinds of row would learn
 * neither.
 */
export function status(run: CodeTestRun | undefined): "passed" | "failed" | "pending" | "none" {
  if (run === undefined) return "none";
  if (run.status === "queued" || run.status === "running") return "pending";
  if (run.status === "errored") return "failed";
  // **An empty run is `failed` here too**, and the summary below says why. A
  // repository with no tests has nothing failing in it, and reporting that as
  // passed is the suite-that-ran-nothing this feature is written against.
  if ((run.outcomes ?? []).length === 0) return "failed";
  return tally(run.outcomes ?? []).failed > 0 ? "failed" : "passed";
}

/**
 * What the row says happened.
 *
 * Every branch of this is a different sentence because every branch is a
 * different situation, and the one that would be easiest to collapse — no run
 * at all versus a run that found no tests — is the one where collapsing does
 * the most harm: the first is "press the button", the second is "write a
 * test".
 */
export function summary(run: CodeTestRun | undefined): string {
  if (run === undefined) {
    return "No unit tests have been run on this branch. Run them from the Tests panel.";
  }
  if (run.status === "queued") return "Queued.";
  if (run.status === "running") return "Running now.";
  if (run.status === "errored") {
    return run.error ?? "These tests could not be run.";
  }
  const outcomes = run.outcomes ?? [];
  if (outcomes.length === 0) {
    return "No unit tests in this repository yet, so nothing was run.";
  }
  const counted = tally(outcomes);
  const parts = [`${counted.passed} passed`];
  if (counted.failed > 0) parts.push(`${counted.failed} failed`);
  if (counted.skipped > 0) parts.push(`${counted.skipped} skipped`);
  return parts.join(", ") + ".";
}

/**
 * The failures worth naming under the row, capped.
 *
 * **Named rather than counted**, because "3 failed" sends you to the panel and
 * `tests/test_daily.py::test_totals` sends you to the test. Capped because a
 * branch where two hundred tests fail has one problem, not two hundred, and a
 * tab that listed them all would bury the proposal checks beside it.
 */
export const MAX_NAMED = 5;

export function namedFailures(run: CodeTestRun | undefined): string[] {
  const failures = (run?.outcomes ?? []).filter(
    (o) => o.outcome === "failed" || o.outcome === "error",
  );
  return failures.slice(0, MAX_NAMED).map((o) => o.id);
}

/** What to say about the ones the cap left out, or null when it left none. */
export function andMore(run: CodeTestRun | undefined): string | null {
  const total = (run?.outcomes ?? []).filter(
    (o) => o.outcome === "failed" || o.outcome === "error",
  ).length;
  if (total <= MAX_NAMED) return null;
  return `and ${total - MAX_NAMED} more`;
}
