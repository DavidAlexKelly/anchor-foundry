/**
 * How long ago a quick link was edited (§317; `ontology-manager` p.30).
 *
 *     "Hovering over the Back home button will also bring up quick links to
 *      recently edited object types, link types, and action types." (p.30)
 *
 * **A list headed "recently edited" that shows no times is one nobody can
 * calibrate.** The order says which is most recent; it says nothing about
 * whether the top row is from four minutes ago or four months, and those are
 * different lists — one is "what I was doing", the other is "this ontology is
 * finished". The whole value of the panel is the first reading.
 *
 * It also keeps the field honest. The endpoint sends `updated_at`; a response
 * field nothing draws is a field nothing checks, and it rots in the quiet way
 * §316's missing union member did.
 */

/** The thresholds, largest unit that still reads as a whole number. */
const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/**
 * "just now", "4 minutes ago", "3 hours ago", "2 days ago", or a date.
 *
 * **Relative up to a week, absolute after it**, which is the point where a
 * relative time stops being the more useful of the two: "23 days ago" is a
 * number a reader has to do arithmetic on, while a date is one they can match
 * against something they remember. A week is also roughly where p.30's list
 * stops being about what anybody is currently doing.
 *
 * `now` is a parameter rather than a call to `Date.now()`, so this is a
 * function of its arguments and a test does not have to freeze a clock to say
 * what it expects.
 *
 * **A future timestamp reads as "just now".** Clocks disagree — the server
 * writes `now()` in Postgres and the browser compares against its own — and a
 * row a second in the future is that disagreement rather than an edit that has
 * not happened yet. "in -1 minutes" would be a bug report about something that
 * is working.
 */
export function editedAgo(iso: string, now: number): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const ago = now - at;
  if (ago < MINUTE) return "just now";
  if (ago < HOUR) return plural(Math.floor(ago / MINUTE), "minute");
  if (ago < DAY) return plural(Math.floor(ago / HOUR), "hour");
  if (ago < 7 * DAY) return plural(Math.floor(ago / DAY), "day");
  return new Date(at).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function plural(count: number, unit: string): string {
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}
