/**
 * The rules a struct declaration has to satisfy before it is worth sending
 * (Foundry `object-link-types` p.149, p.152–158; db 0064).
 *
 * **The server owns every refusal here** — `services/struct_fields.py` is what
 * decides whether a declaration may be stored, and this file does not get a
 * vote. What it does is answer them *early*, where the answer can still be
 * changed: a dialog whose Apply button turns a filled-in form into a 422 with
 * the dialog already closed is a dialog that wastes the work. That is the same
 * split `value-format-editor`'s `incomplete` makes, and the same sentence
 * `STATUS.md` keeps writing about panels — the server owns what is *legal*,
 * the panel owns what to *offer*.
 *
 * Pure, and in `lib/` rather than beside the component, because vitest cannot
 * parse `.tsx`: a rule that lives in a component is a rule with no unit test.
 */

import type { PropertyDataType, StructField } from "@/lib/types";

/**
 * p.149's field types, in this platform's vocabulary.
 *
 * **A mirror of `struct_fields.FIELD_TYPES` on the server, and mirrors go
 * stale** — §191's whole lesson — so `test_struct_properties.py` scans this
 * file and compares the two. The check is against the *server's* list rather
 * than a second copy of this one, which is the direction that catches an
 * addition rather than only a disagreement.
 */
export const FIELD_TYPES: PropertyDataType[] = [
  "boolean", "date", "float", "geopoint", "integer", "string", "timestamp",
];

/** A field name follows the property naming rule, one level down (db 0003). */
const FIELD_NAME = /^[a-z][a-z0-9_]{0,99}$/;

/**
 * A field name, from whatever was typed — the same normalisation the property
 * row above it applies to a property name, one level down.
 *
 * Deliberately **not** the whole rule. It lower-cases, collapses punctuation
 * and joins on underscores, which covers "Postal Code" and "postal-code"; it
 * cannot fix a name that starts with a digit, because there is nothing to
 * turn `1st_line` into that the author would recognise as what they typed. So
 * `problem` still checks, and that branch is reachable through this box rather
 * than only through the API — which is the difference between a second guard
 * and a dead one (§213).
 */
export function toFieldApiName(typed: string): string {
  const words = typed.match(/[A-Za-z0-9]+/g) ?? [];
  return words.map((w) => w.toLowerCase()).join("_").slice(0, 100);
}

/** A new row, typed `string` because that is what most fields are. */
export function blankField(): StructField {
  return { api_name: "", display_name: "", description: "", data_type: "string" };
}

/**
 * Why this declaration cannot be saved yet, or `null`.
 *
 * One sentence at a time, and the first one only: a list of every complaint
 * about a half-typed form is a list somebody has to read to find the one they
 * have already fixed.
 */
export function problem(fields: StructField[]): string | null {
  // p.149: "Structs must have at least 1 field." A struct with none is a
  // `json` property with a more specific name.
  if (fields.length === 0) return "A struct needs at least one field.";
  const seen = new Set<string>();
  for (const [index, field] of fields.entries()) {
    const name = field.api_name.trim();
    if (!name) return `Field ${index + 1} needs a name.`;
    if (!FIELD_NAME.test(name)) {
      return `${name} is not a valid field name: lower case, digits and underscores, starting with a letter.`;
    }
    if (seen.has(name)) return `Two fields are both named ${name}.`;
    seen.add(name);
  }
  return null;
}

/**
 * Which fields have been renamed, comparing what is open against what was
 * loaded — p.158's warning, in this platform's terms.
 *
 * Foundry's version is about a RID: *"changing a struct field's API name will
 * result in a new struct field RID being generated … Any applications that
 * reference the updated struct field will need to be updated as well."* This
 * platform has no RID, and the consequence lands somewhere else instead: a
 * stored value is a mapping keyed by field name, so after a rename every
 * instance still holds the old key and the field reads as empty **until the
 * next sync**. Same warning, different mechanism, and the mechanism is what
 * makes it actionable — the fix is a sync, and saying so is the point.
 *
 * Matched **by position**, because that is the only identity a row in this
 * dialog has: a field is not addressable by the name being edited, and the
 * list is short and hand-ordered. A field added or removed shifts the
 * comparison, which is why an added row (no previous name) is not a rename.
 */
export function renamedFields(
  before: StructField[] | null | undefined,
  after: StructField[],
): string[] {
  const previous = before ?? [];
  const out: string[] = [];
  for (const [index, field] of after.entries()) {
    const was = previous[index]?.api_name;
    const now = field.api_name.trim();
    if (was && now && was !== now) out.push(was);
  }
  return out;
}

/**
 * What to show for a struct value when the declaration is to hand.
 *
 * `[[display name, rendered value], …]` in the **declared** order, which is
 * the order the value is stored in (`_coerce_struct` rebuilds it) and the one
 * p.154 says the author chose. A field the value has nothing for still gets a
 * row: p.59's "semantic grouping" is the point of the type, and an address
 * that silently omits its postcode looks like an address without one rather
 * than like a value that is missing it.
 *
 * Returns `null` for anything that is not a struct value against these fields,
 * so a caller can fall back to whatever it did before rather than render an
 * empty list.
 */
export function structRows(
  fields: StructField[] | null | undefined,
  value: unknown,
): [string, unknown][] | null {
  if (!fields || fields.length === 0) return null;
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const held = value as Record<string, unknown>;
  return fields.map((field) => [
    field.display_name || field.api_name,
    held[field.api_name] ?? null,
  ]);
}
