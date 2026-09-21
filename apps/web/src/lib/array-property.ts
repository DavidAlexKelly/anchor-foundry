/**
 * An array property's element type, in the editor (§347; Foundry
 * `object-link-types` p.86, p.132; db 0087).
 *
 *     "Array — valid as title key: Yes. Valid as primary key: No." (p.86)
 *
 * **The server owns every refusal here** — `services/array_properties.py` is
 * what decides whether a declaration may be stored, and this file does not get
 * a vote. What it does is answer the questions *early*, where the answer can
 * still be changed, which is the split `struct-fields.ts` makes one type over:
 * the server owns what is legal, the panel owns what to offer.
 *
 * **The interesting rule is the transition, not the list.** db 0087 refuses a
 * declaration that says only half of itself — an array with no element type,
 * or an element type on a `string` — and a dropdown that changed the base type
 * without touching `array_of` would produce the second one on every switch
 * away from `array`. That is not a validation to report; it is a state the
 * editor must never be able to reach, so `withDataType` is the only way the
 * row changes its type.
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type { ObjectTypeProperty, PropertyDataType } from "@/lib/types";

/**
 * What this dialog offers as an element type.
 *
 * **A mirror of `array_properties.INNER_TYPES` on the server, minus what this
 * dialog cannot complete** — and mirrors go stale (§191), so
 * `test_array_properties.py` scans this file and compares the two against the
 * *server's* list, which is the direction that catches an addition rather than
 * only a disagreement.
 *
 * One is missing and it is the editor's own reason rather than the server's:
 * `attachment` needs an upload (§39) and this dialog has nowhere to put one,
 * so it is absent from the property dropdown too. Offering it as an element
 * type would be offering a declaration nobody can finish — §214.
 *
 * `struct` **is** here, because the Fields dialog this row already opens
 * describes the *element* (db 0064's column is the element's fields, which is
 * what made p.140's "Struct Array" need nothing new on the server).
 */
export const ELEMENT_TYPES: PropertyDataType[] = [
  "string", "integer", "float", "boolean", "date", "timestamp", "geopoint",
  "geoshape", "json", "struct",
];

/** What a newly-made array holds until somebody says otherwise.
 *
 * A default rather than an empty select, because an empty one is a
 * declaration the server refuses and the reader has to notice a second control
 * to fix it. `string` for the reason the property dropdown starts there: it is
 * the type that accepts the most and claims the least. */
export const DEFAULT_ELEMENT: PropertyDataType = "string";

type Row = Pick<ObjectTypeProperty, "data_type"> & {
  array_of?: PropertyDataType | null;
  struct_fields?: ObjectTypeProperty["struct_fields"];
};

/**
 * One property row with its base type changed, and `array_of` made to agree.
 *
 * **Both directions, because db 0087 refuses both halves of the pairing.**
 * Switching *to* `array` seeds an element type, so the row is never a
 * declaration that says nothing; switching *away* clears it, so the row is
 * never a `string` carrying a claim nothing reads. A dropdown that only set
 * `data_type` would produce the second on every switch away — and it would do
 * it silently, because the row still looks right.
 *
 * Returns a new object; the caller is rebuilding the list anyway.
 */
export function withDataType<T extends Row>(
  property: T, next: PropertyDataType,
): T {
  if (next === "array") {
    return {
      ...property,
      data_type: next,
      array_of: property.array_of ?? DEFAULT_ELEMENT,
    };
  }
  return { ...property, data_type: next, array_of: null };
}

/**
 * Whether this row's Fields dialog is about the element rather than the
 * property (p.140's "Struct Array").
 *
 * The one place the two states are the same button: `struct_fields` describes
 * a struct property's fields and an array-of-struct's *element's* fields, and
 * db 0064's column holds exactly one of those meanings at a time.
 */
export function structuresTheElement(property: Row): boolean {
  return property.data_type === "array" && property.array_of === "struct";
}

/** Whether this row needs the Fields dialog at all — either meaning. */
export function needsFields(property: Row): boolean {
  return property.data_type === "struct" || structuresTheElement(property);
}

/**
 * Why this property cannot be saved yet, or `""`.
 *
 * Only the array half: the row has many other ways to be wrong and the server
 * owns all of them. This one is here because `withDataType` cannot be the only
 * way `array_of` is ever set — a property loaded from an older workspace, or a
 * document hand-edited through the API, can arrive holding an element type
 * this build does not offer, and the Save button should say so rather than
 * posting it.
 */
export function elementRefusal(property: Row): string {
  if (property.data_type !== "array") return "";
  const held = property.array_of;
  if (!held) return "An array needs an element type — what it is a list of.";
  if (!ELEMENT_TYPES.includes(held)) {
    return `This editor cannot declare an array of ${held}.`;
  }
  return "";
}
