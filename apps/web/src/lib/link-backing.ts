/**
 * p.197's backing object type, as the link-type dialogs hold one, and the
 * backing objects the Links panel shows (§667; §666 on the server).
 *
 * > "Backing object type: Object-backed link types expand on many-to-one
 * > cardinality link types, providing first class support for object types as
 * > a link type storage solution." (p.197)
 * >
 * > "Select a link to view the link's backing object properties." (p.199)
 *
 * The server checks the definition (`ontology._normalise_backing`); the form
 * checks it first so its Save button says why it is off. Pure, so the rules
 * are tested without a dialog.
 */

import type { LinkType, ObjectInstance } from "@platform/types";

const PRIMARY_KEY = "$primary_key";

export interface BackingDraft {
  type: string;
  fromLink: string;
  toLink: string;
}

export const NO_BACKING: BackingDraft = { type: "", fromLink: "", toLink: "" };

/** The backing a link already has, for the dialog that edits its join. */
export function backingDraftOf(
  link: Pick<LinkType, "backing_type_id" | "backing_from_link_id" | "backing_to_link_id">,
): BackingDraft {
  return { type: link.backing_type_id ?? "", fromLink: link.backing_from_link_id ?? "",
    toLink: link.backing_to_link_id ?? "" };
}

/** p.199's prerequisite link from the backing type to one end: the links
 * that join that end and the backing type on a pair of properties - the
 * server's `link_backing.side`. */
export function backingLinksFor(
  links: readonly LinkType[], endTypeId: string, backingTypeId: string,
): LinkType[] {
  if (!endTypeId || !backingTypeId) return [];
  return links.filter((l) => !!l.from_property && !!l.to_property && (
    (l.from_object_type_id === backingTypeId && l.to_object_type_id === endTypeId)
    || (l.from_object_type_id === endTypeId && l.to_object_type_id === backingTypeId)));
}

/** Why this backing cannot be saved, or null when it can. */
export function backingProblem(draft: BackingDraft, fromTypeId: string, toTypeId: string): string | null {
  if (!draft.type) return "Choose the backing object type.";
  if (draft.type === fromTypeId || draft.type === toTypeId) {
    return "The backing object type is a third type, between the link's two ends.";
  }
  if (!draft.fromLink || !draft.toLink) return "Choose the link from the backing type to each end.";
  if (draft.fromLink === draft.toLink) return "Each end needs its own link to the backing type.";
  return null;
}

/** The request's fields: all three, or all null to clear a backing. */
export function backingPayload(draft: BackingDraft | null): {
  backing_type_id: string | null; backing_from_link_id: string | null; backing_to_link_id: string | null;
} {
  const chosen = !!(draft && draft.type && draft.fromLink && draft.toLink);
  return {
    backing_type_id: chosen ? draft!.type : null,
    backing_from_link_id: chosen ? draft!.fromLink : null,
    backing_to_link_id: chosen ? draft!.toLink : null,
  };
}

/** What the link table says a backed link joins on; null for a link that is
 * not backed. */
export function backingDescription(
  link: Pick<LinkType, "backing_type_id" | "backing_display_name" | "backing_from_link_id" | "backing_to_link_id">,
): string | null {
  if (!link.backing_type_id) return null;
  if (!link.backing_from_link_id || !link.backing_to_link_id) {
    // db 0132: a backing link was deleted and the backing type kept.
    return "not traversable - a backing link was deleted";
  }
  return `backed by ${link.backing_display_name ?? "an object type"}`;
}

function valueOf(o: ObjectInstance, property: string): string {
  const raw = property === PRIMARY_KEY ? o.primary_key : o.properties[property];
  return raw === null || raw === undefined ? "" : String(raw);
}

/** The backing objects linking to one far object: those whose far property
 * holds the far object's value of the link's far property - each is one
 * link, and its properties are what is known about it. */
export function backingFor(
  group: { far_property: string; backing_far_property?: string | null; backing_items?: ObjectInstance[] },
  item: ObjectInstance,
): ObjectInstance[] {
  if (!group.backing_far_property || !group.backing_items) return [];
  const wanted = valueOf(item, group.far_property);
  return wanted === "" ? [] : group.backing_items.filter((m) => valueOf(m, group.backing_far_property!) === wanted);
}
