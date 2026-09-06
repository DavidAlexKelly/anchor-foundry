/**
 * The browser's half of interfaces (Foundry `object-link-types` p.4, p.53;
 * `ontology` p.60–62).
 *
 * Pure, and separate from the panel, for the reason every `lib/` module here
 * is: the server owns what is **legal**, this owns what is **offered**, and
 * only the second is testable without a database.
 *
 * The division matters more than usual for the implement dialog. The server's
 * `check_implementation` has four refusals, and three of them the dialog can
 * make *unreachable by construction* rather than duplicate:
 *
 * | server refuses                     | dialog's answer                        |
 * | ---------------------------------- | -------------------------------------- |
 * | a property the interface never declared | there is a row per declared property and no way to add one |
 * | a mapping to a property the type lacks  | the select offers the type's own properties only |
 * | a base type that does not match         | it offers only those whose type matches |
 * | a **required** property mapped to nothing | {@link unmappedRequired} gates Save    |
 *
 * So exactly one rule is stated twice, and it is the one a person needs
 * answered before they click rather than after. The other three are absent
 * here because a control that cannot produce a bad request does not need to
 * check for one (§213).
 */

import type {
  InterfaceProperty,
  InterfaceSummary,
  PropertyDataType,
} from "./types";

/** An interface is named like an object type, not like a property: p.60's
 * examples are `Inspectable`, `SchedulableResource`, `MilitaryAsset`. The
 * server's rule is `^[A-Za-z][A-Za-z0-9_]{0,99}$` — the same one
 * `object_types.api_name` has, so the two read alike in the one place they
 * appear side by side. */
export function toInterfaceApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  const joined = words
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join("")
    .slice(0, 100);
  // A name starting with a digit is the one thing capitalising cannot fix,
  // and "3D Asset" is a name somebody types.
  return /^[A-Za-z]/.test(joined) ? joined : "";
}

/** A property's machine name is a property's machine name, interface or not:
 * `^[a-z][a-z0-9_]{0,99}$`, matching `object_type_properties`. */
export function toPropertyApiName(display: string): string {
  const words = display.match(/[A-Za-z0-9]+/g) ?? [];
  const joined = words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
  return /^[a-z]/.test(joined) ? joined : "";
}

/** Base types an interface property may not have, and why there is exactly
 * one of them.
 *
 * `struct` (§245) is a base type whose *fields* are the whole of what it
 * promises, and `check_implementation` compares base types only — so an
 * interface declaring `address` as a struct would be satisfied by any struct
 * at all, including one with none of the same fields. That is a promise
 * nothing enforces, which is the thing this whole resource exists to avoid, so
 * the option is absent rather than misleading (§214).
 *
 * Deliberately a subtraction from `PROPERTY_TYPES` rather than a list of its
 * own: a base type added there should appear here the same day unless somebody
 * writes down why not. */
export const NOT_INTERFACE_TYPES: string[] = ["struct"];

export function interfacePropertyTypes(
  all: PropertyDataType[],
): PropertyDataType[] {
  return all.filter((t) => !NOT_INTERFACE_TYPES.includes(t));
}

export interface DraftProperty {
  api_name: string;
  display_name: string;
  description: string;
  data_type: PropertyDataType;
  required: boolean;
}

export function blankProperty(): DraftProperty {
  return {
    api_name: "",
    display_name: "",
    description: "",
    data_type: "string",
    // Required by default, matching the server's `InterfacePropertyIn`: the
    // direction that cannot silently weaken a promise.
    required: true,
  };
}

/** What is wrong with a draft interface, as one sentence, or null.
 *
 * Named for the person rather than the wire — "two properties are both called
 * status" is what they can act on, and the server's version of the same
 * refusal arrives after a round trip they did not need to make. Every case
 * here is also refused by the server; none of them is *only* refused here. */
export function draftProblem(draft: {
  display_name: string;
  api_name: string;
  properties: DraftProperty[];
}): string | null {
  if (!draft.display_name.trim()) return "An interface needs a name.";
  if (!/^[A-Za-z][A-Za-z0-9_]{0,99}$/.test(draft.api_name)) {
    return "An API name must start with a letter and hold letters, digits and underscores.";
  }
  const seen = new Set<string>();
  for (const p of draft.properties) {
    if (!p.api_name) return "Every property needs a name.";
    if (!/^[a-z][a-z0-9_]{0,99}$/.test(p.api_name)) {
      return `${p.api_name} must start with a lowercase letter and hold lowercase letters, digits and underscores.`;
    }
    if (seen.has(p.api_name)) return `Two properties are both called ${p.api_name}.`;
    seen.add(p.api_name);
  }
  return null;
}

/** Which interfaces to offer as parents of `selfId`.
 *
 * **Self only**, and that is a deliberate stopping point rather than a partial
 * job. p.53 allows any number of parents and the server refuses cycles by
 * walking the graph — naming the path it followed. The browser holds a list of
 * summaries, not the graph, so excluding `B` because `B extends A` would mean
 * fetching every interface's detail to draw one select, and then keeping a
 * second copy of the traversal in step with the first (§191's problem, taken
 * on voluntarily). Extending oneself is the one cycle this list can see, it is
 * the one most likely to be clicked by accident, and the rest arrive as the
 * server's sentence with the path in it.
 *
 * `undefined` for a new interface, which has no id to exclude. */
export function extendable(
  all: InterfaceSummary[],
  selfId: string | undefined,
): InterfaceSummary[] {
  return all.filter((i) => i.id !== selfId);
}

/** The dialog's opening mapping: an interface property is matched to the
 * object type's property of the same name when there is one and its base type
 * agrees.
 *
 * A suggestion, not a rule — p.66's mapping exists precisely because names
 * need not agree, and p.60's argument is that types satisfy one interface
 * while differing in everything else. But a Vehicle whose column really is
 * called `last_inspection_date` should not have to say so by hand, and an
 * offered default that the person can overwrite costs nothing. Names that
 * match with the **wrong type** are deliberately not suggested: that is the
 * case where agreeing names are a coincidence, and filling it in would turn a
 * question into a refusal. */
export function suggestMapping(
  effective: InterfaceProperty[],
  propertyTypes: Record<string, string>,
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of effective) {
    if (propertyTypes[p.api_name] === p.data_type) out[p.api_name] = p.api_name;
  }
  return out;
}

/** Which of the object type's properties may be mapped to `property`: those
 * whose base type is the one the interface declared.
 *
 * This is the whole of the server's base-type refusal, spent on the options
 * rather than on the answer. */
export function candidates(
  property: InterfaceProperty,
  propertyTypes: Record<string, string>,
): string[] {
  return Object.keys(propertyTypes)
    .filter((name) => propertyTypes[name] === property.data_type)
    .sort();
}

/** The required properties with nothing mapped to them, in declaration order.
 *
 * The one rule stated on both sides. An empty list is not a promise the save
 * will succeed — the interface could have been edited since this list was
 * fetched, and the server is the one that decides — it is a promise that
 * *this* refusal is not the one waiting. */
export function unmappedRequired(
  effective: InterfaceProperty[],
  mapping: Record<string, string>,
): string[] {
  return effective
    .filter((p) => p.required && !mapping[p.api_name])
    .map((p) => p.api_name);
}

/** How an interface's row reads when it has no implementations.
 *
 * Its own function because the sentence is the point: p.61's whole argument
 * for modelling `Inspectable` is that you can then look at Vehicle, Equipment
 * and Facility together, and an interface nothing implements has not yet done
 * the thing it was created to do. Saying "0" would report that as a number
 * instead of as the next step. */
export function implementationLabel(count: number): string {
  if (count === 0) return "Nothing yet";
  return count === 1 ? "1 object type" : `${count} object types`;
}
