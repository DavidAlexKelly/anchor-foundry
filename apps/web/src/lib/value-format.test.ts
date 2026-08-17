/**
 * Applying a value formatter (Foundry `object-link-types` p.94–101).
 *
 * The server's job is to refuse a formatter that would not render, and that is
 * tested in `apps/api/tests/test_value_format.py`. This is the other half:
 * given a formatter that saved, what does a reader actually see.
 *
 * Every expectation here is a **string**, not a shape. "It called Intl" is not
 * the claim — "$100K" is, and p.94 is where that example comes from.
 *
 * Note the suite's timezone: `vitest.config.ts` pins `TZ=America/New_York`
 * deliberately, so a test of "render this instant in Europe/London" fails if
 * the timezone option is dropped. On a UTC machine that mutation is invisible.
 */
import { describe, expect, it } from "vitest";

import type { ValueFormat } from "@/lib/types";
import { formatValue } from "./value-format";

/** 2020-07-22T13:00:00Z — p.99's own example instant. */
const AT = "2020-07-22T13:00:00.000Z";

function fmt(raw: unknown, format: ValueFormat | null, now?: number) {
  return formatValue(raw, format, now === undefined ? {} : { now });
}

describe("no formatter", () => {
  it("shows the value as it is", () => {
    expect(fmt(100000, null)).toBe("100000");
    expect(fmt("north", null)).toBe("north");
  });

  it("tells a missing value apart from an empty one", () => {
    // A caller needs the difference: a formatted zero is "$0" and must not
    // read as a blank.
    expect(fmt(null, null)).toBeNull();
    expect(fmt(undefined, null)).toBeNull();
    expect(fmt("", null)).toBeNull();
    expect(fmt(0, { kind: "number", style: "currency", currency: "USD" })).toBe("$0.00");
  });
});

describe("numeric formatting (p.94, p.97–98)", () => {
  it("renders p.94's own two examples", () => {
    // "the value column is displayed in a more compact form with a currency
    // sign ($100K)"
    expect(
      fmt(100000, {
        kind: "number", style: "currency", currency: "USD", notation: "compact",
        maximum_fraction_digits: 0,
      }),
    ).toBe("$100K");
    // "a unit (kg) applied to the weight column"
    expect(
      fmt(72.5, {
        kind: "number", style: "unit", unit: "kilogram", maximum_fraction_digits: 1,
      }),
    ).toBe("72.5 kg");
  });

  it("groups with the locale's separator (p.97)", () => {
    // p.97's own usage note: "Toggle this on to go from 123456 to 123,456."
    expect(fmt(123456, { kind: "number", style: "plain", grouping: true })).toBe("123,456");
    expect(fmt(123456, { kind: "number", style: "plain", grouping: false })).toBe("123456");
  });

  it("rounds and pads to the digit counts p.98 describes", () => {
    // "Set to 2 to display 3.14159 as 3.14."
    expect(fmt(3.14159, { kind: "number", style: "plain", maximum_fraction_digits: 2 }))
      .toBe("3.14");
    // "Set to 2 to display 3.5 as 3.50."
    expect(fmt(3.5, { kind: "number", style: "plain", minimum_fraction_digits: 2 }))
      .toBe("3.50");
    // "Set maximum significant digits to 3 to display 3.14159 as 3.14."
    expect(fmt(3.14159, { kind: "number", style: "plain", maximum_significant_digits: 3 }))
      .toBe("3.14");
    // "Set to 2 to display 5 as 05."
    expect(fmt(5, { kind: "number", style: "plain", minimum_integer_digits: 2 })).toBe("05");
  });

  it("wraps with a prefix and a suffix (p.97's Prefix/Suffix)", () => {
    expect(fmt(12, { kind: "number", style: "affix", prefix: "~", suffix: " units" }))
      .toBe("~12 units");
    // Either alone is a legal formatter; the server refuses only *neither*.
    expect(fmt(12, { kind: "number", style: "affix", prefix: "", suffix: "%%" }))
      .toBe("12%%");
  });

  it("renders a percentage as one", () => {
    expect(fmt(0.25, { kind: "number", style: "percent" })).toBe("25%");
  });

  it("reads a number that arrived as text", () => {
    // Properties are stored untyped, so a `float` column commonly holds "72.5"
    // rather than 72.5 — and a formatter that only handled the number would
    // leave every synced value unformatted.
    expect(fmt("72.5", { kind: "number", style: "unit", unit: "kilogram" })).toBe("72.5 kg");
  });

  it("shows a non-numeric value as itself rather than as NaN", () => {
    // A dataset nobody cleaned puts "n/a" in a numeric column. "NaN" reads
    // like a computed answer; the stored text reads like what is stored.
    expect(fmt("n/a", { kind: "number", style: "currency", currency: "USD" })).toBe("n/a");
  });
});

describe("date and time formatting (p.99–100)", () => {
  it("renders each style p.99 lists", () => {
    const styles: [string, string][] = [
      ["date", "Wed, Jul 22, 2020"],
      ["datetime_long", "Wed, July 22, 2020 at 1:00:00 PM"],
      ["datetime_short", "Jul 22, 2020, 1:00 PM"],
      ["time", "1:00 PM"],
    ];
    for (const [style, expected] of styles) {
      const got = fmt(AT, {
        kind: "datetime",
        style: style as "date",
        timezone: "UTC",
      });
      // The style is in the assertion so a failure names which row broke.
      expect(`${style}: ${got}`).toBe(`${style}: ${expected}`);
    }
  });

  it("renders an ISO instant as one", () => {
    expect(fmt(AT, { kind: "datetime", style: "iso", timezone: "UTC" })).toBe(AT);
  });

  it("places the instant in the zone the property names (p.100)", () => {
    // The same instant, three zones, three different clock readings — which is
    // the whole of what a timezone option is for. This suite runs in New York
    // (see `vitest.config.ts`), so the middle case is not the machine's own.
    const at = "2020-07-22T01:30:00.000Z";
    const style = { kind: "datetime", style: "datetime_short" } as const;
    expect(fmt(at, { ...style, timezone: "UTC" })).toBe("Jul 22, 2020, 1:30 AM");
    expect(fmt(at, { ...style, timezone: "Asia/Tokyo" })).toBe("Jul 22, 2020, 10:30 AM");
    // No timezone means the viewer's, and the viewer here is in New York —
    // where that instant is still the previous day.
    expect(fmt(at, style)).toBe("Jul 21, 2020, 9:30 PM");
  });
});

describe("relative to now (p.99's footnote)", () => {
  const now = Date.parse(AT);

  it("counts back in the largest unit that fits", () => {
    // p.94's own example of a relative rendering is "8 minutes ago".
    expect(fmt(new Date(now - 8 * 60 * 1000).toISOString(),
               { kind: "datetime", style: "relative" }, now)).toBe("8 minutes ago");
    expect(fmt(new Date(now - 3 * 60 * 60 * 1000).toISOString(),
               { kind: "datetime", style: "relative" }, now)).toBe("3 hours ago");
    expect(fmt(new Date(now - 20 * 1000).toISOString(),
               { kind: "datetime", style: "relative" }, now)).toBe("20 seconds ago");
  });

  it("works forwards too", () => {
    expect(fmt(new Date(now + 2 * 60 * 60 * 1000).toISOString(),
               { kind: "datetime", style: "relative" }, now)).toBe("in 2 hours");
  });

  it("stops being relative after 24 hours, and gains a weekday", () => {
    /**
     * p.99, verbatim: "applications will only format in relative terms up to
     * 24 hours ago. After this, it will render in Date and time (short) form
     * **with the day of the week**: Wed, Jul 22, 2020, 1:00 PM."
     *
     * The weekday is the part that makes this its own branch rather than a
     * fall-through to `datetime_short` — which renders the same instant
     * *without* one, and the second assertion is what holds the two apart.
     */
    const old = "2020-07-20T13:00:00.000Z"; // two days before `now`
    expect(fmt(old, { kind: "datetime", style: "relative", timezone: "UTC" }, now))
      .toBe("Mon, Jul 20, 2020, 1:00 PM");
    expect(fmt(old, { kind: "datetime", style: "datetime_short", timezone: "UTC" }, now))
      .toBe("Jul 20, 2020, 1:00 PM");
  });

  it("switches at the boundary rather than near it", () => {
    const style = { kind: "datetime", style: "relative", timezone: "UTC" } as const;
    const justInside = new Date(now - (24 * 60 * 60 * 1000 - 1000)).toISOString();
    const justOutside = new Date(now - 24 * 60 * 60 * 1000).toISOString();
    // Truncated rather than rounded: rounding would read "24 hours ago" here,
    // naming the very boundary this side of the branch exists to stay inside.
    expect(fmt(justInside, style, now)).toBe("23 hours ago");
    expect(fmt(justOutside, style, now)).toBe("Tue, Jul 21, 2020, 1:00 PM");
  });
});

describe("what does not render", () => {
  it("shows an unparseable date as itself rather than as Invalid Date", () => {
    expect(fmt("soon", { kind: "datetime", style: "date" })).toBe("soon");
  });

  it("falls back to the plain number if Intl refuses the options", () => {
    // The server refuses this pair, so reaching it means a formatter that
    // predates the rule. A blank cell is the one outcome that tells a reader
    // nothing, so the number is still shown.
    expect(
      fmt(3.5, {
        kind: "number", style: "plain",
        minimum_fraction_digits: 3, maximum_fraction_digits: 1,
      }),
    ).toBe("3.5");
  });
});
