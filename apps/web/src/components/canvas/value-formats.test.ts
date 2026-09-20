import { describe, expect, it } from "vitest";

import {
  formatSummary, formatsByColumn, numberFormatOf, showNumber, type NumberFormat,
} from "./value-formats";
import { NO_VALUE, valueLabel } from "./metric-card";

/**
 * p.174's value formatting inside a Workshop module, and p.328's "Numeric
 * formatting" which points at it.
 *
 * Almost every test here is about a formatter being **refused**, because that
 * is what this module is for: `formatValue` already renders a good one, and
 * the failure this prevents is a bad one rendering *halfway* - a document
 * written by the raw JSON editor (§212) or by an older build, applied to some
 * values and silently skipped on others.
 */

const PLAIN: NumberFormat = { kind: "number", style: "plain" };

describe("reading a stored formatter", () => {
  it("keeps a formatter that will apply", () => {
    const format = { kind: "number", style: "currency", currency: "USD" };
    expect(numberFormatOf(format)).toBe(format);
  });

  it("drops anything that is not an object", () => {
    for (const raw of [null, undefined, "", 0, 7, "plain", true, [PLAIN]]) {
      expect(numberFormatOf(raw)).toBeNull();
    }
  });

  it("drops a datetime formatter, because both p.174 surfaces are numbers", () => {
    // Not merely unsupported: `formatValue` handed this and a number would
    // parse `1234` as a date, fail, and hand the digits back - a formatter
    // that reads as configured and does nothing at all.
    expect(numberFormatOf({ kind: "datetime", style: "datetime_short" })).toBeNull();
    // **The second one is what makes the `kind` line load-bearing**, and the
    // first on its own did not. §157's two families name no style in common,
    // so every formatter §157's editor can produce is refused by the style
    // list whether the kind is checked or not - deleting the check left the
    // case above passing. A hand-written hybrid is the shape that separates
    // them, and §212 is the reason one can exist: the raw JSON editor holds
    // whatever somebody types.
    expect(numberFormatOf({ kind: "datetime", style: "plain" })).toBeNull();
    expect(numberFormatOf({ kind: "datetime", style: "currency", currency: "USD" }))
      .toBeNull();
  });

  it("drops a style the editor never offers", () => {
    expect(numberFormatOf({ kind: "number", style: "fixed_values" })).toBeNull();
    expect(numberFormatOf({ kind: "number" })).toBeNull();
  });

  it("drops a style missing the thing that style is for", () => {
    // Each of these throws in `Intl.NumberFormat`, which in a cell is the
    // unformatted number appearing for no stated reason.
    expect(numberFormatOf({ kind: "number", style: "currency" })).toBeNull();
    expect(numberFormatOf({ kind: "number", style: "currency", currency: "US" })).toBeNull();
    expect(numberFormatOf({ kind: "number", style: "unit" })).toBeNull();
    expect(numberFormatOf({ kind: "number", style: "unit", unit: "  " })).toBeNull();
    // An affix with neither side formats nothing - the one case where the
    // formatter does not throw and still means nothing.
    expect(numberFormatOf({ kind: "number", style: "affix", prefix: "", suffix: "" })).toBeNull();
    expect(numberFormatOf({ kind: "number", style: "affix", suffix: " kg" })).not.toBeNull();
  });

  it("drops digit counts outside the range Intl accepts", () => {
    // `services/value_format.py`'s `DIGIT_BOUNDS`, which are `Intl`'s own.
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: 101 })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: -1 })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, minimum_integer_digits: 0 })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, minimum_significant_digits: 22 })).toBeNull();
    // Whole numbers only: `Intl` rounds a fraction silently, so `2.5` would
    // become a setting nobody chose.
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: 2.5 })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: "2" })).toBeNull();
    // The edges themselves are legal.
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: 0 })).not.toBeNull();
    expect(numberFormatOf({ ...PLAIN, maximum_fraction_digits: 100 })).not.toBeNull();
  });

  it("drops a crossed min/max pair", () => {
    expect(numberFormatOf({
      ...PLAIN, minimum_fraction_digits: 4, maximum_fraction_digits: 2,
    })).toBeNull();
    expect(numberFormatOf({
      ...PLAIN, minimum_significant_digits: 5, maximum_significant_digits: 2,
    })).toBeNull();
    // Equal is not crossed.
    expect(numberFormatOf({
      ...PLAIN, minimum_fraction_digits: 2, maximum_fraction_digits: 2,
    })).not.toBeNull();
  });

  it("drops an unknown notation and a non-boolean grouping", () => {
    expect(numberFormatOf({ ...PLAIN, notation: "roman" })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, notation: "compact" })).not.toBeNull();
    expect(numberFormatOf({ ...PLAIN, grouping: "yes" })).toBeNull();
    expect(numberFormatOf({ ...PLAIN, grouping: false })).not.toBeNull();
  });
});

describe("the Object Table's per-column map", () => {
  it("keys formatters by property name and drops the ones that would not apply", () => {
    expect(formatsByColumn({
      readings: { kind: "number", style: "plain", maximum_fraction_digits: 1 },
      pressure: { kind: "datetime", style: "date" },
      flow: "compact",
    })).toEqual({
      readings: { kind: "number", style: "plain", maximum_fraction_digits: 1 },
    });
  });

  it("is empty for anything that is not a map", () => {
    for (const raw of [null, undefined, [], "readings", 3]) {
      expect(formatsByColumn(raw)).toEqual({});
    }
  });
});

describe("writing a number", () => {
  it("localises when nothing is set", () => {
    // The thousands separator is the point: `formatValue(n, null)` is
    // `String(n)`, so routing the unformatted case through it would strip the
    // grouping every table and card has always had.
    expect(showNumber(1234567, null)).toBe((1234567).toLocaleString());
    expect(showNumber(1234567, null)).not.toBe("1234567");
  });

  it("applies p.329's own worked example", () => {
    // "setting the maximum fraction digits to 2 displays 3.14159 as 3.14"
    expect(showNumber(3.14159, { ...PLAIN, maximum_fraction_digits: 2 })).toBe("3.14");
  });

  it("applies the rest of p.97-98's options through §157's one formatter", () => {
    expect(showNumber(100000, { kind: "number", style: "currency", currency: "USD", notation: "compact" }))
      .toBe("$100K");
    expect(showNumber(3.5, { ...PLAIN, minimum_fraction_digits: 2 })).toBe("3.50");
    expect(showNumber(1234, { ...PLAIN, grouping: false })).toBe("1234");
  });
});

describe("what the settings button says", () => {
  it("names the absence rather than showing a blank button", () => {
    expect(formatSummary(null)).toBe("Not formatted");
  });

  it("shows the effect on a number rather than the field names", () => {
    // p.329 explains its own option with a before and an after, for the
    // reason a builder cannot picture "maximumFractionDigits: 2".
    const summary = formatSummary({ ...PLAIN, maximum_fraction_digits: 0 }, 3.14159);
    expect(summary).toBe("3.142 → 3");
    expect(summary).not.toContain("maximum");
  });
});

describe("the Metric Card's number (p.328)", () => {
  it("formats the figure", () => {
    expect(valueLabel(1234.5678, { ...PLAIN, maximum_fraction_digits: 1 })).toBe("1,234.6");
  });

  it("leaves the unformatted card exactly as it was", () => {
    expect(valueLabel(1234)).toBe((1234).toLocaleString());
  });

  it("does not format the empty answer into a zero", () => {
    // §226 made an aggregation over an empty set answer nothing, and a
    // currency formatter that turned that into `$0.00` would be a card
    // reporting a figure it never had - undone by a display option.
    expect(valueLabel(null, { kind: "number", style: "currency", currency: "USD" }))
      .toBe(NO_VALUE);
    expect(valueLabel(undefined, { ...PLAIN, minimum_fraction_digits: 2 })).toBe(NO_VALUE);
  });
});
