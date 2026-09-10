/**
 * The editor's status bar (§307; p.15; `code-repositories.md` §2.5).
 *
 * p.15 lists four indicators, and the parity document's reading of them is the
 * brief this file was written to:
 *
 * > "Our equivalent of Code Assist is whatever backs Problems and Preview. The
 * >  lesson worth copying is not the widget, it is that **Foundry tells you
 * >  when the thing that makes the editor smart is not yet ready**, rather than
 * >  silently behaving like a dumb editor."
 *
 * **It reports, it does not decide.** Every number here is computed somewhere
 * else — `verdict` in `branch-checks.ts` says what a branch's checks amount to,
 * the Problems panel counts problems, `editor-drafts.ts` says what happened to
 * a save. A status bar that recomputed any of them would be a second answer to
 * a question already answered one panel away, and the two would disagree the
 * first time either changed. That is also why this is the last thing built:
 * it is meaningless before the things it reports on exist.
 */
import type { RepositoryCheck } from "./types";
import { verdict } from "./branch-checks";

/**
 * What the thing that makes the editor smart is doing.
 *
 * **`idle` is ours and is a divergence worth naming.** Foundry's Code Assist
 * initialises and then runs continuously, so its states are about starting up.
 * Ours analyses **on demand** — the Problems panel is a round trip, and one on
 * every keystroke would cost more than it tells you (§286) — so most of the
 * time nothing is analysing anything.
 *
 * Saying so is the whole point rather than an admission. p.15's lesson is that
 * an editor should not silently behave like a dumb one, and an editor that is
 * not analysing while you type is exactly that: a status bar claiming "Ready"
 * would be the silence p.15 warns about, dressed as reassurance.
 */
export type AssistState = "loading" | "idle" | "working" | "ready" | "unavailable";

export function assistState(input: {
  editorReady: boolean;
  analysing: boolean;
  failed: boolean;
  answered: boolean;
}): AssistState {
  // The editor first: until Monaco has loaded there is no editor to be smart
  // about, and it is loaded dynamically, so this is a real state rather than
  // a moment.
  if (!input.editorReady) return "loading";
  // A failure outranks an answer, because the answer it outranks is stale.
  if (input.failed) return "unavailable";
  if (input.analysing) return "working";
  return input.answered ? "ready" : "idle";
}

export function assistLabel(state: AssistState): string {
  switch (state) {
    case "loading":
      return "Editor loading";
    case "working":
      return "Analysing";
    case "ready":
      return "Analysis ready";
    case "unavailable":
      return "Analysis unavailable";
    default:
      return "Analysis on demand";
  }
}

/**
 * p.15's hover: "details on the initialization progress".
 *
 * Each one says what it *means for you*, not what the software is doing.
 * "Analysis unavailable" tells somebody nothing they can act on; that the
 * publish will still refuse what the panel would have caught tells them
 * whether to keep working.
 */
export function assistDetail(state: AssistState): string {
  switch (state) {
    case "loading":
      return "The code editor is still loading.";
    case "working":
      return "Checking this working set for problems.";
    case "ready":
      return "Problems and Preview have an answer for this working set.";
    case "unavailable":
      return (
        "Problems could not be checked. You can still edit and commit — the " +
        "publish refuses the same things this panel reports, so nothing gets " +
        "through that would not have."
      );
    default:
      return (
        "Nothing is being analysed. Unlike Foundry's Code Assist this runs " +
        "when you open Problems or Preview rather than continuously, so the " +
        "editor is not watching you type."
      );
  }
}

/** Whether the assist indicator should read as a problem. */
export function assistIsAProblem(state: AssistState): boolean {
  return state === "unavailable";
}

/**
 * p.15's Problems indicator, "on the left side of the status bar".
 *
 * **Silent until something has been asked**, because zero problems and never
 * having looked are the same number and one of them is a claim this platform
 * cannot make: Problems is a round trip, so before it has run "0 problems" is
 * not a fact, it is an absence of one — and it is the one somebody would rely
 * on before committing.
 */
export function problemsLabel(count: number | undefined): string | null {
  if (count === undefined) return null;
  if (count === 0) return "No problems";
  return count === 1 ? "1 problem" : `${count} problems`;
}

export function problemsAreAProblem(count: number | undefined): boolean {
  return count !== undefined && count > 0;
}

/**
 * p.15's Checks status, "displayed on the right side of the status bar".
 *
 * `verdict` from `branch-checks.ts` is what decides; this only puts a word to
 * it. The two must not drift, and §296 is why that is said out loud: a second
 * answer to "did the checks pass" is how a branch ends up green on one screen
 * and red on another.
 */
export function checksLabel(checks: RepositoryCheck[] | undefined): string | null {
  if (checks === undefined) return null;
  switch (verdict(checks)) {
    case "failing":
      return "Checks failing";
    case "warning":
      return "Checks warning";
    case "passing":
      return "Checks passed";
    case "unknown":
      return "Checks incomplete";
    default:
      return "No checks";
  }
}

/**
 * **"Not run" is never a tick**, the fourth screen this session to need the
 * sentence and the one most likely to be glanced at rather than read.
 */
export function checksAreAProblem(checks: RepositoryCheck[] | undefined): boolean {
  if (checks === undefined) return false;
  const said = verdict(checks);
  return said === "failing" || said === "unknown";
}

/**
 * p.15's File saving: "after any change, the file saving status displays".
 *
 * **The dangerous misreading is the one this wording exists to prevent.**
 * Foundry's editor saves to the branch; ours keeps drafts in `localStorage`
 * (§281) and nothing reaches the repository until somebody commits. A bar
 * saying "Saved" would let somebody shut the laptop believing their work is in
 * the repository, and it would be *true* in the sense the word usually carries
 * and false in the sense that matters.
 *
 * So the word is never "Saved" on its own: it says where.
 */
export function savingLabel(changedFiles: number, warning: string | null): string {
  if (warning) return "Not kept";
  if (changedFiles === 0) return "Nothing uncommitted";
  const files = changedFiles === 1 ? "1 file" : `${changedFiles} files`;
  return `${files} kept in this browser`;
}

export function savingIsAProblem(warning: string | null): boolean {
  return warning !== null;
}

/**
 * The hover for the saving indicator.
 *
 * The warning when there is one — `editor-drafts.ts` already phrases both of
 * those, and rewording them here would be two sentences about one condition.
 */
export function savingDetail(changedFiles: number, warning: string | null): string {
  if (warning) return warning;
  if (changedFiles === 0) return "Everything here is committed.";
  return (
    "Kept in this browser so a reload does not lose them. They are not in the " +
    "repository until you commit."
  );
}
