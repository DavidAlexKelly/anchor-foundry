/** The arithmetic and formatting the canvas widgets do, with no React in it.
 *
 * **Why this module exists at all.** These functions were private to
 * `widgets.tsx`, where the only thing that could reach them was a browser
 * driving the whole application. That is the right way to check that a click
 * narrows a table; it is a wasteful and imprecise way to check that a month
 * bucket is labelled with its year. A pixel is a lossy way to ask about a
 * number.
 *
 * **The boundary is deliberate and worth keeping.** Nothing here imports
 * React, touches the DOM, or renders anything — so nothing here *can* grow
 * into a second, weaker imitation of the browser suite. Component and
 * interaction testing stays in `e2e/`, which drives real servers in a real
 * browser, because that is where the defects this project actually hits have
 * lived: a widget reading the right data and drawing the wrong thing, a filter
 * sent when it should have been dropped, a section laying out in one column.
 * A jsdom test that passes while the real thing is broken is worse than no
 * test, and this file is arranged so that one cannot be written in it.
 */

// ---- pivot table (roadmap 1.5) ---------------------------------------------

export type PivotPick = { row: string | null; column: string | null };

export type Clause = { property: string; op: string; value: string };

/** The clause list for a pivot selection — the whole list, so clearing one
 *  axis is the *absence* of its clause rather than a clause with an empty
 *  value. A widget that wrote `value: ""` would narrow to the objects whose
 *  property is the empty string, which is a different set and usually none. */
export function pivotClauses(
  pick: PivotPick,
  rowProperty: string,
  columnProperty: string,
): Clause[] {
  const out: Clause[] = [];
  if (pick.row !== null) out.push({ property: rowProperty, op: "eq", value: pick.row });
  if (pick.column !== null) {
    out.push({ property: columnProperty, op: "eq", value: pick.column });
  }
  return out;
}

// ---- time series (roadmap 1.5) ---------------------------------------------

/** A bucket's label, formatted **in UTC** — the boundary the server pinned.
 *
 * Rendering in local time would put a viewer six hours west a day behind the
 * bucket they are looking at: the same disagreement UTC was chosen to remove,
 * reintroduced in the browser. The locale is the viewer's; only the zone is
 * fixed.
 */
export function seriesLabel(iso: string, interval: string): string {
  const when = new Date(iso);
  const opts: Intl.DateTimeFormatOptions =
    interval === "month"
      ? { year: "numeric", month: "short", timeZone: "UTC" }
      : { day: "numeric", month: "short", timeZone: "UTC" };
  const formatted = new Intl.DateTimeFormat(undefined, opts).format(when);
  return interval === "week" ? `w/c ${formatted}` : formatted;
}

// ---- section proportions (roadmap 1.4) -------------------------------------

/** The least of a section a part may be dragged to, as a fraction of the pair
 *  being resized. A part dragged to nothing has no handle left to grab and no
 *  way back except the Settings field — an unrecoverable state reached by an
 *  ordinary gesture, which is the kind worth preventing rather than
 *  documenting. */
export const MIN_SHARE = 0.08;

/** Weights are rounded so the document stays something a person can read and
 *  edit. `2.33,0.67` is describable; sixteen decimal places of float noise is
 *  not, and the roadmap's whole reason for typing proportions first was that
 *  the saved layout should be describable. */
export function roundWeight(value: number): number {
  return Math.round(value * 100) / 100;
}

/** A section's proportions as numbers, one per child.
 *
 * Anything unparseable, negative or zero is dropped rather than honoured: the
 * string is typed by hand, and a section should lay out sensibly before
 * anybody has configured it — and *keep* laying out sensibly halfway through
 * somebody typing. Short lists fall back to 1 per missing child.
 */
export function parseWeights(weights: string | null | undefined, count: number): number[] {
  const parsed = String(weights || "")
    .split(",")
    .map((w) => Number(w.trim()))
    .filter((w) => Number.isFinite(w) && w > 0);
  return Array.from({ length: count }, (_, index) => parsed[index] ?? 1);
}

/** Move the boundary between `index` and `index + 1` so the first takes
 *  `share` of the pair, keeping their combined share fixed.
 *
 * **Only the two either side of a handle move.** Dragging one divider must not
 * shuffle a column at the far end of the section — the parts beyond the pair
 * are not the author's concern when they grab a particular boundary.
 *
 * Clamped to `MIN_SHARE` at both ends, so neither part can be driven to
 * nothing.
 */
export function resizeWeights(current: number[], index: number, share: number): number[] {
  const next = [...current];
  const pair = (next[index] ?? 1) + (next[index + 1] ?? 1);
  const clamped = Math.min(Math.max(share, MIN_SHARE), 1 - MIN_SHARE);
  next[index] = pair * clamped;
  next[index + 1] = pair - (next[index] ?? 0);
  return next;
}

/** What a section's `weights` prop becomes after a resize. */
export function formatWeights(weights: number[]): string {
  return weights.map(roundWeight).join(",");
}
