/**
 * What the Checks tab says about a branch (§285; `code-repositories.md` §5).
 *
 * p.19: *"In the Checks tab, you can view a summary of running and completed
 * checks on each branch. Use the dropdown branch menu to select a different
 * branch. Click on a specific check to view more detailed information."*
 *
 * **The divergence this tab has to state out loud.** Foundry runs checks on a
 * *commit*: you commit to a sandbox and checks start. Ours run on a
 * *proposal*, because the second check asks what the code would do to the
 * project's datasets and a commit nobody has proposed has not said which
 * change it means to make. Since §284 a sandbox is where work happens and a
 * proposal is how it lands, so every commit that matters is on its way to
 * being one — but a tab that implied a per-commit runner exists would be
 * making a promise the product does not keep.
 */
import type { RepositoryCheck } from "./types";

/** Worst first, because a list of checks is read to find the failure.
 *
 * `error` outranks `warn` deliberately: a warning is an answer, and an error
 * means nobody has been told anything about the code (`code_checks.py`). */
const SEVERITY: Record<string, number> = { fail: 0, error: 1, warn: 2, pass: 3 };

export function severity(status: string): number {
  // An unknown status sorts with the failures rather than the passes: a status
  // this build does not recognise is not evidence that anything is fine.
  return SEVERITY[status] ?? 0;
}

/**
 * The checks, worst first, then newest.
 *
 * The server orders by time, which is the right order for "what happened" and
 * the wrong one for "what is wrong" — and this tab is read for the second.
 * Sorting here rather than there because the server's order is also the one
 * `LIMIT` would truncate against, and §280's lesson is not to re-sort a page
 * the server already cut.
 */
export function worstFirst(checks: RepositoryCheck[]): RepositoryCheck[] {
  return [...checks].sort(
    (a, b) =>
      severity(a.status) - severity(b.status) ||
      b.ran_at.localeCompare(a.ran_at) ||
      a.name.localeCompare(b.name),
  );
}

/** How many of each status, for a one-line summary. */
export function tally(checks: RepositoryCheck[]): Record<string, number> {
  const out: Record<string, number> = {};
  for (const c of checks) out[c.status] = (out[c.status] ?? 0) + 1;
  return out;
}

/**
 * The branch's verdict in one word.
 *
 * **`error` is not `pass`.** A check that could not run has told nobody
 * anything, and a branch reporting "passing" on the strength of checks that
 * never completed is the single most misleading thing this tab could say.
 */
export function verdict(checks: RepositoryCheck[]): "failing" | "unknown" | "warning" | "passing" | "none" {
  if (checks.length === 0) return "none";
  if (checks.some((c) => c.status === "fail")) return "failing";
  if (checks.some((c) => c.status === "error")) return "unknown";
  if (checks.some((c) => c.status === "warn")) return "warning";
  return "passing";
}

/** A sentence for the verdict, naming the count that produced it. */
export function verdictNote(checks: RepositoryCheck[]): string {
  const counts = tally(checks);
  switch (verdict(checks)) {
    case "none":
      return "Nothing has been checked on this branch yet.";
    case "failing":
      return `${counts.fail} check${counts.fail === 1 ? "" : "s"} failed. A failing check blocks the proposal it belongs to.`;
    case "unknown":
      return `${counts.error} check${counts.error === 1 ? "" : "s"} could not run, so nothing is known about that code. An error does not block — a freeze on every project every time we cannot answer would be worse.`;
    case "warning":
      return `${counts.warn} warning${counts.warn === 1 ? "" : "s"}, and nothing failed. A warning is the dataset's own policy saying this is allowed but worth seeing.`;
    default:
      return `${counts.pass} check${counts.pass === 1 ? "" : "s"} passed.`;
  }
}

/**
 * What an empty tab means, which is not "everything is fine".
 *
 * Three different emptinesses with three different remedies, and the reader is
 * the one who knows which they are looking at — the shape §276's empty Pull
 * requests tab takes, for the same reason.
 */
export function emptyReason(hasCommits: boolean, isDefaultBranch: boolean): string {
  if (!hasCommits) {
    return "Nothing has been committed to this branch, so there is nothing to check.";
  }
  if (isDefaultBranch) {
    return "No checks on this branch. Checks run on a pull request, and work lands here by applying one — look at the sandbox branch the change is on.";
  }
  return "No checks yet. Open a pull request for this branch and run its checks.";
}

/**
 * Which file a check is about, as far as it can be said.
 *
 * Both anchors are nullable and that is not sloppiness: a check can be about
 * the proposal as a whole, and a file with no model yet is carried by its path
 * (db 0039). "the whole change" is what actually happened; "unknown" would be
 * wrong about it.
 */
export function checkTarget(check: RepositoryCheck): string {
  return check.source_path ?? (check.model_id ? "a transform" : "the whole change");
}
