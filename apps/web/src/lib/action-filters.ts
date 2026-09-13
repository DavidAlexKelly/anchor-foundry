/** Narrowing what an object parameter offers, the parts a document decides
 * (§331; `action-types` p.33-36, p.40-41).
 *
 * > "The object dropdown only shows objects where the specified property
 * > matches any of the provided values. The value can be statically defined by
 * > the user, inferred from another parameter… **If more than one value is
 * > provided to compare against, the result will be an OR operation.**" (p.36)
 *
 * ---
 *
 * **Nothing here evaluates a filter, and this time the browser could not even
 * if it wanted to.** A filter narrows a set of *objects*, and the objects live
 * on the server; the form asks `parameter-choices` what is left and draws that.
 * What is in this file is which values the question depends on — so the form
 * re-asks when one of them changes and not otherwise — and the wording for the
 * two states a narrowed dropdown has that an unnarrowed one does not.
 *
 * **A viewer never receives a filter at all** (p.40-41). Static filter values
 * are readable by anyone who can read the action type, and Foundry's own
 * example reveals that an investigation exists to people who cannot see a
 * document in it — so the server redacts them for anyone who may not edit the
 * action. That is why `waitingFor` comes back as a *parameter name* from the
 * server rather than being worked out here: the form knows which box to point
 * at without being told what the rule is.
 *
 * `dropdown_watches` is the same trick and for the same reason (§332). A form
 * has to know which boxes to re-ask on, and the version of this file that
 * worked it out from the filters knew nothing for the readers the redaction was
 * written for — so the server names the parameters and keeps the rule.
 */

import type { ParameterChoices } from "./action-choices";

import type { ActionDropdownFilter, ActionFilterValue } from "@platform/types";

/** The wire shapes, which live in the shared contract beside every other one.
 * Re-exported under the names this module uses throughout, because in here a
 * filter is only ever a thing to draw and describe. */
export type DropdownFilter = ActionDropdownFilter;
export type FilterValue = ActionFilterValue;

interface HasFilters {
  api_name: string;
  data_type: string;
  dropdown_watches?: string[];
}

/** Every parameter any filter reads.
 *
 * The form keys its choices query on these values, so typing in a parameter no
 * filter mentions does not re-ask — and a form whose object parameters carry no
 * filters asks exactly once, when it opens.
 *
 * **Read off the server's own answer rather than worked out from the filters**
 * (§332). The filters are redacted for anyone who may not edit the action
 * (p.40-41), so the first version of this — which walked `dropdown_filters` —
 * returned nothing for exactly those readers: their Team dropdown said "choose
 * Region first", they chose a region, and nothing re-asked, because nothing had
 * told the form that Region mattered. `dropdown_watches` is sent to everybody
 * for that reason and this reads only it.
 */
export function filterParameters(parameters: HasFilters[]): string[] {
  const named = new Set<string>();
  for (const parameter of parameters ?? []) {
    // Taken as sent. `referenced_parameters` already trimmed these and dropped
    // the blanks, so a guard here would be a second copy of a promise the
    // server makes — free to disagree with it the day one of them changes
    // (§213). Deduplicated and sorted because *this* merges several
    // parameters' lists, which is the one thing the server could not do.
    for (const name of parameter.dropdown_watches ?? []) named.add(name);
  }
  return [...named].sort();
}

/** A stable key over only the values the filters read. */
export function filterKey(
  parameters: HasFilters[],
  values: Record<string, unknown>,
): string {
  return JSON.stringify(
    filterParameters(parameters).map((name) => [name, values?.[name] ?? null]),
  );
}

/** What to say under a dropdown waiting on another box, or `null`.
 *
 * p.36 lets a filter read another parameter, so a dropdown can depend on
 * something nobody has filled in. **Offering every object then would offer
 * exactly the ones the filter exists to exclude**, and the submission would be
 * refused a moment later — so the list is empty and this says which box comes
 * first.
 *
 * The label is looked up rather than shown as an api_name, because the person
 * reading this is looking at a form and the form says "Region", not "region".
 */
export function waitingNote(
  offer: ParameterChoices | null,
  labels: Record<string, string>,
): string | null {
  const waiting = (offer as { waiting_for?: string | null } | null)?.waiting_for;
  if (!waiting) return null;
  return `Choose ${labels?.[waiting] || waiting} first — it decides what can be `
    + "picked here.";
}

/** Whether this offer is empty because it is waiting rather than because the
 * type has no objects.
 *
 * The two look identical on screen and are different things to be told, which
 * is why `emptyNote` must stand down for the first: "there are no Teams" is
 * false and unhelpful when the truth is "you have not said which region".
 */
export function isWaiting(offer: ParameterChoices | null): boolean {
  return !!(offer as { waiting_for?: string | null } | null)?.waiting_for;
}

/** A blank filter, as Add filter leaves it.
 *
 * One empty static value rather than none: the server refuses a filter with no
 * values, and starting somebody in a state it will not save is a control that
 * looks like it works (§214).
 */
export function blankFilter(): DropdownFilter {
  return { property: "", values: [{ kind: "value", value: "" }] };
}

/** One line describing a filter, for the editor's list.
 *
 * Reads as p.36 does — a property, then the values it may match — so somebody
 * checking their own work sees the sentence rather than the shape.
 */
export function filterSummary(
  filter: DropdownFilter,
  labels: Record<string, string>,
): string {
  const property = filter?.property?.trim() || "(no property)";
  const values = (filter?.values ?? []).map((value) =>
    value?.kind === "parameter"
      ? (labels?.[value.parameter] || value.parameter)
      : JSON.stringify(value?.value ?? ""),
  );
  if (values.length === 0) return `${property} matches nothing yet`;
  if (values.length === 1) return `${property} is ${values[0]}`;
  return `${property} is any of ${values.join(", ")}`;
}

/** The parameters a filter value may read.
 *
 * **Not this one**, which would make the dropdown depend on the value it is
 * offering, and not a parameter the action does not declare. A narrowing of
 * what is offerable rather than a validation: the server refuses both, and this
 * is why nobody meets those refusals by the obvious route.
 */
export function readableParameters(
  parameters: { api_name: string }[],
  apiName: string,
): string[] {
  return (parameters ?? [])
    .map((p) => p.api_name)
    .filter((name) => name && name !== apiName);
}

/** p.40-41's warning, for the editor that is about to write a static value.
 *
 * > "Static value filters in object dropdown validations are exposed to all
 * > users who can view the action type. Use of these filters risks exposing
 * > property value combinations to users without permissions to view the
 * > filtered objects." (p.40)
 *
 * **Shown where the static value is typed, and only then.** p.41 is explicit
 * that a filter reading a parameter carries no such risk — "no information
 * about the underlying data is exposed to the action type viewer" — so a
 * warning on every filter would be a warning nobody reads by the third one.
 *
 * This build redacts the filters from everyone who may not edit the action, so
 * the residual risk is smaller than the one p.40 describes. The sentence still
 * belongs on screen: the person choosing between a static value and a parameter
 * is the only one who can choose, and p.41's own mitigation is "relying on
 * object properties or parameters to filter the object set".
 */
export function staticValueWarning(filters: DropdownFilter[]): string | null {
  const hasStatic = (filters ?? []).some((filter) =>
    (filter.values ?? []).some((value) => value?.kind === "value"));
  if (!hasStatic) return null;
  return "A typed-in value is part of the action's definition. Everyone who "
    + "may edit this action can read it, even if they cannot see the objects "
    + "it matches — reading the value from a parameter instead avoids that.";
}
