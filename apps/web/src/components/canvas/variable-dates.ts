/** p.140-141's date and time math and comparisons, as the Variables panel
 * offers them (§565). The server evaluates them
 * (`services/variable_dates.py`); this is each one's inputs and settings, for
 * the panel. Pure. */

/** Every one takes exactly this many inputs. */
export const DATE_ARITY: Record<string, number> = {
  relative_date: 2, relative_time: 2, between_dates: 2, between_times: 2, current_date: 0,
  date_is_on_or_after: 2, date_is_after: 2, date_is_on_or_before: 2, date_is_before: 2,
  date_is_equal: 2,
  time_is_on_or_after: 2, time_is_after: 2, time_is_on_or_before: 2, time_is_before: 2,
  time_is_equal: 2,
};

export const DATE_UNITS = ["days", "weeks", "months", "years"] as const;
export const TIME_UNITS = ["seconds", "minutes", "hours", "days", "weeks", "months", "years"] as const;

export function isDateMath(transform: string): boolean {
  return transform in DATE_ARITY;
}

/** The units a transform counts in, or null for one that takes none. */
export function unitsFor(transform: string): readonly string[] | null {
  if (transform === "relative_date" || transform === "between_dates") return DATE_UNITS;
  if (transform === "relative_time" || transform === "between_times") return TIME_UNITS;
  return null;
}

/** Whether it moves a date or time, and so takes p.140's "add or subtract". */
export function takesDirection(transform: string): boolean {
  return transform === "relative_date" || transform === "relative_time";
}

/** What each input is called. */
export function dateSlotLabels(transform: string): string[] {
  if (transform === "relative_date") return ["Date", "By"];
  if (transform === "relative_time") return ["Time", "By"];
  if (transform === "between_dates" || transform === "between_times") return ["From", "To"];
  return ["First", "Second"];
}
