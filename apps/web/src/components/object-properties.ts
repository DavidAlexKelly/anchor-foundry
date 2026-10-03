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

/** The standard Object View's sections (§725): p.10's split, with p.250's
 * two render hints that are about Object Views taken out of the table.
 *
 * > "Keywords - Enable to highlight this property in its own section when
 * > displaying properties in Object Views." (`object-link-types` p.250)
 *
 * > "Long text - Enable if property values contains a large amount of text.
 * > For example, Object Views will display this property's values in a more
 * > readable format." (p.250)
 *
 * **Prominent first**: a property somebody made prominent already has the
 * view's most visible place, and moving it to a section further down because
 * it also carries a hint would be the hint demoting it. Keywords before Long
 * text, for the same reason - "highlight" is the stronger claim.
 *
 * Separate from `visibleProperties` rather than a change to it: the linked
 * objects' one-line summary reads that split too, and a keyword is no less a
 * thing to summarise an object by.
 */
export function objectViewSections(properties: ObjectTypeProperty[]): {
  prominent: ObjectTypeProperty[];
  keywords: ObjectTypeProperty[];
  long: ObjectTypeProperty[];
  normal: ObjectTypeProperty[];
} {
  const { prominent, normal } = visibleProperties(properties);
  const has = (p: ObjectTypeProperty, hint: string) => (p.render_hints ?? []).includes(hint);
  return {
    prominent,
    keywords: normal.filter((p) => has(p, "keywords")),
    long: normal.filter((p) => !has(p, "keywords") && has(p, "long_text")),
    normal: normal.filter((p) => !has(p, "keywords") && !has(p, "long_text")),
  };
}

/** The property as an Object View formats it (§725). p.249-250's Identifier
 * is "primary keys and foreign keys that have a numerical base type and don't
 * need to be formatted or treated as numbers", and "Object Views won't format
 * the property values as numbers" - so its formatter stands aside there, and
 * the value is shown as it is stored. */
export function asViewed(property: ObjectTypeProperty): ObjectTypeProperty {
  return (property.render_hints ?? []).includes("identifier") && property.value_format
    ? { ...property, value_format: null }
    : property;
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
