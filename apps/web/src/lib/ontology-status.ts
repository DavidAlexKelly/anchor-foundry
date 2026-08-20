/**
 * Ontology resource statuses, as a form needs them (Foundry
 * `object-link-types` p.253–259).
 *
 * **The server is authoritative and this cannot widen it.** `check_deletable`
 * refuses the delete, `link_status` caps what a link may hold, and
 * `propagate_to_properties` demotes a type's properties — all in
 * `services/ontology_status.py`, all enforced whatever the browser believes.
 * What lives here is what a screen has to say *before* somebody acts:
 *
 * * which statuses may be offered at all (p.255 makes `promoted` object-types
 *   only, so offering it on a property is offering a save that fails);
 * * whether Delete is going to be refused, so the button can say so rather
 *   than the response;
 * * what a status change is about to do to everything underneath it, because
 *   p.256's propagation is invisible until it has already happened.
 *
 * That last one is the reason this file exists rather than a `<select>` with
 * five options in it. Demoting an object type silently demotes every property
 * on it; a form that does not warn is a form where somebody discovers the
 * change by re-reading a page they thought they understood.
 */

import type { OntologyStatus } from "@/lib/types";

/** p.254's five, ordered as `services/ontology_status.STATUSES` orders them:
 * increasing "applications may rely on this". The order is what `weakest`
 * means, and it is duplicated deliberately — see `weakest` below. */
export const STATUSES: OntologyStatus[] = [
  "deprecated", "example", "experimental", "active", "promoted",
];

export const STATUS_LABELS: Record<OntologyStatus, string> = {
  promoted: "Promoted",
  active: "Active",
  experimental: "Experimental",
  deprecated: "Deprecated",
  example: "Example",
};

/** p.254's own descriptions, shortened to what changes somebody's decision. */
export const STATUS_HINTS: Record<OntologyStatus, string> = {
  promoted: "A core, vetted resource. Cannot be deleted.",
  active: "In use by applications. Cannot be deleted.",
  experimental: "Still being built. The default for anything new.",
  deprecated: "Due to be removed. Should not be relied on.",
  example: "Notional — for training, not production.",
};

/** p.256: "A resource's status must be `experimental` or `deprecated` before
 * it can be deleted." */
export const DELETABLE: OntologyStatus[] = ["experimental", "deprecated"];

/** Which statuses may be offered for this kind of resource.
 *
 * p.255: `promoted` "applies only to object types. It is not available for
 * properties, link types, action types or interfaces." */
export function statusesFor(
  kind: "object_type" | "property" | "link_type",
  /** p.255 also restricts *who* may apply `promoted`: "only users with the
   * `Ontology Owner` role on the ontology level". A workspace is this
   * platform's ontology, so this is workspace admin.
   *
   * **Left on the list when the type is already promoted**, whoever is
   * looking. The server gates the transition rather than the value (§175), so
   * dropping the option from an editor's dropdown would leave the select with
   * no entry matching its own value — which renders as a blank control that
   * silently demotes the type on the next save. */
  { canPromote = true, current }: { canPromote?: boolean; current?: OntologyStatus } = {},
): OntologyStatus[] {
  if (kind !== "object_type") return STATUSES.filter((s) => s !== "promoted");
  if (canPromote || current === "promoted") return STATUSES;
  return STATUSES.filter((s) => s !== "promoted");
}

/** Why `promoted` is not on offer, or null when it is. */
export function promoteBlockedReason(canPromote: boolean): string | null {
  return canPromote
    ? null
    : "Only a workspace admin can promote an object type — ask one, or choose Active.";
}

export function canDelete(status: OntologyStatus): boolean {
  return DELETABLE.includes(status);
}

/** Why Delete is unavailable, as a sentence, or null when it is available.
 *
 * The same words the server uses, because somebody who sees the tooltip and
 * then somehow reaches the refusal should not be told two different things. */
export function deleteBlockedReason(status: OntologyStatus): string | null {
  return canDelete(status)
    ? null
    : `${STATUS_LABELS[status]} resources cannot be deleted — mark it deprecated or experimental first.`;
}

/** A second copy of the server's ordering, and worth being explicit about.
 *
 * `services/ontology_status.weakest` decides what actually gets stored. This
 * one only decides what a warning *says*. Getting it wrong here cannot corrupt
 * anything — it can only mispredict — but a warning that mispredicts is worse
 * than none, so it has its own tests. */
export function weakest(a: OntologyStatus, b: OntologyStatus): OntologyStatus {
  return STATUSES.indexOf(a) <= STATUSES.indexOf(b) ? a : b;
}

/** What changing an object type to `next` will do to its properties (p.256,
 * p.258), as a sentence, or null when nothing will change.
 *
 * **Propagation only lowers**, so this counts the properties that are
 * currently *above* the new status. p.258 makes promoting properties an
 * option rather than a consequence, so raising a type warns about nothing. */
export function propagationWarning(
  next: OntologyStatus,
  properties: { api_name: string; status: OntologyStatus }[],
): string | null {
  const affected = properties.filter((p) => weakest(p.status, next) !== p.status);
  if (!affected.length) return null;
  const names = affected.slice(0, 3).map((p) => p.api_name).join(", ");
  const rest = affected.length > 3 ? `, and ${affected.length - 3} more` : "";
  return (
    `${affected.length} propert${affected.length === 1 ? "y" : "ies"} ` +
    `(${names}${rest}) will also become ${STATUS_LABELS[next].toLowerCase()}.`
  );
}

/** Whether p.254's deprecation note applies. The form shows those fields only
 * here, because the server refuses them anywhere else. */
export function wantsDeprecationNote(status: OntologyStatus): boolean {
  return status === "deprecated";
}
