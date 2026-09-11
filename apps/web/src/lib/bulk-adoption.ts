/**
 * Moving several transforms into a repository at once (§289).
 *
 * **This is what a change set becomes.** Decision 0001 called the change set
 * "the one genuinely new concept" — *"these three transforms changed together,
 * for one reason"* — and B.1 deletes the only screen that can make one. A
 * commit says the same thing about a repository's files, so the successor to a
 * change set over directly-authored transforms is: adopt them together, then
 * commit together.
 *
 * That successor is only real if adopting is *together*. Six adoptions are six
 * commits and six unrelated moves in the history, and a migration that takes
 * six clicks per transform is one a project with forty of them will not do —
 * which would strand them in practice even though nothing refused.
 *
 * The server owns every refusal (`transform_adoption.adopt_many`); what lives
 * here is what to *offer*, which is the division `model-authoring.ts` and
 * `protected-branches.ts` already take.
 */
import type { Model } from "./types";
import { canAdopt } from "./model-authoring";

/**
 * Which of these can be moved.
 *
 * **A transform already authored in a repository is not offered**, rather than
 * offered and refused. `canAdopt` is the same predicate the per-row button
 * uses, so the two cannot disagree about what is movable — a checkbox that
 * appeared where the button did not would be a difference nobody could explain.
 */
export function movable(models: Model[]): Model[] {
  return models.filter(canAdopt);
}

/**
 * The chosen models, in the order they are listed rather than the order they
 * were ticked.
 *
 * Ticking order is invisible on screen, so a confirmation that listed them
 * that way would name the same set differently every time — and the commit
 * message is built from this.
 */
export function chosen(models: Model[], selected: Set<string>): Model[] {
  return movable(models).filter((m) => selected.has(m.id));
}

/**
 * Whether the move can be asked for at all.
 *
 * A repository has to be named: there is no sensible default when a project
 * has several, and picking the first would put files somewhere nobody chose.
 */
export function canMove(count: number, repositoryId: string): boolean {
  return count > 0 && repositoryId !== "";
}

/**
 * What the button says, so the count is on the control rather than beside it.
 *
 * "Move" and "Move 12 transforms" are different promises, and the second is
 * the one a person checks before pressing.
 */
export function moveLabel(count: number): string {
  if (count === 0) return "Move into a repository";
  return `Move ${count} transform${count === 1 ? "" : "s"} into a repository`;
}

/**
 * The default commit message, matching what the server would derive.
 *
 * **Shown, not sent.** The field is prefilled so somebody can see what will be
 * recorded and change it; leaving it untouched sends nothing, and the server
 * derives the same sentence. A browser that *sent* its own version would be a
 * second implementation of the rule, and the two would drift the first time
 * either was improved — so this exists to be read, and its agreement with the
 * server is a test rather than a mechanism.
 */
export function defaultMessage(names: string[]): string {
  if (names.length === 0) return "";
  if (names.length === 1) return `Move ${names[0]} into this repository`;
  if (names.length <= 3) return `Move ${names.join(", ")} into this repository`;
  return `Move ${names.slice(0, 3).join(", ")} and ${names.length - 3} more into this repository`;
}

/**
 * What to say when nothing can be moved.
 *
 * Three different reasons, and only one of them is a reason to go and do
 * something else — the same shape §276's empty Pull requests tab takes.
 */
export function emptyReason(total: number, movableCount: number): string {
  if (total === 0) return "No transforms in this project yet.";
  if (movableCount === 0) {
    return "Every transform here is already authored in a repository.";
  }
  return "Choose the transforms to move.";
}
