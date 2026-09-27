/** Saving a lineage graph over one that exists (§512; `data-lineage` p.12).
 *
 * > "Save / Open: Save your Data Lineage graph and re-open it by clicking on
 * > Open graph." (p.12)
 *
 * A saved graph's name is unique in its project, so saving a revised view
 * under a name already used was a 409, and the only way to revise one was to
 * delete it and save again. Now the dialog notices the name is taken before
 * anything is sent, and offers to replace it instead.
 */

/** The saved graph a typed name would collide with, if any. The server trims
 * the name and compares it exactly, so this does too: "Orders" and "orders"
 * are two graphs. */
export function savedNamed<T extends { name: string }>(saved: T[] | undefined, typed: string): T | null {
  const name = typed.trim();
  if (!name) return null;
  return saved?.find((g) => g.name === name) ?? null;
}

/** What the submit button says. */
export function saveLabel(existing: { name: string } | null): string {
  return existing ? "Replace" : "Save";
}

/** Said before Replace is pressed, since it overwrites a view somebody else in
 * the project may be relying on. */
export function replaceNote(existing: { name: string }): string {
  return `A saved graph called "${existing.name}" already exists. Replacing it keeps the name and `
    + "saves what you are looking at as its view, for everybody in the project.";
}
