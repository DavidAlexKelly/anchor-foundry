/**
 * Opening a link's far side in the Object Explorer (Foundry `object-views`
 * p.11: "Open a subset of linked objects in a new tab for further
 * exploration").
 *
 * **A link is a derived join, so the subset is a filter.** Migration 0027
 * stores no edges: a link type names two properties, and the linked objects
 * are the ones whose far property equals this object's near value. That makes
 * "these linked objects" expressible in the Explorer's own vocabulary —
 * `type` + `property` + `value` — with no new query capability anywhere, and
 * it is why this unit is a URL rather than an endpoint.
 *
 * The far property may be the reserved primary-key reference rather than a
 * real property, and the Explorer already understands it: the explore route
 * maps the sentinel to "the instance's key, not one of its properties", the
 * same reading `find_by_property` and §155's object-set filters use. So the
 * sentinel is passed through untouched rather than special-cased here — a
 * second spelling of it would be a second thing to keep in step.
 */

import type { LinkedInstances } from "@/lib/types";

/**
 * Where to send a reader who wants this link group's objects on their own.
 *
 * `null` when the object has no value on the near property, so the link points
 * at nothing. A URL there would filter on `undefined` and return an empty
 * page — a link that looks like it worked.
 *
 * A link type with no join at all cannot arrive here: the instance-links
 * endpoint returns only traversable links, which is why `far_property` is a
 * plain `string` on `LinkedInstances` rather than a nullable one. Guarding it
 * anyway would be a branch no test could reach, which is this repo's own
 * definition of a check that is not a check.
 */
export function linkSubsetHref(
  workspaceSlug: string,
  group: Pick<LinkedInstances, "far_type_id" | "far_property" | "matched_value">,
): string | null {
  if (group.matched_value === null || group.matched_value === undefined) return null;
  const params = new URLSearchParams({
    type: group.far_type_id,
    property: group.far_property,
    // `String` rather than a JSON encoding: the join is text-to-text
    // (`instance_store.join_key`), and the Explorer's filter compares text.
    // Anything else here would disagree with the comparison it feeds.
    value: String(group.matched_value),
  });
  return `/${workspaceSlug}/explore?${params.toString()}`;
}
