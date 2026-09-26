/** p.444's **Date Input** (§513): "Allow the user to enter a single data or
 * date range."
 *
 * A single date is a `date` variable holding `YYYY-MM-DD`. **A range is two
 * `date` variables written together by one widget**, a start and an end. The
 * parity row once refused a range as "two instants in one variable, which no
 * kind expresses", and rightly refused two separate pickers, which can
 * disagree. One widget writing both cannot: every change writes the pair,
 * in order, so the end is never before the start.
 *
 * Pure, and outside `widgets.tsx`, because vitest cannot parse `.tsx`.
 */

export const DATE_INPUT_MODES = { single: "Single date", range: "Date range" } as const;
export type DateInputMode = keyof typeof DATE_INPUT_MODES;

/** Whether a value is a calendar day as a `date` variable holds one. A
 * shaped string that is not a real day ("2026-02-30") is not one.
 *
 * **The round trip is the whole test**: a day that reads back as itself from
 * `toISOString` is `YYYY-MM-DD` and real. A shape regex in front of it was
 * removed in §513's sweep, since it refused nothing the round trip allows. */
export function isDay(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** What an `<input type="date">` shows for a stored value: the day, or blank
 * for anything that is not one, rather than whatever text it happens to be. */
export function shownDay(value: unknown): string {
  return isDay(value) ? value : "";
}

/** The pair to write after one end changes: in order, so a start picked after
 * the end swaps them rather than storing a range that runs backwards. A blank
 * end is `null`, and is kept as the open end it is. */
export function orderedRange(start: string, end: string): [string | null, string | null] {
  const s = isDay(start) ? start : null;
  const e = isDay(end) ? end : null;
  if (s && e && s > e) return [e, s];
  return [s, e];
}

/** How many days a range covers, both ends included; null while it is open. */
export function rangeDays(start: unknown, end: unknown): number | null {
  if (!isDay(start) || !isDay(end)) return null;
  const ms = Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`);
  return Math.round(ms / 86_400_000) + 1;
}

/** The line under a range: its length, or which end is open. */
export function rangeText(start: unknown, end: unknown): string {
  const days = rangeDays(start, end);
  if (days !== null) return `${days} day${days === 1 ? "" : "s"}, ${start} to ${end}`;
  if (isDay(start)) return `From ${start}, no end`;
  if (isDay(end)) return `Until ${end}, no start`;
  return "";
}
