/** A property the dataset suggestion offers, read for the dialog (§735;
 * `object-link-types` p.149, p.160).
 *
 * > "Struct properties are created from struct type dataset columns." (p.149)
 *
 * The server reads a column's type as a shape (`services/column_types.py`):
 * a struct column comes back as a `struct` with its members automapped as
 * fields, and a list column as an `array` of its element. Both are a type
 * *and* a second field, and the dialog creates the type from them - so the
 * second field has to travel with the first, or the create is refused for
 * want of the struct's fields.
 */

import type { PropertyInput } from "./api";
import type { SuggestedProperty } from "./types";

/** What the dialog's chip says: the type, and for an array its element. */
export function suggestedTypeLabel(p: SuggestedProperty): string {
  return p.data_type === "array" && p.array_of ? `array of ${p.array_of}` : p.data_type;
}

/** The struct's fields as the dialog lists them, or null for a non-struct. */
export function suggestedFields(p: SuggestedProperty): string | null {
  const fields = p.struct_fields ?? [];
  return fields.length > 0 ? fields.map((f) => f.api_name).join(", ") : null;
}

/** The property the create sends: the type with whatever it needs beside it. */
export function suggestedInput(p: SuggestedProperty): PropertyInput {
  return {
    api_name: p.api_name,
    data_type: p.data_type,
    required: p.required,
    ...(p.array_of ? { array_of: p.array_of } : {}),
    ...(p.struct_fields && p.struct_fields.length > 0 ? { struct_fields: p.struct_fields } : {}),
  };
}
