/**
 * Renaming a dataset, from the browser's side (§435; `dataset-preview` p.2).
 *
 * > "The header also allows some file related operations such as sharing,
 * > moving, renaming, and more."
 *
 * **A subset of the server's rules, stated early and re-decided every time**
 * (§191). The server owns whether a name may be taken — it is the only thing
 * that can know whether another dataset already has it — and this owns what to
 * offer. Nothing here is a second authority: every refusal below is one the
 * `PATCH` makes too, and the button asking first only means somebody finds out
 * before the round trip rather than after it.
 */

/** `datasets.name` is `text CHECK (length BETWEEN 1 AND 200)` (db 0003). */
export const MAX_NAME = 200;

/**
 * Why this rename cannot be asked for, or `null` when it can.
 *
 * **"Unchanged" is a refusal rather than a no-op.** A Rename button that was
 * live on a name nobody had touched would send a request that changes nothing
 * and report success, which teaches a reader that the button does nothing.
 */
export function renameProblem(current: string, next: string): string | null {
  const wanted = next.trim();
  if (wanted === "") return "A dataset needs a name.";
  if (wanted === current) return "That is already its name.";
  if (wanted.length > MAX_NAME) {
    return `A name is at most ${MAX_NAME} characters; this is ${wanted.length}.`;
  }
  return null;
}

/** What to send. Trimmed, because a trailing space is invisible on a screen
 *  and very visible in a `-- input:` line that has to match it exactly. */
export function nameToSend(next: string): string {
  return next.trim();
}

/**
 * What the screen says about a rename that nothing would break.
 *
 * **Silence would be worse than a sentence.** A warning that appears only
 * sometimes is one a reader learns to look for; its absence has to mean
 * something too, and "nothing declares this dataset by name" is the thing they
 * came to find out.
 */
export const NOTHING_NAMES_IT =
  "No transform declares this dataset by name, so renaming it breaks nothing.";

/** Where the file that names this dataset lives, as a link. */
export function fileHref(reference: {
  resource_id: string;
  branch: string;
  path: string;
}): string {
  return (
    `/r/${reference.resource_id}?tab=files`
    + `&branch=${encodeURIComponent(reference.branch)}`
    + `&file=${encodeURIComponent(reference.path)}`
  );
}
