/** p.477–478's **User Select**: "selection of user(s) through a single or
 * multi-select dropdown menu".
 *
 * > "**Label**: Set an optional label for the widget to display text above the
 * > dropdown menu. **Placeholder**: Set optional placeholder text to display in
 * > the widget's empty selection state. **Selected user(s)**… If the selection
 * > is set to 'Single', the widget will be displayed as a single-select dropdown
 * > menu. **Output variable**: … a string variable containing the ID of the
 * > selected user. **Allow clear**: Toggle to enable/disable clearing of the
 * > selected dropdown menu option. If the selection is set to 'Multiple' … a
 * > string array variable containing the ID(s) of the selected user(s).
 * > **Specify Multipass group IDs**: Provide a string array variable of group
 * > IDs to filter users displayed in the dropdown to users in the specified
 * > groups." (p.477–478)
 *
 * ---
 *
 * **The output's *shape* is the setting, which no other picker here does.**
 * §215's Object Selector writes clause lists either way; p.478 makes Single a
 * `string` variable and Multiple a `string[]` one, so the mode changes the kind
 * of variable an author must bind and what every downstream reader sees. That is
 * why `toOutput` and `selectedIds` are a pair and why the mode is threaded
 * through both: a widget that wrote an array into a string variable would be
 * refused on save, and one that wrote a string into an array variable would look
 * fine and read wrong.
 *
 * **The directory is the organisation's, and it was already open.**
 * `GET /org/members` has been visible to every member since the org routes were
 * written — "emails within one org are not sensitive to it" — so this widget
 * needs no new access boundary and does not create one. p.478's group filter is
 * built rather than refused, because this platform has groups of its own
 * (migration 0001) and the setting's shape carries over exactly; what does not
 * carry over is Foundry's "View group membership" permission note, which is
 * about a boundary this platform does not draw.
 *
 * **A disabled user is not offered.** `status` comes back on every row and a
 * picker naming somebody who can no longer sign in is offering an assignment
 * that will never be actioned. The server keeps returning them, because the
 * member-management screens need to *show* a disabled user in order to say so;
 * deciding who a *picker* offers is this module's job, which is the same
 * division §231 and §233 draw between what is legal and what is offered.
 */

export const SELECTION_MODES: Record<string, string> = {
  single: "Single",
  multiple: "Multiple",
};

/** p.477's default. **Single**, because it is the mode whose output is one
 * value: an author who has not chosen yet is likelier to want "who is the
 * owner" than "who is on the team", and the array shape is the one that needs a
 * deliberate binding. */
export const DEFAULT_MODE = "single";

export function modeOf(raw: unknown): string {
  return typeof raw === "string" && Object.hasOwn(SELECTION_MODES, raw)
    ? raw
    : DEFAULT_MODE;
}

export function isMultiple(mode: unknown): boolean {
  return modeOf(mode) === "multiple";
}

export interface User {
  id: string;
  email?: string | null;
  display_name?: string | null;
  status?: string | null;
}

/** Who the dropdown offers, from what the directory returned.
 *
 * **Disabled users are dropped and the order is the server's.** `list_users`
 * orders by display name, which is the order a person scans; re-sorting here
 * would be a second opinion about the same list, and sorting by a *display
 * name* the browser may not have (some users have only an email) would put the
 * unnamed ones somewhere arbitrary.
 */
export function usersOf(raw: unknown): User[] {
  if (!Array.isArray(raw)) return [];
  const out: User[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const u = item as Record<string, unknown>;
    const id = typeof u.id === "string" ? u.id : "";
    if (!id) continue;
    // Only `active` is offered. Not "anything that is not disabled": a status
    // this build has not heard of is one whose meaning it cannot guess, and
    // guessing towards *offering* somebody is the wrong direction.
    if (typeof u.status === "string" && u.status !== "active") continue;
    out.push({
      id,
      email: typeof u.email === "string" ? u.email : null,
      display_name: typeof u.display_name === "string" ? u.display_name : null,
      status: typeof u.status === "string" ? u.status : null,
    });
  }
  return out;
}

/** What one user is called in the list.
 *
 * The display name, falling back to the email, falling back to the id. All
 * three are things a real row can be missing — an invited user has no display
 * name until they sign in — and an option with no text is one nobody can pick
 * on purpose (§215's rule, at a different picker).
 */
export function labelOf(user: User): string {
  return (user.display_name || "").trim() || (user.email || "").trim() || user.id;
}

/** Which users are selected, read back from the output variable.
 *
 * **Both shapes are read whatever the mode says**, and that is deliberate: the
 * mode is a setting somebody can change on a document that already holds a
 * selection, so a widget that only understood its *current* mode would show
 * nothing selected and then overwrite it on the next click. Reading is
 * forgiving; `toOutput` is where the mode decides.
 */
export function selectedIds(raw: unknown, mode: unknown): string[] {
  const values = Array.isArray(raw) ? raw : [raw];
  const out: string[] = [];
  for (const v of values) {
    if (typeof v !== "string") continue;
    const id = v.trim();
    if (!id || out.includes(id)) continue;
    out.push(id);
  }
  // A single-select showing two ticked users is a document that has been
  // through a mode change; the first is what its output variable can hold.
  return isMultiple(mode) ? out : out.slice(0, 1);
}

/** What to write, given the mode.
 *
 * p.478's two shapes: a `string` for Single and a `string[]` for Multiple. The
 * empty single selection is `""` rather than `null` — a string variable holds a
 * string, and `null` is what an *unbound* variable reads as, so writing it would
 * make "cleared" and "never set" the same fact downstream.
 */
export function toOutput(ids: readonly string[], mode: unknown): string | string[] {
  if (isMultiple(mode)) return [...ids];
  return ids[0] ?? "";
}

/** One user picked, in Single mode: replaces, and re-picking the same one is
 * not a clear. p.478 gives clearing its own control, so a click that sometimes
 * selected and sometimes cleared would be two behaviours on one gesture. */
export function pickedSingle(id: string): string[] {
  return id ? [id] : [];
}

/** One user toggled, in Multiple mode. */
export function toggled(ids: readonly string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((v) => v !== id) : [...ids, id];
}

/** p.478's Allow clear. Off by default, matching every other toggle read from a
 * document: a setting nobody has chosen is the unconfigured one. */
export function allowClearOf(raw: unknown): boolean {
  return raw === true;
}

/** p.477's optional Label, or nothing at all — a blank string is a row of
 * whitespace above the widget that no author asked for and none can see to
 * remove (§214's rule, same as the Object Dropdown's). */
export function textOf(raw: unknown): string | null {
  const text = typeof raw === "string" ? raw.trim() : "";
  return text || null;
}

/** p.477's Placeholder, or what the control says without one. */
export function placeholderOf(raw: unknown, mode: unknown): string {
  return textOf(raw) ?? (isMultiple(mode) ? "Select users..." : "Select a user...");
}

/** What the closed control says.
 *
 * The same three answers §215's Object Selector gives, for the same reason:
 * none is the placeholder, one is that person's name, several is a count —
 * naming four people runs off the control and truncating produces a label that
 * changes width whenever somebody ticks a box.
 */
export function summaryOf(
  ids: readonly string[],
  users: readonly User[],
  placeholder: string,
): string {
  if (ids.length === 0) return placeholder;
  if (ids.length === 1) {
    const only = users.find((u) => u.id === ids[0]);
    // A selected id the directory does not contain still has to read as *a*
    // selection: the user may have been disabled since, or the group filter may
    // have narrowed them out, and reporting "none selected" would invite an
    // author to overwrite a value that is still in the variable.
    return only ? labelOf(only) : "1 selected";
  }
  return `${ids.length} selected`;
}

/** p.478's group ids, read from the string-array variable that holds them.
 *
 * `null` means **no filter was configured**; `[]` means one was and it currently
 * names nobody. The caller must keep those apart — see `shouldAsk`.
 */
export function groupIdsOf(raw: unknown): string[] | null {
  if (raw === null || raw === undefined) return null;
  const values = Array.isArray(raw) ? raw : [raw];
  const out: string[] = [];
  for (const v of values) {
    if (typeof v !== "string") continue;
    const id = v.trim();
    if (id && !out.includes(id)) out.push(id);
  }
  return out;
}

/** Whether to ask the directory at all.
 *
 * **The rule the server cannot enforce**, because a repeated query parameter
 * has no empty form: over HTTP "no groups" and "no filter" are the same
 * request, and that request answers with the whole organisation. So a widget
 * configured with a group variable must not ask until that variable names at
 * least one group — otherwise a filtered picker flashes every user in the org
 * before narrowing, which is both wrong and the kind of wrong nobody reports.
 *
 * With no group variable bound there is no filter and asking is correct.
 */
export function shouldAsk(hasGroupVariable: boolean, groupIds: string[] | null): boolean {
  if (!hasGroupVariable) return true;
  return (groupIds?.length ?? 0) > 0;
}
