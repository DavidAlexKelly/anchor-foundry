/** p.463–464's Date and Time Picker: an instant, and the zone it is read in.
 *
 * > "**Selected timestamp**: Output variable of the widget, storing the user's
 * > selected date and time value.
 * >
 * > **Date format**: Sets the date format displayed by the widget. **Time
 * > format**: … either using a 12-hour clock or a 24-hour clock. **Time
 * > precision**: … down to the millisecond, second, or minute.
 * >
 * > **Timezone user editable**: Toggle controlling whether or not the timezone
 * > of the widget is adjustable in view mode by the user. **Default timezone**:
 * > … set statically by manually selecting the timezone, dynamically using a
 * > variable, or set to **local** which uses the viewer's local timezone."
 * > (p.463–464)
 *
 * ---
 *
 * **The timezone is the exact mirror of §202's percent suffix, and it is the
 * inversion that matters.** p.468's percent *changes what the variable holds*:
 * type 25, store 0.25. p.464's timezone must **not**. A `timestamp` variable
 * holds one instant; the zone decides how that instant is written down and how
 * a wall-clock time somebody types is read back into one.
 *
 * Get that backwards and the failure is silent and expensive: two viewers in
 * different zones would write different instants for "the same" time, or worse,
 * the same instant would drift by an offset every time the value made a round
 * trip through the field. So exactly two functions cross the boundary —
 * `toLocalInput` (instant → what the control shows) and `fromLocalInput` (what
 * the control shows → instant) — and the test beside this module asserts they
 * are inverses across a DST transition, a half-hour zone, and UTC.
 *
 * **No timezone library.** `Intl.DateTimeFormat` with an explicit `timeZone`
 * already knows every offset and every DST rule, and it ships with the
 * platform. What is here is the arithmetic to get an offset *out* of it, which
 * is the one thing `Intl` does not hand over directly.
 *
 * **Divergence, stated:** p.464 says "sets the date format" without listing the
 * formats, so `DATE_FORMATS` is ours. It is deliberately short — a format
 * picker with thirty entries is a picker nobody reads — and every entry is
 * unambiguous about which number is the month, which is the failure mode a date
 * format has.
 */

// ---- catalogues -------------------------------------------------------------

export interface DateFormat {
  label: string;
  /** `Intl.DateTimeFormat` options for the date part. */
  options: Intl.DateTimeFormatOptions;
}

/** Four, and no numeric-only ambiguous one on purpose: `03/01/2026` is the 1st
 * of March to half the world and the 3rd of January to the other half, and a
 * widget whose whole job is a date should not be the place that guess is made.
 * The two numeric entries below name their order in the label. */
export const DATE_FORMATS: Record<string, DateFormat> = {
  iso: { label: "2026-03-01", options: { year: "numeric", month: "2-digit", day: "2-digit" } },
  long: { label: "1 March 2026", options: { year: "numeric", month: "long", day: "numeric" } },
  medium: { label: "1 Mar 2026", options: { year: "numeric", month: "short", day: "numeric" } },
  us: { label: "March 1, 2026", options: { year: "numeric", month: "long", day: "numeric" } },
};

export const DEFAULT_DATE_FORMAT = "iso";

export type TimeFormat = "h24" | "h12";

export const TIME_FORMATS: Record<TimeFormat, string> = {
  h24: "24-hour",
  h12: "12-hour",
};

/** p.464's three, and what each one keeps. The milliseconds a `minute`
 * precision discards are discarded from the **stored instant**, not merely
 * hidden — a value shown as 09:30 that is really 09:30:47 is a value that will
 * not compare equal to the 09:30 somebody else picked. */
export type Precision = "minute" | "second" | "millisecond";

export const PRECISIONS: Record<Precision, { label: string; step: number; digits: number }> = {
  // `step` is the `<input type="datetime-local">` attribute, in seconds, which
  // is also what makes the browser show the seconds and milliseconds boxes.
  minute: { label: "Minutes", step: 60, digits: 0 },
  second: { label: "Seconds", step: 1, digits: 0 },
  millisecond: { label: "Milliseconds", step: 0.001, digits: 3 },
};

export const DEFAULT_PRECISION: Precision = "minute";

/** p.464's three ways of choosing the zone. */
export type ZoneMode = "local" | "fixed" | "variable";

export const ZONE_MODES: Record<ZoneMode, string> = {
  local: "The viewer's own timezone",
  fixed: "A timezone I choose",
  variable: "A timezone from a variable",
};

/** A short list rather than all 418 `Intl.supportedValuesOf("timeZone")`
 * entries, because a settings dropdown of 418 is not a control. `zoneOf` below
 * accepts **any** valid IANA name, so a module needing one that is not here can
 * still hold it — the list narrows what the panel offers, not what the widget
 * understands. */
export const COMMON_ZONES = [
  "UTC",
  "Europe/London",
  "Europe/Berlin",
  "America/New_York",
  "America/Chicago",
  "America/Los_Angeles",
  "Asia/Kolkata",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
];

// ---- resolving the zone -----------------------------------------------------

/** Whether `Intl` recognises this zone.
 *
 * Asked rather than assumed, because a zone can arrive from a *variable*
 * (p.464's dynamic option) and a variable holds whatever a derivation put in
 * it. An unknown zone makes `Intl.DateTimeFormat` throw, which in a render is
 * a blank module rather than a wrong time.
 */
export function isZone(name: unknown): name is string {
  if (typeof name !== "string" || !name) return false;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: name });
    return true;
  } catch {
    return false;
  }
}

/** The viewer's own zone — p.464's "local". */
export function localZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

/** p.464's Default timezone, resolved to a name `Intl` will accept.
 *
 * Falls back to the viewer's own zone at every step. A picker whose variable
 * holds nonsense showing the viewer's own time is wrong in a way they can see
 * and correct; one that throws takes the module with it.
 */
export function zoneOf(mode: unknown, fixed: unknown, fromVariable: unknown): string {
  if (mode === "fixed") return isZone(fixed) ? fixed : localZone();
  if (mode === "variable") return isZone(fromVariable) ? fromVariable : localZone();
  return localZone();
}

// ---- the boundary -----------------------------------------------------------

/** The wall-clock parts of `instant` as read in `zone`.
 *
 * `Intl` will format an instant into any zone but will not hand back the parts
 * as numbers, so this asks for a fixed, parseable arrangement and reads them
 * out. `en-CA` with `hour12: false` yields `YYYY-MM-DD, HH:MM:SS`, which is the
 * least surprising thing any locale produces.
 */
function partsIn(instant: Date, zone: string): Record<string, number> {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
    hour12: false,
  }).formatToParts(instant);
  const out: Record<string, number> = {};
  for (const part of parts) {
    if (part.type !== "literal") out[part.type] = Number(part.value);
  }
  // `hour12: false` still renders midnight as 24 in some ICU versions, which
  // would make the day one too small when read back.
  if (out.hour === 24) out.hour = 0;
  return out;
}

/** How far `zone` is ahead of UTC at `instant`, in minutes.
 *
 * The standard construction: format the instant into the zone, read the parts
 * back as if they were UTC, and take the difference. Correct across DST because
 * `Intl` applies the rule for that instant rather than a fixed offset.
 */
export function offsetAt(instant: Date, zone: string): number {
  const p = partsIn(instant, zone);
  const asUtc = Date.UTC(p.year!, p.month! - 1, p.day!, p.hour!, p.minute!, p.second!);
  // Milliseconds are not in the parts, so compare against a whole-second
  // instant rather than letting the remainder show up as an offset.
  return Math.round((asUtc - Math.floor(instant.getTime() / 1000) * 1000) / 60000);
}

function pad(value: number, width = 2): string {
  return String(value).padStart(width, "0");
}

/** p.464's precision, applied to the **instant**. See `PRECISIONS`. */
export function truncate(ms: number, precision: Precision): number {
  if (precision === "millisecond") return ms;
  const unit = precision === "minute" ? 60000 : 1000;
  // `Math.floor`, not a remainder subtraction: for an instant before 1970 the
  // remainder is negative and subtracting it would round *up*, which is the
  // one direction "truncate" must never go.
  return Math.floor(ms / unit) * unit;
}

/** instant → what `<input type="datetime-local">` shows, in `zone`.
 *
 * `""` for no value, which is what the control shows when it is empty — the
 * two have to agree or the field clears itself on the first render.
 */
export function toLocalInput(value: unknown, zone: string, precision: Precision): string {
  const instant = asInstant(value);
  if (instant === null) return "";
  const p = partsIn(instant, zone);
  const date = `${pad(p.year!, 4)}-${pad(p.month!)}-${pad(p.day!)}`;
  const time = `${pad(p.hour!)}:${pad(p.minute!)}`;
  if (precision === "minute") return `${date}T${time}`;
  const seconds = `${time}:${pad(p.second!)}`;
  if (precision === "second") return `${date}T${seconds}`;
  return `${date}T${seconds}.${pad(instant.getUTCMilliseconds(), 3)}`;
}

/** what the control shows, in `zone` → the instant, as an ISO string.
 *
 * **The inverse of `toLocalInput`**, and the pair is asserted as one rather
 * than by example: a widget where picking a time and reading it back gives a
 * different time is a widget that edits its own data, and the examples that
 * break it are the ones nobody thinks to write down.
 *
 * `null` for an empty or unparseable field, matching §202 and §203: a picker
 * nobody has touched has no value.
 */
export function fromLocalInput(text: unknown, zone: string, precision: Precision): string | null {
  if (typeof text !== "string" || !text.trim()) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/
    .exec(text.trim());
  if (!m) return null;
  const [, y, mo, d, h, mi, s, frac] = m;
  const ms = Number((frac ?? "0").padEnd(3, "0"));
  const year = Number(y), month = Number(mo), day = Number(d);
  const hour = Number(h), minute = Number(mi), second = Number(s ?? 0);
  const guess = Date.UTC(year, month - 1, day, hour, minute, second, ms);
  // **The regex counts digits; it does not check that they mean anything.**
  // `Date.UTC` rolls month 13 into the next year and day 45 into the next
  // month, so `2026-13-45T99:99` becomes a real instant almost a year away —
  // silently, and dramatically. A control cannot produce that, but a saved
  // document or a variable can. Reading the parts back is the check that also
  // catches the 31st of February, which no range test would.
  const back = new Date(guess);
  if (
    back.getUTCFullYear() !== year || back.getUTCMonth() !== month - 1
    || back.getUTCDate() !== day || back.getUTCHours() !== hour
    || back.getUTCMinutes() !== minute || back.getUTCSeconds() !== second
  ) {
    return null;
  }
  // Two passes. The offset depends on the instant, and the instant is what we
  // are solving for - so the first pass uses the offset at the *guess*, and the
  // second corrects it. One pass is wrong for exactly the hour on each side of
  // a DST change, which is the hour somebody will pick the day it happens.
  const firstPass = guess - offsetAt(new Date(guess), zone) * 60000;
  const corrected = guess - offsetAt(new Date(firstPass), zone) * 60000;
  const instant = truncate(corrected, precision);
  return Number.isFinite(instant) ? new Date(instant).toISOString() : null;
}

/** Whatever the variable holds → a `Date`, or `null`.
 *
 * A `timestamp` variable holds an ISO string (`coerce` in `pure.ts` passes it
 * through untouched), but a derivation can put anything there and a saved
 * document can carry anything at all.
 */
function asInstant(value: unknown): Date | null {
  if (value === null || value === undefined || value === "") return null;
  const date = value instanceof Date ? value : new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date;
}

// ---- display ----------------------------------------------------------------

/** p.464's Date format and Time format, applied together.
 *
 * Used for the read-only summary beside the control, which is what makes the
 * zone visible: without it two viewers see different times in a field that
 * looks identical, and neither can tell why.
 */
export function formatDisplay(
  value: unknown,
  zone: string,
  dateFormat: unknown,
  timeFormat: unknown,
  precision: Precision,
): string {
  const instant = asInstant(value);
  if (instant === null) return "";
  const shape = DATE_FORMATS[typeof dateFormat === "string" && Object.hasOwn(DATE_FORMATS, dateFormat)
    ? dateFormat : DEFAULT_DATE_FORMAT]!;
  const hour12 = timeFormat === "h12";
  const options: Intl.DateTimeFormatOptions = {
    ...shape.options,
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hour12,
    ...(precision === "minute" ? {} : { second: "2-digit" }),
  };
  const text = new Intl.DateTimeFormat(hour12 ? "en-US" : "en-CA", options).format(instant);
  if (precision !== "millisecond") return text;
  // `Intl` has `fractionalSecondDigits`, but appending keeps the milliseconds
  // adjacent to the seconds in every locale rather than wherever the pattern
  // happens to put them.
  return `${text}.${pad(instant.getUTCMilliseconds(), 3)}`;
}

/** The zone as a viewer would name it: `Europe/London (GMT+1)`.
 *
 * The offset is included because the name alone does not say what time it is —
 * and the offset alone does not say which zone, since it changes twice a year.
 */
export function zoneLabel(zone: string, at: unknown = new Date()): string {
  const instant = asInstant(at) ?? new Date();
  if (!isZone(zone)) return zone;
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: zone, timeZoneName: "shortOffset" })
    .formatToParts(instant);
  const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
  return name ? `${zone} (${name})` : zone;
}
