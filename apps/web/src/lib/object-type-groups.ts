/**
 * Object type groups, as a form needs them (Foundry `object-link-types`
 * p.261-263).
 *
 * The server owns everything that matters and is tested in
 * `apps/api/tests/test_object_type_groups.py`. What lives here is the one
 * decision a *screen* has to make about groups, and it is a decision about
 * whether to write at all.
 *
 * Why "did this change?" is a function with its own tests
 * ------------------------------------------------------
 * Membership is its own resource with its own verb — deliberately, so that an
 * object type's PATCH cannot carry it (see `api.setGroupsForObjectType`). But
 * the edit dialog holds both, and if it PUT the groups on every save it would
 * reintroduce the same failure one layer up: somebody opens the dialog, a
 * colleague files the type under a new group, the first person changes a
 * description and saves, and the grouping is gone. **This repo has met that
 * shape seven times** (§157, §160, §163, §164, §165, §169, §171), and the way
 * out here is not to carry the value more carefully — it is to send nothing
 * when nothing changed.
 *
 * That makes `sameSelection` load-bearing, and wrong in either direction is
 * silent: always-true drops edits somebody made, always-false reintroduces the
 * clobber. Hence a pure function and a test file, rather than an inline
 * `JSON.stringify` comparison that would also depend on the order two
 * different endpoints happen to return.
 */

import type { ObjectTypeGroupRef } from "@/lib/types";

/** Whether two group selections are the same set, ignoring order.
 *
 * Order-insensitive because the two sides come from different places: one is
 * what the server returned (sorted by display name) and the other is whatever
 * order somebody ticked boxes in. A comparison that cared would report a
 * change on every save and undo the point of asking.
 */
export function sameSelection(a: readonly string[], b: readonly string[]): boolean {
  if (a.length !== b.length) return false;
  const left = new Set(a);
  // Compared through the set rather than by sorting both: a duplicate in one
  // side would survive a sort-and-zip as a real difference, and a list naming
  // the same group twice is the same request as naming it once.
  if (left.size !== new Set(b).size) return false;
  return b.every((id) => left.has(id));
}

/** Toggle one group in a selection, without mutating what it was given. */
export function toggleSelection(
  selection: readonly string[],
  groupId: string,
): string[] {
  return selection.includes(groupId)
    ? selection.filter((id) => id !== groupId)
    : [...selection, groupId];
}

/** The object types a membership editor draws: this group's members first,
 * then whatever else the current page holds.
 *
 * **The invariant is that a member is always on screen.** §256 bounded the
 * type listing, so the editor's page may not reach a member — and a ticked box
 * that is not drawn is a membership somebody cannot remove and a group that
 * reads as smaller than it is. The same rule `type-picker.withSelected` keeps
 * for a single choice, applied to a set of them.
 *
 * Members come from the group's own read rather than from the page, because
 * that is the read that knows all of them. `current` is the *unsaved*
 * selection, so a type ticked and then searched away stays visible too — the
 * alternative is a tick that disappears while somebody is still deciding.
 */
export function memberFirst<T extends { id: string }>(
  page: readonly T[],
  members: readonly T[],
  current: readonly string[],
): T[] {
  const pinned = members.filter((m) => current.includes(m.id));
  const seen = new Set(pinned.map((m) => m.id));
  const rest = page.filter((t) => !seen.has(t.id));
  // Anything ticked this session that is neither a saved member nor on the
  // page has to come from the page it was ticked on, which is gone. Nothing
  // can draw it, so it is not drawn - and it is still saved, because `current`
  // is what the save writes.
  return [...pinned, ...rest];
}

/** What a row says about the groups a type is in, when there is no room to
 * draw them all.
 *
 * Returns null for none rather than "0 groups": an ungrouped object type is
 * the ordinary case (p.261 makes grouping a thing somebody does, not a thing
 * every type has), and labelling every row with its absence would be noise on
 * the majority of an ontology.
 */
export function groupSummary(
  groups: readonly ObjectTypeGroupRef[],
  limit = 2,
): string | null {
  if (!groups.length) return null;
  const names = groups.slice(0, limit).map((g) => g.display_name);
  const rest = groups.length - names.length;
  return rest > 0 ? `${names.join(", ")} +${rest}` : names.join(", ");
}

/** The api_name suggested for a display name, in this ontology's shape.
 *
 * Offered on create only: p.262 makes the api_name what search matches on, so
 * renaming one would move a group out from under a saved query.
 */
export function toGroupApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

/** How a group's size reads on its own row.
 *
 * **Zero is a number, not an absence.** p.263 makes a group discoverable
 * whether or not it has members — "all groups will now be discoverable to any
 * user that can view the ontology" — so an empty group is a group, and a
 * listing that said nothing for zero would be hinting at the behaviour p.263
 * describes having removed.
 */
export function memberSummary(count: number): string {
  return `${count} object type${count === 1 ? "" : "s"}`;
}
