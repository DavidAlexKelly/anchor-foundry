/** p.73's two creation actions in the Variables panel: **Duplicate** and **New
 * variable from current**.
 *
 * > "**New variable from current** (object set variables only): Next to the
 * > duplicate variable button, the New variable from current button allows you
 * > to create a new object set variable that automatically takes the current
 * > object set as its input. This is useful when you want to build upon an
 * > existing object set's configuration while maintaining a reference to the
 * > source variable." (p.73)
 *
 * ---
 *
 * **A duplicate is not `{ ...variable, id: newId }`, and the difference is the
 * whole unit.** Three things on a variable are *unique within the module* and a
 * copy cannot carry any of them:
 *
 *   - the **id**, which is the point of an opaque id;
 *   - the **external ID**, which `_refuse_duplicate_external_ids` in
 *     `services/workshop_variables.py` refuses outright when two variables
 *     share one;
 *   - the **label**, which is not enforced but is the only thing a person reads
 *     in the list — two rows called "Region" is a panel that cannot be used.
 *
 * And dropping the external ID **cascades**, because it is §3.4's one mechanism
 * behind three features. The server refuses a variable that is routed without
 * an external ID (p.198: "the URL addresses a variable by its external ID"),
 * one that is on the module interface without one, and one saved into a state
 * without one (p.203: "Variable values are stored within a saved state via
 * their external ID"). So a copy that kept those flags would be a copy the
 * module cannot save, and the failure would arrive as a 422 naming a variable
 * the author did not edit.
 *
 * Hence `duplicate` returns **what it had to drop** alongside the variable. The
 * panel says so. Doing it silently gives an author a copy whose settings tab
 * quietly differs from the original's, with nothing on screen to explain why —
 * and the settings tab is three checkboxes, so the difference is invisible
 * until something downstream stops working.
 *
 * **This module is the arithmetic, not the panel.** Which fields survive a copy
 * and what a new label is are decisions a set of objects can express, and a
 * decision expressed as a set of objects can be tested without a browser.
 */
import type { WorkshopVariable } from "../../lib/types";

/** The three features that hang off an external ID (p.163, p.198, p.202), with
 * the name to show when a copy loses one.
 *
 * Named rather than described in a comment because the panel has to *list*
 * them, and a list built at the point of rendering is a list nothing can check.
 */
export const UNIQUE_SETTINGS = {
  interface: "Module interface",
  routing: "Routing",
  state_saving: "State saving",
} as const;

export type UniqueSetting = keyof typeof UNIQUE_SETTINGS;

/** Which of the three a given variable actually has switched on.
 *
 * Reads the same fields the server's three refusals read, so what the panel
 * reports dropping is what the save would otherwise have refused.
 */
export function settingsOn(variable: WorkshopVariable): UniqueSetting[] {
  const on: UniqueSetting[] = [];
  if (variable.interface !== undefined) on.push("interface");
  if (variable.url_behavior !== undefined && variable.url_behavior !== "never") {
    on.push("routing");
  }
  if (variable.save_state) on.push("state_saving");
  return on;
}

/** A label nothing else in the module is using.
 *
 * "Region" → "Region copy" → "Region copy 2". The bare suffix first because
 * that is what one copy of one thing is called; the number only appears once it
 * is needed, rather than every copy being "Region copy 1" so that the second
 * one can be "Region copy 2".
 *
 * Compared case-insensitively and trimmed: two rows differing only in case read
 * as the same row in a list, which is the problem this is here to avoid.
 */
export function nextLabel(
  variables: Record<string, WorkshopVariable>,
  base: string,
  suffix = "copy",
): string {
  const taken = new Set(
    Object.values(variables).map((v) => v.label.trim().toLowerCase()),
  );
  const stem = `${base.trim()} ${suffix}`.trim();
  if (!taken.has(stem.toLowerCase())) return stem;
  for (let n = 2; ; n += 1) {
    const candidate = `${stem} ${n}`;
    if (!taken.has(candidate.toLowerCase())) return candidate;
  }
}

export interface Duplicated {
  variable: WorkshopVariable;
  /** What the copy could not carry, for the panel to say out loud. */
  dropped: UniqueSetting[];
}

/** p.73's duplicate button.
 *
 * Everything that describes *what the variable is* comes across — its kind, its
 * default, its derivation, its object set definition, its recompute behaviour,
 * its array element type. Everything that is the module's name **for** it does
 * not.
 *
 * `legacy_name` goes too, and it is the one that could be argued either way. It
 * records what this variable was called when the app was a v1 document with
 * string-keyed parameters — a fact about one variable's history. A copy made
 * today was never that parameter, and a second variable claiming to be it would
 * make the conversion record ambiguous in the one direction it exists to keep
 * unambiguous.
 */
export function duplicate(
  variables: Record<string, WorkshopVariable>,
  id: string,
  newId: string,
): Duplicated | null {
  const source = variables[id];
  if (!source) return null;
  const dropped = settingsOn(source);
  const {
    id: _id,
    label: _label,
    external_id: _externalId,
    interface: _interface,
    url_behavior: _url,
    save_state: _save,
    legacy_name: _legacy,
    ...carried
  } = source;
  return {
    variable: { ...carried, id: newId, label: nextLabel(variables, source.label) },
    dropped,
  };
}

/** p.73's "object set variables only".
 *
 * A `time_series_set` is *read through* an object set and is not one, and every
 * other kind has no set to take as an input — so the button is absent rather
 * than disabled for them: a control that can never apply to a string variable
 * is not a control that is temporarily unavailable.
 */
export function canCreateFrom(variable: WorkshopVariable | undefined): boolean {
  return variable?.kind === "object_set";
}

/** p.73's New variable from current.
 *
 * The new variable is an object set **narrowed from** the source, with the
 * source already in the first input slot — which is precisely p.73's "takes the
 * current object set as its input… while maintaining a reference to the source
 * variable". A reference, not a copy: change the source's filters and this one
 * follows, which is the difference between this button and Duplicate.
 *
 * It lands **half configured on purpose**, with the value to filter on still
 * empty. That is the same state the panel's own "Is another set, narrowed"
 * option produces, and the server refuses to save either until the second input
 * arrives. The alternative — guessing a property so the thing is savable
 * immediately — would be inventing a filter nobody asked for on a set somebody
 * is about to configure.
 */
export function fromCurrent(
  variables: Record<string, WorkshopVariable>,
  id: string,
  newId: string,
): WorkshopVariable | null {
  const source = variables[id];
  if (!canCreateFrom(source)) return null;
  return {
    id: newId,
    kind: "object_set",
    label: nextLabel(variables, source!.label, "narrowed"),
    derivation: { transform: "filter_set", inputs: [id], config: { op: "eq" } },
  } as WorkshopVariable;
}
