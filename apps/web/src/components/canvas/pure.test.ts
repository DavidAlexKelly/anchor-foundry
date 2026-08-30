/** Unit tests for the canvas widgets' arithmetic and formatting.
 *
 * **What belongs here**: functions from `pure.ts` — no React, no DOM, no
 * rendering. **What does not**: anything about whether a widget draws the
 * right thing or responds to a click. That lives in `e2e/`, against real
 * servers in a real browser, because a jsdom test that passes while the real
 * application is broken is worse than no test at all.
 *
 * Several of the cases below exist because the browser suite could only reach
 * them through pixels, or could not reach them at all: a 30-part section, a
 * weights string somebody is halfway through typing, a month bucket in a zone
 * behind UTC.
 */
import { describe, expect, it } from "vitest";

import {
  MIN_SHARE, formatWeights, parseWeights, pivotClauses, resizeWeights, roundWeight,
  seedActionForm, seedFromQuery, seriesLabel, seriesPointLabel,
} from "./pure";

describe("pivotClauses", () => {
  it("writes one clause per axis that is picked", () => {
    expect(pivotClauses({ row: "north", column: "open" }, "region", "status")).toEqual([
      { property: "region", op: "eq", value: "north" },
      { property: "status", op: "eq", value: "open" },
    ]);
  });

  it("omits an axis rather than writing an empty value for it", () => {
    // A clause with `value: ""` narrows to the objects whose property *is* the
    // empty string, which is a different set and usually none. Clearing an
    // axis has to be the absence of its clause.
    expect(pivotClauses({ row: "north", column: null }, "region", "status")).toEqual([
      { property: "region", op: "eq", value: "north" },
    ]);
    expect(pivotClauses({ row: null, column: null }, "region", "status")).toEqual([]);
  });

  it("keeps the row clause first, so a narrowing reads in the grid's order", () => {
    const [first] = pivotClauses({ row: "a", column: "b" }, "region", "status");
    expect(first?.property).toBe("region");
  });
});

describe("seriesLabel", () => {
  // Fixed instants, so these say the same thing wherever they run. The zone is
  // pinned in the function; the locale is the runner's, which is why the
  // assertions are about *content* rather than exact punctuation.
  const midnightUtc = "2024-03-04T00:00:00Z";

  it("labels a day bucket by its own UTC date", () => {
    expect(seriesLabel(midnightUtc, "day")).toContain("4");
    expect(seriesLabel(midnightUtc, "day")).not.toContain("w/c");
  });

  it("marks a week bucket as a week", () => {
    // A bucket labelled like a day when it is a week is the chart quietly
    // claiming a resolution it does not have.
    expect(seriesLabel(midnightUtc, "week")).toMatch(/^w\/c /);
  });

  it("gives a month bucket its year, since months repeat and days do not", () => {
    expect(seriesLabel(midnightUtc, "month")).toContain("2024");
  });

  it("puts a month bucket in the month UTC says, not the local one", () => {
    // **The first of a month is where the two diverge**, and nowhere else. A
    // mutation deleting the month formatter's `timeZone` survived a test that
    // used the 4th: in New York that instant is still March, so the label did
    // not move. Midnight UTC on the 1st is the previous *month* locally.
    const firstOfMarch = "2024-03-01T00:00:00Z";
    expect(new Date(firstOfMarch).getTimezoneOffset()).toBeGreaterThan(0);
    expect(seriesLabel(firstOfMarch, "month")).toMatch(/Mar/);
    expect(seriesLabel(firstOfMarch, "month")).not.toMatch(/Feb/);
  });

  it("formats in UTC, not the machine's zone", () => {
    // **The guard this test depends on, checked first.** `vitest.config.ts`
    // pins the process to a zone behind UTC, because on a UTC machine this
    // assertion passes against code with the `timeZone` option deleted — a
    // mutation proved exactly that. A test that sets up its own condition can
    // fail to set it up, and then it is green while testing nothing.
    const offset = new Date(midnightUtc).getTimezoneOffset();
    expect(offset, "the test process must not be running in UTC").toBeGreaterThan(0);

    // An instant at the very start of a UTC day is the *previous* day anywhere
    // west of Greenwich. If this ever renders "3", the label has drifted into
    // local time and every bucket is off by one for half the world.
    expect(seriesLabel(midnightUtc, "day")).toContain("4");
    expect(seriesLabel("2024-03-04T23:59:59Z", "day")).toContain("4");
  });
});

describe("seriesPointLabel", () => {
  // A time series set (p.76) can be asked for by the hour or not bucketed at
  // all, which `seriesLabel`'s day-or-wider vocabulary cannot express.
  const morning = "2024-03-04T09:15:30Z";
  const evening = "2024-03-04T21:45:00Z";

  it("separates two readings on the same day, which a day label cannot", () => {
    // The failure this exists to prevent: a chart keyed on labels draws one
    // point per *distinct* label, so a day-only label over an unbucketed
    // series silently collapses a fortnight of readings into fourteen points.
    expect(seriesPointLabel(morning, "none")).not.toBe(
      seriesPointLabel(evening, "none"),
    );
    expect(seriesPointLabel(morning, "hour")).not.toBe(
      seriesPointLabel(evening, "hour"),
    );
    expect(seriesLabel(morning, "day")).toBe(seriesLabel(evening, "day"));
  });

  it("carries seconds only where two readings can differ by them", () => {
    // An hourly bucket always ends :00:00; printing that is noise on every
    // label of a crowded axis.
    expect(seriesPointLabel(morning, "none")).toContain("30");
    expect(seriesPointLabel(morning, "hour")).not.toContain("15");
  });

  it("reads the hour in UTC, not the machine's zone", () => {
    const offset = new Date(morning).getTimezoneOffset();
    expect(offset, "the test process must not be running in UTC").toBeGreaterThan(0);
    expect(seriesPointLabel(morning, "hour")).toContain("09");
    // And the date has not slipped back a day with it.
    expect(seriesPointLabel("2024-03-04T00:30:00Z", "none")).toContain("4");
  });

  it("hands the wider buckets to seriesLabel rather than relabelling them", () => {
    // One vocabulary for "which day is this", not two that can drift apart.
    for (const interval of ["day", "week", "month"]) {
      expect(seriesPointLabel(morning, interval)).toBe(seriesLabel(morning, interval));
    }
  });

  it("returns anything that is not a timestamp as itself", () => {
    // `at` is JSON from whatever column the dataset mapped. A mapping pointed
    // at the wrong column should show on the axis, not throw `Invalid Date`
    // from inside a chart.
    expect(seriesPointLabel("north", "none")).toBe("north");
    expect(seriesPointLabel(null, "day")).toBe("");
  });
});

describe("parseWeights", () => {
  it("gives one number per child", () => {
    expect(parseWeights("2,1", 2)).toEqual([2, 1]);
  });

  it("pads a short list rather than leaving children unsized", () => {
    expect(parseWeights("3", 3)).toEqual([3, 1, 1]);
    expect(parseWeights("", 2)).toEqual([1, 1]);
    expect(parseWeights(null, 2)).toEqual([1, 1]);
  });

  it("ignores extra numbers left behind by a deleted child", () => {
    expect(parseWeights("1,2,3", 2)).toEqual([1, 2]);
  });

  it("drops values that cannot be a proportion", () => {
    // The string is typed by hand, so it is malformed for as long as somebody
    // is halfway through typing it. A section must keep laying out sensibly
    // throughout, not just once the value is finished.
    expect(parseWeights("2,abc", 2)).toEqual([2, 1]);
    expect(parseWeights("-1,2", 2)).toEqual([2, 1]);
    expect(parseWeights("0,2", 2)).toEqual([2, 1]);
    expect(parseWeights("2,", 2)).toEqual([2, 1]);
  });

  it("tolerates spacing, because people type it", () => {
    expect(parseWeights(" 2 , 1 ", 2)).toEqual([2, 1]);
  });
});

describe("resizeWeights", () => {
  it("moves the boundary to the requested share of the pair", () => {
    expect(resizeWeights([1, 1], 0, 0.75)).toEqual([1.5, 0.5]);
  });

  it("keeps the pair's combined share fixed", () => {
    const before = [2, 4];
    const after = resizeWeights(before, 0, 0.25);
    expect(after[0]! + after[1]!).toBeCloseTo(before[0]! + before[1]!);
  });

  it("leaves every part outside the pair alone", () => {
    // Dragging one divider must not shuffle a column at the far end of the
    // section — the parts beyond the pair are not what the author grabbed.
    const after = resizeWeights([1, 1, 5, 9], 0, 0.9);
    expect(after.slice(2)).toEqual([5, 9]);
  });

  it("resizes an interior boundary without touching the ends", () => {
    const after = resizeWeights([3, 1, 1, 7], 1, 0.5);
    expect(after[0]).toBe(3);
    expect(after[3]).toBe(7);
    expect(after[1]! + after[2]!).toBeCloseTo(2);
  });

  it("refuses to drive either part to nothing", () => {
    // A part dragged to nothing leaves no handle to grab and no way back
    // except the Settings field.
    const collapsed = resizeWeights([1, 1], 0, -5);
    expect(collapsed[0]! / (collapsed[0]! + collapsed[1]!)).toBeCloseTo(MIN_SHARE);
    const swollen = resizeWeights([1, 1], 0, 5);
    expect(swollen[1]! / (swollen[0]! + swollen[1]!)).toBeCloseTo(MIN_SHARE);
  });

  it("is reversible, so the clamp is a floor and not a trap", () => {
    const there = resizeWeights([1, 1], 0, -5);
    const back = resizeWeights(there, 0, 0.5);
    expect(back[0]).toBeCloseTo(1);
    expect(back[1]).toBeCloseTo(1);
  });

  it("survives a section wider than anybody would build", () => {
    // 30 parts is not reachable in the browser suite in any reasonable time,
    // and is exactly where an off-by-one in the pair arithmetic would show.
    const many = Array.from({ length: 30 }, () => 1);
    const after = resizeWeights(many, 28, 0.9);
    expect(after).toHaveLength(30);
    expect(after.slice(0, 28)).toEqual(many.slice(0, 28));
    expect(after[28]! + after[29]!).toBeCloseTo(2);
  });
});

describe("roundWeight and formatWeights", () => {
  it("keeps the saved layout readable", () => {
    // `2.33,0.67` is a layout somebody can read and edit; sixteen decimal
    // places of float noise is not, and describability is the whole reason
    // proportions were typed before the drag handle existed.
    expect(formatWeights([1 / 3, 2 / 3])).toBe("0.33,0.67");
    expect(roundWeight(0.1 + 0.2)).toBe(0.3);
  });

  it("does not dress a whole number up as a decimal", () => {
    expect(formatWeights([2, 1])).toBe("2,1");
  });

  it("rounds a drag's output to something the field can round-trip", () => {
    const dragged = resizeWeights([1, 1], 0, 0.618);
    const written = formatWeights(dragged);
    expect(written).toBe("1.24,0.76");
    // And what comes back out of the field is what went in — a drag that
    // wrote a value the parser then read differently would drift a little on
    // every gesture.
    expect(parseWeights(written, 2)).toEqual([1.24, 0.76]);
  });
});

// ---- the module interface, initialised from a URL (Foundry p.165) ----------
describe("seedFromQuery", () => {
  const iface = (id: string, kind: string, externalId: string) => ({
    id,
    kind,
    external_id: externalId,
    interface: {},
  });

  it("seeds an interface variable from its external ID", () => {
    const seed = seedFromQuery(
      { v_a: iface("v_a", "string", "status") },
      new URLSearchParams("?status=open"),
    );
    expect(seed).toEqual({ v_a: "open" });
  });

  it("ignores a variable that has an external ID but is not on the interface", () => {
    // Otherwise every stable name - including ones that exist only for state
    // saving - becomes settable by anyone who can write a link.
    const seed = seedFromQuery(
      { v_a: { id: "v_a", kind: "string", external_id: "status" } },
      new URLSearchParams("?status=open"),
    );
    expect(seed).toEqual({});
  });

  it("leaves a variable alone when the query does not mention it", () => {
    const seed = seedFromQuery(
      { v_a: iface("v_a", "string", "status") },
      new URLSearchParams("?other=1"),
    );
    expect(seed).toEqual({});
  });

  it("parses numbers and booleans", () => {
    const seed = seedFromQuery(
      { v_n: iface("v_n", "number", "count"), v_b: iface("v_b", "boolean", "open") },
      new URLSearchParams("?count=42&open=true"),
    );
    expect(seed).toEqual({ v_n: 42, v_b: true });
  });

  it("skips a value it cannot parse rather than defaulting it", () => {
    // A wrong number is indistinguishable from a chosen one once it is drawn.
    // `toEqual` treats `{v_n: undefined}` as `{}`, so it cannot tell "skipped"
    // from "set to undefined" - and the difference is the whole assertion.
    // Asserting on the keys is what makes this test able to fail.
    const seed = seedFromQuery(
      { v_n: iface("v_n", "number", "count") },
      new URLSearchParams("?count=banana"),
    );
    expect(Object.keys(seed)).toEqual([]);
  });

  it("refuses object sets and picked objects rather than half-working", () => {
    const seed = seedFromQuery(
      { v_s: iface("v_s", "object_set", "set"), v_o: iface("v_o", "single_object", "obj") },
      new URLSearchParams("?set=x&obj=y"),
    );
    expect(Object.keys(seed)).toEqual([]);
  });
});

describe("Workshop p.512's local parameter defaults", () => {
  const PARAMETERS = [
    { api_name: "status", data_type: "string", required: false, hidden: false,
      default_value: "open" },
    { api_name: "note", data_type: "string", required: false, hidden: false },
  ];

  it("beats the parameter's own default", () => {
    // p.512: "If unspecified, the action type parameter configurations from
    // the Ontology will apply" — so where one *is* specified, it applies.
    expect(seedActionForm(PARAMETERS, {}, { status: "triaged" }).status).toBe("triaged");
  });

  it("does not beat the object's current value", () => {
    // **A local default is a default.** This is an edit form, and a default
    // that overwrote what the object says would show a viewer a value the
    // object does not have and write it back if they pressed Submit.
    expect(seedActionForm(PARAMETERS, { status: "closed" }, { status: "triaged" }).status)
      .toBe("closed");
  });

  it("applies to a parameter that has no default of its own", () => {
    expect(seedActionForm(PARAMETERS, {}, { note: "from the module" }).note)
      .toBe("from the module");
  });

  it("changes nothing when there are none", () => {
    expect(seedActionForm(PARAMETERS, {})).toEqual({ status: "open", note: "" });
    expect(seedActionForm(PARAMETERS, {}, {})).toEqual({ status: "open", note: "" });
  });

  it("seeds a local default that only looks empty", () => {
    // `0` and `false` are answers; the seeding order asks whether a source has
    // *something to say*, not whether it is truthy.
    expect(seedActionForm(PARAMETERS, {}, { status: 0 }).status).toBe("0");
    expect(seedActionForm(PARAMETERS, {}, { status: false }).status).toBe("false");
  });
});
