/**
 * p.255's proposal to promote an object type, as a screen needs it (§767).
 *
 * > "Only users with the `Ontology Owner` role on the ontology level can
 * > directly apply the `promoted` status. Other users must submit a proposal
 * > for review and approval by an `Ontology Owner`." (p.255)
 *
 * The server refuses each case this does not offer; this decides what to
 * draw, so the editor shows the proposal exactly where the status field
 * leaves `promoted` out.
 */

import type { OntologyStatus, PromotionRequest } from "@/lib/types";

/** The proposal waiting for an answer about this type, if there is one. */
export function pendingFor(
  requests: PromotionRequest[],
  typeId: string,
): PromotionRequest | null {
  return requests.find((r) => r.object_type_id === typeId && r.state === "pending") ?? null;
}

/** What the object type's editor offers in place of `promoted`:
 * - `"none"` when the caller may promote it (an admin), or it already is;
 * - `"waiting"` while a proposal is pending;
 * - `"ask"` otherwise. */
export function promotionOffer(
  status: OntologyStatus,
  canPromote: boolean,
  pending: PromotionRequest | null,
): "none" | "waiting" | "ask" {
  if (canPromote || status === "promoted") return "none";
  return pending ? "waiting" : "ask";
}

/** A pending proposal in one line: who asked, and why if they said. */
export function requestLine(request: PromotionRequest): string {
  const who = request.requested_by_name || "Somebody";
  const why = request.reason.trim();
  return why ? `${who} asked: ${why}` : `${who} asked, giving no reason.`;
}
