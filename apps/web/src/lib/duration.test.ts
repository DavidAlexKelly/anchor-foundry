/**
 * How long something took, in words (§358).
 *
 * **A shared rule gets its own file**, which is `test_limits.py`'s lesson from
 * §298 in the other language: `run-logs.test.ts` compares the two callers and
 * agrees whenever they move *together*, so a change to the rule itself is
 * invisible to it. A mutant proved that here too — widening the seconds
 * threshold survived the comparison entirely.
 *
 * The two files together say: the callers agree with each other, and they
 * agree with this.
 */
import { describe, expect, it } from "vitest";
import { durationText } from "./duration";

describe("the unit a duration reads in", () => {
  it("is milliseconds below a second", () => {
    expect(durationText(0.25)).toBe("250ms");
    expect(durationText(0.999)).toBe("999ms");
  });

  it("is seconds from one second", () => {
    // The boundary, because "below" and "at" are one value apart.
    expect(durationText(1)).toBe("1.0s");
    expect(durationText(12.34)).toBe("12.3s");
  });

  it("is seconds up to a minute", () => {
    expect(durationText(59.9)).toBe("59.9s");
  });

  it("is minutes from a minute", () => {
    // **The seam a mutant walked through.** Nothing pinned it, so moving the
    // threshold to 90 seconds changed nothing any test could see — and "89.0s"
    // is exactly the number this function exists to stop a reader converting
    // in their head.
    expect(durationText(60)).toBe("1m");
    expect(durationText(89)).toBe("1m 29s");
  });

  it("drops the seconds when there are none", () => {
    // The seconds are there to save arithmetic, and there is none at zero.
    expect(durationText(120)).toBe("2m");
    expect(durationText(3600)).toBe("60m");
  });

  it("keeps them when there are some", () => {
    // The negative control for the line above: always dropping them would
    // report a two-and-a-half minute run as "2m".
    expect(durationText(150)).toBe("2m 30s");
  });

  it("says nothing it does not know", () => {
    expect(durationText(null)).toBe("—");
  });
});
