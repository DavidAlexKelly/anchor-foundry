import { describe, expect, it } from "vitest";

import {
  METRIC_SUBJECT, SERIES_SUBJECT, paintFor, rulesByColumn, rulesOf, strokeFor,
  subjectProperties,
} from "./conditional-formats";
import { cssFor } from "../../lib/conditional-format";
import type { ConditionalRule } from "@/lib/types";

/**
 * p.175's conditional formatting in a Workshop module.
 *
 * The rule grammar is §158's and is tested in `lib/conditional-format.test.ts`.
 * What is new here is the *subject* — one number rather than an instance's
 * properties — and, as with §404, which stored lists are refused.
 */

const RED: ConditionalRule = {
  kind: "standard", property: SERIES_SUBJECT,
  comparison: "numeric_range", max: 0, colour: "#c00",
};
const GREEN: ConditionalRule = { kind: "always", colour: "#0a0" };

describe("the subject a rule compares", () => {
  it("is named, so §158's dialog titles itself with a phrase", () => {
    // "Rules for latest value" is a sentence; "Rules for value" is a variable.
    expect(SERIES_SUBJECT).toBe("latest value");
    expect(METRIC_SUBJECT).toBe("metric value");
  });

  it("is the only property a rule may read", () => {
    // The evaluator is handed a bag of one, so offering a second would be
    // offering a comparison that can never match.
    expect(subjectProperties(SERIES_SUBJECT)).toEqual([
      { api_name: SERIES_SUBJECT, data_type: "float" },
    ]);
  });
});

describe("reading a stored rule list", () => {
  it("keeps a list that will evaluate", () => {
    const rules = [RED, GREEN];
    expect(rulesOf(rules)).toBe(rules);
  });

  it("treats nothing and an empty list as no rules", () => {
    for (const raw of [null, undefined, [], {}, "red", 3]) {
      expect(rulesOf(raw)).toBeNull();
    }
  });

  it("drops the whole list rather than a rule out of it", () => {
    // **First match wins, so a list is an ordered thing.** Discarding the
    // middle rule silently promotes the third into its place, which is a
    // different set of colours rather than a smaller one - and the author
    // would see two rules where they wrote three and no sign which went.
    expect(rulesOf([RED, "nonsense", GREEN])).toBeNull();
    expect(rulesOf([RED, { kind: "standard", colour: "#00c" }])).toBeNull();
    expect(rulesOf([RED, { kind: "elsewise", colour: "#00c" }])).toBeNull();
  });

  it("drops a rule that asks for nothing", () => {
    // `services/conditional_format.py` refuses one, because a rule with no
    // colour, background or alignment is a rule that matches and does nothing.
    expect(rulesOf([{ kind: "always" }])).toBeNull();
    expect(rulesOf([{
      kind: "standard", property: SERIES_SUBJECT, comparison: "is_null",
    }])).toBeNull();
  });

  it("refuses an Always-true rule that is not last", () => {
    // p.105 calls it a fallback, and the server refuses a misplaced one for
    // the reason that matters here: every rule after it is unreachable, so a
    // document holding one would silently paint everything the fallback's
    // colour while the panel showed four rules.
    expect(rulesOf([GREEN, RED])).toBeNull();
    expect(rulesOf([RED, GREEN])).not.toBeNull();
    expect(rulesOf([GREEN])).not.toBeNull();
  });
});

describe("the per-column map", () => {
  it("keys lists by property name and drops the ones that would not evaluate", () => {
    expect(rulesByColumn({ readings: [RED, GREEN], pressure: [GREEN, RED], flow: 7 }))
      .toEqual({ readings: [RED, GREEN] });
  });

  it("is empty for anything that is not a map", () => {
    for (const raw of [null, undefined, [], "readings"]) {
      expect(rulesByColumn(raw)).toEqual({});
    }
  });
});

describe("painting one number", () => {
  it("applies p.329's own example", () => {
    // "displays the metric in red if its value is less than or equal to zero,
    // and in green otherwise."
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, -5)).toEqual({ colour: "#c00" });
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, 0)).toEqual({ colour: "#c00" });
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, 1)).toEqual({ colour: "#0a0" });
  });

  it("paints nothing when there are no rules", () => {
    expect(paintFor(null, SERIES_SUBJECT, -5)).toBeNull();
    expect(paintFor([], SERIES_SUBJECT, -5)).toBeNull();
  });

  it("reads the subject it is given, not whichever one the rule names", () => {
    // A card's rules and a column's rules are the same grammar over different
    // numbers, and a rule written against one subject must not fire on the
    // other - that would be the metric coloured by the sparkline's last point.
    expect(paintFor([RED], METRIC_SUBJECT, -5)).toBeNull();
  });

  it("leaves a missing number to the rules that ask about it", () => {
    const grey: ConditionalRule = {
      kind: "standard", property: SERIES_SUBJECT,
      comparison: "is_null", colour: "#999",
    };
    // A series with no readings is not zero, so the numeric rule must not
    // fire - but `is_null` is the comparison p.106 provides for exactly this.
    expect(paintFor([RED, grey], SERIES_SUBJECT, null)).toEqual({ colour: "#999" });
    expect(paintFor([RED], SERIES_SUBJECT, null)).toBeNull();
    expect(paintFor([RED], SERIES_SUBJECT, undefined)).toBeNull();
    // And it is genuinely absence rather than zero, which the rule above
    // *would* have matched.
    expect(paintFor([RED], SERIES_SUBJECT, 0)).toEqual({ colour: "#c00" });
  });
});

describe("a read in flight", () => {
  it("paints nothing, so a loading table does not flash the fallback", () => {
    // **The fallback is what makes this matter.** p.105's Always-true rule
    // matches anything and is last by construction, so a pending row - which
    // has no number - falls through every threshold rule and lands on it.
    // Without this the whole table would go green and then settle, which reads
    // as "all of these are fine" about data nobody has read yet.
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, null, { pending: true })).toBeNull();
    // Not merely the missing-value case: a number that *has* arrived is still
    // not painted while the request it belongs to is in flight, which is what
    // `placeholderData` leaves on screen between pages.
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, -5, { pending: true })).toBeNull();
  });

  it("paints again the moment the read lands", () => {
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, null, { pending: false }))
      .toEqual({ colour: "#0a0" });
    expect(paintFor([RED, GREEN], SERIES_SUBJECT, -5)).toEqual({ colour: "#c00" });
  });
});

describe("the sparkline's stroke", () => {
  it("is the same colour as the number, because p.175 is one rule", () => {
    expect(strokeFor({ colour: "#c00" })).toBe("#c00");
  });

  it("is undefined when no rule matched, so the stylesheet keeps the theme", () => {
    expect(strokeFor(null)).toBeUndefined();
    expect(strokeFor(undefined)).toBeUndefined();
  });

  it("is not taken from a background", () => {
    // A rule asking only for a background says nothing about a line, and
    // drawing the line in the colour meant to sit *behind* the number would
    // make it invisible against its own backdrop.
    expect(strokeFor({ background: "#fee" })).toBeUndefined();
    expect(strokeFor({ colour: "#c00", background: "#fee" })).toBe("#c00");
  });
});

describe("a rule's answer as inline style (moved out of property-value)", () => {
  it("was private and untested until §405 needed it twice more", () => {
    expect(cssFor({ colour: "#c00" })).toEqual({ color: "#c00" });
    expect(cssFor(null)).toBeUndefined();
    expect(cssFor({})).toBeUndefined();
  });

  it("gives a background room to read as a box rather than a smear", () => {
    // p.102's screenshot is explicit about "colored boxes".
    const css = cssFor({ background: "#fee" })!;
    expect(css.background).toBe("#fee");
    expect(css.padding).toBe("1px 6px");
  });
});
