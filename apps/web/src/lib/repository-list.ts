/**
 * The Code pillar, as a list of repositories (§291).
 *
 * **B.1's deletion, and the hole it exposed.** `code/page.tsx` opened with
 * *"There is no 'new repository' button, and its absence is the design"* —
 * true when decision 0001 made the pillar a view over `model_versions`, and
 * false since §94 gave the project real `code_repos`. Grepping for the create
 * call turns up nothing in `apps/web` at all: **a repository can only be made
 * by calling the API directly**, and none can be listed anywhere, so the whole
 * repository application is reachable only by a `/r/{id}` link somebody
 * already has.
 *
 * §275's adopt dialog had already been caught out by it — "Create one on the
 * Code screen, then move this transform into it" names a screen with no such
 * control. That sentence is the same shape §290 found in the Pull requests
 * tab: a pointer at a place that cannot do what it says, and no test can
 * notice because every test of it asserts its wording.
 *
 * So the pillar becomes what it should have been: the project's repositories,
 * each opening into the application. The rules here are what to *offer*; the
 * server owns every refusal (`routes/repositories.py`), which is the division
 * `model-authoring.ts`, `protected-branches.ts` and `bulk-adoption.ts` take.
 */
import type { Repository } from "./types";

/**
 * Where a repository opens.
 *
 * **`/r/{resource_id}`, never a slug path**, and that is the whole point of
 * the registry's stable ids (`(app)/r/[resourceId]/page.tsx`): a link built
 * from a workspace and project slug stops working the moment somebody renames
 * either, which is exactly when a shared link is most likely to be clicked.
 * A list that linked by slug would quietly undo that for the one screen that
 * produces most of these links.
 */
export function openHref(repository: Repository): string {
  return `/r/${repository.resource_id}`;
}

/**
 * Whether this role is offered the create form.
 *
 * `POST /repositories` is editor-level, so a viewer's button would be a
 * control that looks like it works — §214's shape. Offered-and-refused is
 * worse than not offered: it teaches people the product is unreliable rather
 * than that they are reading rather than writing.
 */
export function canCreate(role: string): boolean {
  return role === "editor" || role === "owner";
}

/**
 * What an empty list says, which is two different situations with two
 * different remedies — and only one of them is something the reader can do.
 */
export function emptyReason(count: number, role: string): string | null {
  if (count > 0) return null;
  if (canCreate(role)) {
    return (
      "No repositories in this project yet. A repository holds transforms as " +
      "files, with branches, review and history — create one, then move a " +
      "transform into it from the Models screen."
    );
  }
  return (
    "No repositories in this project yet. Creating one needs edit access, so " +
    "ask somebody who has it."
  );
}

/**
 * The line under a repository's name.
 *
 * The **default branch**, because it is the branch the application opens on
 * and the branch protection applies to (§284) — the one fact about a
 * repository that changes what happens when you click it. A description is
 * shown when there is one and nothing is invented when there is not.
 */
export function subtitle(repository: Repository): string {
  const branch = `default branch ${repository.default_branch}`;
  return repository.description ? `${repository.description} · ${branch}` : branch;
}
