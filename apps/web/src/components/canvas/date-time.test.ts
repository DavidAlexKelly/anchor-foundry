import { describe, expect, it } from "vitest";

import {
  COMMON_ZONES, DATE_FORMATS, DEFAULT_DATE_FORMAT, DEFAULT_PRECISION, PRECISIONS,
  TIME_FORMATS, ZONE_MODES, formatDisplay, fromLocalInput, isZone, offsetAt,
  toLocalInput, truncate, zoneLabel, zoneOf, type Precision,
} from "./date-time";

/** p.463–464's Date and Time Picker. */

const UTC = "UTC";
/** **This is also the zone `vitest.config.ts` runs the suite in**, deliberately
 * (see the note there). That makes it the right zone for the DST cases, which
 * assert exact instants — and the *wrong* zone for any assertion whose point is
 * that a value differs from the viewer's own, because there the two coincide
 * and the assertion cannot fail. §205's harness found one such test. */
const NY = "America/New_York";
/** A half-hour offset, which is where an implementation that stores offsets as
 * whole hours falls over. */
const KOLKATA = "Asia/Kolkata";

/** A zone the suite is provably not running in, whatever it is running in.
 * Computed rather than named, so this stays true if the config's `TZ` changes. */
function notLocal(): string {
  const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return local === "Asia/Tokyo" ? "Europe/Berlin" : "Asia/Tokyo";
}

describe("the catalogues", () => {
  it("has p.464's two time formats", () => {
    expect(Object.keys(TIME_FORMATS).sort()).toEqual(["h12", "h24"]);
  });

  it("has p.464's three precisions", () => {
    expect(Object.keys(PRECISIONS).sort()).toEqual(["millisecond", "minute", "second"]);
  });

  it("has p.464's three ways of choosing a zone", () => {
    expect(Object.keys(ZONE_MODES).sort()).toEqual(["fixed", "local", "variable"]);
  });

  it("defaults to the coarsest precision", () => {
    // Named rather than compared to the constant (§203): minutes is what a
    // picker should open at, because a widget that demands milliseconds of
    // somebody choosing a meeting time is asking a question they do not have.
    expect(DEFAULT_PRECISION).toBe("minute");
  });

  it("gives every precision a step the control understands", () => {
    expect(PRECISIONS.minute.step).toBe(60);
    expect(PRECISIONS.second.step).toBe(1);
    expect(PRECISIONS.millisecond.step).toBe(0.001);
  });

  it("gives every date format a label and options", () => {
    for (const [name, format] of Object.entries(DATE_FORMATS)) {
      expect(format.label, name).toBeTruthy();
      expect(Object.keys(format.options).length, name).toBeGreaterThan(0);
    }
  });

  it("has a default date format that is in the catalogue", () => {
    expect(DATE_FORMATS[DEFAULT_DATE_FORMAT]).toBeDefined();
  });

  it("offers only zones Intl recognises", () => {
    // A dropdown entry that throws when chosen is worse than one that is
    // missing: it takes the module with it.
    for (const zone of COMMON_ZONES) expect(isZone(zone), zone).toBe(true);
  });
});

describe("isZone", () => {
  it("accepts a real zone and refuses anything else", () => {
    expect(isZone("Europe/London")).toBe(true);
    expect(isZone("Mars/Olympus")).toBe(false);
    expect(isZone("")).toBe(false);
    expect(isZone(null)).toBe(false);
    expect(isZone(7)).toBe(false);
  });
});

describe("zoneOf", () => {
  it("uses the fixed zone when one is chosen", () => {
    expect(zoneOf("fixed", NY, "Asia/Tokyo")).toBe(NY);
  });

  it("uses the variable's value in variable mode", () => {
    // p.464's "dynamically using a variable".
    expect(zoneOf("variable", NY, "Asia/Tokyo")).toBe("Asia/Tokyo");
  });

  it("falls back to the viewer's own zone rather than throwing", () => {
    // **A variable holds whatever a derivation put in it.** An unknown zone
    // makes `Intl` throw, which in a render is a blank module rather than a
    // wrong time — so a bad value shows the viewer's own time, which is wrong
    // in a way they can see and correct.
    // **Every zone passed in here has to be one the suite is not running in.**
    // The first version used `NY`, which *is* the suite's own zone — so a
    // mutant that returned the fixed zone in local mode returned the same
    // answer as the fallback, and the assertion could not fail.
    const local = zoneOf("local", null, null);
    const other = notLocal();
    expect(isZone(local)).toBe(true);
    expect(other).not.toBe(local);
    expect(zoneOf("variable", other, "Mars/Olympus")).toBe(local);
    expect(zoneOf("fixed", "Mars/Olympus", other)).toBe(local);
    expect(zoneOf("something else", other, other)).toBe(local);
  });
});

describe("offsetAt", () => {
  it("is zero for UTC", () => {
    expect(offsetAt(new Date("2026-03-01T12:00:00Z"), UTC)).toBe(0);
  });

  it("follows a DST transition", () => {
    // New York moves from -05:00 to -04:00 at 07:00 UTC on 8 March 2026.
    expect(offsetAt(new Date("2026-03-08T06:00:00Z"), NY)).toBe(-300);
    expect(offsetAt(new Date("2026-03-08T08:00:00Z"), NY)).toBe(-240);
  });

  it("handles a half-hour zone", () => {
    expect(offsetAt(new Date("2026-03-01T12:00:00Z"), KOLKATA)).toBe(330);
  });
});

describe("truncate", () => {
  it("keeps everything at millisecond precision", () => {
    expect(truncate(1_700_000_000_123, "millisecond")).toBe(1_700_000_000_123);
  });

  it("drops milliseconds at second precision", () => {
    expect(truncate(1_700_000_000_123, "second")).toBe(1_700_000_000_000);
  });

  it("drops seconds at minute precision", () => {
    expect(truncate(1_700_000_047_123, "minute")).toBe(1_700_000_040_000);
  });

  it("truncates downward before 1970, not upward", () => {
    // **The one direction "truncate" must never go.** A remainder subtraction
    // rounds *up* for a negative instant, which would put a value a minute
    // later than the one somebody picked.
    const before = Date.UTC(1969, 0, 1, 0, 0, 30, 500);
    expect(truncate(before, "minute")).toBe(Date.UTC(1969, 0, 1, 0, 0, 0, 0));
    expect(truncate(before, "second")).toBe(Date.UTC(1969, 0, 1, 0, 0, 30, 0));
  });
});

describe("toLocalInput", () => {
  it("writes the wall clock in the given zone", () => {
    const iso = "2026-03-01T12:00:00.000Z";
    expect(toLocalInput(iso, UTC, "minute")).toBe("2026-03-01T12:00");
    expect(toLocalInput(iso, NY, "minute")).toBe("2026-03-01T07:00");
    expect(toLocalInput(iso, KOLKATA, "minute")).toBe("2026-03-01T17:30");
  });

  it("shows as much as the precision asks for", () => {
    const iso = "2026-03-01T12:34:56.789Z";
    expect(toLocalInput(iso, UTC, "minute")).toBe("2026-03-01T12:34");
    expect(toLocalInput(iso, UTC, "second")).toBe("2026-03-01T12:34:56");
    expect(toLocalInput(iso, UTC, "millisecond")).toBe("2026-03-01T12:34:56.789");
  });

  it("is empty for no value", () => {
    // Which is what the control shows when it is empty - the two have to agree
    // or the field clears itself on the first render.
    for (const empty of [null, undefined, ""]) {
      expect(toLocalInput(empty, UTC, "minute")).toBe("");
    }
  });

  it("is empty for something that is not a date", () => {
    expect(toLocalInput("not a date", UTC, "minute")).toBe("");
    expect(toLocalInput({}, UTC, "minute")).toBe("");
  });

  it("does not roll the day back at midnight", () => {
    // `hour12: false` is the option that historically resolved to `h24` in some
    // engines, rendering midnight as 24 and making the day one too small when
    // read back. `hourCycle: "h23"` makes that impossible by construction.
    expect(toLocalInput("2026-03-01T00:00:00.000Z", UTC, "minute")).toBe("2026-03-01T00:00");
    expect(toLocalInput("2026-03-01T05:00:00.000Z", NY, "minute")).toBe("2026-03-01T00:00");
  });
});

describe("fromLocalInput", () => {
  it("reads a wall clock in the given zone back to an instant", () => {
    expect(fromLocalInput("2026-03-01T12:00", UTC, "minute")).toBe("2026-03-01T12:00:00.000Z");
    expect(fromLocalInput("2026-03-01T07:00", NY, "minute")).toBe("2026-03-01T12:00:00.000Z");
    expect(fromLocalInput("2026-03-01T17:30", KOLKATA, "minute")).toBe("2026-03-01T12:00:00.000Z");
  });

  it("applies the precision to the stored instant", () => {
    // Not merely to what is shown: a value displayed as 09:30 that is really
    // 09:30:47 will not compare equal to the 09:30 somebody else picked.
    expect(fromLocalInput("2026-03-01T12:34:56.789", UTC, "minute"))
      .toBe("2026-03-01T12:34:00.000Z");
    expect(fromLocalInput("2026-03-01T12:34:56.789", UTC, "second"))
      .toBe("2026-03-01T12:34:56.000Z");
    expect(fromLocalInput("2026-03-01T12:34:56.789", UTC, "millisecond"))
      .toBe("2026-03-01T12:34:56.789Z");
  });

  it("is null for an empty or unparseable field", () => {
    for (const bad of ["", "   ", "not a date", "2026-03-01", null, 7]) {
      expect(fromLocalInput(bad, UTC, "minute"), String(bad)).toBeNull();
    }
  });

  it("refuses digits that are the right shape and the wrong number", () => {
    // **The regex counts digits; it does not check they mean anything.**
    // `Date.UTC` rolls month 13 into the next year and day 45 into the next
    // month, so this used to become a real instant almost a year away -
    // silently. A control cannot produce it; a saved document or a variable
    // can.
    expect(fromLocalInput("2026-13-45T99:99", UTC, "minute")).toBeNull();
    expect(fromLocalInput("2026-00-01T00:00", UTC, "minute")).toBeNull();
    expect(fromLocalInput("2026-03-01T24:00", UTC, "minute")).toBeNull();
    expect(fromLocalInput("2026-03-01T12:60", UTC, "minute")).toBeNull();
  });

  it("refuses a day that does not exist in its month", () => {
    // Which no range check would catch: 31 is a legal day and February is a
    // legal month.
    expect(fromLocalInput("2026-02-31T12:00", UTC, "minute")).toBeNull();
    expect(fromLocalInput("2026-02-29T12:00", UTC, "minute")).toBeNull();
    // ...and 2028 is a leap year, so the same date is fine there.
    expect(fromLocalInput("2028-02-29T12:00", UTC, "minute")).toBe("2028-02-29T12:00:00.000Z");
  });

  it("pads a short fractional second", () => {
    expect(fromLocalInput("2026-03-01T12:00:00.5", UTC, "millisecond"))
      .toBe("2026-03-01T12:00:00.500Z");
  });

  it("resolves the hour after a DST change correctly", () => {
    // **Where a single-pass offset lookup is wrong**, and the day somebody will
    // pick it. New York springs forward at 02:00 local on 8 March 2026; 03:00
    // local that morning is 07:00 UTC, not 08:00.
    expect(fromLocalInput("2026-03-08T03:00", NY, "minute")).toBe("2026-03-08T07:00:00.000Z");
    expect(fromLocalInput("2026-03-08T01:00", NY, "minute")).toBe("2026-03-08T06:00:00.000Z");
  });
});

describe("toLocalInput and fromLocalInput round-trip", () => {
  /** Asserted as a property, not by example. **The zone must not change what
   * is stored** — that is the whole inversion of §202's percent rule — and a
   * widget where picking a time and reading it back gives a different time is
   * a widget that edits its own data. */
  const instants = [
    "2026-03-01T12:00:00.000Z",
    "2026-01-15T23:59:00.000Z",
    "2026-07-04T00:00:00.000Z",
    // Either side of New York's spring-forward.
    "2026-03-08T06:30:00.000Z",
    "2026-03-08T08:30:00.000Z",
    // And its autumn fall-back, where a local hour happens twice.
    "2026-11-01T05:30:00.000Z",
    "1969-12-31T23:59:00.000Z",
  ];

  for (const zone of [UTC, NY, KOLKATA]) {
    for (const precision of ["minute", "second", "millisecond"] as Precision[]) {
      for (const iso of instants) {
        it(`survives ${iso} in ${zone} at ${precision}`, () => {
          const shown = toLocalInput(iso, zone, precision);
          expect(fromLocalInput(shown, zone, precision)).toBe(iso);
        });
      }
    }
  }

  it("survives a second trip through the field", () => {
    // The realistic case: somebody picks, the control reformats, they edit the
    // reformatted value. If that is not stable the instant walks on every edit.
    const once = fromLocalInput("2026-03-08T03:00", NY, "minute");
    const shown = toLocalInput(once, NY, "minute");
    expect(fromLocalInput(shown, NY, "minute")).toBe(once);
  });
});

describe("formatDisplay", () => {
  it("is empty for no value", () => {
    expect(formatDisplay(null, UTC, "iso", "h24", "minute")).toBe("");
    expect(formatDisplay("nonsense", UTC, "iso", "h24", "minute")).toBe("");
  });

  it("shows the time in the given zone", () => {
    const iso = "2026-03-01T12:00:00.000Z";
    expect(formatDisplay(iso, UTC, "iso", "h24", "minute")).toContain("12:00");
    expect(formatDisplay(iso, NY, "iso", "h24", "minute")).toContain("07:00");
  });

  it("honours p.464's 12-hour and 24-hour clocks", () => {
    const iso = "2026-03-01T19:00:00.000Z";
    expect(formatDisplay(iso, UTC, "iso", "h12", "minute")).toMatch(/7:00\s*PM/i);
    expect(formatDisplay(iso, UTC, "iso", "h24", "minute")).toContain("19:00");
  });

  it("shows seconds only when the precision asks for them", () => {
    const iso = "2026-03-01T12:34:56.789Z";
    expect(formatDisplay(iso, UTC, "iso", "h24", "minute")).not.toContain("56");
    expect(formatDisplay(iso, UTC, "iso", "h24", "second")).toContain("56");
    expect(formatDisplay(iso, UTC, "iso", "h24", "millisecond")).toContain(".789");
  });

  it("falls back to the default date format for one it does not know", () => {
    const iso = "2026-03-01T12:00:00.000Z";
    expect(formatDisplay(iso, UTC, "klingon", "h24", "minute"))
      .toBe(formatDisplay(iso, UTC, DEFAULT_DATE_FORMAT, "h24", "minute"));
    expect(formatDisplay(iso, UTC, "constructor", "h24", "minute"))
      .toBe(formatDisplay(iso, UTC, DEFAULT_DATE_FORMAT, "h24", "minute"));
  });

  it("uses a different date format when asked", () => {
    const iso = "2026-03-01T12:00:00.000Z";
    expect(formatDisplay(iso, UTC, "long", "h24", "minute")).toContain("March");
    expect(formatDisplay(iso, UTC, "iso", "h24", "minute")).not.toContain("March");
  });
});

describe("zoneLabel", () => {
  it("names the zone and its offset at that moment", () => {
    // The name alone does not say what time it is; the offset alone does not
    // say which zone, since it changes twice a year.
    expect(zoneLabel(UTC, "2026-03-01T12:00:00Z")).toContain("UTC");
    expect(zoneLabel(NY, "2026-03-01T12:00:00Z")).toContain("GMT-5");
    expect(zoneLabel(NY, "2026-07-01T12:00:00Z")).toContain("GMT-4");
  });

  it("returns an unknown zone unchanged rather than throwing", () => {
    expect(zoneLabel("Mars/Olympus")).toBe("Mars/Olympus");
  });
});
