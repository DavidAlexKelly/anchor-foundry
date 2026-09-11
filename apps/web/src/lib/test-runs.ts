/**
 * What the Tests panel says about a run (§295; p.14's Tests helper).
 *
 * Foundry: *"When your repository contains unit tests, the Tests Helper lets
 * you run those tests and displays their results."* One sentence, and the
 * whole specification — `code-repositories.md` §8 records that the Unit tests
 * chapter (p.56) is a pointer to per-language docs that are not in
 * `docs/pal/`. So the design decisions here are ours, and each one is written
 * down where it is made.
 *
 * The server owns what is *legal* (`services/code_test_runs.py`), the worker
 * owns what actually happened (db 0071), and this owns what to *say* — the
 * division `branch-checks.ts` and `problems.ts` already take.
 */
import type { CodeTestOutcome, CodeTestRun } from "./types";

export const PASSED = "passed";
export const FAILED = "failed";
export const ERROR = "error";
export const SKIPPED = "skipped";

/** Whether this run has finished, either way. */
export function isSettled(run: CodeTestRun): boolean {
  return run.status === "succeeded" || run.status === "failed" || run.status === "errored";
}

/**
 * Whether the panel should keep asking.
 *
 * **The panel polls because there is nothing to push to it.** A run is a job
 * (decision 0004: unit tests are customer Python and do not run in the API),
 * so the only way to learn it finished is to ask — and the only way to stop
 * asking forever is for this to go false, which is why it is a named rule
 * rather than an inline `!==`.
 */
export function shouldPoll(run: CodeTestRun | undefined): boolean {
  return run !== undefined && !isSettled(run);
}

/**
 * How the outcomes are ordered.
 *
 * **Failures first, then errors, then the rest in the order they ran.** A run
 * with two hundred tests and one failure is the ordinary case, and a panel
 * that made you scroll for it would be a panel people stop opening. Within a
 * severity the original order is kept, because that is the file order and it
 * is the only order the reader can predict.
 */
const SEVERITY: Record<string, number> = {
  [FAILED]: 0,
  [ERROR]: 1,
  [SKIPPED]: 2,
  [PASSED]: 3,
};

export function worstFirst(outcomes: readonly CodeTestOutcome[]): CodeTestOutcome[] {
  return outcomes
    .map((o, index) => ({ o, index }))
    .sort((a, b) => {
      const severity = (SEVERITY[a.o.outcome] ?? 9) - (SEVERITY[b.o.outcome] ?? 9);
      return severity !== 0 ? severity : a.index - b.index;
    })
    .map((entry) => entry.o);
}

/** How many of each, for the summary line. */
export function tally(outcomes: readonly CodeTestOutcome[]): {
  passed: number;
  failed: number;
  skipped: number;
} {
  return {
    passed: outcomes.filter((o) => o.outcome === PASSED).length,
    // Errors count as failures here, and only here: the *row* keeps them apart
    // because the first thing to look at differs, and the *count* does not
    // because "3 failed" and "2 failed, 1 errored" say the same thing to
    // somebody deciding whether to look.
    failed: outcomes.filter((o) => o.outcome === FAILED || o.outcome === ERROR).length,
    skipped: outcomes.filter((o) => o.outcome === SKIPPED).length,
  };
}

/**
 * The sentence at the top of the panel.
 *
 * **A run with no tests is not a pass**, and this is where that shows up for a
 * reader. "Nothing failed" and "everything passed" are the same number, and
 * `code-repositories.md` §10 names this feature specifically: *"a failing test
 * is reported as failing. A test suite that cannot fail is the exact thing
 * this repo does not accept."* A panel that said "All tests passed" over an
 * empty list would be that failure, wearing a green tick.
 */
export function verdict(run: CodeTestRun | undefined): string {
  if (run === undefined) return "No tests have been run on this branch yet.";
  if (run.status === "queued") return "Waiting to run…";
  if (run.status === "running") return "Running…";
  if (run.status === "errored") {
    return run.error ?? "These tests could not be run.";
  }
  const outcomes = run.outcomes ?? [];
  if (outcomes.length === 0) {
    return (
      "No unit tests found. pytest collects files named test_*.py or *_test.py — " +
      "add one and this will run it."
    );
  }
  const counted = tally(outcomes);
  const parts = [`${counted.passed} passed`];
  if (counted.failed > 0) parts.push(`${counted.failed} failed`);
  if (counted.skipped > 0) parts.push(`${counted.skipped} skipped`);
  return parts.join(", ");
}

/**
 * Whether the verdict is bad news, so the panel can colour it.
 *
 * **`errored` is bad news too**, and it is the case a boolean over `failed`
 * alone would miss: a run that could not happen is not a pass, and a panel
 * that showed it in the same colour as a success would be the quietest
 * possible way to lose a test suite.
 */
export function isAProblem(run: CodeTestRun | undefined): boolean {
  if (run === undefined || !isSettled(run)) return false;
  if (run.status === "errored") return true;
  return (run.outcomes ?? []).length === 0 || tally(run.outcomes ?? []).failed > 0;
}

/**
 * What one row says about how long a test took.
 *
 * Sub-millisecond tests are the majority and "0ms" on two hundred rows is
 * noise, so they say nothing at all. A duration is shown when it is
 * information.
 */
export function durationLabel(outcome: CodeTestOutcome): string | null {
  if (outcome.duration_ms < 1) return null;
  if (outcome.duration_ms < 1000) return `${outcome.duration_ms}ms`;
  return `${(outcome.duration_ms / 1000).toFixed(1)}s`;
}

/**
 * Where clicking a row should go, or null when there is nowhere.
 *
 * pytest reports a file for a test it collected and nothing for one it could
 * not — a collection error names the module that would not import. **Null
 * rather than a guess**: a row that jumped somewhere plausible and wrong is
 * worse than one that does not jump, because the reader believes it.
 */
export function target(outcome: CodeTestOutcome): { path: string; line: number } | null {
  if (!outcome.file) return null;
  return { path: outcome.file, line: outcome.line ?? 1 };
}

/**
 * What the button says.
 *
 * Named for what it will do rather than for the state it is in: "Running…" on
 * a button somebody just pressed is a progress report, and a button that still
 * said "Run tests" while a run was in flight would invite a second press that
 * the server refuses (`MAX_QUEUED_PER_REPO`).
 */
export function runLabel(run: CodeTestRun | undefined): string {
  if (run !== undefined && !isSettled(run)) return "Running…";
  return "Run tests";
}

/**
 * Whether this role is offered the Run button.
 *
 * **`POST /tests` is editor-level**, because asking for tests to run executes
 * code the caller supplied — the line `preview_transform` draws, and the one
 * `code_test_runs.py` takes. A viewer's button would be a control that looks
 * like it works (§214), and it is a *different* rule from the editor's
 * read-only state: that is about a pinned commit, and running a pinned
 * commit's tests would be refused for a reason nobody could read off the
 * screen.
 *
 * The first version of the panel used the editor's `readOnly` for this, which
 * is always false where the panel renders — so the check was a check that
 * could not fire.
 */
export function canEditProject(role: string): boolean {
  return role === "editor" || role === "owner";
}
