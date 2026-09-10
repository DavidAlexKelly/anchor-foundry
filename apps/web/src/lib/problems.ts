/**
 * What the Problems panel says (§286; `code-repositories.md` §2.4).
 *
 * p.14: *"The Problems helper tells you about any issues detected in your
 * code. Click on a specific issue listed here to open up the problematic
 * code."*
 *
 * The server decides what is wrong — every rule it applies is one the publish
 * path already enforces, which is the point: a panel with rules of its own
 * would be a second opinion, and the two would drift. What lives here is how a
 * list of problems reads: what to count, what an empty panel means, and where
 * a click goes.
 */
import type { RepositoryProblem } from "./types";

/** How many will refuse a publish, and how many are worth knowing anyway. */
export function counts(problems: RepositoryProblem[]): { errors: number; warnings: number } {
  return {
    errors: problems.filter((p) => p.severity === "error").length,
    warnings: problems.filter((p) => p.severity !== "error").length,
  };
}

/**
 * The panel's one-line summary.
 *
 * **Errors and warnings are counted separately**, because the question the
 * summary answers is "can I commit this and have it publish", and only one of
 * the two numbers bears on it. A single total would make one warning look like
 * one error.
 */
export function summary(problems: RepositoryProblem[]): string {
  const { errors, warnings } = counts(problems);
  if (errors === 0 && warnings === 0) return "No problems found.";
  const parts: string[] = [];
  if (errors) parts.push(`${errors} error${errors === 1 ? "" : "s"}`);
  if (warnings) parts.push(`${warnings} warning${warnings === 1 ? "" : "s"}`);
  const tail = errors
    ? " — an error will refuse a publish."
    : " — nothing here will stop a publish.";
  return parts.join(", ") + tail;
}

/**
 * Where a problem points, as text.
 *
 * **A line of 0 is not line 1.** The reader says 0 when it could not say
 * where, and a panel that offered "line 1" for that would send somebody to the
 * top of a file for no reason and teach them the line numbers are decoration.
 */
export function location(problem: RepositoryProblem): string {
  return problem.line > 0 ? `${problem.path}:${problem.line}` : problem.path;
}

/**
 * The line to reveal when this problem is clicked, or nothing.
 *
 * Separate from `location` because one is text and the other is an
 * instruction, and a reader that returned 1 for "nowhere in particular" would
 * make the editor jump for no reason.
 */
export function revealLine(problem: RepositoryProblem): number | undefined {
  return problem.line > 0 ? problem.line : undefined;
}

/**
 * What an empty panel means — and it is not always "your code is fine".
 *
 * A repository with no source files has nothing to check, which is a different
 * answer from "everything checked out", and the difference matters to somebody
 * wondering whether the panel is working at all.
 */
export function emptyNote(sourceFileCount: number): string {
  return sourceFileCount === 0
    ? "No transforms in this repository yet, so there is nothing to check."
    : "No problems found.";
}

/** Whether a path is one the panel looks at, so the empty note can tell the
 *  two emptinesses apart. Kept in step with the server's own list by being the
 *  same two extensions and nothing else. */
export function isSourceFile(path: string): boolean {
  return path.endsWith(".sql") || path.endsWith(".py");
}

/**
 * The problems for one file, in the order the server gave them.
 *
 * **Not re-sorted** (§213, §280). The server already orders errors before
 * warnings and then by file and line, and re-sorting a list somebody else has
 * ordered is how two orders start to disagree — the second one usually while
 * nobody is looking.
 */
export function forPath(problems: RepositoryProblem[], path: string): RepositoryProblem[] {
  return problems.filter((p) => p.path === path);
}
