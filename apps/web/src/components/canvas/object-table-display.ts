/** p.224-225's Object Table "Display & formatting" block.
 *
 * > "**Number of lines to display per row**: This number controls the height of
 * > each table row. **Enable value wrapping**: When enabled, allows text
 * > content to wrap within cells… **Number of frozen columns**: This number
 * > determines the number of frozen columns that are anchored to the left of
 * > the table and will remain visible when a user scrolls to the right. **Empty
 * > state message**: Configure what is displayed by the widget if the object
 * > set backing the widget is empty. By Default, the widget will display a
 * > generic table icon alongside a "No objects found" message… **Custom "No
 * > value" display**: When enabled, override what is displayed in the table when
 * > there is no value for a cell. By default, "No value" will be displayed."
 * > (p.224)
 *
 * > "**Fit columns horizontally**: When enabled, columns will auto-resize to
 * > fill the current width of the table. **Enable narrow headers**: When
 * > enabled, table headers will narrow from 50 pixels to 30 pixels.
 * > **Conditional formatting colors entire cell**: When enabled, conditional
 * > formatting will color an entire cell." (p.225)
 *
 * ---
 *
 * **Every one of these is a number or a flag off a saved document**, which is
 * the reason they are here rather than inline in the widget: a document holds
 * whatever an author, an older version of the panel, or the raw JSON editor put
 * there, and `Number(null)` is `0` while `Number("")` is also `0` (§203). A
 * frozen-column count of `0` and one nobody has set are different answers, and
 * a table that silently read the second as the first would unfreeze itself
 * whenever a prop went missing.
 */

import type { CSSProperties } from "react";

// ---- rows -------------------------------------------------------------------

/** p.224's "Number of lines to display per row". */
export const DEFAULT_LINES = 1;
export const MAX_LINES = 10;

/** A line count a row can actually be drawn at.
 *
 * Clamped rather than trusted: a document can name `0` (a row with no height),
 * `-1`, or `1e9` (a row taller than the page), and each is a table nobody can
 * read rather than an error anybody would see.
 */
export function linesOf(raw: unknown): number {
  // **No guard for `null`/`""`, and the harness is why.** §203's `rowsOf` had
  // to check absence *before* coercing, because `Number(null)` is a finite `0`
  // and zero rows was a different answer from "not set". Here it is not: the
  // default is 1 and so is the floor, so `0` clamps to exactly what absence
  // gives. The guard could never change a result, which makes it a branch no
  // test can hold (§202). Same coercion fact, opposite conclusion — and what
  // decides it is whether the default coincides with the clamp.
  const value = Number(raw);
  if (!Number.isFinite(value)) return DEFAULT_LINES;
  return Math.min(MAX_LINES, Math.max(1, Math.floor(value)));
}

/** p.224's "Enable value wrapping". Off unless a document says otherwise —
 * this is the behaviour every table already had, and a stored default of "on"
 * would change the shape of every table that predates the setting. */
export function wrapOf(raw: unknown): boolean {
  return raw === true;
}

/** How a cell is drawn, given the two settings above.
 *
 * **They do different work and both stay honest.** Wrapping decides whether
 * long text may break; the line count decides how many lines are shown and,
 * through the row's minimum height, how tall the row is — which is what p.224
 * says it controls. Without the minimum, a line count above 1 would do nothing
 * visible on a table of short values, and a setting that sometimes does nothing
 * is one nobody trusts the rest of the time.
 */
export function cellStyle(lines: number, wrap: boolean): CSSProperties {
  if (!wrap) {
    // **No clamp and no `overflow`, and that is not a shortcut.** A clamped,
    // overflow-hidden box does not report the width its content needs, so a
    // `nowrap` value inside one gets *clipped* where it should have widened its
    // column and let the grid scroll. The browser suite caught it: a table that
    // never scrolls sideways makes "the frozen column did not move" pass for
    // the wrong reason.
    return { whiteSpace: "nowrap" };
  }
  return {
    whiteSpace: "normal",
    display: "-webkit-box",
    WebkitLineClamp: lines,
    WebkitBoxOrient: "vertical",
    overflow: "hidden",
  } as CSSProperties;
}

/** The height a row must be, so the line count shows even on short values.
 *
 * Applied as a cell's `height`, which CSS defines as a minimum for table cells
 * (`min-height` on one is undefined - Chromium honours it, which is why the
 * browser suite cannot tell the two apart).
 */
export function rowMinHeight(lines: number, lineHeight: number): number {
  return lines * lineHeight;
}

// ---- frozen columns ---------------------------------------------------------

/** p.224's "Number of frozen columns", clamped to the columns that exist.
 *
 * **Clamped to `total`, not `total - 1`.** Freezing every column is pointless
 * rather than wrong — there is nothing left to scroll past — and refusing it
 * would mean a table that quietly unfroze a column when a property was removed
 * from the object type.
 */
export function frozenOf(raw: unknown, total: number): number {
  // No absence guard, for the reason given on `linesOf`: none frozen is the
  // default *and* the floor, so a coerced `0` is already the right answer.
  const value = Number(raw);
  if (!Number.isFinite(value)) return 0;
  return Math.min(Math.max(0, total), Math.max(0, Math.floor(value)));
}

/** Where each frozen column has to be pinned, given the measured widths.
 *
 * `null` for a column that is not frozen, so a caller can map straight over its
 * columns without tracking an index offset.
 *
 * **The offsets are cumulative and have to be measured**, because a sticky
 * column sits at a fixed distance from the left edge and the second frozen
 * column's distance is the first one's width. CSS cannot add up the widths of
 * elements for us, so the widget measures and this does the arithmetic — which
 * is the half worth testing.
 */
export function stickyLefts(widths: readonly number[], frozen: number): (number | null)[] {
  let running = 0;
  return widths.map((width, index) => {
    if (index >= frozen) return null;
    const left = running;
    running += Number.isFinite(width) ? width : 0;
    return left;
  });
}

// ---- empty state ------------------------------------------------------------

/** p.224's Empty state message. */
export const EMPTY_MODES: Record<string, string> = {
  default: "Default",
  custom: "Custom",
};

export const DEFAULT_EMPTY_MESSAGE = "No objects found";

export function emptyModeOf(raw: unknown): string {
  return raw === "custom" ? "custom" : "default";
}

/** What an empty table says.
 *
 * A custom mode with a blank message falls back to p.224's wording rather than
 * showing nothing: an author who switched the mode and has not typed yet should
 * see a table that still explains itself.
 */
export function emptyMessageOf(mode: unknown, custom: unknown): string {
  if (emptyModeOf(mode) !== "custom") return DEFAULT_EMPTY_MESSAGE;
  return typeof custom === "string" && custom.trim() ? custom : DEFAULT_EMPTY_MESSAGE;
}

// ---- empty cells ------------------------------------------------------------

/** p.224: "By default, 'No value' will be displayed."
 *
 * **A divergence resolved in Foundry's favour.** Every other value in this
 * platform renders an empty as `∅`, and this widget now says "No value",
 * because p.224 states it and this is the widget p.224 is about. `∅` stays
 * everywhere else — the change is scoped to the Object Table rather than made
 * platform-wide off one page.
 */
export const DEFAULT_NO_VALUE = "No value";

export function noValueOf(enabled: unknown, custom: unknown): string {
  if (enabled !== true) return DEFAULT_NO_VALUE;
  // An empty string is a real answer here — "show nothing where there is
  // nothing" is a legitimate thing to configure, and is the reason this checks
  // the type rather than the truthiness.
  return typeof custom === "string" ? custom : DEFAULT_NO_VALUE;
}

// ---- table-level flags ------------------------------------------------------

/** p.225's "Fit columns horizontally".
 *
 * **Default on, which is a divergence and a deliberate one.** p.225 words it as
 * something you enable, so Foundry's default is presumably off — but every
 * table this platform has ever drawn is full-width, and defaulting to off would
 * change the appearance of every saved module the day this shipped. A new
 * setting must not restyle documents that predate it.
 */
export function fitColumnsOf(raw: unknown): boolean {
  return raw !== false;
}

/** p.225's "Enable narrow headers".
 *
 * p.225 gives pixel values — "narrow from 50 pixels to 30 pixels" — and ours
 * are not 50 to begin with, so what is kept is the *relation*: the header is
 * shorter when this is on. Copying the numbers would be copying a measurement
 * of a different design.
 */
export function narrowHeadersOf(raw: unknown): boolean {
  return raw === true;
}

/** p.225's "Conditional formatting colors entire cell".
 *
 * Off by default: colouring the text is what this platform already did, and
 * this setting says when to colour more than that.
 */
export function fillsCellOf(raw: unknown): boolean {
  return raw === true;
}
