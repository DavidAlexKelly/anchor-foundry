/**
 * Value formatting *inside a Workshop module* (`foundry_workshop` p.174, and
 * p.328's "Numeric formatting" which points at it).
 *
 * > "Value formatting applies special formatting when rendering values in
 * > user-facing applications… In Workshop, value formatting can be used to
 * > render values when setting up **time series property columns in the Object
 * > Table widget** and **time series property displays in the Metric Card
 * > widget**. This formatting is local to the Workshop module, and not global
 * > to the ontology." (p.174)
 *
 * Those two surfaces are the whole of it. Everywhere else a property is
 * written by the ontology's own formatter (§157), which is why this is a
 * handful of props on two widgets rather than an override layer over every
 * value on the page.
 *
 * ---
 *
 * **"Not global to the ontology" is structural here, not a policy.** §157
 * permits a formatter only on a property whose base type is `integer` or
 * `float` (`services/value_format.py`'s `NUMERIC_TYPES`, from p.95's "you will
 * see a type of formatting depending on the base type"). Neither of p.174's
 * two surfaces has one available to inherit:
 *
 * * the Object Table's time series column formats the series' **latest
 *   value**, and the property behind it is a `time_series` — so it can carry
 *   no ontology formatter at all;
 * * the Metric Card's number is an **aggregate this widget computed**, not a
 *   stored property value, so there is no property to ask.
 *
 * So there is no precedence rule to get wrong and none is written. The module's
 * formatter is the only formatter either surface can have. If a future surface
 * *does* have both, that is the moment to decide which wins — and it will need
 * deciding out loud rather than inheriting a default chosen here for a case
 * that could not happen.
 *
 * ---
 *
 * **Read defensively, because this lives in the layout JSON** (§212: the raw
 * editor can hold anything, and so can a document written by an older build).
 * `formatValue` already survives a formatter `Intl` throws on by falling back
 * to the bare number — but silently, and a currency sign that vanished on some
 * rows and not others is the kind of thing nobody reports. These readers drop
 * a formatter that would not apply *whole*, so a column is either formatted
 * the way it says or plainly not.
 *
 * The rules mirror `services/value_format.py` exactly, because that file is
 * where they are enforced for the ontology and two copies that drift are worse
 * than one that is duplicated on purpose. They are duplicated rather than
 * imported for the reason `value-format.ts` gives: this runs in a browser and
 * that runs in Python.
 */

import type { ValueFormat } from "@/lib/types";
import { formatValue } from "../../lib/value-format";

export type NumberFormat = ValueFormat & { kind: "number" };

/** p.97's Base type dropdown, minus Fixed Values (§157 does not build it). */
const STYLES = ["plain", "currency", "unit", "percent", "affix"] as const;

const NOTATIONS = ["standard", "compact", "scientific", "engineering"] as const;

/** `Intl.NumberFormat`'s own ranges — outside them it throws. Same numbers as
 * `services/value_format.py`'s `DIGIT_BOUNDS`. */
const DIGITS: Record<string, [number, number]> = {
  minimum_integer_digits: [1, 21],
  minimum_fraction_digits: [0, 100],
  maximum_fraction_digits: [0, 100],
  minimum_significant_digits: [1, 21],
  maximum_significant_digits: [1, 21],
};

/** Min/max pairs that must not cross. `Intl` throws on a crossed pair, and a
 * thrown formatter is a cell that shows an unformatted number. */
const PAIRS: [string, string][] = [
  ["minimum_fraction_digits", "maximum_fraction_digits"],
  ["minimum_significant_digits", "maximum_significant_digits"],
];

/**
 * One stored formatter, or `null` when there is nothing usable there.
 *
 * **A `datetime` formatter is dropped rather than applied.** Both of p.174's
 * surfaces are numbers, and `formatValue` handed a datetime formatter for a
 * number would parse `1234` as a date and return the digits back unchanged —
 * a formatter that appears configured and does nothing, which is the one
 * outcome §157's server-side refusals exist to prevent.
 */
export function numberFormatOf(raw: unknown): NumberFormat | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const it = raw as Record<string, unknown>;
  if (it.kind !== "number") return null;
  if (!STYLES.includes(it.style as (typeof STYLES)[number])) return null;

  // The thing each style is *for*. A currency with no code throws; a unit with
  // no unit throws; an affix with neither side is a formatter that formats
  // nothing and would read as a bug in `Intl` rather than an unfinished panel.
  if (it.style === "currency" && !(typeof it.currency === "string" && it.currency.length === 3))
    return null;
  if (it.style === "unit" && !(typeof it.unit === "string" && it.unit.trim() !== ""))
    return null;
  if (it.style === "affix") {
    const prefix = typeof it.prefix === "string" ? it.prefix : "";
    const suffix = typeof it.suffix === "string" ? it.suffix : "";
    if (prefix === "" && suffix === "") return null;
  }
  if (it.notation !== undefined
      && !NOTATIONS.includes(it.notation as (typeof NOTATIONS)[number])) return null;
  if (it.grouping !== undefined && typeof it.grouping !== "boolean") return null;

  for (const [field, [lo, hi]] of Object.entries(DIGITS)) {
    const value = it[field];
    if (value === undefined) continue;
    if (typeof value !== "number" || !Number.isInteger(value)) return null;
    if (value < lo || value > hi) return null;
  }
  for (const [lo, hi] of PAIRS) {
    const low = it[lo] as number | undefined;
    const high = it[hi] as number | undefined;
    if (low !== undefined && high !== undefined && low > high) return null;
  }
  return raw as NumberFormat;
}

/**
 * The Object Table's per-column formatters, keyed by property API name.
 *
 * **A sibling map rather than a field on each column.** The table's `columns`
 * prop is a comma-separated string of API names, and turning it into a list of
 * objects would rewrite every table already saved. A map
 * beside it is additive, and it also survives the thing a list would not: a
 * column removed and added back keeps the formatting somebody set on it.
 */
export function formatsByColumn(raw: unknown): Record<string, NumberFormat> {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const out: Record<string, NumberFormat> = {};
  for (const [name, value] of Object.entries(raw as Record<string, unknown>)) {
    const format = numberFormatOf(value);
    if (format) out[name] = format;
  }
  return out;
}

/**
 * A number as text, through the module's formatter when there is one.
 *
 * **Unformatted stays `toLocaleString()`.** That is what both surfaces already
 * wrote before p.174's option existed, and `formatValue(n, null)` is
 * `String(n)` — so routing the no-formatter case through it would quietly drop
 * the thousands separator from every table and card that never asked for
 * anything.
 */
export function showNumber(value: number, format: NumberFormat | null): string {
  if (!format) return value.toLocaleString();
  return formatValue(value, format) ?? value.toLocaleString();
}

/**
 * How the panel describes a formatter in one line, so a builder can see what
 * is set without opening the dialog.
 *
 * p.329's own worked example is the shape to aim for — "setting the maximum
 * fraction digits to 2 displays 3.14159 as 3.14" — so this says what it does
 * to a number rather than naming its fields.
 */
export function formatSummary(format: NumberFormat | null, sample = 1234.5678): string {
  if (!format) return "Not formatted";
  return `${sample.toLocaleString()} → ${showNumber(sample, format)}`;
}
