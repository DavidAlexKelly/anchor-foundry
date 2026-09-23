/**
 * Filling in `action-types` p.66's struct parameter (§450).
 *
 * > "Struct property values can be created and modified with actions, through
 * > values supplied in a struct parameter. A struct parameter is a parameter
 * > of base type `STRUCT`, where the type contains nested parameter fields
 * > that have their own individual names and base types." (p.66)
 *
 * **The fields are the property's, and this end is only given them.** p.73
 * allows one struct parameter per struct property, so the schema lives in the
 * ontology and the server sends it down derived — there is nothing here that
 * could disagree with it.
 *
 * What is here is the arithmetic of editing one field of an object value
 * without losing the others, which is the part that is wrong in every
 * nested-form implementation that feels bad to use.
 */

// **The shared declaration, not one of ours.** `StructField` is what db 0064
// stores and what every other reader of a struct already uses — a second
// interface here would be a second answer to "what is a field" (§292).
export type { StructField } from "./types";
import type { StructField } from "./types";

/** The value of a struct parameter, as the form holds it. */
export type StructValue = Record<string, unknown>;

/** What the form is holding for this parameter, as an object.
 *
 * **Anything that is not an object reads as empty**, which is the honest
 * answer for a parameter nobody has touched (`null`) and for one whose stored
 * value predates the schema. Returning the value unchanged would make the
 * field inputs read properties off a string.
 */
export function asStruct(value: unknown): StructValue {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as StructValue)
    : {};
}

/**
 * The value after one field changes.
 *
 * **A new object every time**, because React compares by identity and a
 * mutated one is a change nothing re-renders for.
 *
 * **A blank field is removed rather than stored as `""`.** The server drops
 * undeclared keys and coerces the declared ones, and an empty string sent for
 * an integer field is a coercion failure where "the reader left it alone" is
 * what actually happened. Absent is how a struct says nothing about a field.
 */
export function setField(
  value: unknown, field: string, next: unknown,
): StructValue {
  const current = { ...asStruct(value) };
  if (next === null || next === undefined || next === "") {
    delete current[field];
    return current;
  }
  current[field] = next;
  return current;
}

/** Whether a struct has anything in it, for p.25's required check.
 *
 * An object with every field blank is not a value somebody supplied — and
 * `hasValue` in `canvas/pure.ts` answers `true` for any object, which is
 * right for an attachment reference and wrong here. */
export function isFilled(value: unknown): boolean {
  return Object.keys(asStruct(value)).length > 0;
}

/** What one field's control is called.
 *
 * Qualified by the parameter, because a form may hold two structs with a
 * `summary` each and a screen reader hearing "Summary" twice has no way to
 * tell them apart. */
export function fieldLabel(parameterLabel: string, field: StructField): string {
  return `${parameterLabel} — ${field.display_name.trim() || field.api_name}`;
}

/** What a control says when a struct parameter arrives without its fields.
 *
 * **Not a text box** (§214): a struct typed by hand into one input is a value
 * that can essentially never be valid, and the old refusal in
 * `actions.py` existed to prevent exactly that. This end says what it does
 * not know instead.
 *
 * **Where it is reached: a struct parameter no rule writes.** The fields are
 * the *property's*, found through the rule (p.73 pairs one parameter with one
 * struct property), so a parameter nothing names has no property and no
 * fields — the half-wired state a builder is in while putting an action
 * together, which is exactly when somebody is looking at this form.
 *
 * That is the only way in, which is why the sentence names the rule rather
 * than the box. p.73's pairing is enforced at save time, and the ontology
 * refuses to retype a property an action writes (`ontology.type_impact`), so a
 * wired parameter cannot lose its fields afterwards. Every surface that draws
 * a struct parameter is sent them (`struct_fields_for_parameters`), and the
 * one that is not — the Explorer's inline-edit grid — never offers such an
 * action at all: `workshop` p.241 limits inline edits to single primitive
 * types, and `INLINE_EDIT_PARAMETER_TYPES` refuses a struct on that ground. */
export function unknownFieldsNote(parameterLabel: string): string {
  return (
    `${parameterLabel} is a struct, and this form was not told which fields it `
    + `has — so there is nothing safe to offer. Check that a rule on this `
    + `action names a struct property for it to write.`
  );
}
