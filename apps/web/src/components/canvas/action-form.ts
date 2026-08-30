/** p.510-513's Inline Action widget, the parts a document decides.
 *
 * > "**Define parameter defaults (table and form)**: Set local default values
 * > for parameters in the Inline Action view. If unspecified, the action type
 * > parameter configurations from the Ontology will apply. **Set custom Action
 * > title**: Customize the widget header by replacing the default title with
 * > your own text." (p.512)
 *
 * > "**Inline Action form state if invalid**: Configure how the Action form
 * > appears when submission criteria are not met. Choose between `disabled` or
 * > `hidden` to either disable or hide invalid Actions. **Hide header**:
 * > Control the visibility of the Action header. … **On successful action
 * > submit**: Configure a Workshop event to trigger after an Action is
 * > successfully submitted." (p.513)
 *
 * ---
 *
 * **Whether the criteria are met is not decided here, and that is deliberate.**
 * p.513's setting needs the answer before anything is written, and the only
 * honest way to have it is to ask the server — `POST .../check` runs the same
 * `check_criteria` the executor runs. What is in this file is what a *document*
 * says: which of p.513's two states to use, what to call the widget, which
 * defaults are the module's rather than the ontology's. The rule that governs
 * writes stays in one place, which is the argument `CanvasActionForm` has made
 * since §130.
 */

/** p.513's "form state if invalid". */
export const INVALID_STATES: Record<string, string> = {
  disabled: "Disabled",
  hidden: "Hidden",
};

export const DEFAULT_INVALID_STATE = "disabled";

export function invalidStateOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(INVALID_STATES, raw)
    ? raw
    : DEFAULT_INVALID_STATE;
}

/** p.512's custom Action title, or the action's own name.
 *
 * A blank override is not a title: p.512 calls it "replacing the default title
 * with your own text", and an empty box in a settings panel is what a builder
 * who changed their mind leaves behind.
 */
export function headerTitleOf(custom: unknown, actionName: string | undefined): string {
  const text = typeof custom === "string" ? custom.trim() : "";
  return text || actionName || "Action";
}

/** p.513's Hide header. */
export function hideHeaderOf(raw: unknown): boolean {
  return raw === true;
}

/** p.512's local parameter defaults, as a saved document can hold them.
 *
 * Tolerant, because this prop is an object and the raw JSON editor can put
 * anything in it. Values are kept as they arrive rather than stringified here:
 * the form seeds strings, but *what a default is* is the document's business
 * and `seedActionForm` is the one place that decides how a value becomes a
 * field.
 */
export function localDefaultsOf(raw: unknown): Record<string, unknown> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    if (!name.trim()) continue;
    if (value === undefined || value === null) continue;
    out[name] = value;
  }
  return out;
}

export interface FormState {
  /** p.513's setting, as the document holds it. */
  invalidState: unknown;
  /** What the server said about these values, or `undefined` while it is still
   *  being asked — which is neither valid nor invalid. */
  valid: boolean | undefined;
}

/** Whether the form is drawn at all.
 *
 * **`undefined` draws it.** A form that vanished while the check was in flight
 * and reappeared a moment later would flicker on every object a viewer clicks,
 * and p.513's `hidden` is about an action that *cannot* be submitted rather
 * than about one nobody has asked about yet — §210's rule that unresolved is
 * not empty, one widget along.
 */
export function formVisible({ invalidState, valid }: FormState): boolean {
  if (valid !== false) return true;
  // `invalidStateOf(x) !== "hidden"` and `x !== "hidden"` cannot differ while
  // `INVALID_STATES` has two keys, so the harness reports the second as a
  // survivor — the identical finding §213 recorded about `viewModeOf`, and the
  // second time in five units. **It is a property of two-valued settings**: a
  // normalising read collapses to a bare comparison whenever there are exactly
  // two legal values, because everything that is not one of them becomes the
  // other. The read stays for the reason it did there — a third state added to
  // p.513 would make the bare comparison treat it as `disabled`, silently —
  // and no test can hold it today.
  return invalidStateOf(invalidState) !== "hidden";
}

/* **There is no `submitEnabled` here, and the first draft had one.** It read
 * `valid !== false` with `invalidState` in its signature doing nothing — both
 * of p.513's states forbid submitting, one by removing the form and one by
 * disabling it, so the setting cannot change that answer. A function whose
 * parameter cannot affect its result is a guard nothing can test (§213), and
 * the widget writes the condition inline instead. */
