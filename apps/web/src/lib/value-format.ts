/**
 * Applying a property's value formatter (Foundry `object-link-types`
 * p.94–101).
 *
 * > "Value formatting refers to applying a special formatter to the value of a
 * > property, transforming the raw value to a more readable version … the
 * > weight column [has] a unit ("kg") applied and the value column is
 * > displayed in a more compact form with a currency sign ("$100K")." (p.94)
 *
 * **Here rather than on the server, for a reason the spec states.** p.100
 * offers "the application user's current timezone" as a legitimate choice, and
 * a server does not know what that is. Formatting on the way out would also
 * change what the API returns — `"$100K"` where it used to return `100000` —
 * which makes filters, actions, aggregations and exports wrong all at once.
 * The stored value stays raw; only what a person looks at changes.
 *
 * **A separate rule from conditional formatting**, which colours a value by
 * comparing it. The comparison is against the *raw* value: a rule saying
 * "green above 50000" must not be handed `"$100K"` to compare, because a
 * string never was above anything. This module returns text and nothing else,
 * so the two cannot be confused.
 *
 * Pure on purpose — the same boundary `components/canvas/pure.ts` draws, for
 * the same reason. A formatter is exactly the kind of rule where a browser
 * test proves "something rendered" and a unit test proves *what*.
 */

import type { ValueFormat } from "@/lib/types";

/** Milliseconds in the window p.99 formats relatively. */
const RELATIVE_WINDOW_MS = 24 * 60 * 60 * 1000;

const RELATIVE_UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["hour", 60 * 60 * 1000],
  ["minute", 60 * 1000],
  ["second", 1000],
];

/**
 * The raw value as text, formatted if the property says so.
 *
 * Returns `null` when there is nothing to show, so a caller can tell "no
 * value" from "the empty string" — a formatted zero is `"$0"` and must not be
 * mistaken for a blank.
 *
 * `now` is a parameter rather than a call to `Date.now()` so "8 minutes ago"
 * is testable. A relative format tested against the real clock is a test that
 * asserts the code ran.
 */
export function formatValue(
  raw: unknown,
  format: ValueFormat | null | undefined,
  options: { now?: number; locale?: string } = {},
): string | null {
  if (raw === null || raw === undefined || raw === "") return null;
  if (!format) return String(raw);
  const locale = options.locale ?? "en-US";
  if (format.kind === "number") return formatNumber(raw, format, locale);
  return formatDateTime(raw, format, locale, options.now ?? Date.now());
}

/** p.97–98's options, on `Intl.NumberFormat`.
 *
 * **A value that is not a number comes back as itself.** Properties are stored
 * untyped, so a column declared `float` can hold `"n/a"` from a dataset nobody
 * cleaned. `Intl` renders that as `NaN`, which reads like a computed answer
 * rather than like the text that is actually stored.
 */
function formatNumber(
  raw: unknown,
  format: ValueFormat & { kind: "number" },
  locale: string,
): string {
  const n = typeof raw === "number" ? raw : Number(String(raw).trim());
  if (!Number.isFinite(n)) return String(raw);

  const opts: Intl.NumberFormatOptions = {};
  if (format.style === "currency") {
    opts.style = "currency";
    opts.currency = format.currency;
  } else if (format.style === "unit") {
    opts.style = "unit";
    opts.unit = format.unit;
  } else if (format.style === "percent") {
    opts.style = "percent";
  }
  if (format.grouping !== undefined) opts.useGrouping = format.grouping;
  if (format.notation) opts.notation = format.notation;
  if (format.minimum_integer_digits !== undefined)
    opts.minimumIntegerDigits = format.minimum_integer_digits;
  if (format.minimum_fraction_digits !== undefined)
    opts.minimumFractionDigits = format.minimum_fraction_digits;
  if (format.maximum_fraction_digits !== undefined)
    opts.maximumFractionDigits = format.maximum_fraction_digits;
  if (format.minimum_significant_digits !== undefined)
    opts.minimumSignificantDigits = format.minimum_significant_digits;
  if (format.maximum_significant_digits !== undefined)
    opts.maximumSignificantDigits = format.maximum_significant_digits;

  let text: string;
  try {
    text = new Intl.NumberFormat(locale, opts).format(n);
  } catch {
    // The server refuses the combinations `Intl` throws on, so reaching here
    // means a formatter that predates a rule or arrived some other way. The
    // number is still worth showing — a blank cell is the one outcome that
    // tells a reader nothing.
    text = String(n);
  }
  if (format.style === "affix") {
    return `${format.prefix ?? ""}${text}${format.suffix ?? ""}`;
  }
  return text;
}

/** p.99's table, one branch per row. */
function formatDateTime(
  raw: unknown,
  format: ValueFormat & { kind: "datetime" },
  locale: string,
  now: number,
): string {
  const at = new Date(String(raw));
  // Same reasoning as a non-numeric number: an unparseable date shown as
  // "Invalid Date" hides what is actually stored.
  if (Number.isNaN(at.getTime())) return String(raw);
  const zone = format.timezone;

  if (format.style === "iso") return at.toISOString();
  if (format.style === "relative") return formatRelative(at, locale, now, zone);

  const base: Intl.DateTimeFormatOptions = zone ? { timeZone: zone } : {};
  const styles: Record<string, Intl.DateTimeFormatOptions> = {
    date: { weekday: "short", year: "numeric", month: "short", day: "numeric" },
    datetime_long: {
      weekday: "short", year: "numeric", month: "long", day: "numeric",
      hour: "numeric", minute: "2-digit", second: "2-digit",
    },
    datetime_short: {
      year: "numeric", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    },
    time: { hour: "numeric", minute: "2-digit" },
  };
  return new Intl.DateTimeFormat(locale, { ...base, ...styles[format.style] }).format(at);
}

/**
 * p.99's footnote, which is a rule rather than a detail:
 *
 * > "When formatting Relative to now, applications will only format in
 * > relative terms up to 24 hours ago. After this, it will render in Date and
 * > time (short) form **with the day of the week**."
 *
 * The weekday is the part worth naming: past the window this is *not* the
 * `datetime_short` style, it is that style plus a weekday, so the two cannot
 * share a branch.
 */
function formatRelative(
  at: Date,
  locale: string,
  now: number,
  zone?: string,
): string {
  const delta = at.getTime() - now;
  if (Math.abs(delta) >= RELATIVE_WINDOW_MS) {
    return new Intl.DateTimeFormat(locale, {
      ...(zone ? { timeZone: zone } : {}),
      weekday: "short", year: "numeric", month: "short", day: "numeric",
      hour: "numeric", minute: "2-digit",
    }).format(at);
  }
  const relative = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, ms] of RELATIVE_UNITS) {
    // Truncated, not rounded. Rounding makes 23h59m read "24 hours ago" — a
    // reading that names the very boundary this branch exists to stay inside,
    // so it looks like the fallback failed. Truncation is also what elapsed
    // time usually means: "8 minutes ago" is *at least* 8.
    if (Math.abs(delta) >= ms) return relative.format(Math.trunc(delta / ms), unit);
  }
  return relative.format(0, "second");
}
