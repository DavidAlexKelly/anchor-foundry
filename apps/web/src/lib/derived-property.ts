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

/** p.145's four arithmetic aggregations, which `derived_properties` calls
 * `NUMERIC_AGGREGATES`. They were refused outright until §406, with a hint
 * saying instance properties were stored untyped — true when written, untrue
 * from §220. */
export const NUMERIC_AGGREGATES = ["sum", "avg", "min", "max"];

/** `object_sets.AGGREGATABLE_TYPES`. A date has an order but no arithmetic the
 * two stores agree on, so it is not here. */
const AGGREGATABLE_TYPES = ["integer", "float"];

const AGGREGATE_LABELS: Record<string, string> = {
  sum: "Sum", avg: "Average", min: "Minimum", max: "Maximum",
};

/** Only what the arithmetic rule reads, so a caller can pass an ontology
 * property row or a stub. */
export interface DerivableProperty {
  api_name: string;
  data_type?: string | null;
  display_name?: string | null;
  /** p.169's **native**: a property that is itself derived is not one. */
  derivation?: unknown;
}

function derivable(prop: DerivableProperty): boolean {
  return AGGREGATABLE_TYPES.includes(String(prop.data_type ?? ""))
    && (prop.derivation === null || prop.derivation === undefined);
}

/**
 * The properties an aggregation may run over (p.146, narrowed by p.169).
 *
 * **Two lists, the same split the Metric Card makes.** The four arithmetic
 * aggregations are arithmetic on a stored value, so each needs a declared
 * `integer` or `float`; every other aggregation is a text-identity question
 * and works on anything. p.169's "native" is the second half: a derived
 * property at the far end is itself a chain, so there is no column to push an
 * aggregation into.
 */
export function derivableProperties<T extends DerivableProperty>(
  properties: readonly T[],
  aggregate: string,
): T[] {
  if (!NUMERIC_AGGREGATES.includes(aggregate)) return [...properties];
  return properties.filter(derivable);
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
  /** The properties of the type the chain lands on, for the arithmetic rule
   * below. Omitted by callers that have not read the far type yet, in which
   * case that rule is not checked here — the server still checks it, so the
   * cost is a 422 rather than a bad save. */
  farProperties: readonly DerivableProperty[] = [],
): string | null {
  if (!state.hops.length) return "Choose a link to follow.";
  if (state.reachesMany && !aggregate)
    return "This chain can reach more than one object, so it needs an aggregation.";
  if (aggregate && aggregate !== "count" && !property.trim())
    return "Choose which property of the linked object to derive.";
  if (NUMERIC_AGGREGATES.includes(aggregate) && property.trim() && farProperties.length) {
    // §406's rule, in the one place the answer can still be changed. The
    // picker already narrows the list, so reaching this means a property that
    // was chosen and then invalidated - by switching the aggregation, or by
    // adding a hop that lands somewhere else.
    const chosen = farProperties.find((p) => p.api_name === property.trim());
    if (!chosen || !derivable(chosen)) {
      return `${AGGREGATE_LABELS[aggregate] ?? aggregate} needs a declared `
        + `integer or float on the linked object type's own properties, and `
        + `${property.trim()} is not one.`;
    }
  }
  return null;
}
