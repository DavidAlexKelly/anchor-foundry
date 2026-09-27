/** Tags on resources (§511; db 0105; `dataset-preview` p.3, `app-building` p.35).
 *
 * Not `lib/tags.ts`, which is a repository's git tags.
 *
 * > "You can create and manage tags from the Tags section of Platform
 * > Settings. Once they are created, they can be added … in the filesystem."
 * > (`app-building` p.35)
 *
 * The rules are the API's (`services/resource_tags.py`); this is how the tags
 * page and a resource's Details say them.
 */

export type Tag = { id: string; category: string; name: string; created_at: string };
export type TagUsage = Tag & { uses: number };

/** "Sensitivity: PII", or the name alone for a tag with no category. */
export function tagLabel(tag: Pick<Tag, "category" | "name">): string {
  return tag.category ? `${tag.category}: ${tag.name}` : tag.name;
}

/** Tags in their categories, in the order given (the API sorts them), with
 * the uncategorised ones as a group of their own called "". */
export function byCategory<T extends Pick<Tag, "category">>(tags: T[]): { category: string; tags: T[] }[] {
  const groups: { category: string; tags: T[] }[] = [];
  for (const tag of tags) {
    const last = groups[groups.length - 1];
    if (last && last.category === tag.category) last.tags.push(tag);
    else groups.push({ category: tag.category, tags: [tag] });
  }
  return groups;
}

/** The tags a resource does not carry yet: what "Add a tag" offers. */
export function addable<T extends Pick<Tag, "id">>(all: T[], on: Pick<Tag, "id">[]): T[] {
  const have = new Set(on.map((t) => t.id));
  return all.filter((t) => !have.has(t.id));
}

/** How many resources carry a tag, as a phrase. */
export function usesText(uses: number): string {
  return uses === 0 ? "not used yet" : `on ${uses} resource${uses === 1 ? "" : "s"}`;
}
