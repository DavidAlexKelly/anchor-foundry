/**
 * What of an object may be shown, and in what order (Foundry
 * `object-link-types` p.111; `object-views` p.10–11).
 *
 * > "Normal properties are displayed in a regular table, and hidden properties
 * > are not visible." (`object-views` p.10)
 *
 * **One rule, three surfaces.** The standard Object View honoured visibility
 * from the day it existed (§121–§122) and the Object Explorer honours it in
 * its columns — but the Linked objects component did not: its one-line summary
 * read straight off `instance.properties`, so a property somebody marked
 * hidden appeared next to every linked object that had one. A second copy of
 * "which properties may I draw" is how that happens, so there is one copy now
 * and it is here.
 *
 * Pure on purpose: `apps/web/src/components/canvas/pure.ts` draws the boundary
 * and the reason applies exactly — a rule about what may be *shown* is worth a
 * test that can make it fail, and a rule tangled into a component is not.
 */

import type { ObjectTypeProperty } from "@/lib/types";

/** The properties a reader may see, split the way p.10 splits them.
 *
 * Declaration order within each group, which is the object type's own — a view
 * that re-sorted would disagree with the Ontology Manager about what the type
 * looks like.
 */
export function visibleProperties(properties: ObjectTypeProperty[]): {
  prominent: ObjectTypeProperty[];
  normal: ObjectTypeProperty[];
} {
  const visible = properties.filter((p) => p.visibility !== "hidden");
  return {
    prominent: visible.filter((p) => p.visibility === "prominent"),
    normal: visible.filter((p) => p.visibility !== "prominent"),
  };
}

/** A one-line summary of an instance, for a row somebody might click.
 *
 * **Prominent first, hidden never.** Prominent is the object type saying "this
 * is what identifies one of these" (p.10), which is exactly the question a
 * one-line summary asks — so a type that marks `name` prominent gets `name` in
 * its link rows rather than whichever three properties happened to be declared
 * first.
 *
 * `properties` is the *type's* declaration, not the instance's keys: an
 * instance can carry a key the type no longer declares (§38 makes that
 * possible, and the note in `STATUS.md` about orphaned keys says why it is
 * left alone), and a summary that read the instance would show it.
 */
export function summarise(
  instance: { properties: Record<string, unknown> },
  properties: ObjectTypeProperty[],
  limit = 3,
): string {
  const { prominent, normal } = visibleProperties(properties);
  const parts: string[] = [];
  for (const property of [...prominent, ...normal]) {
    if (parts.length >= limit) break;
    const value = instance.properties[property.api_name];
    if (value === null || value === undefined || String(value) === "") continue;
    parts.push(`${property.display_name || property.api_name}: ${String(value)}`);
  }
  return parts.join(" · ");
}
