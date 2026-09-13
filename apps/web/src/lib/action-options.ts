/** A multiple-choice parameter's allowed values, the parts a document decides
 * (§335; `action-types` p.33).
 *
 * > "…action editors can reduce allowed values to just those that are
 * > properties of an object set… **If only one linked object is available in
 * > the resulting object set and the parameter is required, the parameter
 * > dropdown will automatically prefill with the corresponding property
 * > value.** The resulting multiple choice options will be derived from the set
 * > of objects that the user has permission to view." (p.33)
 *
 * ---
 *
 * **Nothing here decides what the options are.** They are the distinct values a
 * property takes across a set of objects, which only the store can answer — and
 * only the store can say honestly how many distinct values there were, which is
 * the whole reason §335 groups rather than collapsing a page. What is in this
 * file is the wording for the states a derived dropdown has that a plain text
 * box does not, and the editor's side of writing one.
 *
 * **p.33's prefill is not here either.** The condition is about the object set
 * and the form is only ever shown what the set left, so the server sends the
 * value and this decides nothing about it.
 */

import type { ParameterChoices } from "./action-choices";

/** What a multiple-choice parameter's options are derived from. */
export interface ParameterOptions {
  object_type_id: string;
  property: string;
}

/** The parameter types p.33's multiple choice applies to.
 *
 * **Not `object`** — that is p.33's *other* shape and has had its own dropdown
 * since §330, so a parameter carrying both would be two answers to "what may I
 * pick". `json` and `attachment` are out for a plainer reason: a dropdown of
 * them is not a thing anybody can read. The server refuses both; this is the
 * editor not offering a setting that could not have been saved.
 */
export const OPTIONABLE_TYPES = [
  "string", "integer", "float", "boolean", "date", "timestamp", "geopoint",
];

export function optionable(dataType: string): boolean {
  return OPTIONABLE_TYPES.includes(dataType);
}

/** Whether this parameter draws a list of values rather than a box.
 *
 * Reads the *offer*, not the document: the document is redacted for anyone who
 * may not edit the action (p.40-41), and the people filling a form in are
 * mostly those people — which is §332's defect, already paid for once.
 */
export function hasValues(
  offer: ParameterChoices | null | undefined,
): boolean {
  return !!offer && offer.kind === "values";
}

/** What to say under a derived dropdown with nothing in it, or `null`.
 *
 * §214: an empty dropdown is a control that looks like it works — somebody
 * opens it, finds nothing, and cannot tell whether the list failed to load.
 * Here the truth is usually that no object has a value for that property, which
 * is a thing an editor can act on and a blank control is not.
 */
export function emptyValuesNote(
  offer: ParameterChoices | null | undefined,
): string | null {
  if (!hasValues(offer) || (offer?.values ?? []).length > 0) return null;
  return "No object has a value for the property this list is drawn from, so "
    + "there is nothing to choose yet.";
}

/** p.33's list, truncated, or `null`.
 *
 * §256's rule for a control rather than a listing, and the number it names is
 * the *distinct* total the server counted rather than the rows it read — see
 * `action_options.options`. Nothing here can check that; the sentence is
 * written so it stays true either way.
 */
export function valuesTruncationNote(
  offer: ParameterChoices | null | undefined,
): string | null {
  if (!hasValues(offer) || !offer?.truncated) return null;
  return `Showing the first ${(offer.values ?? []).length} values — there are `
    + "more than this control holds.";
}

/** A blank options document, as "Get options from an object set" leaves it.
 *
 * Both fields empty, and that is deliberate: the server refuses a document
 * naming no type and one naming no property, so there is no half of this worth
 * seeding. Unlike §333's blank walk — which starts somewhere saveable because a
 * walk *has* a sensible default — p.33 has no default object set, and inventing
 * one would put a type nobody chose in front of an editor.
 */
export function blankOptions(): ParameterOptions {
  return { object_type_id: "", property: "" };
}

/** One line describing where a parameter's options come from.
 *
 * Reads as p.33 does — a property, of a type — so somebody checking their own
 * work sees the sentence rather than the shape.
 */
export function optionsSummary(
  options: ParameterOptions | null | undefined,
  typeNames: Record<string, string>,
): string {
  if (!options?.object_type_id) return "Whatever is typed in";
  const type = typeNames?.[options.object_type_id] || "an object type";
  if (!options.property) return `A property of ${type}, not yet chosen`;
  return `The ${options.property} of every ${type}`;
}

/** What to say when the document cannot yet produce a dropdown, or `null`.
 *
 * The panel says it rather than letting Save produce a 422 several fields
 * later. Not a second authority — the server makes the same refusals — so this
 * exists to keep anybody from meeting them by the obvious route.
 */
export function optionsProblem(
  options: ParameterOptions | null | undefined,
  dataType: string,
): string | null {
  if (!options) return null;
  if (!optionable(dataType)) {
    return dataType === "object"
      // p.33's other shape, and the more useful sentence: this parameter
      // already has a dropdown, so the answer is not "you cannot" but "you
      // have one".
      ? "This parameter holds an object, so its dropdown is the list of "
        + "objects it may be set to rather than a list of values."
      : `A ${dataType} cannot be offered as a list of values.`;
  }
  if (!options.object_type_id) return "Choose the object type to read from.";
  if (!options.property) return "Choose the property that holds the values.";
  return null;
}
