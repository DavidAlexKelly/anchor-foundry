/** p.274's Object Set Title widget: "a summary of a given object set as a title".
 *
 * > "**Contains single object**: If toggled on, the widget will display the
 * > title of the single object from the inputted object set. If toggled off,
 * > the widget will display the title of the object type and the total count of
 * > objects from the inputted object set… **Title override**: Allows overriding
 * > the title displayed on the widget with text of choice. This option is only
 * > available when Contains single object is disabled. **Render widget when the
 * > object set is empty** — Yes: Allows selection of an object type to display
 * > as a placeholder if the inputted object set is empty. No: Default option.
 * > Widget will not render in the module view if the inputted object set is
 * > empty." (p.274)
 *
 * ---
 *
 * **The whole widget is one string and one decision about whether to exist**,
 * which is why it is worth a module: the string has four sources depending on
 * two toggles, and "does not render at all" is a state a widget can get wrong
 * in a way nobody notices until a page has a hole in it.
 *
 * p.274's own asymmetry is the thing to keep honest: **the title override
 * applies only when the widget is *not* showing a single object.** Foundry says
 * the option is "only available" then — available is a statement about the
 * panel, and this module makes it a statement about the *value* too, so a
 * document carrying an override from before the toggle was flipped cannot
 * quietly rename somebody's object.
 */

export interface SetTitleInput {
  /** p.274's Contains single object. */
  single: boolean;
  /** The object type's display name, once resolved. */
  typeName: string | undefined;
  /** The title of the first object in the set, when there is one. */
  objectTitle: string | undefined;
  /** How many objects the set holds. */
  total: number | undefined;
  /** p.274's Title override. */
  override: unknown;
}

export function singleOf(raw: unknown): boolean {
  return raw === true;
}

export function showIconOf(raw: unknown): boolean {
  return raw === true;
}

/** p.274's "Render widget when the object set is empty", whose **default is
 * No** — the widget does not render at all. Stated as the positive so a
 * document that omits it gets p.274's default rather than the opposite. */
export function renderWhenEmptyOf(raw: unknown): boolean {
  return raw === true;
}

/** The override, but only where p.274 allows one.
 *
 * `null` when it does not apply, so a caller cannot use it by accident: the
 * check lives here rather than at the call site, which is the difference
 * between a rule and a convention.
 */
export function overrideFor(single: boolean, raw: unknown): string | null {
  if (single) return null;
  return typeof raw === "string" && raw.trim() ? raw : null;
}

/** What the widget says.
 *
 * The four sources, in p.274's order of precedence:
 *
 * 1. the single object's title, when Contains single object is on;
 * 2. the override, when it is off and one is set;
 * 3. the type name and the count;
 * 4. a bare count, when the type has not resolved yet — a number with no noun
 *    is poor, and it beats the flash of an empty heading on every load.
 */
export function titleFor({ single, typeName, objectTitle, total, override }: SetTitleInput): string {
  if (single) {
    // **Not the type name.** A single-object title that fell back to the type
    // would read as a real answer — "Site" where "Site 14" was meant — and the
    // reader has no way to tell it apart from an object genuinely called that.
    return objectTitle ?? "";
  }
  const chosen = overrideFor(single, override);
  if (chosen) return chosen;
  const count = total ?? 0;
  if (!typeName) return String(count);
  return `${typeName} · ${count.toLocaleString()}`;
}

export interface RenderInput {
  /** False until the set definition has resolved; nothing is known yet. */
  resolved: boolean;
  total: number | undefined;
  renderWhenEmpty: boolean;
}

/** Whether the widget draws at all (p.274's "Widget will not render").
 *
 * **Unresolved is not empty.** A set whose definition has not come back yet has
 * an unknown count, and treating that as zero would make every module with this
 * widget flash a gap on load and then fill it — the same rule `visibleWhen`
 * follows for a section (§81), arrived at from the other direction.
 */
export function shouldRender({ resolved, total, renderWhenEmpty }: RenderInput): boolean {
  if (!resolved || total === undefined) return true;
  return total > 0 || renderWhenEmpty;
}
