/**
 * Building a derived property's link chain (Foundry `object-link-types`
 * p.144–147).
 *
 * > "The dropdown menu shows all available link types from your current object
 * > type. After selecting a link type, you can optionally add additional link
 * > types to traverse multiple levels of connections (up to 3 levels)." (p.145)
 *
 * **A second copy of a server rule, and worth being honest about why.**
 * `services/derived_properties.py` decides what is *legal*; this decides what
 * to *offer*, which is the same walk asked for a different reason. The
 * alternative is an editor that lists every link in the workspace and lets
 * somebody build a chain the save then rejects — the trap `value-format-editor`
 * and `conditional-format-editor` both avoid. The server stays authoritative:
 * nothing here can widen what a save accepts, only narrow what a form suggests.
 *
 * Pure, so the walk can be tested without a browser — which matters more here
 * than usual, because the one thing I got wrong on the server side was the
 * direction of a `one_to_many` hop, and that is exactly the kind of mistake a
 * rendering test cannot see.
 */

import type { LinkType } from "@/lib/types";

/** p.147: "up to 3 levels total". */
export const MAX_HOPS = 3;

/** One link, offered from a particular end. */
export interface Hop {
  link_type_id: string;
  /** Where following it from here lands. */
  far_type_id: string;
  far_type_display_name: string;
  /** What the end being travelled *to* is called (`object-link-types` p.192),
   * so a self-link's two directions read differently. */
  label: string;
  /** Whether following it from here can reach more than one object (p.145). */
  reaches_many: boolean;
}

/**
 * Whether following this link in this direction can reach more than one
 * object.
 *
 * **`one_to_many` is named from the `to` side.** This platform puts the
 * foreign key on the `from` side (db 0027), so many `from` rows point at one
 * `to` row — `works_in` is Person→Department with the department id on the
 * person. The "many" is therefore reached travelling *inbound*. The server got
 * this backwards first (§161) and three tests caught it; this copy is written
 * from the corrected reading, and has its own test for the same reason.
 */
export function reachesMany(
  cardinality: LinkType["cardinality"],
  outbound: boolean,
): boolean {
  if (cardinality === "many_to_many") return true;
  if (cardinality === "one_to_many") return !outbound;
  return false;
}

/**
 * The links that can be followed from `typeId`, each named for the end it
 * lands on.
 *
 * A link touching this type at both ends (a self-link) appears **twice**,
 * because the two directions land somewhere different — the same rule the
 * traversal picker follows (§156).
 *
 * A link with no join is left out entirely: db 0027 allows a link type to be
 * defined and not traversable, and there is nothing to follow along one.
 */
export function hopsFrom(links: LinkType[], typeId: string): Hop[] {
  const out: Hop[] = [];
  for (const link of links) {
    if (!link.from_property || !link.to_property) continue;
    if (link.from_object_type_id === typeId) {
      out.push({
        link_type_id: link.id,
        far_type_id: link.to_object_type_id,
        far_type_display_name: link.to_display_name,
        label: `${link.to_side_name || link.display_name} → ${link.to_display_name}`,
        reaches_many: reachesMany(link.cardinality, true),
      });
    }
    if (link.to_object_type_id === typeId) {
      out.push({
        link_type_id: link.id,
        far_type_id: link.from_object_type_id,
        far_type_display_name: link.from_display_name,
        label: `${link.from_side_name || link.display_name} → ${link.from_display_name}`,
        reaches_many: reachesMany(link.cardinality, false),
      });
    }
  }
  return out;
}

/** A chain being built: the hops chosen so far, in order. */
export interface ChainState {
  hops: Hop[];
  /** Where the chain currently stands — the start type, or the last landing. */
  here: string;
  /** Whether any hop so far can reach more than one object, which is what
   * makes an aggregation compulsory (p.145). */
  reachesMany: boolean;
  /** Whether another hop may be added (p.147). */
  canExtend: boolean;
}

/** Walk the chosen hops from the starting type, reporting where it stands. */
export function chainState(startTypeId: string, hops: Hop[]): ChainState {
  const here = hops.length ? hops[hops.length - 1]!.far_type_id : startTypeId;
  return {
    hops,
    here,
    reachesMany: hops.some((h) => h.reaches_many),
    canExtend: hops.length < MAX_HOPS,
  };
}

/** The rules the save would apply, in the one place the answer can still be
 * changed. Returns the first problem as a sentence, or null.
 *
 * Mirrors `derived_properties.parse`'s refusals — deliberately, and only the
 * ones an editor can put in front of somebody before they press Apply. */
export function derivationProblem(
  state: ChainState,
  aggregate: string,
  property: string,
): string | null {
  if (!state.hops.length) return "Choose a link to follow.";
  if (state.reachesMany && !aggregate)
    return "This chain can reach more than one object, so it needs an aggregation.";
  if (aggregate && aggregate !== "count" && !property.trim())
    return "Choose which property of the linked object to derive.";
  return null;
}
