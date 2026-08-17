/**
 * Attaching a property to a shared property, as a rule rather than a form
 * (Foundry `object-link-types` p.187–188).
 *
 * **A second copy of `services/shared_properties.INHERITED`, and the reason it
 * is worth having one.** The server resolves the inherited fields on every
 * read and adopts them on a fresh attach, so nothing here can make a save
 * succeed or fail. What it decides is what the *form* shows between choosing a
 * shared property and saving — and a form that showed the old display name
 * until the next reload would be showing something that has already stopped
 * being true.
 *
 * The failure mode of getting this list wrong is silent in both directions: a
 * field left out is one the server overwrites on save, so the form and the
 * stored row simply disagree; a field added that Foundry does not share is one
 * the server refuses on the *next* save, from a value this file put there.
 * That is why it is here, pure, with its own test, rather than inline in the
 * dialog where only a browser could reach it.
 */

import type { PropertyInput } from "@/lib/api";
import type { SharedProperty } from "@/lib/types";

/** p.181, p.184 and p.190 give the same list three times. Not `api_name`:
 * p.188 keeps that local so downstream consumers holding it keep working. */
export const INHERITED = [
  "display_name", "description", "visibility", "value_format",
] as const;

/** The property as it will be once attached to `shared`.
 *
 * `required`, `edit_only`, `conditional_format` and `derivation` are untouched
 * on purpose: none appears on Foundry's list of shared metadata, and each is a
 * statement about *this* object type — its data quality, its backing datasets,
 * its links, and (for a conditional format) possibly another of its
 * properties. */
export function attached(prop: PropertyInput, shared: SharedProperty): PropertyInput {
  return {
    ...prop,
    shared_property_id: shared.id,
    display_name: shared.display_name,
    description: shared.description,
    visibility: shared.visibility,
    value_format: shared.value_format,
  };
}

/** p.188's Detach: "remove the association between the property and the shared
 * property". Nothing else changes — detaching is not a way to lose a display
 * name, and the server keeps the last inherited values for the same reason. */
export function detached(prop: PropertyInput): PropertyInput {
  return { ...prop, shared_property_id: null };
}

/** The shared properties that may be offered for a property of `dataType`
 * (p.181: "Base types … must match the column type in order to be applied on
 * an object type").
 *
 * Offering the rest would be offering a save that fails — the rule the derived
 * property editor follows about links, and the trap the value-format and
 * conditional-format editors both avoid. */
export function offerableTo(
  shared: SharedProperty[],
  dataType: string,
): SharedProperty[] {
  return shared.filter((s) => s.data_type === dataType);
}
