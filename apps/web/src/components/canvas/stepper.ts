/** p.312-313's Stepper: "help navigate the user through a multi-step workflow,
 * displaying and tracking progress as they walk through a sequence of steps".
 *
 * > "**Type**: **Linear**: Users are required to complete the steps in order.
 * > **Non-linear**: Users can freely navigate between steps and complete them
 * > in any order." (p.312)
 *
 * > "**Steps**: … **Label**: Sets the label to be displayed for the step…
 * > **On click**: Set event(s) to be triggered when the step is clicked…
 * > **Is completed**: Set a boolean variable to be used a check to determine
 * > when a step has been completed. **Icon**… **Template**: **Text only**:
 * > Displays ordered numbers for each step… **Use icons**… **Show step
 * > number**: Toggle on to also display step numbers on the widget when set to
 * > linear stepper type and set to use icons. **Completed color**: Sets the
 * > color for a step when it has been completed… **Active color**: Sets the
 * > color for the currently active step the user is on." (p.313)
 *
 * ---
 *
 * **Completion is read, never stored.** p.313 says a step is complete when a
 * *boolean variable* says so, which means the widget owns no progress of its
 * own: the module decides what completing a step means, the variable records
 * it, and this draws the answer. A stepper holding its own idea of progress
 * would disagree with the module the moment anything else wrote to those
 * variables — §207's rule about selections, in a widget that looks nothing
 * like a table.
 *
 * **Which step is active is derived from that**, and is not a fourth thing to
 * store: the active step is the first incomplete one. p.313 names an active
 * colour and never says what sets it, and any *stored* answer could disagree
 * with the completion variables it is drawn beside.
 */

/** p.312's Type. */
export const STEPPER_TYPES: Record<string, string> = {
  linear: "Linear — in order",
  non_linear: "Non-linear — any order",
};

export const DEFAULT_TYPE = "linear";

export function typeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(STEPPER_TYPES, raw) ? raw : DEFAULT_TYPE;
}

/** p.313's Template. */
export const TEMPLATES: Record<string, string> = {
  text: "Text only — numbered",
  icons: "Use icons",
};

export const DEFAULT_TEMPLATE = "text";

export function templateOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(TEMPLATES, raw) ? raw : DEFAULT_TEMPLATE;
}

export interface Step {
  label: string;
  /** p.313's "Is completed": the id of a boolean variable. */
  completedVariable?: string;
  /** p.313's Icon. A *name*, drawn as a mark — see the widget. */
  icon?: string;
}

/** p.313's Steps, as a saved document can hold them.
 *
 * Tolerant for §212's reason. A step with no label is dropped rather than
 * drawn blank: a numbered circle with nothing beside it is a step nobody can
 * identify, and the workflow it belongs to is the thing being navigated.
 */
export function stepsOf(raw: unknown): Step[] {
  if (!Array.isArray(raw)) return [];
  const out: Step[] = [];
  for (const entry of raw) {
    if (!entry || typeof entry !== "object") continue;
    const item = entry as Partial<Step>;
    if (typeof item.label !== "string" || !item.label.trim()) continue;
    out.push({
      label: item.label.trim(),
      ...(typeof item.completedVariable === "string" && item.completedVariable
        ? { completedVariable: item.completedVariable } : {}),
      ...(typeof item.icon === "string" && item.icon.trim()
        ? { icon: item.icon.trim() } : {}),
    });
  }
  return out;
}

/** Whether a step's variable says it is done.
 *
 * **`true` and only `true`.** A variable a module has never written holds
 * `undefined`, and a step that counted that as done would open a workflow with
 * every stage already ticked. The string `"false"` is the other direction of
 * the same mistake.
 */
export function isCompleted(value: unknown): boolean {
  return value === true;
}

/** Which step the viewer is on: **the first incomplete one**.
 *
 * When every step is complete there is no step left to be on, and `null` says
 * so — a workflow that highlighted its last step forever would look unfinished
 * to the person who had just finished it.
 */
export function activeIndex(completed: readonly boolean[]): number | null {
  const index = completed.findIndex((done) => !done);
  return index === -1 ? null : index;
}

export interface Reach {
  index: number;
  completed: readonly boolean[];
  type: unknown;
}

/** Whether a step can be gone to at all.
 *
 * p.312's Linear — "users are required to complete the steps in order" — is the
 * whole difference between the two types, and it is a rule about *clicking*
 * rather than about drawing: every step is shown either way, because a
 * workflow whose later stages were invisible would give a viewer no idea how
 * much was left.
 *
 * **A completed step stays reachable**, so somebody can go back and look at
 * what they did. "In order" constrains how far forward you may go, not whether
 * you may return.
 */
export function isReachable({ index, completed, type }: Reach): boolean {
  if (typeOf(type) !== "linear") return true;
  return completed.slice(0, index).every(Boolean);
}

/** What a step is, for the colour it takes.
 *
 * Completed wins over active, and the pair cannot both be true anyway —
 * `activeIndex` is the first *incomplete* step — but stating the order here is
 * what keeps a later change to one of them from silently changing the other.
 */
export function stateOf(
  index: number, completed: readonly boolean[], active: number | null,
): string {
  if (completed[index]) return "completed";
  if (active === index) return "active";
  return "upcoming";
}

export const DEFAULT_COMPLETED_COLOUR = "#14646e";
export const DEFAULT_ACTIVE_COLOUR = "#8a6d3b";

function colourOf(raw: unknown, fallback: string): string {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text || fallback;
}

/** p.313's Completed color. */
export function completedColourOf(raw: unknown): string {
  return colourOf(raw, DEFAULT_COMPLETED_COLOUR);
}

/** p.313's Active color. */
export function activeColourOf(raw: unknown): string {
  return colourOf(raw, DEFAULT_ACTIVE_COLOUR);
}

/** p.313's "Show step number".
 *
 * > "Toggle on to also display step numbers on the widget **when set to linear
 * > stepper type and set to use icons**."
 *
 * Both conditions, which is p.313 being precise rather than fussy: the text
 * template already *is* the numbers, so "also display" has nothing to add to
 * it, and a non-linear workflow has no order for a number to mean.
 */
export function showsStepNumber(
  { template, type, show }: { template: unknown; type: unknown; show: unknown },
): boolean {
  if (templateOf(template) !== "icons") return false;
  if (typeOf(type) !== "linear") return false;
  return show === true;
}
