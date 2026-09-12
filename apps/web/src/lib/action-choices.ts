/** What an object parameter offers, the parts a document decides (§330;
 * `action-types` p.25, p.33-37).
 *
 * > "After configuring the filters, the action form will render a dropdown with
 * > only objects that match the filter. **The value selected is also validated
 * > before the action is executed.**" (p.34)
 *
 * > "The resulting multiple choice options will be derived from the set of
 * > objects that the user has permission to view." (p.33)
 *
 * ---
 *
 * **The dropdown is a convenience; the refusal is the rule.** p.34 says both
 * halves in one sentence, and the server does both — `check_object_values` runs
 * on the submit path whether or not anybody drew a form. So nothing in this
 * file decides what is *allowed*: it decides what a control shows, and what to
 * say when the control cannot show everything.
 *
 * An object parameter with no declared type gets nothing here, and keeps the
 * text box it has had since db 0044. That is deliberate: the type can also be
 * *guessed* from the action's rules, and offering a guessed list would be worse
 * than offering none, because a reader cannot tell a wrong list from a short
 * one.
 */

export interface ParameterChoice {
  id: string;
  primary_key: string;
  /** The type's title property, or the primary key — what every other listing
   * in this platform shows when a type has no title. */
  label: string;
}

export interface ParameterChoices {
  parameter: string;
  object_type_id: string;
  object_type_name: string;
  items: ParameterChoice[];
  /** Whether there are more objects than the control can hold. */
  truncated: boolean;
  /** The parameter a p.36 filter reads that nothing has supplied yet (§331).
   * `null` when the list is simply what it is — "there is nothing to choose"
   * and "fill in the other box first" are different things to be told. */
  waiting_for?: string | null;
}

/** The offer for one parameter, or `null` when there is none.
 *
 * `null` and "an empty list" are different answers and the form draws them
 * differently: no offer means nobody declared what this parameter holds, so the
 * text box stands; an empty offer means the type is known and has no objects,
 * which is a thing to say out loud.
 */
export function offerFor(
  apiName: string,
  offers: ParameterChoices[] | undefined,
): ParameterChoices | null {
  return (offers ?? []).find((o) => o.parameter === apiName) ?? null;
}

export function labelOf(choice: ParameterChoice): string {
  return choice?.label?.trim() || choice?.primary_key || "";
}

/** What to say under a dropdown that could not show everything, or `null`.
 *
 * §256's rule, one control down: a listing is a page, and somebody picking from
 * a control that quietly held the first fifty of a thousand would never learn
 * the rest existed. Said rather than paged, because p.33-37 describes a control
 * you pick from rather than a listing you page through — and the fix is a
 * filter (p.36), which is the next unit and what this sentence points at.
 */
export function truncationNote(offer: ParameterChoices | null): string | null {
  if (!offer?.truncated) return null;
  return `Showing the first ${offer.items.length} ${offer.object_type_name} `
    + "objects. Narrow the parameter with a filter to reach the rest.";
}

/** What to say when the type has no objects at all, or `null`.
 *
 * Distinct from the note above and from no offer at all. A dropdown with one
 * empty entry is a control that looks like it works (§214): somebody opens it,
 * finds nothing, and cannot tell whether the list failed to load.
 */
export function emptyNote(offer: ParameterChoices | null): string | null {
  if (!offer || offer.items.length > 0) return null;
  return `There are no ${offer.object_type_name} objects to choose from.`;
}

/** Whether the form should draw a dropdown for this parameter at all. */
export function hasOffer(
  apiName: string,
  offers: ParameterChoices[] | undefined,
): boolean {
  return offerFor(apiName, offers) !== null;
}

/** Which object types the action's parameters are typed against.
 *
 * What the editor needs to show the current setting, keyed by api_name. Reads
 * the *declaration* rather than the offer, because an editor is looking at what
 * the action says and an offer only exists for a type the reader can see.
 */
export function declaredTypes(
  parameters: { api_name: string; data_type: string; object_type_id?: string | null }[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const parameter of parameters ?? []) {
    if (parameter.data_type !== "object") continue;
    if (!parameter.object_type_id) continue;
    out[parameter.api_name] = parameter.object_type_id;
  }
  return out;
}

/** What the editor says about an object parameter nobody has typed.
 *
 * Not a refusal — the parameter works exactly as it always has, and every
 * action written before §330 is in this state. It is a sentence about what
 * declaring the type would buy, addressed to the person who can do it.
 */
export function untypedNote(parameter: {
  data_type: string;
  object_type_id?: string | null;
}): string | null {
  if (parameter?.data_type !== "object") return null;
  if (parameter?.object_type_id) return null;
  return "This parameter takes an object but does not say of which type, so "
    + "the form asks for an id. Choose a type to give it a dropdown — and to "
    + "have the value checked before the action runs.";
}
